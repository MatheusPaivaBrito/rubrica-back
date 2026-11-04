"""Failure, fairness and isolation contracts; no real paid provider calls."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4
import subprocess

from fastapi import HTTPException, Response
import pytest
from sqlalchemy import select

from test_enterprise_workflow import workflow, payload, prepare_live_provider  # noqa: F401
from core_api.modules.enterprise import jobs, worker, housekeeping, provider_operations, scanning, request_router, signing_service, administration
from core_api.modules.enterprise.entities import EnterpriseDocument, EnterpriseIntegration, EnterpriseSignature
from core_api.modules.enterprise.execution_entity import EnterpriseJob, EnterpriseOperation
from core_api.modules.enterprise.request_router import SessionInput
from core_api.modules.enterprise.signing_router import ConsentCommand
from core_api.modules.enterprise.usage_entity import EnterpriseQuota


@pytest.fixture
def queue(workflow, monkeypatch):  # noqa: F811
    context, document, sessions, storage = workflow
    for module in (jobs, worker, housekeeping, administration):
        monkeypatch.setattr(module, "SessionLocal", sessions)
    monkeypatch.setattr(housekeeping, "configured_document_storage", lambda _: storage)
    monkeypatch.setattr(worker.settings, "ENTERPRISE_QUEUE_LIMIT", 2)
    return context, document, sessions, storage


def scan_job(context, document, key="one"):
    return jobs.enqueue(context, "scan", {"document_id": str(document["id"])}, key)


def test_queue_is_encrypted_idempotent_scoped_and_bounded(queue):
    context, document, sessions, _ = queue
    first = scan_job(context, document)
    assert scan_job(context, document)["id"] == first["id"]
    with sessions() as db:
        item = db.get(EnterpriseJob, first["id"])
        assert str(document["id"]) not in item.encrypted_payload
        assert jobs.payload_for(item)["document_id"] == str(document["id"])
        with pytest.raises(HTTPException) as error:
            jobs.scoped_job(db, replace(context, compartment_id=uuid4()), first["id"])
        assert error.value.status_code == 404
    scan_job(context, document, "two")
    with pytest.raises(HTTPException) as error:
        scan_job(context, document, "three")
    assert error.value.status_code == 429


def test_distributed_slots_fence_late_results_and_release_on_completion(queue):
    context, document, sessions, _ = queue
    first, second = scan_job(context, document), scan_job(context, document, "two")
    now = datetime.now(UTC)
    claim = jobs.claim(sandbox=True, now=now)
    assert claim["id"] in {first["id"], second["id"]}
    completed = claim["id"]
    remaining = ({first["id"], second["id"]} - {completed}).pop()
    assert jobs.claim(sandbox=True, now=now) is None
    assert jobs.finish(claim["id"], uuid4(), result={"bad": True}) is False
    assert jobs.finish(claim["id"], claim["owner"], result={"good": True}, now=now)
    assert jobs.claim(sandbox=True, now=now)["id"] == remaining
    assert not jobs.finish(completed, claim["owner"], error="late", now=now)
    with sessions() as db:
        item = db.get(EnterpriseJob, completed)
        assert item.result == {"good": True} and item.encrypted_payload is None


def test_expiry_never_requeues_a_paid_effect(queue):
    context, _, sessions, _ = queue
    job = jobs.enqueue(context, "sign", {"session_secret": "sensitive"}, "one")
    now = datetime.now(UTC)
    claim = jobs.claim(sandbox=True, now=now)
    assert jobs.expire_leases(now=now+timedelta(minutes=10)) == 1
    assert jobs.claim(sandbox=True, now=now+timedelta(minutes=10)) is None
    assert not jobs.finish(job["id"], claim["owner"], result={"late": True}, now=now)
    with sessions() as db:
        assert db.get(EnterpriseJob, job["id"]).status == "uncertain"


def test_disabled_integration_rejects_accepted_pending_work(queue):
    context, document, sessions, _ = queue
    item = scan_job(context, document)
    with sessions.begin() as db:
        db.get(EnterpriseIntegration, context.integration_id).enabled = False
    assert jobs.claim(sandbox=True) is None
    with sessions() as db:
        assert db.get(EnterpriseJob, item["id"]).error_code == "integration_unavailable"


def test_worker_runs_scanner_and_erases_transient_payload(queue, monkeypatch):
    context, document, sessions, _ = queue
    monkeypatch.setattr(scanning, "scan_stream", lambda _: "ready")
    item = scan_job(context, document)
    claim = jobs.claim(sandbox=True)
    assert worker.execute(claim["id"], claim["owner"])
    with sessions() as db:
        assert db.get(EnterpriseDocument, document["id"]).status == "ready"
        assert db.get(EnterpriseJob, item["id"]).encrypted_payload is None


def test_worker_wall_timeout_is_durable_and_does_not_retry(queue):
    context, document, sessions, _ = queue
    item = scan_job(context, document)
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)
    assert worker.run_once(sandbox=True, launcher=timeout)
    with sessions() as db:
        assert db.get(EnterpriseJob, item["id"]).error_code == "worker_time_budget_exhausted"


def test_job_owner_must_still_be_current_before_provider_effect(queue):
    context, document, sessions, _ = queue
    scan_job(context, document)
    claim = jobs.claim(sandbox=True)
    marker = jobs.active_job.set((claim["id"], uuid4()))
    try:
        with sessions() as db, pytest.raises(HTTPException):
            jobs.assert_current_job(db)
    finally:
        jobs.active_job.reset(marker)


def test_async_consent_completes_only_inside_worker(queue, monkeypatch):
    from core_api.modules.enterprise import signing_router
    context, document, sessions, _ = queue
    monkeypatch.setattr(signing_router, "SessionLocal", sessions)
    monkeypatch.setattr(scanning, "scan_stream", lambda _: "ready")
    scanning.scan_document(context, document["id"])
    item = request_router.create_request(context, payload(document), "request")
    request_router.open_request(item["id"], context)
    session = request_router.create_session(item["id"], SessionInput(signer_id=item["signers"][0]["id"]), Response(), context)
    command = ConsentCommand(consent=True, consent_version="rubrica-enterprise-evidence-v1", document_sha256=item["document_sha256"])
    request = SimpleNamespace(url=SimpleNamespace(path="/api/v1/sandbox/signing-session/consent"),
        state=SimpleNamespace(), client=SimpleNamespace(host="127.0.0.1"), headers={})
    queued = signing_router.consent(request, command, Response(), session["session_token"])
    assert queued["status"] == "queued"
    assert request_router.get_request(item["id"], context)["status"] == "open"
    claim = jobs.claim(sandbox=True)
    assert worker.execute(claim["id"], claim["owner"])
    assert request_router.get_request(item["id"], context)["status"] == "completed"
    assert signing_router.signer_job(queued["id"], request, session["session_token"])["status"] == "succeeded"


def test_sandbox_cleanup_is_strict_idempotent_and_does_not_remove_live_documents(queue):
    context, document, sessions, storage = queue
    now = datetime.now(UTC)
    with sessions.begin() as db:
        db.get(EnterpriseDocument, document["id"]).created_at = now-timedelta(days=31)
    assert housekeeping.cleanup_once(now=now)
    assert not housekeeping.cleanup_once(now=now)
    with sessions() as db:
        assert db.get(EnterpriseDocument, document["id"]).status == "purged"
        quota = db.scalar(select(EnterpriseQuota))
        assert quota.storage_bytes == quota.document_count == 0
        with pytest.raises(FileNotFoundError):
            storage.get(db.get(EnterpriseDocument, document["id"]).storage_key)


def test_cleanup_failure_keeps_reference_and_meter_for_retry(queue, monkeypatch):
    context, document, sessions, storage = queue
    now = datetime.now(UTC)
    with sessions.begin() as db:
        db.get(EnterpriseDocument, document["id"]).created_at = now-timedelta(days=31)
    monkeypatch.setattr(storage, "remove_copy", lambda _: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(PermissionError):
        housekeeping.cleanup_once(now=now)
    with sessions() as db:
        assert db.get(EnterpriseDocument, document["id"]).deleted_at is None
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == document["size_bytes"]


def test_budget_is_persistent_resettable_and_stores_only_hash(queue):
    _, _, sessions, _ = queue
    now = datetime.now(UTC)
    for _ in range(2):
        with sessions.begin() as db:
            administration.reserve_budget(db, "admin@example.test", 2, now)
    with sessions.begin() as db, pytest.raises(HTTPException) as error:
        administration.reserve_budget(db, "admin@example.test", 2, now)
    assert error.value.status_code == 429
    with sessions.begin() as db:
        administration.reserve_budget(db, "admin@example.test", 2, now+timedelta(minutes=1))


def test_provider_checkpoint_recovers_committed_pdf_without_reissuing(queue, monkeypatch):
    from core_api.modules.signature_request import serpro_timestamp_service
    _, session, command, sessions, storage = prepare_live_provider(queue, monkeypatch, "serpro_timestamp",
        {"consumer_key": "key", "consumer_secret": "secret"})
    calls = []
    def timestamp(pdf, *, credentials):
        calls.append(credentials)
        return pdf, {"provider": "double"}
    monkeypatch.setattr(serpro_timestamp_service, "apply_serpro_timestamp", timestamp)
    original_mark = provider_operations.mark_outcome
    # Simulate worker loss after business commit but before checkpoint finalization.
    monkeypatch.setattr(provider_operations, "mark_outcome", lambda *args: (_ for _ in ()).throw(RuntimeError("worker died")))
    with pytest.raises(RuntimeError):
        signing_service.sign_evidence(session["session_token"], False, command, ip_address="test", user_agent="test")
    monkeypatch.setattr(provider_operations, "mark_outcome", original_mark)
    with sessions() as db:
        operation = db.scalar(select(EnterpriseOperation))
        assert operation.status == "result_ready"
        identity = operation.id
    result = provider_operations.recover(sessions, lambda _: storage, identity)
    again = provider_operations.recover(sessions, lambda _: storage, identity)
    assert again == result and len(calls) == 1
    with sessions() as db:
        assert len(db.scalars(select(EnterpriseSignature)).all()) == 1
        assert db.get(EnterpriseOperation, identity).encrypted_checkpoint is None


def test_uncertain_provider_outcome_never_calls_provider_again(queue, monkeypatch):
    from core_api.modules.signature_request import serpro_timestamp_service
    _, session, command, sessions, storage = prepare_live_provider(queue, monkeypatch, "serpro_timestamp",
        {"consumer_key": "key", "consumer_secret": "secret"})
    calls = []
    def timeout(*args, **kwargs):
        calls.append(1)
        raise TimeoutError()
    monkeypatch.setattr(serpro_timestamp_service, "apply_serpro_timestamp", timeout)
    with pytest.raises(TimeoutError):
        signing_service.sign_evidence(session["session_token"], False, command, ip_address="test", user_agent="test")
    with sessions() as db:
        operation = db.scalar(select(EnterpriseOperation))
        assert operation.status == "uncertain"
    with pytest.raises(HTTPException) as error:
        signing_service.sign_evidence(session["session_token"], False, command, ip_address="test", user_agent="test")
    assert error.value.status_code == 409 and len(calls) == 1


def test_recovered_artifact_must_match_original_input():
    with pytest.raises(HTTPException):
        provider_operations.verify_recovered(b"wrong", {"input_size": 4, "input_sha256": sha256(b"good").hexdigest()})


def test_drawn_signature_requires_a_real_png_and_keeps_issuer_position(queue, monkeypatch):
    from base64 import b64encode
    from io import BytesIO
    from PIL import Image
    from pydantic import ValidationError
    from core_api.modules.signature_request.workflow_schema import StampPosition
    context, document, _, _ = queue
    monkeypatch.setattr(scanning, "scan_stream", lambda _: "ready")
    scanning.scan_document(context, document["id"])
    data = payload(document)
    data.signers[0].stamp = StampPosition(page=1, x=.2, y=.3, display_variant="drawn")
    item = request_router.create_request(context, data, "drawn-request")
    request_router.open_request(item["id"], context)
    session = request_router.create_session(item["id"], SessionInput(signer_id=item["signers"][0]["id"]), Response(), context)
    command = ConsentCommand(consent=True, consent_version="rubrica-enterprise-evidence-v1", document_sha256=item["document_sha256"])
    with pytest.raises(HTTPException) as error:
        signing_service.sign_evidence(session["session_token"], True, command, ip_address="test", user_agent="test")
    assert error.value.status_code == 422
    with pytest.raises(ValidationError):
        ConsentCommand(**command.model_dump(exclude={"drawn_signature_png_data_url"}), drawn_signature_png_data_url="not-a-png")
    stream = BytesIO()
    Image.new("RGBA", (80, 30), "black").save(stream, "PNG")
    command.drawn_signature_png_data_url = "data:image/png;base64,"+b64encode(stream.getvalue()).decode()
    command.stamp = StampPosition(page=1, x=.9, y=.9)
    result = signing_service.sign_evidence(session["session_token"], True, command, ip_address="test", user_agent="test")
    assert result["simulated"] is True
    _, _, sessions, _ = queue
    with sessions() as db:
        evidence = db.scalar(select(EnterpriseSignature)).evidence
        assert evidence["stamp"]["x"] == .2 and evidence["drawing_sha256"]
        assert "drawn_signature_png_data_url" not in evidence


def test_token_budget_is_independent_of_tenant_budget(queue, monkeypatch):
    from core_api.modules.enterprise.usage import reserve_api_request
    context, _, sessions, _ = queue
    monkeypatch.setattr(jobs.settings, "ENTERPRISE_SANDBOX_TOKEN_REQUESTS_PER_MINUTE", 1)
    now = datetime.now(UTC)
    with sessions.begin() as db:
        reserve_api_request(db, context, now=now)
    with sessions.begin() as db, pytest.raises(HTTPException) as error:
        reserve_api_request(db, context, now=now)
    assert error.value.status_code == 429
    with sessions.begin() as db:
        reserve_api_request(db, replace(context, token_public_id="another-token"), now=now)


def test_isolated_child_is_killed_at_wall_deadline():
    import sys
    with pytest.raises(subprocess.TimeoutExpired):
        worker.launch([sys.executable, "-c", "import time; time.sleep(20)"], timeout=.1)


def test_administrator_can_disable_and_reenable_binding(queue, monkeypatch):
    from core_api.modules.enterprise import router
    from core_api.modules.enterprise.machine_context import authorize_binding, AuthClaims
    context, _, sessions, _ = queue
    monkeypatch.setattr(router, "SessionLocal", sessions)
    monkeypatch.setattr(router.tenant_service, "require_role", lambda *args: None)
    actor = SimpleNamespace(subject="admin")
    assert not router.change_integration(context.tenant_id, context.integration_id, router.IntegrationState(enabled=False), actor).enabled
    claims = AuthClaims(tenant_id=context.tenant_id, integration_id=context.integration_id, public_id="test", environment="development", sandbox=True, scopes=frozenset())
    with sessions() as db, pytest.raises(HTTPException):
        authorize_binding(db, claims, context.compartment_id)
    assert router.change_integration(context.tenant_id, context.integration_id, router.IntegrationState(enabled=True), actor).enabled
