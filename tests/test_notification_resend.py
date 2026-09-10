from urllib.error import HTTPError

from fastapi.testclient import TestClient

from auth_api.modules.accounts.notification_client import request_account_email
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
