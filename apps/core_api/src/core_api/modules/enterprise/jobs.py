"""Encrypted durable jobs, distributed lease limits and scope-restricted polling."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from uuid import UUID, uuid4
from contextvars import ContextVar

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.enterprise.entities import EnterpriseIntegration, EnterpriseSigningSession
from core_api.modules.enterprise.execution_entity import EnterpriseExecutionSlot, EnterpriseJob
from core_api.modules.enterprise.lifecycle import lock_operational
from core_api.modules.enterprise.machine_context import MachineContext, require_machine
from core_api.modules.enterprise.provider_vault import encrypt_configuration, decrypt_configuration

router = APIRouter(tags=["enterprise processing jobs"])
active_job = ContextVar("enterprise_active_job", default=None)


def job_read(job):
    return {"id": job.id, "kind": job.kind, "status": job.status, "result": job.result, "error_code": job.error_code,
            "attempts": job.attempts, "sandbox": job.sandbox}


def enqueue(context, kind, payload, idempotency):
    if kind not in {"scan", "sign", "serpro_callback", "reconcile"}:
        raise ValueError("Unsupported processing kind")
    digest = sha256(json.dumps([str(context.compartment_id), context.sandbox, kind, idempotency], separators=(",", ":")).encode()).hexdigest()
    with SessionLocal.begin() as db:
        lock_operational(db, context.tenant_id)
        existing = db.scalar(select(EnterpriseJob).where(EnterpriseJob.dedup_key == digest))
        if existing:
            return job_read(existing)
        count = db.scalar(select(func.count()).select_from(EnterpriseJob).where(EnterpriseJob.tenant_id == context.tenant_id,
            EnterpriseJob.sandbox == context.sandbox, EnterpriseJob.status.in_(["queued", "running"])))
        if count >= settings.ENTERPRISE_QUEUE_LIMIT:
            raise HTTPException(429, "Tenant processing queue is full", headers={"Retry-After": "10"})
        item = EnterpriseJob(id=uuid4(), tenant_id=context.tenant_id, integration_id=context.integration_id,
            compartment_id=context.compartment_id, sandbox=context.sandbox, kind=kind, dedup_key=digest)
        secret = payload.get("session_secret") or payload.get("attempt", {}).get("session_secret")
        if secret:
            item.signing_session_id = db.scalar(select(EnterpriseSigningSession.id).where(
                EnterpriseSigningSession.digest == sha256(secret.encode()).hexdigest()))
        item.encrypted_payload = encrypt_configuration(context.tenant_id, f"processing-job:{item.id}", context.sandbox, 1, payload)
        db.add(item)
        db.flush()
        return job_read(item)


def payload_for(job):
    if not job.encrypted_payload:
        raise HTTPException(410, "Processing payload was erased")
    return decrypt_configuration(job.tenant_id, f"processing-job:{job.id}", job.sandbox, 1, job.encrypted_payload)


def claim(*, sandbox, now=None):
    now = now or datetime.now(UTC)
    with SessionLocal.begin() as db:
        saturated = select(EnterpriseJob.tenant_id).where(EnterpriseJob.sandbox == sandbox,
            EnterpriseJob.status == "running", EnterpriseJob.lease_until > now).group_by(EnterpriseJob.tenant_id).having(
                func.count() >= (1 if sandbox else settings.ENTERPRISE_TENANT_CONCURRENCY))
        candidates = db.scalars(select(EnterpriseJob).join(EnterpriseIntegration, EnterpriseIntegration.id == EnterpriseJob.integration_id).where(
            EnterpriseIntegration.environment == settings.ENVIRONMENT, EnterpriseJob.sandbox == sandbox,
            EnterpriseJob.status == "queued", EnterpriseJob.tenant_id.not_in(saturated)).order_by(EnterpriseJob.created_at, EnterpriseJob.id).limit(25))
        job = None
        # A tenant holding a long signing transaction cannot stall other tenants.
        for candidate in candidates:
            account = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == candidate.tenant_id)
                .with_for_update(skip_locked=True))
            if account is not None:
                job = candidate
                break
        if job is None:
            return None
        try:
            lock_operational(db, job.tenant_id)
        except HTTPException:
            job.status, job.error_code, job.encrypted_payload = "failed", "contract_unavailable", None
            return None
        integration = db.get(EnterpriseIntegration, job.integration_id)
        if not integration.enabled or integration.deleted_at is not None:
            job.status, job.error_code, job.encrypted_payload = "failed", "integration_unavailable", None
            return None
        # Account lock serializes admission for this tenant across processes.
        active = db.scalar(select(func.count()).select_from(EnterpriseJob).where(EnterpriseJob.tenant_id == job.tenant_id,
            EnterpriseJob.sandbox == sandbox, EnterpriseJob.status == "running", EnterpriseJob.lease_until > now))
        if active >= (1 if sandbox else settings.ENTERPRISE_TENANT_CONCURRENCY):
            return None
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        limit = 1 if sandbox else settings.ENTERPRISE_EXECUTION_CONCURRENCY
        for number in range(limit):
            db.execute(insert(EnterpriseExecutionSlot).values(id=uuid4(), environment=settings.ENVIRONMENT, sandbox=sandbox, number=number)
                .on_conflict_do_nothing(index_elements=["environment", "sandbox", "number"]))
        slot = db.scalar(select(EnterpriseExecutionSlot).where(EnterpriseExecutionSlot.environment == settings.ENVIRONMENT,
            EnterpriseExecutionSlot.sandbox == sandbox, EnterpriseExecutionSlot.number < limit,
            or_(EnterpriseExecutionSlot.lease_until.is_(None), EnterpriseExecutionSlot.lease_until <= now))
            .order_by(EnterpriseExecutionSlot.number).limit(1).with_for_update(skip_locked=True))
        if slot is None:
            return None
        job = db.scalar(select(EnterpriseJob).where(EnterpriseJob.id == job.id, EnterpriseJob.status == "queued")
            .with_for_update(skip_locked=True).execution_options(populate_existing=True))
        if job is None:
            return None
        job.status, job.owner, job.attempts = "running", uuid4(), job.attempts + 1
        job.lease_until = now + timedelta(seconds=settings.ENTERPRISE_JOB_TIMEOUT_SECONDS + 15)
        slot.job_id, slot.lease_until = job.id, job.lease_until
        return {"id": job.id, "owner": job.owner, "timeout": settings.ENTERPRISE_JOB_TIMEOUT_SECONDS}


def finish(identity, owner, *, result=None, error=None, now=None):
    now = now or datetime.now(UTC)
    with SessionLocal.begin() as db:
        job = db.scalar(select(EnterpriseJob).where(EnterpriseJob.id == identity).with_for_update())
        if job is None or job.owner != owner or job.status != "running":
            return False
        if job.lease_until is None or (job.lease_until.replace(tzinfo=UTC) if job.lease_until.tzinfo is None else job.lease_until) <= now:
            error = "processing_lease_expired"
        job.status = "succeeded" if error is None else "uncertain" if job.kind != "scan" else "failed"
        job.result, job.error_code = result if error is None else None, error
        if error is None:
            job.encrypted_payload = None
        for slot in db.scalars(select(EnterpriseExecutionSlot).where(EnterpriseExecutionSlot.job_id == identity)):
            slot.job_id, slot.lease_until = None, None
        return True


def expire_leases(*, now=None):
    now = now or datetime.now(UTC)
    with SessionLocal.begin() as db:
        rows = list(db.scalars(select(EnterpriseJob).join(EnterpriseIntegration, EnterpriseIntegration.id == EnterpriseJob.integration_id)
            .where(EnterpriseIntegration.environment == settings.ENVIRONMENT, EnterpriseJob.status == "running", EnterpriseJob.lease_until <= now)
            .order_by(EnterpriseJob.id).limit(50).with_for_update(of=EnterpriseJob, skip_locked=True)))
        for job in rows:
            job.status, job.error_code = ("failed" if job.kind == "scan" else "uncertain"), "worker_lease_expired"
        return len(rows)


def scoped_job(db, context, identity):
    item = db.scalar(select(EnterpriseJob).where(EnterpriseJob.id == identity, EnterpriseJob.tenant_id == context.tenant_id,
        EnterpriseJob.integration_id == context.integration_id, EnterpriseJob.compartment_id == context.compartment_id,
        EnterpriseJob.sandbox == context.sandbox))
    if item is None:
        raise HTTPException(404, "Processing job not found")
    return item


@router.get("/api/v1/compartments/{compartment_id}/jobs/{job_id}")
@router.get("/api/v1/sandbox/compartments/{compartment_id}/jobs/{job_id}")
def poll_job(job_id: UUID, context: MachineContext = Depends(require_machine("documents:read"))):
    with SessionLocal() as db:
        return job_read(scoped_job(db, context, job_id))


@router.post("/api/v1/compartments/{compartment_id}/jobs/{job_id}/retry", status_code=202)
@router.post("/api/v1/sandbox/compartments/{compartment_id}/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: UUID, context: MachineContext = Depends(require_machine("documents:create"))):
    with SessionLocal.begin() as db:
        lock_operational(db, context.tenant_id)
        item = scoped_job(db, context, job_id)
        if item.kind != "scan":
            raise HTTPException(403, "Signature retries require the original restricted signer session")
        if item.status not in {"failed", "uncertain"} or not item.encrypted_payload:
            raise HTTPException(409, "Only retained failed/uncertain jobs can be retried")
        # Paid-effect fencing remains in provider_operations; this cannot issue
        # another signature for an uncertain provider outcome.
        item.status, item.error_code = "queued", None
        return job_read(item)


def assert_current_job(db):
    active = active_job.get()
    if active is None:
        return
    job = db.get(EnterpriseJob, active[0])
    expiry = job.lease_until.replace(tzinfo=UTC) if job and job.lease_until and job.lease_until.tzinfo is None else job.lease_until if job else None
    if not job or job.owner != active[1] or job.status != "running" or not expiry or expiry <= datetime.now(UTC):
        raise HTTPException(409, "Processing lease no longer permits a provider effect")
