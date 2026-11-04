from datetime import UTC, datetime, timedelta
from hashlib import sha256
import hmac
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException, Response
import httpx
import pytest
from sqlalchemy import select, func

from test_enterprise_storage import storage_db as make_storage_db
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.enterprise import lifecycle, lifecycle_router as routes, retention, webhooks
from core_api.modules.enterprise.entities import EnterpriseDocument, EnterpriseIntegration
from core_api.modules.enterprise.lifecycle_entity import EnterpriseLifecycle, EnterpriseNotice, EnterprisePurgeCopy, EnterpriseWebhook, EnterpriseWebhookDelivery
from core_api.modules.enterprise.provider_vault import decrypt_configuration
from core_api.modules.enterprise.usage_entity import EnterpriseQuota, EnterpriseUsageEvent
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


@pytest.fixture
def contract_db(monkeypatch, tmp_path):
    env = make_storage_db.__wrapped__(monkeypatch, tmp_path)
    env.context = SimpleNamespace(subject="admin@example.test")
    for module in (retention, webhooks, routes):
        monkeypatch.setattr(module, "SessionLocal", env.sessions)
    monkeypatch.setattr(retention, "configured_document_storage", lambda _: env.store)
    monkeypatch.setattr(retention.settings, "ENTERPRISE_RETENTION_PURGE_ENABLED", True)
    monkeypatch.setattr(webhooks.settings, "ENTERPRISE_WEBHOOK_ALLOWED_HOSTS", "hooks.example.test")
    with env.sessions.begin() as db:
        db.add(TenantEntity(id=env.tenant, name="Enterprise", slug="enterprise"))
        db.add(TenantMemberEntity(tenant_id=env.tenant, auth_user_id=env.context.subject, role="admin", status="active"))
        db.add(BillingAccountEntity(tenant_id=env.tenant, status="active", current_product_code="rubrica_enterprise",
            usage_period_starts_at=NOW - timedelta(days=40), created_at=NOW - timedelta(days=40)))
        db.add(EnterpriseQuota(tenant_id=env.tenant, sandbox=True, storage_bytes=9, document_count=1))
    return env


def suspend(env, *, at=NOW):
    with env.sessions.begin() as db:
        account = db.scalar(select(BillingAccountEntity))
        account.cancel_at_period_end, account.cancels_at = True, at
        lifecycle.sync_contract(db, account, now=at)


def test_cycle_is_fixed_30_days_and_cancellation_has_explicit_deadlines(contract_db):
    env = contract_db
    with env.sessions() as db:
        account = db.scalar(select(BillingAccountEntity))
        assert lifecycle.contract_view(account, now=NOW)["cycle_end"] == NOW + timedelta(days=20)
        account.cancel_at_period_end, account.cancels_at = True, NOW + timedelta(days=2)
        before = lifecycle.contract_view(account, now=NOW)
        assert before["operational"] and before["status"] == "cancellation_pending"
        assert before["delete_after"] == NOW + timedelta(days=32)
        at_cut = lifecycle.contract_view(account, now=NOW + timedelta(days=2))
        assert not at_cut["operational"] and at_cut["recovery"]


def test_authorization_suspends_at_exact_cutoff_without_waiting_for_worker(contract_db):
    with contract_db.sessions() as db:
        account = db.scalar(select(BillingAccountEntity))
        account.cancel_at_period_end, account.cancels_at = True, NOW
        lifecycle.require_operational(db, account, now=NOW - timedelta(microseconds=1))
        with pytest.raises(HTTPException) as error:
            lifecycle.require_operational(db, account, now=NOW)
        assert error.value.status_code == 403


def test_payment_failure_uses_invoice_cutoff_not_another_full_month(contract_db):
    env = contract_db
    with env.sessions.begin() as db:
        account = db.scalar(select(BillingAccountEntity))
        account.status, account.current_period_ends_at = "past_due", NOW + timedelta(days=30)
        lifecycle.mark_payment_failure(db, env.tenant, NOW)
        db.flush()
        view = lifecycle.contract_view(account, lifecycle.lifecycle_for(db, env.tenant), now=NOW)
        assert not view["operational"] and view["suspends_at"] == NOW


def test_notices_deduplicate_and_regularization_before_deadline_cancels_suspension(contract_db):
    env = contract_db
    suspend(env)
    with env.sessions.begin() as db:
        account = db.scalar(select(BillingAccountEntity))
        lifecycle.sync_contract(db, account, now=NOW + timedelta(days=1))
        assert db.scalar(select(func.count()).select_from(EnterpriseNotice).where(EnterpriseNotice.kind == "contract.suspended")) == 1
        account.cancel_at_period_end = False
        state, view = lifecycle.sync_contract(db, account, now=NOW + timedelta(days=20))
        assert view["operational"] and state.suspended_at is None and state.revision == 2
        assert db.scalar(select(EnterpriseNotice).where(EnterpriseNotice.kind == "contract.reactivated"))


def test_deadline_does_not_slide_and_payment_after_expiry_cannot_restore_lost_data(contract_db):
    env = contract_db
    suspend(env)
    with env.sessions.begin() as db:
        account = db.scalar(select(BillingAccountEntity))
        account.cancels_at = NOW + timedelta(days=10)
        state, view = lifecycle.sync_contract(db, account, now=NOW + timedelta(days=5))
        assert lifecycle.utc(view["delete_after"]) == NOW + timedelta(days=30)
        account.cancel_at_period_end = False
        assert not lifecycle.contract_view(account, state, now=NOW + timedelta(days=30))["operational"]


def test_recovery_admin_can_export_but_cannot_rotate_tokens(contract_db, monkeypatch):
    env = contract_db
    from core_api.modules.enterprise.router import require_storage_access, require_enterprise
    suspend(env, at=datetime.now(UTC) - timedelta(days=1))
    with env.sessions() as db:
        require_storage_access(db, env.tenant, env.context)
        with pytest.raises(HTTPException):
            require_enterprise(db, env.tenant, env.context)
    from core_api.modules.signature_request.workflow_service import WorkflowError
    with pytest.raises(WorkflowError):
        routes.contract_status(env.tenant, SimpleNamespace(subject="outsider@example.test"))


def test_purge_waits_30_days_then_removes_current_copy_without_touching_external_storage(contract_db):
    env = contract_db
    suspend(env)
    retention.synchronize_once(now=NOW + timedelta(days=29))
    with env.sessions() as db:
        assert db.scalar(select(EnterprisePurgeCopy)) is None
        assert db.scalar(select(EnterpriseNotice).where(EnterpriseNotice.kind == "contract.purge_warning"))
    retention.synchronize_once(now=NOW + timedelta(days=30))
    assert retention.purge_once(now=NOW + timedelta(days=30))
    retention.synchronize_once(now=NOW + timedelta(days=30))
    with env.sessions() as db:
        document = db.get(EnterpriseDocument, env.document)
        assert document.status == "purged" and document.deleted_at
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 0
        assert db.scalar(select(EnterpriseLifecycle)).status == "purged"
        assert db.scalar(select(func.count()).select_from(EnterpriseUsageEvent).where(EnterpriseUsageEvent.kind == "storage.removed")) == 1
    assert not retention.purge_once(now=NOW + timedelta(days=31))


def test_denied_purge_preserves_references_and_counter_and_retries(contract_db, monkeypatch):
    env = contract_db
    suspend(env)
    retention.synchronize_once(now=NOW + timedelta(days=30))
    monkeypatch.setattr(env.store, "remove_copy", lambda _: (_ for _ in ()).throw(PermissionError("locked")))
    retention.purge_once(now=NOW + timedelta(days=30))
    with env.sessions() as db:
        assert db.scalar(select(EnterprisePurgeCopy)).status == "retry"
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 9
        assert db.get(EnterpriseDocument, env.document).deleted_at is None


def test_disabling_destructive_worker_does_not_extend_operational_access(contract_db, monkeypatch):
    env = contract_db
    monkeypatch.setattr(retention.settings, "ENTERPRISE_RETENTION_PURGE_ENABLED", False)
    suspend(env)
    retention.synchronize_once(now=NOW + timedelta(days=31))
    assert not retention.purge_once(now=NOW + timedelta(days=31))
    with env.sessions() as db:
        state = db.scalar(select(EnterpriseLifecycle))
        assert state.status == "expired"
        assert not lifecycle.contract_view(db.scalar(select(BillingAccountEntity)), state, now=NOW + timedelta(days=31))["operational"]
        assert db.scalar(select(EnterprisePurgeCopy)) is None


def test_stale_purge_intent_is_cancelled_after_timely_regularization(contract_db):
    env = contract_db
    suspend(env)
    with env.sessions.begin() as db:
        document = db.get(EnterpriseDocument, env.document)
        db.add(EnterprisePurgeCopy(tenant_id=env.tenant, integration_id=env.integration, document_id=env.document,
            sandbox=True, source_kind="original", source_id=env.document, storage_key=document.storage_key,
            namespace=document.storage_namespace, size_bytes=9, next_attempt_at=NOW))
        db.scalar(select(BillingAccountEntity)).cancel_at_period_end = False
    retention.purge_once(now=NOW + timedelta(days=10))
    with env.sessions() as db:
        assert db.scalar(select(EnterprisePurgeCopy)).status == "cancelled"
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 9


def configured(env):
    result = routes.configure_webhook(env.tenant, env.integration, routes.WebhookConfiguration(url="https://hooks.example.test/rubrica"), Response(), env.context)
    return result


def test_webhook_secret_only_disclosed_on_rotation_and_encrypted_in_database(contract_db):
    env = contract_db
    first = configured(env)
    second = configured(env)
    assert first["secret"] != second["secret"] and second["version"] == 2
    result = routes.webhook_status(env.tenant, env.integration, env.context)
    assert "secret" not in result
    with env.sessions() as db:
        endpoint = db.scalar(select(EnterpriseWebhook))
        assert second["secret"] not in endpoint.encrypted_secret
        assert decrypt_configuration(env.tenant, f"webhook:{endpoint.id}", True, 2, endpoint.encrypted_secret)["secret"] == second["secret"]


@pytest.mark.parametrize("url", ["http://hooks.example.test", "https://127.0.0.1", "https://hooks.example.test:8443/x",
    "https://user:secret@hooks.example.test", "https://hooks.example.test/x?token=secret", "https://hooks.example.test/#x", "https://attacker.test"])
def test_webhooks_reject_unapproved_or_unsafe_destinations(contract_db, url):
    with pytest.raises(HTTPException):
        webhooks.webhook_url(url)


def enqueue_event(env):
    with env.sessions.begin() as db:
        integration = db.get(EnterpriseIntegration, env.integration)
        event_id = uuid4()
        webhooks.enqueue(db, integration, event_id, "signature.completed", {"source_id": str(uuid4())}, now=NOW)
        webhooks.enqueue(db, integration, event_id, "signature.completed", {"source_id": "must not replace"}, now=NOW)
    return event_id


@pytest.mark.parametrize("status,expected", [(204, "delivered"), (200, "delivered"), (302, "pending"), (429, "pending"), (500, "pending"), (401, "dead"), (410, "dead")])
def test_delivery_is_pinned_signed_bounded_and_status_drives_retries(contract_db, monkeypatch, status, expected):
    env = contract_db
    result = configured(env)
    event_id = enqueue_event(env)
    received = []
    def handler(request):
        received.append(request)
        assert str(request.url) == "https://8.8.8.8/rubrica"
        assert request.headers["Host"] == "hooks.example.test"
        assert request.extensions["sni_hostname"] == "hooks.example.test"
        body = request.read()
        signature = hmac.new(result["secret"].encode(), str(int(NOW.timestamp())).encode() + b"." + body, sha256).hexdigest()
        assert request.headers["X-Rubrica-Signature"] == f"t={int(NOW.timestamp())},v1={signature}"
        assert json.loads(body)["id"] == str(event_id) and json.loads(body)["sandbox"] is True
        return httpx.Response(status, headers={"Location": "http://127.0.0.1"})
    original = httpx.Client
    monkeypatch.setattr(webhooks, "pinned_address", lambda _: "8.8.8.8")
    monkeypatch.setattr(webhooks.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    assert webhooks.dispatch_once(now=NOW)
    assert len(received) == 1
    with env.sessions() as db:
        deliveries = list(db.scalars(select(EnterpriseWebhookDelivery)))
        assert len(deliveries) == 1 and deliveries[0].status == expected and deliveries[0].attempts == 1


def test_retry_window_and_manual_replay_keep_event_id(contract_db):
    env = contract_db
    configured(env)
    event_id = enqueue_event(env)
    webhooks.dispatch_once(now=NOW + timedelta(hours=24))
    with env.sessions() as db:
        row = db.scalar(select(EnterpriseWebhookDelivery))
        row_id = row.id
        assert row.status == "dead" and row.attempts == 0
    result = routes.replay(env.tenant, env.integration, row_id, env.context)
    assert result["event_id"] == event_id
    with pytest.raises(HTTPException):
        routes.replay(env.tenant, uuid4(), row_id, env.context)


def test_notice_email_retries_with_stable_recipient_idempotency_key(contract_db, monkeypatch):
    env = contract_db
    suspend(env)
    from core_api.modules.billing import notification_client
    calls = []
    def failure(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("unavailable")
    monkeypatch.setattr(notification_client, "request_billing_email", failure)
    retention.email_notice_once(now=NOW + timedelta(seconds=1))
    monkeypatch.setattr(notification_client, "request_billing_email", lambda **kwargs: calls.append(kwargs))
    retention.email_notice_once(now=NOW + timedelta(seconds=30))
    assert len(calls) == 2 and calls[0]["idempotency_key"] == calls[1]["idempotency_key"]
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseNotice)).email_complete


def test_timely_payment_is_persisted_before_worker_wakes_after_deadline(contract_db):
    env = contract_db
    suspend(env)
    with env.sessions.begin() as db:
        account = db.scalar(select(BillingAccountEntity))
        account.cancel_at_period_end = False
        lifecycle.regularize_contract(db, account, now=NOW + timedelta(days=29))
    retention.synchronize_once(now=NOW + timedelta(days=31))
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseLifecycle)).status == "active"
        assert db.scalar(select(EnterprisePurgeCopy)) is None
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 9


def test_crash_after_delete_retries_idempotently_without_double_meter_change(contract_db, monkeypatch):
    env = contract_db
    suspend(env)
    retention.synchronize_once(now=NOW + timedelta(days=30))
    original = retention.record_usage
    monkeypatch.setattr(retention, "record_usage", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash")))
    retention.purge_once(now=NOW + timedelta(days=30))
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 9
        assert db.scalar(select(EnterprisePurgeCopy)).status == "retry"
    monkeypatch.setattr(retention, "record_usage", original)
    retention.purge_once(now=NOW + timedelta(days=30, minutes=1))
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 0
        assert db.scalar(select(func.count()).select_from(EnterpriseUsageEvent).where(EnterpriseUsageEvent.kind == "storage.removed")) == 1


def test_purge_includes_soft_deleted_legacy_references_without_negative_meter(contract_db):
    env = contract_db
    with env.sessions.begin() as db:
        db.get(EnterpriseDocument, env.document).deleted_at = NOW - timedelta(days=1)
        quota = db.scalar(select(EnterpriseQuota))
        quota.storage_bytes, quota.document_count = 0, 0
    suspend(env)
    retention.synchronize_once(now=NOW + timedelta(days=30))
    assert retention.purge_once(now=NOW + timedelta(days=30))
    with env.sessions() as db:
        assert db.scalar(select(EnterprisePurgeCopy)).counted is False
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 0
        assert db.get(EnterpriseDocument, env.document).rubrica_copy_deleted_at


def test_changing_endpoint_requires_disable_and_does_not_silently_forward_old_events(contract_db):
    env = contract_db
    configured(env)
    enqueue_event(env)
    payload = routes.WebhookConfiguration(url="https://hooks.example.test/new-path")
    with pytest.raises(HTTPException):
        routes.configure_webhook(env.tenant, env.integration, payload, Response(), env.context)
    routes.disable_webhook(env.tenant, env.integration, env.context)
    routes.configure_webhook(env.tenant, env.integration, payload, Response(), env.context)
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseWebhookDelivery)).status == "dead"
        assert db.scalar(select(EnterpriseWebhookDelivery)).error_code == "endpoint_replaced"


def test_event_size_is_bounded_before_network_delivery():
    with pytest.raises(ValueError):
        webhooks.canonical_body({"data": "x" * 16385})


def test_outbox_deduplicates_even_when_production_session_has_autoflush_disabled(contract_db):
    env = contract_db
    configured(env)
    with env.sessions.begin() as db:
        db.autoflush = False
        integration = db.get(EnterpriseIntegration, env.integration)
        identity = uuid4()
        for _ in range(2):
            webhooks.enqueue(db, integration, identity, "signature.completed", {}, now=NOW)
    with env.sessions() as db:
        assert db.scalar(select(func.count()).select_from(EnterpriseWebhookDelivery)) == 1


def test_schema_roundtrip_preserves_existing_billing_and_document_rows():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa
    path = Path(__file__).parents[1] / "apps/core_api/alembic/versions/0039_enterprise_lifecycle.py"
    spec = importlib.util.spec_from_file_location("enterprise_lifecycle_schema", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(sa.text("CREATE TABLE billing_accounts (id TEXT PRIMARY KEY, status TEXT)"))
        db.execute(sa.text("INSERT INTO billing_accounts VALUES ('account', 'active')"))
        with Operations.context(MigrationContext.configure(db)):
            module.upgrade()
            assert "enterprise_purge_copies" in sa.inspect(db).get_table_names()
            module.downgrade()
        assert db.scalar(sa.text("SELECT status FROM billing_accounts")) == "active"


def test_downgrade_preserves_administrator_recovery_access(contract_db):
    env = contract_db
    cutoff = datetime.now(UTC) - timedelta(days=1)
    suspend(env, at=cutoff)
    with env.sessions.begin() as db:
        account = db.scalar(select(BillingAccountEntity))
        account.current_product_code = "rubrica_team"
    from core_api.modules.enterprise.router import require_storage_access
    with env.sessions() as db:
        require_storage_access(db, env.tenant, env.context)
    assert routes.contract_status(env.tenant, env.context)["recovery"]


def test_recovery_administrator_can_cancel_open_requests_without_losing_completed_signatures(contract_db):
    from core_api.modules.enterprise.entities import EnterpriseRequest, EnterpriseSignature
    env = contract_db
    suspend(env, at=datetime.now(UTC) - timedelta(days=1))
    with env.sessions.begin() as db:
        document = db.get(EnterpriseDocument, env.document)
        request = EnterpriseRequest(compartment_id=env.compartment, document_id=env.document,
            document_sha256=document.sha256, idempotency_key="recovery", payload_sha256="0" * 64, signers=[],
            status="open", expires_at=datetime.now(UTC) + timedelta(days=10), token_public_id="token")
        db.add(request)
        db.flush()
        identity = request.id
        db.add(EnterpriseSignature(request_id=identity, signer_id=uuid4(), signed_at=datetime.now(UTC), evidence={"preserved": True},
            evidence_sha256="0" * 64, evidence_hmac="0" * 64, artifact_storage_key="signed/artifact", artifact_sha256="0" * 64, artifact_size=1))
    assert routes.recovery_requests(env.tenant, env.integration, env.context)[0]["id"] == identity
    assert routes.cancel_recovery_request(env.tenant, env.integration, identity, env.context)["status"] == "cancelled"
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseSignature)).evidence == {"preserved": True}


def test_expiration_worker_emits_one_terminal_event(contract_db):
    from core_api.modules.enterprise.entities import EnterpriseRequest
    env = contract_db
    configured(env)
    with env.sessions.begin() as db:
        document = db.get(EnterpriseDocument, env.document)
        db.add(EnterpriseRequest(compartment_id=env.compartment, document_id=env.document,
            document_sha256=document.sha256, idempotency_key="expired", payload_sha256="0" * 64, signers=[], status="open",
            expires_at=NOW - timedelta(days=1), token_public_id="token"))
    retention.synchronize_once(now=NOW)
    retention.synchronize_once(now=NOW)
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseRequest)).status == "expired"
        assert len([row for row in db.scalars(select(EnterpriseWebhookDelivery)) if row.payload["type"] == "request.expired"]) == 1


def test_cloned_or_cross_environment_event_is_never_dispatched(contract_db, monkeypatch):
    env = contract_db
    configured(env)
    enqueue_event(env)
    with env.sessions.begin() as db:
        row = db.scalar(select(EnterpriseWebhookDelivery))
        row.payload = row.payload | {"environment": "production"}
    monkeypatch.setattr(webhooks, "deliver", lambda *a: pytest.fail("must not contact another environment's endpoint"))
    webhooks.dispatch_once(now=NOW)
    with env.sessions() as db:
        row = db.scalar(select(EnterpriseWebhookDelivery))
        assert row.status == "dead" and row.error_code == "event_binding_mismatch" and row.attempts == 0
