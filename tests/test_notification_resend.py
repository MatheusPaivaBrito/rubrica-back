from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from auth_api.modules.accounts.notification_client import (
    AccountEmailDeliveryError,
    request_account_email,
)
from auth_api.modules.accounts.tenant_client import provision_account_tenant
from auth_api.modules.accounts.account_schema import PublicRegistration
from notification_api.infrastructure.settings import settings as notification_settings
from notification_api.main import app
from notification_api.modules.messaging.contracts.provider import ProviderDelivery
from notification_api.modules.messaging.domains.resend.resend_service import (
    ResendEmailProvider,
)


def test_resend_internal_endpoint_requires_service_authentication() -> None:
    response = TestClient(app).post(
        "/internal/providers/resend/emails",
        json={
            "recipient": "person@example.com",
            "subject": "Verify",
            "content": "Body",
            "idempotency_key": "verification-123",
        },
    )

    assert response.status_code == 403


def test_resend_internal_endpoint_delivers_with_valid_service_key(monkeypatch) -> None:
    monkeypatch.setattr(notification_settings, "NOTIFICATION_INTERNAL_SERVICE_KEY", "test-key")
    monkeypatch.setattr(
        ResendEmailProvider,
        "deliver",
        lambda self, **kwargs: ProviderDelivery(
            provider_message_id="email_123",
            status="accepted",
        ),
    )

    response = TestClient(app).post(
        "/internal/providers/resend/emails",
        headers={
            "X-Rubrica-Service": "auth_api",
            "X-Rubrica-Service-Key": "test-key",
        },
        json={
            "recipient": "person@example.com",
            "subject": "Verify",
            "content": "Body",
            "idempotency_key": "verification-123",
        },
    )

    assert response.status_code == 202
    assert response.json()["provider"] == "resend"
    assert response.json()["delivery_id"] == "email_123"


def test_auth_client_uses_internal_resend_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(
        "auth_api.modules.accounts.notification_client.settings.NOTIFICATION_INTERNAL_SERVICE_KEY",
        "shared-key",
    )
    monkeypatch.setattr("auth_api.modules.accounts.notification_client.httpx.post", fake_post)

    request_account_email(
        recipient="person@example.com",
        subject="Reset",
        body="Use the link",
        idempotency_key="reset-123",
        metadata={"template": "password_recovery"},
    )

    assert str(captured["url"]).endswith("/internal/providers/resend/emails")
    assert captured["headers"] == {
        "X-Rubrica-Service": "auth_api",
        "X-Rubrica-Service-Key": "shared-key",
    }
    assert captured["json"] == {
        "recipient": "person@example.com",
        "subject": "Reset",
        "content": "Use the link",
        "idempotency_key": "reset-123",
    }


def test_auth_client_surfaces_notification_failure(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise __import__("httpx").ConnectError("offline")

    monkeypatch.setattr("auth_api.modules.accounts.notification_client.httpx.post", fail)

    with pytest.raises(AccountEmailDeliveryError):
        request_account_email(
            recipient="person@example.com",
            subject="Reset",
            body="Use the link",
            idempotency_key="reset-123",
            metadata={"template": "password_recovery"},
        )


def test_auth_client_provisions_tenant_with_internal_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(
        "auth_api.modules.accounts.tenant_client.settings.CORE_INTERNAL_SERVICE_KEY",
        "core-key",
    )
    monkeypatch.setattr("auth_api.modules.accounts.tenant_client.httpx.post", fake_post)

    provision_account_tenant(
        PublicRegistration(
            name="Owner",
            email="OWNER@example.com",
            password="secure-password",
            preferred_locale="pt-BR",
        )
    )

    assert str(captured["url"]).endswith("/internal/tenants/provision")
    assert captured["headers"] == {
        "X-Rubrica-Service": "auth_api",
        "X-Rubrica-Service-Key": "core-key",
    }
    assert captured["json"] == {
        "owner_email": "owner@example.com",
        "name": "Owner",
        "default_locale": "pt-BR",
        "country_code": None,
    }


def test_resend_http_errors_do_not_expose_raw_response(monkeypatch) -> None:
    monkeypatch.setattr(notification_settings, "RESEND_API_KEY", "test-api-key")

    def fail(_request, timeout):
        raise HTTPError(
            url="https://api.resend.com/emails",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(
        "notification_api.modules.messaging.domains.resend.resend_service.urlopen",
        fail,
    )

    try:
        ResendEmailProvider(subject="Reset", idempotency_key="reset-123").deliver(
            recipient="person@example.com",
            content="Body",
            media=None,
        )
    except RuntimeError as exc:
        assert "HTTP 401" in str(exc)
        assert "test-api-key" not in str(exc)
    else:
        raise AssertionError("Resend provider should reject an HTTP 401 response")
