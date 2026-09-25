import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from redis import Redis
from starlette.requests import Request

from auth_api.infrastructure.settings import settings
from auth_api.main import app
from auth_api.modules.sessions.session_schema import LoginRequest, LoginResponse
from auth_api.modules.sessions.session_router import require_mfa_session
from auth_api.modules.sessions.session_service import SessionService, session_service
from core_api.infrastructure.auth_context import authenticated_context
from core_api.infrastructure.auth_context import _resolve_context
from core_api.infrastructure.settings import settings as core_settings


def test_browser_auth_responses_keep_refresh_token_in_httponly_cookie(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "AUTH_PUBLIC_WEB_URL", "https://rubricasignature.com")
    tokens = LoginResponse(access_token="access-secret", refresh_token="refresh-secret", session_id="session-id")
    monkeypatch.setattr(session_service, "login", lambda payload: tokens)
    monkeypatch.setattr(session_service, "refresh", lambda token: tokens)
    monkeypatch.setattr("auth_api.modules.sessions.session_router.verify_login_turnstile", lambda *_args: None)
    client = TestClient(app, base_url="https://rubricasignature.com")

    login = client.post("/auth/login", json={"email": "person@example.com", "password": "password123"})
    assert login.status_code == 200
    assert login.json()["access_token"] == "access-secret"
    assert "refresh_token" not in login.json()
    assert "refresh_token=refresh-secret" in "; ".join(login.headers.get_list("set-cookie"))

    assert client.post("/auth/refresh", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    refresh = client.post("/auth/refresh", json={}, headers={"Origin": "https://rubricasignature.com"})
    assert refresh.status_code == 200
    assert "refresh_token" not in refresh.json()

    monkeypatch.setattr(session_service, "refresh", lambda token: None)
    rejected = client.post("/auth/refresh", json={}, headers={"Origin": "https://rubricasignature.com"})
    assert rejected.status_code == 401
    assert "Max-Age=0" in "; ".join(rejected.headers.get_list("set-cookie"))


def test_session_checks_password_token_version(monkeypatch) -> None:
    user = SimpleNamespace(id=uuid4(), is_active=True, token_version=2)

    class Database:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, *_args):
            return user

    monkeypatch.setattr("auth_api.modules.sessions.session_service.SessionLocal", Database)
    assert SessionService._user_is_active({"user_id": str(user.id), "token_version": 2})
    assert not SessionService._user_is_active({"user_id": str(user.id), "token_version": 1})
    assert not SessionService._user_is_active({"user_id": str(user.id)})


def test_access_lookup_rejects_stale_mapping_during_rotation(monkeypatch) -> None:
    service = SessionService()
    service._redis = SimpleNamespace(get=lambda _key: "session-id")
    monkeypatch.setattr(service, "_load_state", lambda _session_id: {"access_key": "new-token-key"})
    assert service._state_for_token("access", "old-token") is None


@pytest.mark.parametrize("role", ["signature_admin", "signature_operator", "signature_signer"])
def test_account_context_requires_mfa_before_granting_roles(monkeypatch, role: str) -> None:
    user = SimpleNamespace(id=uuid4(), public_slug="account-public", preferred_locale="pt-BR", mfa_enabled=False, mfa_exempt=False)

    class Database:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, *_args):
            return user

    service = SessionService()
    monkeypatch.setattr(service, "current_session", lambda _token: SimpleNamespace(subject="user@example.com", session_id="session"))
    monkeypatch.setattr(service, "_state_for_token", lambda *_args: {"user_id": str(user.id), "session_id": "session"})
    monkeypatch.setattr("auth_api.modules.sessions.session_service.SessionLocal", Database)
    monkeypatch.setattr("auth_api.modules.sessions.session_service.access_control_service.context_for_user", lambda _id: ([role], ["*"]))

    context = service.ui_context("access-token")

    assert context.account_public_slug == "account-public"
    assert context is not None
    assert context.mfa_setup_required
    assert context.roles == []
    assert context.permission_keys == []

    user.mfa_enabled = True
    enabled_context = service.ui_context("access-token")
    assert enabled_context is not None
    assert not enabled_context.mfa_setup_required
    assert enabled_context.roles == [role]
    assert enabled_context.permission_keys == ["*"]

    user.mfa_enabled = False
    user.mfa_exempt = True
    exempt_context = service.ui_context("access-token")
    assert exempt_context is not None
    assert not exempt_context.mfa_setup_required
    assert exempt_context.roles == [role]
    assert exempt_context.permission_keys == ["*"]


def test_core_rejects_account_without_mfa(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            return b'{"subject":"user@example.com","mfa_setup_required":true,"roles":[],"permission_keys":[]}'

    monkeypatch.setattr("core_api.infrastructure.auth_context.urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(HTTPException) as error:
        _resolve_context("access-token")
    assert error.value.status_code == 403


def test_auth_profile_requires_completed_mfa(monkeypatch) -> None:
    request = Request({"type": "http", "method": "GET", "path": "/users/me/identifiers", "headers": []})
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="access-token")
    monkeypatch.setattr(session_service, "current_session", lambda _token: SimpleNamespace(subject="user@example.com", session_id="session"))
    monkeypatch.setattr(session_service, "ui_context", lambda _token: SimpleNamespace(mfa_setup_required=True))

    with pytest.raises(HTTPException) as error:
        asyncio.run(require_mfa_session(request, credentials))
    assert error.value.status_code == 403


def test_core_rejects_cross_origin_cookie_mutations(monkeypatch) -> None:
    monkeypatch.setattr(core_settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(core_settings, "PUBLIC_WEB_URL", "https://rubricasignature.com")
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/documents",
        "headers": [(b"cookie", b"access_token=secret"), (b"origin", b"https://evil.example")],
    })
    with pytest.raises(HTTPException) as error:
        asyncio.run(authenticated_context(request, None))
    assert error.value.status_code == 403

    monkeypatch.setattr("core_api.infrastructure.auth_context._resolve_context", lambda _token: "allowed")
    bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    assert asyncio.run(authenticated_context(request, bearer)) == "allowed"


@pytest.mark.skipif(not os.getenv("RUBRICA_TEST_REDIS_URL"), reason="requires isolated Redis")
def test_login_attempts_are_limited_with_real_redis(monkeypatch) -> None:
    redis = Redis.from_url(os.environ["RUBRICA_TEST_REDIS_URL"], decode_responses=True)
    prefix = f"rubrica-login-test-{uuid4().hex}"
    monkeypatch.setattr(settings, "AUTH_REDIS_KEY_PREFIX", prefix)
    calls = []

    class Database:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def scalar(self, *_args):
            calls.append(1)
            return None

    monkeypatch.setattr("auth_api.modules.sessions.session_service.SessionLocal", Database)
    service = SessionService()
    service._redis = redis
    try:
        for _ in range(11):
            assert service.login(LoginRequest(email="person@example.com", password="wrongpass")) is None
        assert len(calls) == 10
    finally:
        keys = list(redis.scan_iter(f"{prefix}:*"))
        if keys:
            redis.delete(*keys)


@pytest.mark.skipif(not os.getenv("RUBRICA_TEST_REDIS_URL"), reason="requires isolated Redis")
def test_refresh_rotation_replay_and_logout_with_real_redis(monkeypatch) -> None:
    redis = Redis.from_url(os.environ["RUBRICA_TEST_REDIS_URL"], decode_responses=True)
    prefix = f"rubrica-security-test-{uuid4().hex}"
    monkeypatch.setattr(settings, "AUTH_REDIS_KEY_PREFIX", prefix)
    user = SimpleNamespace(id=uuid4(), email="person@example.com", token_version=1, is_active=True)
    monkeypatch.setattr(SessionService, "_user_is_active", staticmethod(lambda state: user.is_active and state.get("token_version") == user.token_version))
    service = SessionService()
    service._redis = redis
    try:
        original = service._create_session(user)
        assert service.current_session(original.access_token) is not None
        rotated = service.refresh(original.refresh_token)
        assert rotated is not None
        assert rotated.refresh_token != original.refresh_token
        assert service.current_session(original.access_token) is None
        assert service.current_session(rotated.access_token) is not None
        assert service.refresh(original.refresh_token) is None
        assert service.current_session(rotated.access_token) is None

        another = service._create_session(user)
        user.token_version += 1
        assert service.current_session(another.access_token) is None
        assert service.refresh(another.refresh_token) is None
        user.token_version -= 1

        racing = service._create_session(user)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(service.refresh, [racing.refresh_token] * 2))
        assert sum(result is not None for result in results) == 1
        assert service.current_session(racing.access_token) is None
    finally:
        keys = list(redis.scan_iter(f"{prefix}:*"))
        if keys:
            redis.delete(*keys)
