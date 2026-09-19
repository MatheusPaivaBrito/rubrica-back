from fastapi.testclient import TestClient

from core_api.main import app
from core_api.infrastructure.settings import settings


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
    client = TestClient(app)
    assert client.get("/contact/config").json() == {"turnstile_site_key": ""}
    assert client.post("/contact/messages", json=MESSAGE).status_code == 503


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
    response = TestClient(app).post("/contact/messages", json=MESSAGE)
    assert response.status_code == 202
    assert sent[0]["recipient"] == "contact@example.com"
    assert "joao@example.com" in sent[0]["body"]
    assert sent[0]["subject"] == "[Rubrica contact] support"


def test_contact_rejects_bad_input_and_failed_turnstile(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CONTACT_TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setattr(settings, "CONTACT_TURNSTILE_SECRET_KEY", "secret-key")
    client = TestClient(app)
    assert client.post("/contact/messages", json={**MESSAGE, "email": "wrong"}).status_code == 422
    assert client.post("/contact/messages", json={**MESSAGE, "topic": "billing\nBcc: bad"}).status_code == 422

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"success": False}

    monkeypatch.setattr("core_api.modules.contact.router.httpx.post", lambda *args, **kwargs: Response())
    assert client.post("/contact/messages", json=MESSAGE).status_code == 400


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

    response = TestClient(app).post(
        "/contact/messages",
        json={**MESSAGE, "topic": "enterprise", "company": "Acme", "team_size": "21-100"},
    )

    assert response.status_code == 202
    assert sent[0]["subject"] == "[Rubrica contact] enterprise"
    assert "Company: Acme" in sent[0]["body"]
    assert "Company size: 21-100" in sent[0]["body"]

    incomplete = TestClient(app).post(
        "/contact/messages",
        json={**MESSAGE, "topic": "enterprise"},
    )
    assert incomplete.status_code == 422
