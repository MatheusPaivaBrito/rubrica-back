from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
import pytest


def test_auth_internal_routes_reject_external_calls(monkeypatch):
    from auth_api.modules.machine_credentials.router import router, settings
    monkeypatch.setattr(settings, "CORE_INTERNAL_SERVICE_KEY", "service-secret")
    app = FastAPI()
    app.include_router(router)
    # Reject at the dependency boundary without a threadpool/real network.
    from auth_api.modules.machine_credentials.router import require_core
    for headers in (("", ""), ("core_api", "wrong"), ("other", "service-secret")):
        with pytest.raises(HTTPException) as error:
            require_core(*headers)
        assert error.value.status_code == 403
    require_core("core_api", "service-secret")
    assert {route.path for route in app.routes} >= {
        "/internal/machine-credentials/rotate", "/internal/machine-credentials/revoke",
        "/internal/machine-credentials/introspect",
    }


def test_core_requires_enterprise_contract_and_membership(monkeypatch):
    from core_api.modules.enterprise.router import require_enterprise, tenant_service
    calls = []
    monkeypatch.setattr(tenant_service, "require_role", lambda *args: calls.append(args))
    context = SimpleNamespace(subject="admin@example.com")
    tenant = uuid4()
    from datetime import UTC, datetime, timedelta
    past = datetime.now(UTC) - timedelta(days=1)
    for account in (None, SimpleNamespace(current_product_code="rubrica_team", status="active"),
                    SimpleNamespace(current_product_code="rubrica_enterprise", status="past_due", cancel_at_period_end=False,
                        usage_period_starts_at=past, created_at=past, current_period_ends_at=past)):
        rows = iter([account, None])
        with pytest.raises(HTTPException) as error:
            require_enterprise(SimpleNamespace(scalar=lambda _: next(rows)), tenant, context)
        assert error.value.status_code == 403
    account = SimpleNamespace(current_product_code="rubrica_enterprise", status="active", cancel_at_period_end=False,
        usage_period_starts_at=datetime.now(UTC), created_at=datetime.now(UTC))
    rows = iter([account, None])
    require_enterprise(SimpleNamespace(scalar=lambda _: next(rows)), tenant, context)
    assert calls[-1][1:] == (tenant, context.subject, {"admin"})


def test_auth_rejects_environment_mismatch(monkeypatch):
    from auth_api.modules.machine_credentials.router import settings, validate_environment
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(HTTPException) as error:
        validate_environment("staging")
    assert error.value.status_code == 403
