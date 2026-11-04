"""HTTP contract across independent Auth/Core stores with no external providers."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from test_enterprise_postgres_execution import pg_workflow  # noqa: F401


@pytest.fixture
def http_environment(pg_workflow, monkeypatch):  # noqa: F811
    from auth_api.infrastructure.database.connection import Base as AuthBase
    from auth_api.modules.machine_credentials import router as auth
    from core_api.bootstrap.app import create_app
    from core_api.modules.enterprise import machine_context, signing_router, worker, telemetry, scanning
    context, _, sessions, storage = pg_workflow
    monkeypatch.setattr(signing_router, "configured_document_storage", lambda _: storage)
    for module in (machine_context, signing_router, worker, telemetry):
        monkeypatch.setattr(module, "SessionLocal", sessions)
    auth_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    from auth_api.modules.machine_credentials.entity import MachineCredentialEntity, MachineCredentialAuditEntity, MachineRetirementEntity
    AuthBase.metadata.create_all(auth_engine, tables=[item.__table__ for item in (
        MachineCredentialEntity, MachineCredentialAuditEntity, MachineRetirementEntity)])
    monkeypatch.setattr(auth, "SessionLocal", sessionmaker(auth_engine, expire_on_commit=False))
    monkeypatch.setattr(auth.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(auth.settings, "CORE_INTERNAL_SERVICE_KEY", "http-test-internal")
    monkeypatch.setattr(machine_context.settings, "CORE_INTERNAL_SERVICE_KEY", "http-test-internal")
    monkeypatch.setattr(scanning, "scan_stream", lambda _: "ready")
    auth_app = FastAPI()
    auth_app.include_router(auth.router)
    auth_client = TestClient(auth_app)
    async_client = httpx.AsyncClient
    monkeypatch.setattr(machine_context.httpx, "AsyncClient", lambda **kwargs: async_client(
        transport=httpx.ASGITransport(app=auth_app), **kwargs))
    def internal_post(url, **kwargs):
        assert "/internal/machine-credentials/" in url
        return auth_client.post("/internal/" + url.split("/internal/", 1)[1],
            headers=kwargs["headers"], json=kwargs["json"])
    monkeypatch.setattr(machine_context.httpx, "post", internal_post)
    client = TestClient(create_app())
    headers = {"X-Rubrica-Service": "core_api", "X-Rubrica-Service-Key": "http-test-internal"}
    binding = dict(tenant_id=str(context.tenant_id), integration_id=str(context.integration_id), environment="development",
        sandbox=True, subject="admin", scopes=["documents:create", "documents:read", "documents:download",
            "signature_requests:create", "signature_requests:read", "signature_requests:open", "signing_sessions:create"])
    response = auth_client.post("/internal/machine-credentials/rotate", headers=headers, json=binding)
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    yield client, auth_client, context, headers, binding, token
    client.close()
    auth_client.close()
    auth_engine.dispose()


def test_http_sandbox_document_to_signed_result_and_rotated_token(http_environment):
    from core_api.modules.enterprise import jobs, worker
    from core_api.modules.enterprise.developer_portal import sample_pdf
    client, auth_client, context, service_headers, binding, token = http_environment
    base = f"/api/v1/sandbox/compartments/{context.compartment_id}"
    headers = {"Authorization": f"Bearer {token}"}
    uploaded = client.post(f"{base}/documents?filename=ficticio.pdf", headers=headers | {
        "Content-Type": "application/pdf", "Idempotency-Key": "http-upload"}, content=sample_pdf())
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()
    scanned = client.post(f"{base}/documents/{document['id']}/scan", headers=headers)
    assert scanned.status_code == 202, scanned.text
    claim = jobs.claim(sandbox=True)
    assert worker.execute(claim["id"], claim["owner"])
    assert client.get(f"{base}/jobs/{scanned.json()['id']}", headers=headers).json()["status"] == "succeeded"
    request = client.post(f"{base}/signature-requests", headers=headers | {"Idempotency-Key": "http-request"}, json={
        "document_id": document["id"], "expires_at": (datetime.now(UTC)+timedelta(days=1)).isoformat(),
        "signers": [{"external_id": "fake-person", "name": "Ficticio", "email": "ficticio@example.test", "signature_mode": "evidence",
            "stamp": {"page": 1, "x": .5, "y": .8, "locale": "pt-BR"}}]})
    assert request.status_code == 201, request.text
    item = request.json()
    assert client.post(f"{base}/signature-requests/{item['id']}/open", headers=headers).status_code == 200
    response = client.post(f"{base}/signature-requests/{item['id']}/sessions", headers=headers, json={"signer_id": item["signers"][0]["id"]})
    assert response.status_code == 200, response.text
    restricted = {"Authorization": f"Bearer {response.json()['session_token']}"}
    consent = client.post("/api/v1/sandbox/signing-session/consent", headers=restricted, json={
        "consent": True, "consent_version": "rubrica-enterprise-evidence-v1", "document_sha256": item["document_sha256"]})
    assert consent.status_code == 202, consent.text
    claim = jobs.claim(sandbox=True)
    assert worker.execute(claim["id"], claim["owner"])
    result = client.get(f"/api/v1/sandbox/signing-session/jobs/{consent.json()['id']}", headers=restricted)
    assert result.status_code == 200 and result.json()["status"] == "succeeded"
    pdf = client.get(f"{base}/signature-requests/{item['id']}/artifact", headers=headers)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["cache-control"] == "private, no-store"
    assert client.get(f"/api/v1/sandbox/compartments/{uuid4()}/documents", headers=headers).status_code == 404
    assert client.get(f"/api/v1/compartments/{context.compartment_id}/documents", headers=headers).status_code == 401
    rotated = auth_client.post("/internal/machine-credentials/rotate", headers=service_headers, json=binding)
    assert rotated.status_code == 200
    assert client.get(f"{base}/documents", headers=headers).status_code == 401
    assert auth_client.post("/internal/machine-credentials/introspect", json={"secret": token, "sandbox": True, "permission": "documents:read"}).status_code == 403


def test_public_documentation_has_self_hosted_assets_and_no_internal_schema(http_environment):
    client = http_environment[0]
    page = client.get("/docs")
    assert page.status_code == 200 and "Content-Security-Policy" in page.headers
    assert client.get("/docs/style.css").headers["content-type"].startswith("text/css")
    schema = client.get("/docs/openapi.json").json()
    assert all(path.startswith("/api/v1/") for path in schema["paths"])
    assert not any("internal" in path for path in schema["paths"])
    assert client.get("/docs/sample.pdf").content.startswith(b"%PDF")
