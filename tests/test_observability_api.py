import asyncio

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from observability_api.bootstrap.app import create_app
from observability_api.infrastructure.grafana_client import GrafanaClient, GrafanaStatus
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
    async def unavailable(_self) -> GrafanaStatus:
        return GrafanaStatus(available=False, reason="connection")

    monkeypatch.setattr("observability_api.infrastructure.grafana_client.GrafanaClient.status", unavailable)
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
    for forbidden in ("user_id", "tenant_id", "document_id", "request_id", "trace_id", "email"):
        assert forbidden not in response.text


class StubAsyncClient:
    def __init__(self, outcome, **_kwargs) -> None:
        self.outcome = outcome

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def get(self, url: str, **_kwargs):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome(url)


@pytest.mark.parametrize(
    ("outcome", "reason"),
    (
        (httpx.TimeoutException("timeout"), "timeout"),
        (httpx.ConnectError("connection"), "connection"),
        (lambda url: httpx.Response(401, request=httpx.Request("GET", url)), "http_401"),
        (lambda url: httpx.Response(403, request=httpx.Request("GET", url)), "http_403"),
        (lambda url: httpx.Response(429, request=httpx.Request("GET", url)), "http_429"),
        (lambda url: httpx.Response(500, request=httpx.Request("GET", url)), "http_500"),
        (
            lambda url: httpx.Response(
                200,
                request=httpx.Request("GET", url),
                content=b"not-json",
            ),
            "invalid_response",
        ),
    ),
)
def test_grafana_client_degrades_without_leaking_credentials(
    monkeypatch, outcome, reason
) -> None:
    monkeypatch.setattr(
        "observability_api.infrastructure.grafana_client.httpx.AsyncClient",
        lambda **kwargs: StubAsyncClient(outcome, **kwargs),
    )
    client = GrafanaClient(
        base_url="http://grafana:3000",
        timeout_seconds=1,
        service_token="secret-token",
    )

    status = asyncio.run(client.status())

    assert status == GrafanaStatus(available=False, reason=reason)
    assert "secret-token" not in repr(status)


def test_grafana_client_reports_platform_version(monkeypatch) -> None:
    def outcome(url: str) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"version": "12.0.0"},
        )

    monkeypatch.setattr(
        "observability_api.infrastructure.grafana_client.httpx.AsyncClient",
        lambda **kwargs: StubAsyncClient(outcome, **kwargs),
    )

    status = asyncio.run(
        GrafanaClient(base_url="http://grafana:3000", timeout_seconds=1).status()
    )

    assert status == GrafanaStatus(available=True, version="12.0.0")
