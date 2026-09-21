import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from auth_api.infrastructure.settings import settings
from auth_api.modules.sessions.session_router import login
from auth_api.modules.sessions.session_schema import LoginRequest
from auth_api.modules.sessions.turnstile import verify_login_turnstile


def test_production_login_fails_closed_without_turnstile_keys(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "AUTH_TURNSTILE_SITE_KEY", "")
    monkeypatch.setattr(settings, "AUTH_TURNSTILE_SECRET_KEY", "")

    monkeypatch.setattr("auth_api.modules.sessions.session_router.session_service.login", lambda _payload: pytest.fail("Credentials must not be checked"))
    request = Request({"type": "http", "method": "POST", "path": "/auth/login", "headers": [], "client": ("203.0.113.8", 1234)})
    with pytest.raises(HTTPException) as error:
        asyncio.run(login(LoginRequest(email="user@example.com", password="password123"), Response(), request))
    assert error.value.status_code == 503


def test_login_turnstile_checks_action_hostname_and_ip(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "AUTH_PUBLIC_WEB_URL", "https://rubricasignature.com")
    monkeypatch.setattr(settings, "AUTH_TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setattr(settings, "AUTH_TURNSTILE_SECRET_KEY", "secret-key")
    calls = []

    def verify(_url, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"success": True, "action": "login", "hostname": "rubricasignature.com"})

    monkeypatch.setattr("auth_api.modules.sessions.turnstile.httpx.post", verify)
    verify_login_turnstile("valid-token", "203.0.113.8")

    assert calls[0]["data"] == {"secret": "secret-key", "response": "valid-token", "remoteip": "203.0.113.8"}


@pytest.mark.parametrize("response", [
    {"success": False, "action": "login", "hostname": "rubricasignature.com"},
    {"success": True, "action": "contact", "hostname": "rubricasignature.com"},
    {"success": True, "action": "login", "hostname": "evil.example"},
])
def test_login_turnstile_rejects_invalid_claims(monkeypatch, response) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "AUTH_PUBLIC_WEB_URL", "https://rubricasignature.com")
    monkeypatch.setattr(settings, "AUTH_TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setattr(settings, "AUTH_TURNSTILE_SECRET_KEY", "secret-key")
    monkeypatch.setattr("auth_api.modules.sessions.turnstile.httpx.post", lambda *_args, **_kwargs: SimpleNamespace(raise_for_status=lambda: None, json=lambda: response))

    with pytest.raises(HTTPException) as error:
        verify_login_turnstile("valid-token")
    assert error.value.status_code == 400


def test_login_turnstile_requires_token_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "AUTH_TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setattr(settings, "AUTH_TURNSTILE_SECRET_KEY", "secret-key")

    with pytest.raises(HTTPException) as error:
        verify_login_turnstile(None)
    assert error.value.status_code == 400
