"""Isolated Core-owned workers. No HTTP listener, no cross-service database reads."""
import argparse
from datetime import UTC, datetime, timedelta
import json
import logging
import os
import resource
import signal
import subprocess
import sys
import time
from uuid import UUID

from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.enterprise import jobs
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseIntegration, EnterpriseRequest, EnterpriseSigningSession
from core_api.modules.enterprise.execution_entity import EnterpriseJob, EnterpriseOperation
from core_api.modules.enterprise.machine_context import AuthClaims, authorize_binding

logger = logging.getLogger(__name__)


def execute(identity, owner):
    try:
        return _execute(identity, owner)
    except Exception:
        jobs.finish(identity, owner, error="processing_unavailable")
        return False


def _execute(identity, owner):
    with SessionLocal() as db:
        job = db.get(EnterpriseJob, identity)
        if not job or job.owner != owner or job.status != "running":
            return False
        payload = jobs.payload_for(job)
        context = authorize_binding(db, AuthClaims(tenant_id=job.tenant_id, integration_id=job.integration_id,
            public_id=payload.get("token_public_id", "processing-worker"), environment=settings.ENVIRONMENT,
            sandbox=job.sandbox, scopes=frozenset()), job.compartment_id)
        kind = job.kind
    marker = jobs.active_job.set((identity, owner))
    try:
        if kind == "scan":
            from core_api.modules.enterprise.scanning import scan_document
            result = scan_document(context, UUID(payload["document_id"]))
        elif kind == "sign":
            from core_api.modules.enterprise.signing_router import ConsentCommand
            from core_api.modules.enterprise.signing_service import sign_evidence
            result = sign_evidence(payload["session_secret"], context.sandbox, ConsentCommand.model_validate(payload["command"]),
                ip_address=payload["ip_address"], user_agent=payload["user_agent"])
        elif kind == "serpro_callback":
            from core_api.modules.enterprise.serproid_authorization import complete_authorization
            result = complete_authorization(UUID(payload["tenant_id"]), payload["attempt"], payload["code"])
        elif kind == "reconcile":
            from core_api.modules.enterprise.provider_operations import recover
            from core_api.modules.document.storage import configured_document_storage
            result = recover(SessionLocal, configured_document_storage, UUID(payload["operation_id"]))
        else:
            raise ValueError("Invalid processing kind")
        result = json.loads(json.dumps(result, default=str))
        return jobs.finish(identity, owner, result=result)
    except Exception:
        jobs.finish(identity, owner, error="processing_failed_or_uncertain")
        return False
    finally:
        jobs.active_job.reset(marker)


def child_limits():
    # A separate PID contains parser memory/CPU and a hard parent wall timeout.
    memory = settings.ENTERPRISE_JOB_MEMORY_MIB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (settings.ENTERPRISE_JOB_TIMEOUT_SECONDS, settings.ENTERPRISE_JOB_TIMEOUT_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)


def launch(command, *, timeout, **kwargs):
    process = subprocess.Popen(command, start_new_session=True, preexec_fn=child_limits)
    try:
        return subprocess.CompletedProcess(command, process.wait(timeout=timeout))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise


def run_once(*, sandbox=False, launcher=launch):
    jobs.expire_leases()
    claim = jobs.claim(sandbox=sandbox)
    if not claim:
        return False
    try:
        result = launcher([sys.executable, "-m", "core_api.modules.enterprise.worker", "--job", str(claim["id"]), "--owner", str(claim["owner"])],
            timeout=claim["timeout"], check=False, preexec_fn=child_limits)
        if result.returncode:
            jobs.finish(claim["id"], claim["owner"], error="worker_process_failed")
    except subprocess.TimeoutExpired:
        jobs.finish(claim["id"], claim["owner"], error="worker_time_budget_exhausted")
    return True


def recover_once(*, now=None):
    from core_api.modules.enterprise.provider_operations import recover
    from core_api.modules.document.storage import configured_document_storage
    now = now or datetime.now(UTC)
    with SessionLocal() as db:
        operation = db.scalar(select(EnterpriseOperation).join(EnterpriseRequest, EnterpriseRequest.id == EnterpriseOperation.request_id)
            .join(EnterpriseCompartment, EnterpriseCompartment.id == EnterpriseRequest.compartment_id)
            .join(EnterpriseIntegration, EnterpriseIntegration.id == EnterpriseCompartment.integration_id).where(
                EnterpriseIntegration.environment == settings.ENVIRONMENT, EnterpriseOperation.status.in_(["prepared", "remote_pending", "uncertain", "result_ready"]))
            .order_by(EnterpriseOperation.updated_at).limit(1))
        if operation is None:
            return False
        identity, status = operation.id, operation.status
        updated = operation.updated_at.replace(tzinfo=UTC) if operation.updated_at.tzinfo is None else operation.updated_at
    if status != "result_ready" and now - updated < timedelta(seconds=settings.ENTERPRISE_JOB_TIMEOUT_SECONDS + 15):
        return False
    if status == "prepared":
        with SessionLocal.begin() as db:
            current = db.scalar(select(EnterpriseOperation).where(EnterpriseOperation.id == identity).with_for_update())
            if current.status == "prepared":
                current.status, current.owner, current.error_code = "failed", UUID(int=0), "expired_before_provider"
        return True
    try:
        result = recover(SessionLocal, configured_document_storage, identity)
        with SessionLocal.begin() as db:
            operation = db.get(EnterpriseOperation, identity)
            session_ids = select(EnterpriseSigningSession.id).where(EnterpriseSigningSession.request_id == operation.request_id,
                EnterpriseSigningSession.signer_id == operation.signer_id)
            for job in db.scalars(select(EnterpriseJob).where(EnterpriseJob.signing_session_id.in_(session_ids),
                EnterpriseJob.status.in_(["uncertain", "failed"]))):
                job.status, job.result, job.encrypted_payload, job.error_code = "succeeded", json.loads(json.dumps(result, default=str)), None, None
    except Exception:
        with SessionLocal.begin() as db:
            current = db.scalar(select(EnterpriseOperation).where(EnterpriseOperation.id == identity).with_for_update())
            if current.status in {"remote_pending", "uncertain", "result_ready"}:
                if current.status != "result_ready":
                    current.status = "uncertain"
                current.error_code = "provider_result_requires_reconciliation"
                current.updated_at = now
    return True


def maintenance_once():
    from core_api.modules.enterprise.telemetry import relay_once
    from core_api.modules.enterprise.retention import synchronize_once, purge_once, email_notice_once
    from core_api.modules.enterprise.closure import finalize_once
    from core_api.modules.enterprise.storage_migration import migrate_once
    from core_api.modules.enterprise.storage_removal import remove_once
    from core_api.modules.enterprise.webhooks import dispatch_once
    from core_api.modules.enterprise.housekeeping import cleanup_once
    operations = [recover_once, cleanup_once, finalize_once]
    if settings.ENTERPRISE_LIFECYCLE_WORKER_ENABLED:
        operations += [synchronize_once, purge_once, email_notice_once, dispatch_once]
    if settings.ENTERPRISE_STORAGE_WORKER_ENABLED:
        operations += [migrate_once, remove_once]
    if settings.ENTERPRISE_TELEMETRY_RELAY_ENABLED:
        operations += [relay_once]
    for operation in operations:
        try:
            operation()
        except Exception:
            logger.warning("Enterprise maintenance deferred", extra={"operation": operation.__name__})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=["live", "sandbox", "maintenance"], default="live")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--job", type=UUID)
    parser.add_argument("--owner", type=UUID)
    args = parser.parse_args()
    if args.job:
        if not args.owner:
            parser.error("A fenced owner is required")
        raise SystemExit(0 if execute(args.job, args.owner) else 1)
    while True:
        if args.lane == "maintenance":
            maintenance_once()
        else:
            run_once(sandbox=args.lane == "sandbox")
        if args.once:
            return
        time.sleep(1 if args.lane != "maintenance" else 5)


if __name__ == "__main__":
    main()
