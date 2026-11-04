"""Fence paid effects before the network and checkpoint verified PDFs separately.

A timeout is uncertainty, never permission to issue another paid signature.
"""
import asyncio
from contextlib import nullcontext
from datetime import datetime
from hashlib import sha256
from hmac import new as hmac_new
from io import BytesIO
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from core_api.infrastructure.settings import settings
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseIntegration, EnterpriseRequest, EnterpriseSignature, EnterpriseSigningSession
from core_api.modules.enterprise.execution_entity import EnterpriseOperation
from core_api.modules.enterprise.lifecycle import contract_view, lifecycle_for
from core_api.modules.enterprise.machine_context import MachineContext
from core_api.modules.enterprise.provider_vault import encrypt_configuration, decrypt_configuration
from core_api.modules.enterprise.storage_settings import for_mode
from core_api.modules.enterprise.usage import record_usage, reserve_signature, reserve_storage


def command_hash(command):
    return sha256(json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepare(sessions, resolver, secret, sandbox, command):
    if sandbox:
        return None
    with sessions.begin() as db:
        context, request, signer, session = resolver(db, secret, sandbox, lock=True)
        if signer["signature_mode"] == "evidence":
            return None
        existing = db.scalar(select(EnterpriseOperation).where(EnterpriseOperation.request_id == request.id,
            EnterpriseOperation.signer_id == session.signer_id).with_for_update())
        if existing and existing.command_sha256 != command_hash(command):
            raise HTTPException(409, "A provider operation cannot change its consent command")
        if existing and existing.status in {"remote_pending", "uncertain", "result_ready", "completed"}:
            return {"id": existing.id, "owner": existing.owner, "signature_id": existing.signature_id, "status": existing.status}
        busy = db.scalar(select(EnterpriseOperation.id).where(EnterpriseOperation.request_id == request.id,
            EnterpriseOperation.status.in_(["prepared", "remote_pending", "uncertain", "result_ready"])).limit(1))
        if busy:
            raise HTTPException(409, "A previous provider operation must be resolved before signing again")
        if existing is None:
            existing = EnterpriseOperation(id=uuid4(), request_id=request.id, signer_id=session.signer_id,
                tenant_id=context.tenant_id, signature_id=uuid4(), command_sha256=command_hash(command), owner=uuid4(), status="prepared")
            db.add(existing)
        else:
            existing.owner, existing.status, existing.error_code = uuid4(), "prepared", None
        db.flush()
        return {"id": existing.id, "owner": existing.owner, "signature_id": existing.signature_id, "status": "prepared"}


def checkpoint(db, operation, payload):
    operation.encrypted_checkpoint = encrypt_configuration(operation.tenant_id, f"signature-operation:{operation.id}", False, 1, payload)


def load(operation):
    if not operation.encrypted_checkpoint:
        raise HTTPException(409, "Provider checkpoint is unavailable")
    return decrypt_configuration(operation.tenant_id, f"signature-operation:{operation.id}", False, 1, operation.encrypted_checkpoint)


def remote_started(sessions, token, context, pdf, evidence, provider_evidence):
    with sessions.begin() as db:
        from core_api.modules.enterprise.jobs import assert_current_job
        assert_current_job(db)
        operation = db.scalar(select(EnterpriseOperation).where(EnterpriseOperation.id == token["id"]).with_for_update())
        if operation.status != "prepared" or operation.owner != token["owner"]:
            raise HTTPException(409, "Provider operation ownership expired")
        mode = "live"
        key = f"tenants/{context.tenant_id}/enterprise/{mode}/{context.integration_id}/{context.compartment_id}/{operation.signature_id}/result"
        checkpoint(db, operation, {"input_sha256": sha256(pdf).hexdigest(), "input_size": len(pdf), "storage_key": key,
            "evidence": evidence, "provider_evidence": provider_evidence, "signed_at": evidence["signed_at"]})
        operation.status = "remote_pending"


def save_result(sessions, token, storage, artifact, provider_evidence):
    with sessions() as db:
        operation = db.get(EnterpriseOperation, token["id"])
        payload = load(operation)
    digest = sha256(artifact).hexdigest()
    try:
        size = storage.put_existing(payload["storage_key"], BytesIO(artifact), sha256=digest)
    except FileExistsError:
        from core_api.modules.enterprise.document_access import verified_content
        with verified_content(storage, payload["storage_key"], digest, len(artifact)):
            pass
        size = len(artifact)
    with sessions.begin() as db:
        operation = db.scalar(select(EnterpriseOperation).where(EnterpriseOperation.id == token["id"]).with_for_update())
        if operation.owner != token["owner"] or operation.status != "remote_pending":
            raise HTTPException(409, "Provider operation ownership changed")
        payload.update(artifact_sha256=digest, artifact_size=size, provider_evidence=provider_evidence)
        checkpoint(db, operation, payload)
        operation.status, operation.error_code = "result_ready", None
    return payload["storage_key"], size


def mark_outcome(sessions, token, success):
    with sessions.begin() as db:
        operation = db.scalar(select(EnterpriseOperation).where(EnterpriseOperation.id == token["id"]).with_for_update())
        if operation.owner != token["owner"]:
            return
        if success:
            operation.status, operation.error_code = "completed", None
            operation.encrypted_checkpoint = None
        elif operation.status == "prepared":
            operation.status, operation.error_code = "failed", "failed_before_provider"
        elif operation.status == "remote_pending":
            operation.status, operation.error_code = "uncertain", "provider_result_uncertain"


def verify_recovered(artifact, payload):
    if len(artifact) > 100_000_000 or sha256(artifact[:payload["input_size"]]).hexdigest() != payload["input_sha256"]:
        raise HTTPException(409, "Recovered PDF does not match the consented provider input")
    mode = payload["evidence"]["signature_mode"]
    if mode == "serpro_timestamp":
        from core_api.modules.signature_request.serpro_timestamp_service import validate_pdf_timestamp
        return validate_pdf_timestamp(artifact)
    if mode != "serproid" or not settings.ENTERPRISE_SERPROID_TRUST_ROOTS_FILE:
        raise HTTPException(503, "Recovery trust configuration is unavailable")
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import async_validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext
    from core_api.modules.signature_request.serpro_timestamp_service import _load_trust_roots
    signatures = PdfFileReader(BytesIO(artifact), strict=True).embedded_signatures
    if not signatures:
        raise HTTPException(409, "Recovered certificate signature is missing")
    signature = signatures[-1]
    expected = (payload.get("provider_evidence") or {}).get("certificate_sha256")
    if signature.signer_cert.sha256.hex() != expected:
        raise HTTPException(409, "Recovered signature certificate does not match the authorized signer")
    context = ValidationContext(trust_roots=_load_trust_roots(settings.ENTERPRISE_SERPROID_TRUST_ROOTS_FILE),
        allow_fetching=True, revocation_mode="require")
    result = asyncio.run(async_validate_pdf_signature(signature, signer_validation_context=context))
    if not result.intact or not result.valid or not result.trusted or result.revoked or getattr(result.coverage, "name", "") != "ENTIRE_FILE":
        raise HTTPException(409, "Recovered signature failed cryptographic verification")
    return payload["provider_evidence"]


def recover(sessions, storage_factory, identity, *, artifact=None):
    from core_api.modules.billing.billing_entity import BillingAccountEntity
    with sessions.begin() as db:
        operation = db.get(EnterpriseOperation, identity)
        if operation is None:
            raise HTTPException(404, "Provider operation not found")
        account = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == operation.tenant_id).with_for_update())
        view = contract_view(account, lifecycle_for(db, operation.tenant_id))
        if not (view["operational"] or view["recovery"]):
            raise HTTPException(403, "The contract no longer allows recovery of this result")
        db.scalar(select(EnterpriseRequest).where(EnterpriseRequest.id == operation.request_id).with_for_update())
        existing = db.get(EnterpriseSignature, operation.signature_id)
        if existing is not None:
            operation.status, operation.error_code, operation.encrypted_checkpoint = "completed", None, None
            from core_api.modules.enterprise.signing_service import signature_read
            return signature_read(existing, False)
        return _recover_locked(db, sessions, storage_factory, identity, artifact=artifact)


def _recover_locked(guard_db, sessions, storage_factory, identity, *, artifact=None):
    # Snapshot read only; cryptographic verification may fetch revocation data.
    with sessions() as db:
        operation = db.get(EnterpriseOperation, identity)
        payload = load(operation)
        status = operation.status
    storage = storage_factory(for_mode(settings, False))
    if status in {"remote_pending", "uncertain"}:
        if artifact is None:
            try:
                with storage.get(payload["storage_key"]) as stream:
                    artifact = stream.read(100_000_001)
            except FileNotFoundError as exc:
                raise HTTPException(409, "Provider outcome is uncertain; reconcile the original result without reissuing") from exc
        provider_evidence = verify_recovered(artifact, payload)
        token = {"id": identity, "owner": operation.owner}
        # This writes bytes only; it never invokes a signature provider.
        with sessions.begin() as db:
            current = db.get(EnterpriseOperation, identity)
            current.status = "remote_pending"
        save_result(sessions, token, storage, artifact, provider_evidence)
    with nullcontext(guard_db) as db:
        operation = db.get(EnterpriseOperation, identity)
        db.refresh(operation)
        payload = load(operation)
        request = db.scalar(select(EnterpriseRequest).where(EnterpriseRequest.id == operation.request_id).with_for_update())
        compartment = db.get(EnterpriseCompartment, request.compartment_id)
        integration = db.get(EnterpriseIntegration, compartment.integration_id)
        if integration.tenant_id != operation.tenant_id or integration.environment != settings.ENVIRONMENT or integration.sandbox:
            raise HTTPException(409, "Provider recovery binding mismatch")
        existing = db.get(EnterpriseSignature, operation.signature_id)
        if existing is None:
            from core_api.modules.enterprise.document_access import verified_content
            with verified_content(storage, payload["storage_key"], payload["artifact_sha256"], payload["artifact_size"]):
                pass
            context = MachineContext(operation.tenant_id, integration.id, compartment.id, request.token_public_id, False)
            reserve_signature(db, context)
            reserve_storage(db, context, payload["artifact_size"])
            evidence = payload["evidence"]
            canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
            existing = EnterpriseSignature(id=operation.signature_id, request_id=request.id, signer_id=operation.signer_id,
                signed_at=datetime.fromisoformat(payload["signed_at"]), evidence=evidence, evidence_sha256=sha256(canonical).hexdigest(),
                evidence_hmac=hmac_new(settings.EVIDENCE_SECRET.encode(), canonical, "sha256").hexdigest(),
                artifact_storage_key=payload["storage_key"], artifact_sha256=payload["artifact_sha256"], artifact_size=payload["artifact_size"],
                provider_evidence=payload.get("provider_evidence"))
            db.add(existing)
            record_usage(db, context, "signature.completed", existing.id, bytes_count=existing.artifact_size, now=existing.signed_at)
            request.signers = [entry | {"status": "signed"} if entry["id"] == str(operation.signer_id) else entry for entry in request.signers]
            if request.status == "open" and all(entry["status"] == "signed" for entry in request.signers):
                request.status = "completed"
            for session in db.scalars(select(EnterpriseSigningSession).where(EnterpriseSigningSession.request_id == request.id,
                EnterpriseSigningSession.signer_id == operation.signer_id)):
                session.used_at = existing.signed_at
        operation.status, operation.error_code = "completed", None
        operation.encrypted_checkpoint = None
        db.flush()
        from core_api.modules.enterprise.signing_service import signature_read
        return signature_read(existing, False)
