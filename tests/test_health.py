import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core_api.infrastructure.auth_context import authenticated_context
from core_api.main import app as core_app
from auth_api.main import app as auth_app


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

def test_auth_routes_are_registered() -> None:
    paths = {route.path for route in auth_app.routes}

    assert "/health" in paths
    assert "/auth/login" in paths
    assert "/auth/refresh" in paths
    assert "/auth/logout" in paths
    assert "/auth/logout-all" in paths
    assert "/sessions/me" in paths
    assert "/access-control/ui-context" in paths
    assert "/access-control/context" in paths
    assert "/users/signers" in paths


def test_core_business_routes_require_an_access_token() -> None:
    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/documents", "query_string": b""})

    with pytest.raises(HTTPException) as error:
        asyncio.run(authenticated_context(request, None))

    assert error.value.status_code == 401
