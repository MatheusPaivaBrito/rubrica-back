import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
from hmac import new as hmac_new
from io import BytesIO
from itertools import permutations
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import stripe
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import delete, event as sqlalchemy_event, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from pypdf import PdfReader, PdfWriter

from auth_api.infrastructure.database.connection import SessionLocal as AuthSessionLocal
from auth_api.infrastructure.settings import settings as auth_settings
from auth_api.main import app as auth_app
from auth_api.modules.accounts import account_service, tenant_client
from auth_api.modules.sessions.session_service import session_service
from auth_api.modules.users.user_entity import UserEntity
from core_api.infrastructure import auth_context
from core_api.infrastructure.database.connection import SessionLocal, engine
from core_api.infrastructure.settings import settings as core_settings
from core_api.main import app as core_app
from core_api.modules.billing.billing_entity import BillingAccountEntity, BillingEventEntity, BillingPaymentEntity
from core_api.modules.billing.billing_schema import BillingCheckoutRead
from core_api.modules.billing.billing_service import BillingService, billing_service
from core_api.modules.billing.notification_client import BillingEmailDeliveryError
from core_api.modules.billing.providers.fake_provider import FakeBillingProvider
from core_api.modules.billing.providers.protocol import BillingProviderError, ProviderSubscriptionChange
from core_api.modules.billing.providers.stripe_provider import StripeBillingProvider
from core_api.modules.document.document_entity import DocumentEntity
from core_api.modules.document.document_schema import DocumentCreate
from core_api.modules.document.storage import LocalDocumentStorage
from core_api.modules.signature_request.database_workflow_service import DatabaseSignatureWorkflowService
from core_api.modules.signature_request.signature_request_entity import (
    SignatureEntity,
    SignatureOperationEntity,
    SignatureRequestEntity,
)
from core_api.modules.signature_request import identity_client
from core_api.modules.signature_request.workflow_schema import ReopenSignatureRequest, RequestStatus, SignatureMode, SignatureRequestCreate, SignerCreate, StampPosition
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.signature_request.workflow_service import WorkflowError
from shared_kernel.time.datetime_service import DateTimeService
from toolbox.seeds.local_test_accounts import _ensure_test_cpf


pytestmark = pytest.mark.skipif(os.getenv("RUBRICA_DATABASE_TESTS") != "1", reason="requires Rubrica PostgreSQL")


@pytest.fixture(scope="module", autouse=True)
def isolated_core_database() -> None:
    """Keep integration records isolated without bypassing append-only triggers."""
    with SessionLocal.begin() as db:
        db.execute(text("TRUNCATE TABLE tenants CASCADE"))
    yield
    with SessionLocal.begin() as db:
        db.execute(text("TRUNCATE TABLE tenants CASCADE"))


@pytest.fixture
def auth_identities(monkeypatch: pytest.MonkeyPatch):
    users = []
    emails = ("database@example.com", "second@example.com", "signed@example.com", "pending@example.com")
    with AuthSessionLocal.begin() as db:
        for index, email in enumerate(emails, start=1000):
            user = UserEntity(email=email, email_verified=True, password_hash="unused")
            db.add(user)
            db.flush()
            _ensure_test_cpf(db, user, index)
            users.append(user.id)

    service_key = "qa-core-to-auth"
    monkeypatch.setattr(auth_settings, "CORE_INTERNAL_SERVICE_KEY", service_key)
    monkeypatch.setattr(core_settings, "CORE_INTERNAL_SERVICE_KEY", service_key)
    try:
        with TestClient(auth_app) as client:
            def get_identity(url, *, params, headers, timeout):
                return client.get(url, params=params, headers=headers)

            monkeypatch.setattr(
                identity_client, "httpx",
                SimpleNamespace(get=get_identity, HTTPError=identity_client.httpx.HTTPError),
            )
            yield
    finally:
        with AuthSessionLocal.begin() as db:
            db.execute(delete(UserEntity).where(UserEntity.id.in_(users)))


@pytest.fixture
def trusted_timestamp(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"count": 0, "failures_remaining": 0}

    def apply_timestamp(pdf: bytes) -> tuple[bytes, dict[str, object]]:
        calls["count"] += 1
        # The external provider callback must run after the preparation
        # transaction released its request lock.
        with SessionLocal.begin() as db:
            operation = db.scalar(
                select(SignatureOperationEntity).where(
                    SignatureOperationEntity.status == "processing"
                )
            )
            assert operation is not None
            locked_request = db.scalar(
                select(SignatureRequestEntity)
                .where(SignatureRequestEntity.id == operation.signature_request_id)
                .with_for_update(nowait=True)
            )
            assert locked_request is not None
        if calls["failures_remaining"]:
            calls["failures_remaining"] -= 1
            raise RuntimeError("simulated timestamp outage")
        return pdf, {
            "provider": "integration-test",
            "token_sha256": "0" * 64,
            "policy_oid": "2.16.76.1.2",
        }

    monkeypatch.setattr(
        "core_api.modules.signature_request.serpro_timestamp_service.apply_serpro_timestamp",
        apply_timestamp,
    )
    return calls


@pytest.mark.skipif(not os.getenv("RUBRICA_TEST_REDIS_URL"), reason="requires isolated Redis")
def test_registration_provisions_one_workspace_and_rejects_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    unique = uuid4().hex
    email = f"registration-{unique}@example.test"
    payload = {
        "name": "Test registration",
        "email": email,
        "country_code": "BR",
        "identity_document_type": "PASSPORT",
        "identity_document_country": "JP",
        "identity_document_value": unique[:12],
    }
    sent = []
    service_key = "qa-auth-to-core"
    monkeypatch.setattr(auth_settings, "CORE_INTERNAL_SERVICE_KEY", service_key)
    monkeypatch.setattr(core_settings, "CORE_INTERNAL_SERVICE_KEY", service_key)
    monkeypatch.setattr(
        account_service, "request_account_email", lambda **message: sent.append(message)
    )
    with (
        Redis.from_url(os.environ["RUBRICA_TEST_REDIS_URL"], decode_responses=True) as redis,
        TestClient(auth_app) as auth,
        TestClient(core_app) as core,
    ):
        monkeypatch.setattr(session_service, "_redis", redis)

        def provision(url, *, json, headers, timeout):
            return core.post(url, json=json, headers=headers)

        monkeypatch.setattr(
            tenant_client, "httpx",
            SimpleNamespace(post=provision, HTTPError=tenant_client.httpx.HTTPError),
        )
        try:
            for missing in ("country_code", "identity_document_value"):
                invalid = {key: value for key, value in payload.items() if key != missing}
                assert auth.post("/auth/register", json=invalid).status_code == 422
            assert auth.post("/auth/register", json=payload).status_code == 202
            for duplicate in (
                payload | {"email": email.upper(), "identity_document_value": unique[-12:]},
                payload | {"email": f"duplicate-{email}"},
            ):
                conflict = auth.post("/auth/register", json=duplicate)
                assert conflict.status_code == 409
                assert conflict.json() == {"detail": "E-mail or identity document is already registered"}
            assert len(sent) == 1
            assert sent[0]["recipient"] == email
            credentials = {"email": email, "password": "Qa-Example-Password-123!"}
            assert auth.post("/auth/login", json=credentials).status_code == 401
            activation_link = next(
                line for line in sent[0]["email"].text.splitlines() if "/verify-email?" in line
            )
            token = parse_qs(urlsplit(activation_link).query)["token"][0]
            activation = {"token": token, "new_password": credentials["password"]}
            assert auth.post("/auth/verify-email", json=activation).status_code == 200
            assert auth.post("/auth/verify-email", json=activation).status_code == 422
            login = auth.post("/auth/login", json=credentials)
            assert login.status_code == 200
            assert login.json()["access_token"]

            with AuthSessionLocal() as db:
                user = db.scalar(select(UserEntity).where(UserEntity.email == email))
                assert user is not None and user.is_active and user.email_verified
                user_id = user.id
                assert db.scalar(select(UserEntity.id).where(UserEntity.email == f"duplicate-{email}")) is None
            with SessionLocal() as db:
                workspace, = db.scalars(
                    select(TenantEntity)
                    .join(TenantMemberEntity, TenantMemberEntity.tenant_id == TenantEntity.id)
                    .where(TenantMemberEntity.auth_user_uuid == user_id)
                )
                assert (workspace.kind, workspace.country_code, workspace.currency) == ("personal", "BR", "BRL")
        finally:
            with AuthSessionLocal.begin() as db:
                db.execute(delete(UserEntity).where(UserEntity.email.in_((email, f"duplicate-{email}"))))


def test_signature_entitlement_limit_and_active_subscription() -> None:
    tenant_id = uuid4()
    with SessionLocal.begin() as db:
        db.add(TenantEntity(id=tenant_id, name="Entitlement test", slug=f"entitlement-{tenant_id}"))
        db.flush()
        db.add(
            BillingAccountEntity(
                tenant_id=tenant_id,
                status="not_configured",
                signatures_used=4,
                free_signatures_limit=5,
            )
        )

    try:
        with SessionLocal.begin() as db:
            billing_service.consume_signature(db, tenant_id)

        with pytest.raises(WorkflowError) as error:
            with SessionLocal.begin() as db:
                billing_service.consume_signature(db, tenant_id)
        assert error.value.status_code == 402

        with SessionLocal.begin() as db:
            account = db.scalar(
                select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant_id)
            )
            assert account is not None
            assert account.signatures_used == 5
            account.status = "active"

        with SessionLocal.begin() as db:
            billing_service.consume_signature(db, tenant_id)

        with SessionLocal() as db:
            account = db.scalar(
                select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant_id)
            )
            assert account is not None
            assert account.signatures_used == 5
    finally:
        pass


@pytest.fixture
def subscription_webhook(monkeypatch):
    tenant_id = uuid4()
    with SessionLocal.begin() as db:
        db.add(TenantEntity(id=tenant_id, name="Webhook QA", slug=f"webhook-{tenant_id}"))
        db.flush()
        db.add(BillingAccountEntity(tenant_id=tenant_id, signatures_used=3))
    monkeypatch.setattr(billing_service, "_get_provider", FakeBillingProvider)
    event_id = f"evt_qa_{uuid4().hex}"
    now = int(DateTimeService.utc_now().timestamp())
    payload = json.dumps({
        "id": event_id,
        "type": "customer.subscription.created",
        "created": now,
        "data": {"object": {
            "id": f"sub_{tenant_id.hex}",
            "status": "active",
            "current_period_start": now,
            "current_period_end": now + 30 * 24 * 3600,
            "metadata": {"tenant_id": str(tenant_id), "product_code": "rubrica_base"},
        }},
    }).encode()
    return tenant_id, event_id, payload


def test_signed_stripe_webhook_route_applies_valid_event_and_rejects_tampering(monkeypatch, subscription_webhook):
    tenant_id, event_id, payload = subscription_webhook
    event = json.loads(payload) | {"object": "event"}
    payload = json.dumps(event).encode()
    webhook_secret = "whsec_local_rubrica_fixture"
    monkeypatch.setattr(core_settings, "STRIPE_SECRET_KEY", "sk_test_local_fixture")
    monkeypatch.setattr(core_settings, "STRIPE_RUNTIME_WEBHOOK_SECRET_FILE", None)
    monkeypatch.setattr(core_settings, "STRIPE_WEBHOOK_SECRET", webhook_secret)
    monkeypatch.setattr(billing_service, "_get_provider", StripeBillingProvider)
    timestamp = str(event["created"])
    signature = hmac_new(webhook_secret.encode(), timestamp.encode() + b"." + payload, sha256).hexdigest()
    headers = {"Stripe-Signature": f"t={timestamp},v1={signature}", "Content-Type": "application/json"}

    with TestClient(core_app) as http:
        path = "/billing/webhooks/stripe"
        assert http.post(path, content=payload + b" ", headers=headers).status_code == 400
        with SessionLocal() as db:
            assert db.scalar(select(BillingEventEntity.id).filter_by(provider_event_id=event_id)) is None
        accepted = http.post(path, content=payload, headers=headers)
        assert accepted.status_code == 200
        assert accepted.json()["duplicate"] is False
        repeated = http.post(path, content=payload, headers=headers)
        assert repeated.status_code == 200
        assert repeated.json()["duplicate"] is True
    with SessionLocal() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        assert (account.status, account.signatures_used) == ("active", 3)


@pytest.mark.parametrize("late_event_type", [
    "customer.subscription.updated", "invoice.payment_succeeded", "invoice.payment_failed",
    "checkout.session.completed",
])
def test_cancelled_subscription_survives_redelivery_and_backend_restart(subscription_webhook, late_event_type):
    tenant_id, activation_id, activation_payload = subscription_webhook
    activation = json.loads(activation_payload)
    subscription = activation["data"]["object"]
    now = activation["created"]
    period_end = subscription["current_period_end"]
    invoice = {
        "id": f"in_{tenant_id.hex}", "subscription": subscription["id"],
        "metadata": subscription["metadata"], "status": "paid",
        "billing_reason": "subscription_create", "currency": "brl", "amount_paid": 2990,
    }

    def event_payload(event_type, created, resource):
        return json.dumps({
            "id": f"evt_qa_{uuid4().hex}", "type": event_type, "created": created,
            "data": {"object": resource},
        }).encode()

    checkout = event_payload("checkout.session.completed", now - 1, {
        "id": f"cs_{tenant_id.hex}", "subscription": subscription["id"],
        "payment_status": "paid", "metadata": subscription["metadata"],
    })
    paid = event_payload("invoice.payment_succeeded", now + 1, invoice)
    cancellation = event_payload("customer.subscription.updated", now + 2, subscription | {
        "cancel_at_period_end": True, "cancel_at": period_end,
    })

    # Only webhooks reach the Core after payment. The browser never returns.
    original_service = BillingService(FakeBillingProvider())
    assert not original_service.receive_webhook(checkout, "qa").duplicate
    assert not original_service.receive_webhook(activation_payload, "qa").duplicate
    assert not original_service.receive_webhook(paid, "qa").duplicate
    assert original_service.receive_webhook(activation_payload, "qa").duplicate
    assert not original_service.receive_webhook(cancellation, "qa").duplicate

    engine.dispose()
    restarted_service = BillingService(FakeBillingProvider())
    assert restarted_service.receive_webhook(activation_payload, "qa").duplicate
    assert restarted_service.receive_webhook(paid, "qa").duplicate
    assert restarted_service.receive_webhook(cancellation, "qa").duplicate
    with SessionLocal() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        assert (account.status, account.cancel_at_period_end, account.signatures_used) == ("active", True, 3)
        assert account.cancels_at.timestamp() == period_end
        assert restarted_service._paid_access_enabled(account)

    deletion = event_payload("customer.subscription.deleted", period_end, subscription | {"status": "canceled"})
    assert not restarted_service.receive_webhook(deletion, "qa").duplicate
    assert restarted_service.receive_webhook(deletion, "qa").duplicate
    assert restarted_service.receive_webhook(paid, "qa").duplicate
    if late_event_type == "customer.subscription.updated":
        late_resource = subscription
    elif late_event_type == "checkout.session.completed":
        late_resource = json.loads(checkout)["data"]["object"]
    else:
        late_resource = invoice | {"id": f"in_late_{tenant_id.hex}", "billing_reason": "subscription_cycle"}
    if late_event_type == "invoice.payment_failed":
        late_resource |= {"status": "open", "amount_paid": 0}
    late_created_at = period_end + 1 if late_event_type == "checkout.session.completed" else period_end
    late_event = event_payload(late_event_type, late_created_at, late_resource)
    assert not restarted_service.receive_webhook(late_event, "qa").duplicate
    assert restarted_service.receive_webhook(late_event, "qa").duplicate

    with SessionLocal() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        assert (account.status, account.cancel_at_period_end, account.signatures_used) == ("cancelled", False, 3)
        assert account.grace_period_ends_at is None
        assert not restarted_service._paid_access_enabled(account)
        assert db.scalars(select(BillingEventEntity.status).filter_by(provider_event_id=activation_id)).one() == "processed"
        assert db.scalars(select(BillingEventEntity.status).filter_by(
            provider_event_id=json.loads(late_event)["id"],
        )).one() == "ignored_stale"
        payments = {payment.provider_payment_id: payment for payment in db.scalars(
            select(BillingPaymentEntity).filter_by(tenant_id=tenant_id),
        )}
        assert (payments[invoice["id"]].status, payments[invoice["id"]].amount_paid_minor) == ("paid", 2990)
        if late_event_type.startswith("invoice."):
            assert payments.keys() == {invoice["id"], late_resource["id"]}
            assert payments[late_resource["id"]].status == ("paid" if late_resource["status"] == "paid" else "failed")
        else:
            assert payments.keys() == {invoice["id"]}

    # A truly new subscription can still be purchased after terminal cancellation.
    replacement_id = f"sub_replacement_{tenant_id.hex}"
    replacement = event_payload("customer.subscription.created", period_end + 2, subscription | {
        "id": replacement_id, "current_period_start": period_end + 2, "current_period_end": period_end + 3600,
    })
    assert not restarted_service.receive_webhook(replacement, "qa").duplicate
    with SessionLocal() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        assert (account.provider_subscription_id, account.status) == (replacement_id, "active")


def test_concurrent_checkout_reuses_the_same_customer_and_session(monkeypatch):
    tenant_id = uuid4()
    subject = "checkout-owner@example.test"
    price_id = "price_qa_essential_monthly_brl"
    with SessionLocal.begin() as db:
        db.add(TenantEntity(id=tenant_id, name="Checkout QA", slug=f"checkout-{tenant_id}", country_code="BR"))
        db.flush()
        db.add(TenantMemberEntity(tenant_id=tenant_id, auth_user_id=subject, role="admin"))

    customers = []
    sessions = []
    def create_customer(**parameters):
        customers.append(parameters)
        return SimpleNamespace(id="cus_qa_concurrent")

    def create_session(**parameters):
        sessions.append(stripe.StripeObject.construct_from({
            "id": "cs_qa_concurrent", "status": "open", "payment_status": "unpaid",
            "url": "https://checkout.stripe.test/session", **parameters,
        }, None))
        return sessions[-1]

    monkeypatch.setattr(core_settings, "STRIPE_SECRET_KEY", "sk_test_local_fixture")
    monkeypatch.setattr(core_settings, "STRIPE_PRICE_ESSENTIAL_MONTHLY_BRL", price_id)
    monkeypatch.setattr(stripe.Customer, "create", create_customer)
    monkeypatch.setattr(stripe.checkout.Session, "create", create_session)
    monkeypatch.setattr(stripe.checkout.Session, "list", lambda **_: SimpleNamespace(auto_paging_iter=lambda: iter(sessions)))
    monkeypatch.setattr(stripe.checkout.Session, "list_line_items", lambda *_args, **_: {
        "data": [{"price": {"id": price_id}, "quantity": 1}],
    })
    service = BillingService(StripeBillingProvider())
    simultaneous = Barrier(2)

    def open_checkout():
        simultaneous.wait(timeout=10)
        return service.create_checkout(tenant_id, subject, "rubrica_base").checkout_url

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(open_checkout) for _ in range(2)]
        assert [result.result(timeout=10) for result in results] == ["https://checkout.stripe.test/session"] * 2

    assert len(customers) == len(sessions) == 1
    with SessionLocal() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        assert (account.provider_customer_id, account.status) == ("cus_qa_concurrent", "not_configured")


@pytest.mark.parametrize("delivery_order", list(permutations(("checkout", "subscription", "invoice"))))
def test_first_payment_is_recorded_once_in_each_delivery_order(subscription_webhook, delivery_order):
    tenant_id, _, subscription_payload = subscription_webhook
    subscription = json.loads(subscription_payload)
    resource = subscription["data"]["object"]
    customer = f"cus_{tenant_id.hex}"
    with SessionLocal.begin() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        account.provider_customer_id = customer

    def payload(event_type, obj):
        return json.dumps({
            "id": f"evt_{uuid4().hex}", "type": event_type, "created": subscription["created"],
            "data": {"object": obj},
        }).encode()

    invoice = {"id": f"in_{tenant_id.hex}", "customer": customer, "billing_reason": "subscription_create",
               "status": "paid", "currency": "jpy", "amount_due": 3900, "amount_paid": 3900,
               "parent": {"subscription_details": {"subscription": resource["id"], "metadata": resource["metadata"]}}}
    events = {
        "checkout": payload("checkout.session.completed", {
            "id": f"cs_{tenant_id.hex}", "subscription": resource["id"], "customer": customer,
            "metadata": resource["metadata"], "payment_status": "paid",
        }),
        "subscription": subscription_payload,
        "invoice": payload("invoice.payment_succeeded", invoice),
    }
    for key in delivery_order:
        assert not billing_service.receive_webhook(events[key], "qa").duplicate
    for key in reversed(delivery_order):
        assert billing_service.receive_webhook(events[key], "qa").duplicate
    # A separate delivery ID for the very same invoice must also have only one financial effect.
    assert not billing_service.receive_webhook(payload("invoice.payment_succeeded", invoice), "qa").duplicate
    with SessionLocal() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        payment = db.scalars(select(BillingPaymentEntity).filter_by(tenant_id=tenant_id)).one()
        assert (account.status, account.provider_subscription_id, account.signatures_used) == ("active", resource["id"], 3)
        assert (payment.status, payment.currency, payment.amount_paid_minor) == ("paid", "JPY", 3900)


def test_seat_upgrade_retry_recovers_payment_webhook_received_after_timeout(monkeypatch, subscription_webhook):
    tenant_id, _, activation_payload = subscription_webhook
    assert not billing_service.receive_webhook(activation_payload, "qa").duplicate
    activation = json.loads(activation_payload)
    subscription = activation["data"]["object"]
    invoice_id = f"in_{tenant_id.hex}"
    attempts = []

    class LostResponseProvider(FakeBillingProvider):
        def update_subscription_seats(self, **params):
            attempts.append(params)
            if len(attempts) == 1:
                raise BillingProviderError("Simulated response loss")
            return ProviderSubscriptionChange(invoice_id=invoice_id)

    with SessionLocal.begin() as db:
        db.get(TenantEntity, tenant_id).currency = "BRL"
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        account.current_product_code = "rubrica_intermediate"
        account.contracted_seats = 3
    paid = json.dumps({
        "id": f"evt_{uuid4().hex}", "type": "invoice.payment_succeeded", "created": activation["created"] + 1,
        "data": {"object": {
            "id": invoice_id, "subscription": subscription["id"], "metadata": subscription["metadata"],
            "billing_reason": "subscription_update", "status": "paid", "currency": "brl", "amount_paid": 1143,
        }},
    }).encode()
    monkeypatch.setattr("core_api.modules.billing.billing_service.tenant_service.require_role", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(core_settings, "STRIPE_PRICE_PROFESSIONAL_MONTHLY_BRL", "price_base")
    monkeypatch.setattr(core_settings, "STRIPE_PRICE_SEAT_MONTHLY_BRL", "price_seat")
    service = BillingService(LostResponseProvider())
    with pytest.raises(WorkflowError, match="Simulated response loss"):
        service.change_seats(tenant_id, "test-admin", 4, "month")
    assert not service.receive_webhook(paid, "qa").duplicate
    with SessionLocal() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        assert (account.contracted_seats, account.pending_provider_invoice_id) == (3, None)
    assert service.change_seats(tenant_id, "test-admin", 4, "month").status == "applied"
    assert service.receive_webhook(paid, "qa").duplicate
    assert attempts[0] == attempts[1]
    with SessionLocal() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        payment = db.scalars(select(BillingPaymentEntity).filter_by(tenant_id=tenant_id)).one()
        assert (account.contracted_seats, account.pending_provider_invoice_id) == (4, None)
        assert (payment.status, payment.amount_paid_minor) == ("paid", 1143)


@pytest.mark.parametrize("late_event_type", ["invoice.payment_succeeded", "invoice.payment_failed"])
def test_invoice_from_a_previous_cycle_cannot_change_current_cycle(subscription_webhook, late_event_type):
    tenant_id, _, activation_payload = subscription_webhook
    assert not billing_service.receive_webhook(activation_payload, "qa").duplicate
    activation = json.loads(activation_payload)
    subscription = activation["data"]["object"]
    previous_start, current_start = subscription["current_period_start"], subscription["current_period_end"]
    current_end = current_start + current_start - previous_start

    def renewal(event_type, start, end):
        succeeded = event_type == "invoice.payment_succeeded"
        invoice = {
            "id": f"in_{uuid4().hex}", "subscription": subscription["id"],
            "metadata": subscription["metadata"], "billing_reason": "subscription_cycle",
            "status": "paid" if succeeded else "open", "currency": "brl",
            "amount_paid": 2990 if succeeded else 0, "amount_due": 2990,
            "lines": {"data": [{"period": {"start": start, "end": end}}]},
        }
        return json.dumps({
            "id": f"evt_{uuid4().hex}", "type": event_type, "created": current_start + 1,
            "data": {"object": invoice},
        }).encode()

    # Late failures cannot revoke a paid renewal, and old payments cannot cover a failed renewal.
    current_event_type = (
        "invoice.payment_failed" if late_event_type == "invoice.payment_succeeded" else "invoice.payment_succeeded"
    )
    current_renewal = renewal(current_event_type, current_start, current_end)
    assert not billing_service.receive_webhook(current_renewal, "qa").duplicate
    with SessionLocal.begin() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        account.files_uploaded_in_period = 7
        expected_status = account.status
        expected_grace = account.grace_period_ends_at
    late_renewal = renewal(late_event_type, previous_start, current_start)
    assert not billing_service.receive_webhook(late_renewal, "qa").duplicate
    assert billing_service.receive_webhook(late_renewal, "qa").duplicate
    with SessionLocal() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        assert account.status == expected_status
        assert account.grace_period_ends_at == expected_grace
        assert account.current_period_ends_at.timestamp() == current_end
        assert account.files_uploaded_in_period == 7
        assert len(db.scalars(select(BillingPaymentEntity).filter_by(tenant_id=tenant_id)).all()) == 2


@pytest.mark.parametrize(("event_type", "initial_status", "matching"), [
    ("invoice.payment_succeeded", "past_due", False),
    ("invoice.payment_succeeded", "past_due", True),
    ("invoice.payment_failed", "active", False),
    ("invoice.payment_failed", "active", True),
])
def test_proration_payment_does_not_change_renewal_status(subscription_webhook, event_type, initial_status, matching):
    tenant_id, _, activation_payload = subscription_webhook
    assert not billing_service.receive_webhook(activation_payload, "qa").duplicate
    activation = json.loads(activation_payload)
    subscription = activation["data"]["object"]
    succeeded = event_type == "invoice.payment_succeeded"
    invoice = {
        "id": f"in_{uuid4().hex}", "subscription": subscription["id"],
        "metadata": subscription["metadata"], "billing_reason": "subscription_update",
        "status": "paid" if succeeded else "open", "amount_due": 1143,
        "amount_paid": 1143 if succeeded else 0, "currency": "brl",
    }
    grace = DateTimeService.utc_now() + timedelta(days=1) if initial_status == "past_due" else None
    with SessionLocal.begin() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        account.status = initial_status
        account.grace_period_ends_at = grace
        account.pending_provider_invoice_id = invoice["id"] if matching else "in_other_upgrade"
        account.pending_contracted_seats = 4
        account.pending_product_code = "rubrica_intermediate"
        expected_seats = 4 if matching and succeeded else account.contracted_seats
    event = json.dumps({
        "id": f"evt_{uuid4().hex}", "type": event_type, "created": activation["created"] + 1,
        "data": {"object": invoice},
    }).encode()
    assert not billing_service.receive_webhook(event, "qa").duplicate
    assert billing_service.receive_webhook(event, "qa").duplicate
    with SessionLocal() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        payment = db.scalars(select(BillingPaymentEntity).filter_by(tenant_id=tenant_id)).one()
        assert (account.status, account.grace_period_ends_at) == (initial_status, grace)
        assert account.contracted_seats == expected_seats
        assert account.pending_contracted_seats == (None if matching and succeeded else 4)
        assert payment.status == ("paid" if succeeded else "failed")


def test_invoice_waiting_on_update_checks_the_committed_subscription(monkeypatch, subscription_webhook):
    tenant_id, _, payload = subscription_webhook
    assert not billing_service.receive_webhook(payload, "qa").duplicate
    old_subscription = f"sub_{tenant_id.hex}"
    invoice_event = json.loads(payload) | {
        "id": f"evt_qa_{uuid4().hex}",
        "type": "invoice.payment_failed",
        "data": {"object": {
            "id": "in_old", "subscription": old_subscription, "metadata": {"tenant_id": str(tenant_id)},
        }},
    }
    webhook_lookup_started = Event()
    get_account = billing_service._account_entity

    def observed_lookup(db, lookup_tenant_id, *, lock=False):
        if lock:
            webhook_lookup_started.set()
        account = get_account(db, lookup_tenant_id, lock=lock)
        webhook_lookup_started.set()
        return account

    monkeypatch.setattr(billing_service, "_account_entity", observed_lookup)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with SessionLocal.begin() as db:
            account = get_account(db, tenant_id, lock=True)
            account.provider_subscription_id = "sub_replacement"
            delivery = pool.submit(billing_service.receive_webhook, json.dumps(invoice_event).encode(), "qa")
            assert webhook_lookup_started.wait(10)
        assert not delivery.result(timeout=10).duplicate

    with SessionLocal() as db:
        account = get_account(db, tenant_id)
        event = db.scalar(select(BillingEventEntity).filter_by(provider_event_id=invoice_event["id"]))
        assert account.status == "active"
        assert account.provider_subscription_id == "sub_replacement"
        assert event.status == "ignored_stale"


def test_webhook_retry_success_is_preserved_when_an_earlier_attempt_records_failure(
    monkeypatch, subscription_webhook,
):
    tenant_id, event_id, payload = subscription_webhook
    rolled_back = Event()
    retry_finished = Event()
    original_begin = SessionLocal.begin
    apply_event = billing_service._apply_event
    should_fail = True

    class TransientFailure(RuntimeError):
        pass

    def apply_then_fail_once(*args):
        nonlocal should_fail
        result = apply_event(*args)
        if should_fail:
            should_fail = False
            raise TransientFailure("First delivery rolled back")
        return result

    @contextmanager
    def pause_after_rollback():
        try:
            with original_begin() as db:
                yield db
        except TransientFailure:
            rolled_back.set()
            assert retry_finished.wait(10), "Parallel retry did not finish"
            raise

    monkeypatch.setattr(billing_service, "_apply_event", apply_then_fail_once)
    monkeypatch.setattr(SessionLocal, "begin", pause_after_rollback)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(billing_service.receive_webhook, payload, "qa")
        try:
            assert rolled_back.wait(10), "First delivery did not reach rollback"
            assert not billing_service.receive_webhook(payload, "qa").duplicate
        finally:
            retry_finished.set()
        with pytest.raises(TransientFailure):
            first.result(timeout=10)

    with SessionLocal() as db:
        event = db.scalars(select(BillingEventEntity).filter_by(provider_event_id=event_id)).one()
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        assert (event.status, event.error_code) == ("processed", None)
        assert (account.status, account.signatures_used) == ("active", 3)
    assert billing_service.receive_webhook(payload, "qa").duplicate


def test_webhook_email_outage_does_not_roll_back_subscription_or_reapply_it(
    monkeypatch, subscription_webhook,
):
    tenant_id, event_id, payload = subscription_webhook
    notifications = []

    def unavailable(_db, delivered_event_id, *_args):
        notifications.append(delivered_event_id)
        raise BillingEmailDeliveryError("Simulated local email outage")

    monkeypatch.setattr(billing_service, "_notify_billing_event", unavailable)
    assert not billing_service.receive_webhook(payload, "qa").duplicate
    assert billing_service.receive_webhook(payload, "qa").duplicate
    assert notifications == [event_id]
    with SessionLocal() as db:
        assert db.scalar(select(BillingAccountEntity.status).filter_by(tenant_id=tenant_id)) == "active"
        assert db.scalar(select(BillingEventEntity.status).filter_by(provider_event_id=event_id)) == "processed"


def test_webhook_persistence_error_is_not_reported_as_duplicate(subscription_webhook):
    _, event_id, payload = subscription_webhook
    event = json.loads(payload)
    event["data"]["object"]["metadata"]["tenant_id"] = str(uuid4())

    with pytest.raises(IntegrityError):
        billing_service.receive_webhook(json.dumps(event).encode(), "qa")
    with SessionLocal() as db:
        assert db.scalar(select(BillingEventEntity.id).filter_by(provider_event_id=event_id)) is None


def test_webhook_insert_collision_resumes_the_unprocessed_event(monkeypatch, subscription_webhook):
    tenant_id, event_id, payload = subscription_webhook
    original_begin = SessionLocal.begin
    first_insert = True

    @contextmanager
    def insert_from_competing_delivery():
        nonlocal first_insert
        if first_insert:
            first_insert = False
            with original_begin() as db:
                db.add(BillingEventEntity(
                    tenant_id=tenant_id,
                    provider="stripe",
                    provider_event_id=event_id,
                    event_type="customer.subscription.created",
                    resource_id=f"sub_{tenant_id.hex}",
                    payload_hash=sha256(payload).hexdigest(),
                    status="received",
                ))
        with original_begin() as db:
            yield db

    monkeypatch.setattr(SessionLocal, "begin", insert_from_competing_delivery)
    assert not billing_service.receive_webhook(payload, "qa").duplicate
    assert billing_service.receive_webhook(payload, "qa").duplicate
    with SessionLocal() as db:
        assert db.scalar(select(BillingEventEntity.status).filter_by(provider_event_id=event_id)) == "processed"


def _stripe_event_payload(event_type, resource):
    return json.dumps({
        "id": f"evt_qa_{uuid4().hex}", "object": "event", "type": event_type,
        "created": int(DateTimeService.utc_now().timestamp()), "data": {"object": resource},
    }).encode()


@pytest.fixture
def paid_stripe_invoice(subscription_webhook):
    tenant_id, _, subscription = subscription_webhook
    customer = f"cus_{tenant_id.hex}"
    with SessionLocal.begin() as db:
        account = db.scalar(select(BillingAccountEntity).filter_by(tenant_id=tenant_id))
        account.provider_customer_id = customer
        account.files_uploaded_in_period = 7
    assert not billing_service.receive_webhook(subscription, "qa").duplicate
    return tenant_id, {
        "id": f"in_{tenant_id.hex}", "customer": customer, "subscription": f"sub_{tenant_id.hex}",
        "metadata": {"tenant_id": str(tenant_id)}, "billing_reason": "subscription_create",
        "status": "paid", "currency": "brl", "amount_due": 2990, "amount_paid": 2990,
    }


@pytest.mark.parametrize("same_event", [True, False], ids=["same-event-id", "same-invoice-distinct-events"])
def test_parallel_workers_apply_a_paid_invoice_once(paid_stripe_invoice, monkeypatch, same_event):
    tenant_id, invoice = paid_stripe_invoice
    first = _stripe_event_payload("invoice.payment_succeeded", invoice)
    second = first if same_event else _stripe_event_payload("invoice.payment_succeeded", invoice)
    ready = Barrier(2)

    class ConcurrentProvider(FakeBillingProvider):
        def construct_webhook_event(self, *, payload, signature):
            ready.wait(timeout=10)
            return super().construct_webhook_event(payload=payload, signature=signature)

    notifications = []
    monkeypatch.setattr(BillingService, "_notify_billing_event", staticmethod(
        lambda _db, event_id, *_args: notifications.append(event_id),
    ))
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(BillingService(ConcurrentProvider()).receive_webhook, payload, "qa")
                    for payload in (first, second)]
        assert sorted(request.result(timeout=10).duplicate for request in requests) == [False, same_event]

    with SessionLocal() as db:
        payment = db.scalars(select(BillingPaymentEntity).filter_by(tenant_id=tenant_id)).one()
        events = db.scalars(select(BillingEventEntity.status).filter_by(
            tenant_id=tenant_id, event_type="invoice.payment_succeeded",
        )).all()
        assert (payment.status, payment.amount_paid_minor) == ("paid", 2990)
        assert sorted(events) == (["processed"] if same_event else ["ignored_stale", "processed"])
        assert notifications == [payment.provider_event_id]


def test_paid_webhook_retries_after_postgres_connection_failure(paid_stripe_invoice):
    tenant_id, invoice = paid_stripe_invoice
    payload = _stripe_event_payload("invoice.payment_succeeded", invoice)
    event_id = json.loads(payload)["id"]
    failures = []

    def unavailable(*_args):
        failures.append(True)
        raise OperationalError(None, None, ConnectionRefusedError("Simulated PostgreSQL outage"))

    engine.dispose()
    with TestClient(core_app, raise_server_exceptions=False) as http:
        path = "/billing/webhooks/stripe"
        headers = {"Stripe-Signature": "qa"}
        sqlalchemy_event.listen(engine, "do_connect", unavailable)
        try:
            assert http.post(path, content=payload, headers=headers).status_code == 500
        finally:
            sqlalchemy_event.remove(engine, "do_connect", unavailable)
        assert failures
        with SessionLocal() as db:
            assert db.scalar(select(BillingEventEntity.id).filter_by(provider_event_id=event_id)) is None
            assert db.scalar(select(BillingPaymentEntity.id).filter_by(tenant_id=tenant_id)) is None
        response = http.post(path, content=payload, headers=headers)
        assert response.status_code == 200 and response.json()["duplicate"] is False
        repeated = http.post(path, content=payload, headers=headers)
        assert repeated.status_code == 200 and repeated.json()["duplicate"] is True
    with SessionLocal() as db:
        payment = db.scalars(select(BillingPaymentEntity).filter_by(tenant_id=tenant_id)).one()
        assert (payment.status, payment.amount_paid_minor) == ("paid", 2990)


def test_postgres_rollback_after_paid_invoice_flush_can_be_retried(paid_stripe_invoice, monkeypatch):
    tenant_id, invoice = paid_stripe_invoice
    payload = _stripe_event_payload("invoice.payment_succeeded", invoice)
    event_id = json.loads(payload)["id"]
    with SessionLocal.begin() as db:
        account = db.scalar(select(BillingAccountEntity).filter_by(tenant_id=tenant_id))
        account.status = "past_due"
    apply_event = billing_service._apply_event

    def apply_and_rollback(db, *args):
        assert apply_event(db, *args)
        db.flush()
        db.execute(text("SELECT 1 / 0"))

    with monkeypatch.context() as changes:
        changes.setattr(billing_service, "_apply_event", apply_and_rollback)
        with pytest.raises(DBAPIError) as error:
            billing_service.receive_webhook(payload, "qa")
    assert error.value.orig.sqlstate == "22012"
    with SessionLocal() as db:
        assert db.scalar(select(BillingAccountEntity.status).filter_by(tenant_id=tenant_id)) == "past_due"
        assert db.scalar(select(BillingPaymentEntity.id).filter_by(tenant_id=tenant_id)) is None
        assert db.scalar(select(BillingEventEntity.status).filter_by(provider_event_id=event_id)) == "failed"

    assert not billing_service.receive_webhook(payload, "qa").duplicate
    assert billing_service.receive_webhook(payload, "qa").duplicate
    with SessionLocal() as db:
        assert db.scalar(select(BillingAccountEntity.status).filter_by(tenant_id=tenant_id)) == "active"
        assert db.scalars(select(BillingPaymentEntity.amount_paid_minor).filter_by(tenant_id=tenant_id)).one() == 2990
        assert db.scalar(select(BillingEventEntity.status).filter_by(provider_event_id=event_id)) == "processed"


@pytest.mark.parametrize(("event_type", "fields"), [
    ("charge.refunded", {"amount": 2990, "amount_refunded": 1000, "refunded": False}),
    ("charge.refunded", {"amount": 2990, "amount_refunded": 2990, "refunded": True}),
    ("charge.dispute.created", {"amount": 2990, "status": "needs_response"}),
    ("charge.dispute.closed", {"amount": 2990, "status": "lost"}),
], ids=["partial-refund", "full-refund", "dispute-opened", "dispute-lost"])
def test_refund_and_dispute_deliveries_preserve_subscription_and_original_invoice(paid_stripe_invoice, event_type, fields):
    tenant_id, invoice = paid_stripe_invoice
    assert not billing_service.receive_webhook(_stripe_event_payload("invoice.payment_succeeded", invoice), "qa").duplicate
    resource = {"id": f"stripe_qa_{uuid4().hex}", "currency": "brl", **fields}
    if event_type == "charge.refunded":
        resource |= {"object": "charge", "customer": invoice["customer"]}
    else:
        resource |= {"object": "dispute", "charge": "ch_qa_disputed", "payment_intent": "pi_qa_disputed"}
    payload = _stripe_event_payload(event_type, resource)
    assert not billing_service.receive_webhook(payload, "qa").duplicate
    assert billing_service.receive_webhook(payload, "qa").duplicate
    with SessionLocal() as db:
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        payment = db.scalars(select(BillingPaymentEntity).filter_by(tenant_id=tenant_id)).one()
        delivery = db.scalars(select(BillingEventEntity).filter_by(provider_event_id=json.loads(payload)["id"])).one()
        assert (account.status, account.cancel_at_period_end, account.files_uploaded_in_period) == ("active", False, 7)
        assert (payment.status, payment.amount_paid_minor, payment.provider_payment_id) == ("paid", 2990, invoice["id"])
        assert (delivery.status, delivery.event_type) == ("processed", event_type)


@pytest.mark.parametrize("conflicting_reference", ["customer", "subscription"])
def test_signed_webhook_cannot_move_a_stripe_reference_to_the_wrong_workspace(
    paid_stripe_invoice, monkeypatch, conflicting_reference,
):
    owner_id, invoice = paid_stripe_invoice
    other_id = uuid4()
    with SessionLocal.begin() as db:
        db.add(TenantEntity(id=other_id, name="Other Workspace", slug=f"other-{other_id}"))
        db.flush()
        db.add(BillingAccountEntity(tenant_id=other_id))

    customer_event = conflicting_reference == "customer"
    resource = {"metadata": {"tenant_id": str(other_id)}, "status": "active"}
    if customer_event:
        resource |= {"id": "cs_local_wrong_workspace", "customer": invoice["customer"], "subscription": "sub_new_qa"}
    else:
        resource["id"] = invoice["subscription"]
    event_type = "checkout.session.completed" if customer_event else "customer.subscription.updated"
    payload = _stripe_event_payload(event_type, resource)
    event = json.loads(payload)
    timestamp = str(event["created"])
    secret = "whsec_local_scope_fixture"
    signature = hmac_new(secret.encode(), timestamp.encode() + b"." + payload, sha256).hexdigest()
    monkeypatch.setattr(core_settings, "STRIPE_SECRET_KEY", "sk_test_local_fixture")
    monkeypatch.setattr(core_settings, "STRIPE_RUNTIME_WEBHOOK_SECRET_FILE", None)
    monkeypatch.setattr(core_settings, "STRIPE_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(billing_service, "_get_provider", StripeBillingProvider)

    with TestClient(core_app, raise_server_exceptions=False) as http:
        path = "/billing/webhooks/stripe"
        headers = {"Stripe-Signature": f"t={timestamp},v1={signature}"}
        response = http.post(path, content=payload, headers=headers)
        assert response.status_code == 200 and response.json()["duplicate"] is False
        retry = http.post(path, content=payload, headers=headers)
        assert retry.status_code == 200 and retry.json()["duplicate"] is True
    with SessionLocal() as db:
        owner = db.scalar(select(BillingAccountEntity).filter_by(tenant_id=owner_id))
        other = db.scalar(select(BillingAccountEntity).filter_by(tenant_id=other_id))
        delivery = db.scalars(select(BillingEventEntity).filter_by(provider_event_id=event["id"])).one()
        assert (owner.status, owner.provider_customer_id, owner.provider_subscription_id) == (
            "active", invoice["customer"], invoice["subscription"],
        )
        assert (other.status, other.provider_customer_id, other.provider_subscription_id) == ("not_configured", None, None)
        assert (delivery.status, delivery.error_code, delivery.tenant_id) == ("ignored_stale", "workspace_scope_conflict", None)


def test_paid_invoice_without_metadata_is_routed_by_linked_subscription(paid_stripe_invoice):
    tenant_id, invoice = paid_stripe_invoice
    resource = {key: value for key, value in invoice.items() if key not in {"customer", "metadata"}}
    assert not billing_service.receive_webhook(_stripe_event_payload("invoice.payment_succeeded", resource), "qa").duplicate
    with SessionLocal() as db:
        payment = db.scalars(select(BillingPaymentEntity).filter_by(tenant_id=tenant_id)).one()
        assert payment.provider_payment_id == invoice["id"]


@pytest.mark.parametrize(("field", "value"), [
    ("price_id", "price_unconfigured_qa"), ("quantity", 100), ("customer_id", "cus_unrelated_qa"),
])
def test_checkout_rejects_client_supplied_provider_fields(monkeypatch, field, value):
    checkout_attempts = []

    def checkout(*args, **kwargs):
        checkout_attempts.append((args, kwargs))
        return BillingCheckoutRead(checkout_url="https://checkout.stripe.test/session")

    monkeypatch.setattr(billing_service, "create_checkout", checkout)
    monkeypatch.setattr(auth_context, "_resolve_context", lambda _token: auth_context.AuthContext(
        subject="checkout-qa@example.test", roles=frozenset(), permission_keys=frozenset({"documents:write"}),
    ))
    with TestClient(core_app) as http:
        response = http.post(f"/billing/tenants/{uuid4()}/checkout", headers={"Authorization": "Bearer qa"},
                             json={"product_code": "rubrica_base", "billing_interval": "month", field: value})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert not checkout_attempts


def test_workspace_admin_cannot_open_checkout_for_another_workspace(monkeypatch):
    owner_id, other_id = uuid4(), uuid4()
    subject = "checkout-scope-qa@example.test"
    with SessionLocal.begin() as db:
        for tenant_id in (owner_id, other_id):
            db.add(TenantEntity(id=tenant_id, name="Checkout scope", slug=f"checkout-{tenant_id}", country_code="BR"))
        db.flush()
        db.add(TenantMemberEntity(tenant_id=owner_id, auth_user_id=subject, role="admin"))

    def unexpected_customer(**_kwargs):
        pytest.fail("An unrelated workspace reached the Stripe customer API")

    monkeypatch.setattr(core_settings, "STRIPE_SECRET_KEY", "sk_test_local_fixture")
    monkeypatch.setattr(billing_service, "_get_provider", StripeBillingProvider)
    monkeypatch.setattr(stripe.Customer, "create", unexpected_customer)
    monkeypatch.setattr(auth_context, "_resolve_context", lambda _token: auth_context.AuthContext(
        subject=subject, roles=frozenset(), permission_keys=frozenset({"documents:write"}),
    ))
    with TestClient(core_app) as http:
        response = http.post(f"/billing/tenants/{other_id}/checkout", headers={"Authorization": "Bearer qa"},
                             json={"product_code": "rubrica_base", "billing_interval": "month"})
    assert response.status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(BillingAccountEntity.id).filter_by(tenant_id=other_id)) is None


@pytest.mark.usefixtures("auth_identities")
def test_database_workflow_round_trip(
    tmp_path: Path, trusted_timestamp: dict[str, int]
) -> None:
    service = DatabaseSignatureWorkflowService(LocalDocumentStorage(tmp_path / "objects"))
    organization = f"database-smoke-{uuid4()}"
    try:
        with SessionLocal.begin() as db:
            tenant = TenantEntity(name="Database smoke test", slug=organization)
            db.add(tenant)
            db.flush()
            db.add(
                TenantMemberEntity(
                    tenant_id=tenant.id,
                    auth_user_id="operator",
                    role="admin",
                )
            )
            db.add(
                BillingAccountEntity(
                    tenant_id=tenant.id,
                    status="active",
                    current_product_code="rubrica_base",
                )
            )
        source = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.write(source)
        original = source.getvalue()
        document = service.create_document(DocumentCreate(organization_id=organization, title="Smoke", original_filename="smoke.pdf", content_type="application/pdf", created_by="operator"), original)
        with SessionLocal.begin() as db:
            foreign_tenant = TenantEntity(
                name="Foreign tenant",
                slug=f"foreign-{uuid4()}",
            )
            db.add(foreign_tenant)
            db.flush()
            db.add(
                TenantMemberEntity(
                    tenant_id=foreign_tenant.id,
                    auth_user_id="foreign-user@example.com",
                    role="admin",
                    status="active",
                )
            )
        with pytest.raises(WorkflowError) as cross_tenant_error:
            service.get_content(
                document.id,
                actor_id="foreign-user@example.com",
            )
        assert cross_tenant_error.value.status_code == 403
        request = service.create_request(SignatureRequestCreate(document_id=document.id, expires_at=DateTimeService.utc_now() + timedelta(hours=1), created_by="operator"))
        first_signer = service.add_signer(request.id, SignerCreate(name="Database User", email="database@example.com"), "operator")
        second_signer = service.add_signer(request.id, SignerCreate(name="Second User", email="second@example.com"), "operator")
        for signer in (first_signer, second_signer):
            service.update_signer_signature_mode(request.id, signer.id, "operator", SignatureMode.SERPRO_TIMESTAMP)
        service.open_request(request.id, "operator")
        link = service.create_signing_link(request.id, "operator")
        token = link.signing_url.rsplit("/", maxsplit=1)[-1]
        stamp = StampPosition(page=1, x=0.65, y=0.8)
        trusted_timestamp["failures_remaining"] = 1
        with pytest.raises(RuntimeError, match="simulated timestamp outage"):
            service.sign(token, "database@example.com", True, stamp)
        with SessionLocal() as db:
            failed_operation = db.scalar(
                select(SignatureOperationEntity).where(
                    SignatureOperationEntity.signature_request_id == request.id
                )
            )
            assert failed_operation is not None
            assert failed_operation.status == "failed"
            assert failed_operation.attempt_count == 1
            tenant_id = db.scalar(
                select(DocumentEntity.tenant_id).where(DocumentEntity.id == document.id)
            )
            billing_account = db.scalar(
                select(BillingAccountEntity).where(
                    BillingAccountEntity.tenant_id == tenant_id
                )
            )
            assert billing_account is not None
            assert billing_account.signatures_used == 0
        service.sign(token, "database@example.com", True, stamp)
        service.sign(token, "database@example.com", True, stamp)
        assert trusted_timestamp["count"] == 2
        assert service.get_request(request.id, "operator").status == RequestStatus.OPEN
        assert service.signing_signed_document(token, "second@example.com")[2].startswith(b"%PDF")
        service.sign(token, "second@example.com", True, StampPosition(page=1, x=0.35, y=0.7))
        assert trusted_timestamp["count"] == 3
        consolidated = service.signing_signed_document(token, "second@example.com")[2]
        consolidated_text = "\n".join((page.extract_text() or "") for page in PdfReader(BytesIO(consolidated)).pages)
        assert "Database User" in consolidated_text
        assert "Second User" in consolidated_text
        with SessionLocal() as db:
            signatures = list(db.scalars(
                select(SignatureEntity)
                .where(SignatureEntity.signature_request_id == request.id)
                .order_by(SignatureEntity.signed_at, SignatureEntity.id)
            ).all())
            assert signatures[1].document_sha256 == signatures[0].artifact_sha256

        completed_request = service.get_request(request.id, "operator")
        assert completed_request.status == RequestStatus.COMPLETED
        assert completed_request.document_title == "Smoke"
        assert completed_request.original_filename == "smoke.pdf"
        listed_document = next(
            item for item in service.list_documents("operator") if item.id == document.id
        )
        assert listed_document.size_bytes == len(original)
        assert listed_document.signature_request_count == 1
        assert listed_document.completed_signature_count == 2
        assert service.get_content(document.id)[1] == original
        with SessionLocal.begin() as db:
            persisted_request = db.scalar(select(SignatureRequestEntity).where(SignatureRequestEntity.id == request.id))
            persisted_request.expires_at = DateTimeService.utc_now() - timedelta(days=730)
        assert service.signing_context(token, "database@example.com").stamp == stamp.model_copy(
            update={"country_code": "BR", "template": "BR", "show_flag": True, "locale": "pt-BR"}
        )
        assert service.signing_signed_document(token, "database@example.com")[2].startswith(b"%PDF")
        assert service.get_signing_link(request.id, "operator").signing_url == link.signing_url
        historical_link = service.create_signing_link(request.id, "operator")
        historical_token = historical_link.signing_url.rsplit("/", maxsplit=1)[-1]
        assert service.signing_signed_document(historical_token, "database@example.com")[2].startswith(b"%PDF")
        with pytest.raises(WorkflowError) as denied:
            service.signing_context(historical_token, "outside-admin@example.com", administrator=True)
        assert denied.value.status_code == 403
        with pytest.raises(WorkflowError) as denied:
            service.signing_document(historical_token, "outside-admin@example.com", administrator=True)
        assert denied.value.status_code == 403
        with pytest.raises(WorkflowError) as denied:
            service.signing_signed_document(historical_token, "outside-admin@example.com", administrator=True)
        assert denied.value.status_code == 403
        with SessionLocal() as db:
            owner_tenant_id = db.scalar(select(DocumentEntity.tenant_id).where(DocumentEntity.id == document.id))
        contacts = service.list_signer_contacts(owner_tenant_id, "operator")
        assert [(contact.name, contact.email) for contact in contacts] == [("Second User", "second@example.com"), ("Database User", "database@example.com")]
        assert [contact.email for contact in service.list_signer_contacts(owner_tenant_id, "operator", "database")] == ["database@example.com"]
        with pytest.raises(WorkflowError) as denied:
            service.list_signer_contacts(owner_tenant_id, "outside-admin@example.com")
        assert denied.value.status_code == 403
        administrator_view = service.signing_context(historical_token, "operator", administrator=True)
        assert administrator_view.viewer_mode == "administrator"
        assert administrator_view.request.status == RequestStatus.COMPLETED
        assert service.signing_signed_document(historical_token, "operator", administrator=True)[2].startswith(b"%PDF")
        signer_view = service.signing_context(historical_token, "database@example.com", administrator=True)
        assert signer_view.viewer_mode == "signer"
        filename, artifact_hash, artifact = service.signed_document(request.id)
        assert filename.endswith("signed.pdf")
        assert artifact_hash
        assert artifact.startswith(b"%PDF")
        artifact_metadata = PdfReader(BytesIO(artifact)).metadata
        assert artifact_metadata.get("/RubricaEvidenceJSON")
        evidence = service.signature_evidence(request.id, "operator")
        assert len(evidence) == 2
        assert evidence[0].evidence_sha256
        assert evidence[0].subject_hmac_sha256 != "database@example.com"
        assert "signature.completed" in [event.action for event in service.audit_events(request.id, "operator")]
        with pytest.raises(IntegrityError):
            with SessionLocal.begin() as db:
                signature_id = db.scalar(
                    select(SignatureEntity.id).where(
                        SignatureEntity.signature_request_id == request.id
                    ).limit(1)
                )
                db.execute(
                    update(SignatureEntity)
                    .where(SignatureEntity.id == signature_id)
                    .values(document_sha256="f" * 64)
                )
        with SessionLocal() as db:
            tenant_id = db.scalar(
                select(DocumentEntity.tenant_id).where(DocumentEntity.id == document.id)
            )
            billing_account = db.scalar(
                select(BillingAccountEntity).where(
                    BillingAccountEntity.tenant_id == tenant_id
                )
            )
            assert billing_account is not None
            assert billing_account.signatures_used == 0
            assert billing_account.free_signatures_limit == 5
    finally:
        pass


@pytest.mark.usefixtures("auth_identities")
def test_expired_request_reopens_as_immutable_round_with_signed_base(tmp_path: Path) -> None:
    service = DatabaseSignatureWorkflowService(LocalDocumentStorage(tmp_path / "round-objects"))
    organization = f"reopen-{uuid4()}"
    with SessionLocal.begin() as db:
        tenant = TenantEntity(name="Reopening test", slug=organization)
        db.add(tenant)
        db.flush()
        db.add(TenantMemberEntity(tenant_id=tenant.id, auth_user_id="operator", role="admin"))
        db.add(BillingAccountEntity(tenant_id=tenant.id, status="active", current_product_code="rubrica_base"))
    source = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(source)
    document = service.create_document(DocumentCreate(organization_id=organization, title="Round test", original_filename="round.pdf", content_type="application/pdf", created_by="operator"), source.getvalue())
    first = service.create_request(SignatureRequestCreate(document_id=document.id, expires_at=DateTimeService.utc_now() + timedelta(hours=1), created_by="operator"))
    service.add_signer(first.id, SignerCreate(name="Signed User", email="signed@example.com"), "operator")
    pending = service.add_signer(first.id, SignerCreate(name="Pending User", email="pending@example.com"), "operator")
    service.open_request(first.id, "operator")
    token = service.create_signing_link(first.id, "operator").signing_url.rsplit("/", 1)[-1]
    service.sign(token, "signed@example.com", True, StampPosition(page=1, x=0.5, y=0.5))
    signed_bytes = service.signed_document(first.id, "operator")[2]
    with SessionLocal.begin() as db:
        persisted = db.get(SignatureRequestEntity, first.id)
        assert persisted is not None
        persisted.expires_at = DateTimeService.utc_now() - timedelta(minutes=1)

    assert service.get_request(first.id, "operator").status == RequestStatus.EXPIRED
    with pytest.raises(WorkflowError) as expired_link:
        service.create_signing_link(first.id, "operator")
    assert expired_link.value.status_code == 409
    payload = ReopenSignatureRequest(
        expires_at=DateTimeService.utc_now() + timedelta(days=2),
        reason="Prazo solicitado pelo emissor",
        pending_signer_ids=[pending.id],
    )
    reopened = service.reopen_request(first.id, "operator", payload)
    duplicate = service.reopen_request(first.id, "operator", payload)

    assert duplicate.id == reopened.id
    assert reopened.parent_request_id == first.id
    assert reopened.round_number == 2
    assert reopened.preserved_signature_count == 1
    assert reopened.status == RequestStatus.DRAFT
    assert [item.email for item in service.list_signers(reopened.id, "operator")] == ["pending@example.com"]
    with SessionLocal() as db:
        unchanged = db.get(SignatureRequestEntity, first.id)
        child = db.get(SignatureRequestEntity, reopened.id)
        assert unchanged is not None and unchanged.status == RequestStatus.OPEN.value
        assert child is not None and child.base_artifact_sha256 == sha256(signed_bytes).hexdigest()

    service.open_request(reopened.id, "operator")
    reopened_token = service.create_signing_link(reopened.id, "operator").signing_url.rsplit("/", 1)[-1]
    metadata, presented = service.signing_document(reopened_token, "pending@example.com")
    assert presented == signed_bytes
    assert metadata.sha256 == sha256(signed_bytes).hexdigest()
    service.sign(reopened_token, "pending@example.com", True, StampPosition(page=1, x=0.3, y=0.7))
    final = service.signed_document(reopened.id, "operator")[2]
    evidence = PdfReader(BytesIO(final)).metadata["/RubricaEvidenceJSON"]
    assert evidence.count('"schema":"rubrica-signature-evidence-v1"') == 2
