import asyncio

import pytest
from fastapi import HTTPException
from fastapi import Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from core_api.infrastructure.auth_context import authenticated_context
from core_api.main import app as core_app
from auth_api.main import app as auth_app
from auth_api.modules.sessions.session_router import _set_auth_cookies
from auth_api.modules.sessions.session_schema import LoginResponse


def test_core_routes_are_registered() -> None:
    paths = {route.path for route in core_app.routes}

    assert "/health" in paths
    assert "/ui-manifest" in paths
    assert "/items" not in paths
    assert "/documents" in paths
    assert "/documents/{document_id}/versions" in paths
    assert "/documents/{document_id}/download" in paths
    assert "/signature-requests" in paths
    assert "/signature-requests/{request_id}/signers" in paths
    assert "/signature-requests/{request_id}/audit" in paths
    assert "/signing/links/{token}/sign" in paths
    assert "/signing/links/{token}/document" in paths
    assert "/signing/links/{token}/download" in paths
    assert "/signing/links/{token}/signed-document" in paths
    assert "/signature-requests/{request_id}/signed-document" in paths
    assert "/signature-requests/{request_id}/evidence" in paths
    assert "/tenants" in paths
    assert "/tenants/{tenant_id}/members" in paths
    assert "/tenants/{tenant_id}/preferences" in paths
    assert "/billing/tenants/{tenant_id}/account" in paths
    assert "/billing/tenants/{tenant_id}/payments" in paths
    assert "/billing/tenants/{tenant_id}/checkout" in paths
    assert "/billing/tenants/{tenant_id}/portal" in paths
    assert "/billing/webhooks/stripe" in paths
    assert "/internal/tenants/provision" in paths


def test_internal_tenant_provisioning_requires_service_authentication() -> None:
    response = TestClient(core_app).post(
        "/internal/tenants/provision",
        json={
            "owner_email": "owner@example.com",
            "name": "Owner",
            "default_locale": "en",
        },
    )

    assert response.status_code == 403


def test_auth_routes_are_registered() -> None:
    paths = {route.path for route in auth_app.routes}

    assert "/health" in paths
    assert "/auth/login" in paths
    assert "/auth/refresh" in paths
    assert "/auth/logout" in paths
    assert "/auth/logout-all" in paths
    assert "/auth/register" in paths
    assert "/auth/verify-email/request" in paths
    assert "/auth/verify-email" in paths
    assert "/auth/password-recovery" in paths
    assert "/auth/password-reset" in paths
    assert "/auth/mfa/setup" in paths
    assert "/auth/mfa/confirm" in paths
    assert "/auth/mfa" in paths
    assert "/auth/mfa/challenge" in paths
    assert "/auth/mfa/status" in paths
    assert "/auth/mfa/recovery-codes" in paths
    assert "/sessions/me" in paths
    assert "/access-control/ui-context" in paths
    assert "/access-control/context" in paths
    assert "/users/signers" in paths
    assert "/users/me/preferences" in paths


def test_production_auth_cookies_are_secure_and_persistent(monkeypatch) -> None:
    monkeypatch.setattr("auth_api.modules.sessions.session_router.settings.ENVIRONMENT", "production")
    response = Response()

    _set_auth_cookies(
        response,
        LoginResponse(access_token="access-token", refresh_token="refresh-token", session_id="session-id"),
    )

    cookies = response.headers.getlist("set-cookie")
    assert any("access_token=" in cookie and "Max-Age=900" in cookie and "Secure" in cookie and "HttpOnly" in cookie for cookie in cookies)
    assert any("refresh_token=" in cookie and "Max-Age=604800" in cookie and "Secure" in cookie and "HttpOnly" in cookie for cookie in cookies)


def test_core_business_routes_require_an_access_token() -> None:
    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/documents", "query_string": b""})

    with pytest.raises(HTTPException) as error:
        asyncio.run(authenticated_context(request, None))

    assert error.value.status_code == 401
