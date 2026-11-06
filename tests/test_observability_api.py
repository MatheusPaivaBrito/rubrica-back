import asyncio

from httpx import ASGITransport, AsyncClient

from observability_api.bootstrap.app import create_app
from observability_api.infrastructure.settings import settings


def request(app, method: str, path: str, **kwargs):
    async def send():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_health_does_not_depend_on_platform_infra() -> None:
    response = request(create_app(), "GET", "/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_platform_status_reports_unavailable(monkeypatch) -> None:
    async def unavailable():
        return {"operational": False, "authorized": False, "reason": "connection"}

    monkeypatch.setattr("observability_api.modules.platform_status.service.ensure", unavailable)
    monkeypatch.setattr(settings, "OBSERVABILITY_INTERNAL_SERVICE_KEY", "test-service-key")

    response = request(
        create_app(),
        "GET",
        "/internal/observability/platform/status",
        headers={"X-Rubrica-Service-Key": "test-service-key"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "unavailable",
        "provider": "grafana",
        "version": None,
        "reason": "connection",
    }


def test_platform_status_rejects_missing_or_invalid_internal_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OBSERVABILITY_INTERNAL_SERVICE_KEY", "expected-key")
    app = create_app()
    assert request(app, "GET", "/internal/observability/platform/status").status_code == 403
    response = request(
        app,
        "GET",
        "/internal/observability/platform/status",
        headers={"X-Rubrica-Service-Key": "wrong-key"},
    )
    assert response.status_code == 403
    assert "expected-key" not in response.text


def test_metrics_use_rubrica_namespace_without_sensitive_labels() -> None:
    response = request(create_app(), "GET", "/metrics")

    assert response.status_code == 200
    assert "rubrica_http_requests_total" in response.text
    assert "rubrica_business_metrics_collection_success" in response.text
    assert "nexodesk_" not in response.text
    from prometheus_client.parser import text_string_to_metric_families
    forbidden = {"user_id", "tenant_id", "document_id", "request_id", "trace_id", "email"}
    for family in text_string_to_metric_families(response.text):
        for sample in family.samples:
            # Route templates may contain {document_id}; actual identity labels may not.
            assert not forbidden.intersection(sample.labels)
