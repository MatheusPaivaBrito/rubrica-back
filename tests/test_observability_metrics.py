import asyncio

from httpx import ASGITransport, AsyncClient

from auth_api.bootstrap.app import create_app as create_auth_app
from core_api.bootstrap.app import create_app as create_core_app
from eventing_api.bootstrap.app import create_app as create_eventing_app
from notification_api.main import app as notification_app


def request(app, path: str):
    async def send():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(path)

    return asyncio.run(send())


def test_all_selected_apis_expose_internal_prometheus_metrics() -> None:
    apps = (
        ("auth_api", create_auth_app()),
        ("core_api", create_core_app()),
        ("eventing_api", create_eventing_app()),
        ("notification_api", notification_app),
    )
    for service, app in apps:
        response = request(app, "/metrics")
        assert response.status_code == 200
        assert "rubrica_http_requests_total" in response.text
        assert service not in {""}


def test_route_labels_use_templates_instead_of_concrete_identifiers() -> None:
    app = create_core_app()
    request(app, "/documents/00000000-0000-0000-0000-000000000001")
    metrics = request(app, "/metrics").text

    assert "/documents/{document_id}" in metrics
    assert "00000000-0000-0000-0000-000000000001" not in metrics
