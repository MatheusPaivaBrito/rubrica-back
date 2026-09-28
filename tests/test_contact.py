import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from core_api.infrastructure.settings import settings
from core_api.modules.contact.router import ContactMessage, contact_config, submit_contact


MESSAGE = {
    "name": "João Teste",
    "email": "joao@example.com",
    "topic": "support",
    "message": "Preciso de ajuda com uma assinatura.",
    "turnstile_token": "valid-token",
}


def test_contact_config_fails_closed_without_turnstile(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CONTACT_TURNSTILE_SITE_KEY", "")
    monkeypatch.setattr(settings, "CONTACT_TURNSTILE_SECRET_KEY", "")
    assert contact_config() == {"turnstile_site_key": ""}
    with pytest.raises(HTTPException) as error:
        submit_contact(ContactMessage(**MESSAGE))
    assert error.value.status_code == 503


def test_contact_verifies_turnstile_before_delivering(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CONTACT_TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setattr(settings, "CONTACT_TURNSTILE_SECRET_KEY", "secret-key")
    monkeypatch.setattr(settings, "CONTACT_INBOX_EMAIL", "contact@example.com")
    sent = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"success": True, "hostname": "example.com"}

    def verify(url, **kwargs):
        assert url.endswith("/siteverify")
        assert kwargs["data"]["secret"] == "secret-key"
        assert kwargs["data"]["response"] == "valid-token"
        return Response()

    monkeypatch.setattr("core_api.modules.contact.router.httpx.post", verify)
    monkeypatch.setattr("core_api.modules.contact.router.request_billing_email", lambda **kwargs: sent.append(kwargs))
    response = submit_contact(ContactMessage(**MESSAGE))
    assert response == {"status": "accepted"}
    assert sent[0]["recipient"] == "contact@example.com"
    assert "joao@example.com" in sent[0]["body"]
    assert sent[0]["subject"] == "[Rubrica contact] support"


def test_contact_rejects_bad_input_and_failed_turnstile(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CONTACT_TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setattr(settings, "CONTACT_TURNSTILE_SECRET_KEY", "secret-key")
    with pytest.raises(ValidationError):
        ContactMessage(**{**MESSAGE, "email": "wrong"})
    with pytest.raises(ValidationError):
        ContactMessage(**{**MESSAGE, "topic": "billing\nBcc: bad"})

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"success": False}

    monkeypatch.setattr("core_api.modules.contact.router.httpx.post", lambda *args, **kwargs: Response())
    with pytest.raises(HTTPException) as error:
        submit_contact(ContactMessage(**MESSAGE))
    assert error.value.status_code == 400


def test_enterprise_contact_includes_company_context(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CONTACT_TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setattr(settings, "CONTACT_TURNSTILE_SECRET_KEY", "secret-key")
    sent = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"success": True, "hostname": "example.com"}

    monkeypatch.setattr("core_api.modules.contact.router.httpx.post", lambda *args, **kwargs: Response())
    monkeypatch.setattr("core_api.modules.contact.router.request_billing_email", lambda **kwargs: sent.append(kwargs))

    response = submit_contact(
        ContactMessage(**{**MESSAGE, "topic": "enterprise", "company": "Acme", "team_size": "21-100"})
    )
    assert response == {"status": "accepted"}
    assert sent[0]["subject"] == "[Rubrica contact] enterprise"
    assert "Company: Acme" in sent[0]["body"]
    assert "Company size: 21-100" in sent[0]["body"]

    with pytest.raises(ValidationError):
        ContactMessage(**{**MESSAGE, "topic": "enterprise"})
