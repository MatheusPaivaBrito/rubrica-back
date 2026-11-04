from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from secrets import token_urlsafe
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.enterprise.document_access import lookup_document, require_available
from core_api.modules.enterprise.entities import (
    EnterpriseCompartment, EnterpriseRequest, EnterpriseSigningSession,
)
from core_api.modules.enterprise.machine_context import MachineContext, require_machine
from core_api.modules.tenant.tenant_service import tenant_service
from core_api.modules.signature_request.workflow_schema import StampPosition
from core_api.modules.enterprise.entities import EnterpriseProvider
from core_api.modules.enterprise.provider_vault import load_configuration
from core_api.modules.enterprise.entities import EnterpriseIntegration
from core_api.modules.enterprise.storage_policy import enroll_document
from core_api.modules.enterprise.storage_access import ensure_signable_copy

router = APIRouter(tags=["enterprise signature requests"])


class SignerInput(BaseModel):
    external_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160, pattern=r"\S")
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    signature_mode: Literal["evidence", "serpro_timestamp", "serproid"] = "evidence"
    stamp: StampPosition | None = None


class RequestInput(BaseModel):
    document_id: UUID
    expires_at: datetime
    signers: list[SignerInput] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_request(self):
        if self.expires_at.tzinfo is None:
            raise ValueError("Timezone-aware expiry required")
        if len({item.external_id for item in self.signers}) != len(self.signers):
            raise ValueError("Signer external IDs must be unique")
        return self


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def lookup_request(db, context, request_id, *, lock=False):
    statement = select(EnterpriseRequest).where(
        EnterpriseRequest.id == request_id,
        EnterpriseRequest.compartment_id == context.compartment_id,
        EnterpriseRequest.deleted_at.is_(None),
    )
    item = db.scalar(statement.with_for_update() if lock else statement)
    if item is None:
        raise HTTPException(404, "Signature request not found")
    return item


def request_read(item):
    status = item.status
    if status in {"draft", "open"} and utc(item.expires_at) <= datetime.now(UTC):
        status = "expired"
    return {"id": item.id, "document_id": item.document_id,
            "document_sha256": item.document_sha256, "status": status,
            "expires_at": item.expires_at, "signers": item.signers}


def audit(db, context, item, action):
    tenant_service._audit(db, context.tenant_id, f"integration:{context.integration_id}",
        action, {"request_id": str(item.id), "compartment_id": str(context.compartment_id),
                 "token_public_id": context.token_public_id, "sandbox": context.sandbox})
    if action.startswith("enterprise.request."):
        from uuid import NAMESPACE_URL, uuid5
        from core_api.modules.enterprise.webhooks import enqueue
        integration = db.get(EnterpriseIntegration, context.integration_id)
        enqueue(db, integration, uuid5(NAMESPACE_URL, f"{action}:{item.id}"), action.removeprefix("enterprise."),
            {"request_id": str(item.id), "document_id": str(item.document_id), "compartment_id": str(item.compartment_id)})


def create_request(context, payload, idempotency_key):
    if payload.expires_at <= datetime.now(UTC):
        raise HTTPException(422, "Expiry must be in the future")
    checksum = sha256(json.dumps(payload.model_dump(mode="json"), sort_keys=True,
                                separators=(",", ":")).encode()).hexdigest()
    with SessionLocal.begin() as db:
        from core_api.modules.enterprise.lifecycle import lock_operational
        lock_operational(db, context.tenant_id)
        db.scalar(select(EnterpriseIntegration).where(EnterpriseIntegration.id == context.integration_id).with_for_update())
        compartment = db.scalar(select(EnterpriseCompartment).where(
            EnterpriseCompartment.id == context.compartment_id,
            EnterpriseCompartment.integration_id == context.integration_id,
            EnterpriseCompartment.deleted_at.is_(None),
        ).with_for_update())
        if compartment is None:
            raise HTTPException(404, "Compartment not found")
        existing = db.scalar(select(EnterpriseRequest).where(
            EnterpriseRequest.compartment_id == context.compartment_id,
            EnterpriseRequest.idempotency_key == idempotency_key,
        ))
        if existing:
            if existing.payload_sha256 != checksum or existing.deleted_at is not None:
                raise HTTPException(409, "Idempotency key already used with different content")
            return request_read(existing)
        document = lookup_document(db, context, payload.document_id)
        ensure_signable_copy(db, document)
        item = EnterpriseRequest(document_id=document.id, compartment_id=context.compartment_id,
            document_sha256=document.sha256, idempotency_key=idempotency_key,
            payload_sha256=checksum, expires_at=payload.expires_at,
            token_public_id=context.token_public_id,
            signers=[signer.model_dump(mode="json") | {"id": str(uuid4()), "status": "pending",
                     "identity_source": "integrator_declared"} for signer in payload.signers])
        db.add(item)
        db.flush()
        enroll_document(db, context, document.id)
        audit(db, context, item, "enterprise.request.created")
        return request_read(item)


@router.post("/api/v1/compartments/{compartment_id}/signature-requests", status_code=201)
@router.post("/api/v1/sandbox/compartments/{compartment_id}/signature-requests", status_code=201)
def create(payload: RequestInput,
           idempotency_key: str = Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
           context: MachineContext = Depends(require_machine("signature_requests:create"))):
    return create_request(context, payload, idempotency_key)


@router.get("/api/v1/compartments/{compartment_id}/signature-requests/{request_id}")
@router.get("/api/v1/sandbox/compartments/{compartment_id}/signature-requests/{request_id}")
def get_request(request_id: UUID, context: MachineContext = Depends(require_machine("signature_requests:read"))):
    with SessionLocal() as db:
        return request_read(lookup_request(db, context, request_id))


@router.post("/api/v1/compartments/{compartment_id}/signature-requests/{request_id}/open")
@router.post("/api/v1/sandbox/compartments/{compartment_id}/signature-requests/{request_id}/open")
def open_request(request_id: UUID, context: MachineContext = Depends(require_machine("signature_requests:open"))):
    with SessionLocal.begin() as db:
        item = lookup_request(db, context, request_id, lock=True)
        if utc(item.expires_at) <= datetime.now(UTC) or item.status not in {"draft", "open"}:
            raise HTTPException(409, "Signature request cannot be opened")
        document = lookup_document(db, context, item.document_id)
        require_available(document)
        if document.sha256 != item.document_sha256:
            raise HTTPException(409, "Frozen document hash mismatch")
        if item.status == "draft":
            snapshots = {}
            for signer in item.signers:
                mode = signer["signature_mode"]
                if mode == "evidence" or context.sandbox:
                    continue
                load_configuration(db, context.tenant_id, mode, False)
                config = db.scalar(select(EnterpriseProvider).where(
                    EnterpriseProvider.tenant_id == context.tenant_id,
                    EnterpriseProvider.provider == mode, EnterpriseProvider.sandbox.is_(False),
                    EnterpriseProvider.deleted_at.is_(None)))
                snapshots[mode] = config.version
            item.signers = [signer | {"provider_version": snapshots.get(signer["signature_mode"])} for signer in item.signers]
            item.status = "open"
            audit(db, context, item, "enterprise.request.opened")
        return request_read(item)


@router.post("/api/v1/compartments/{compartment_id}/signature-requests/{request_id}/cancel")
@router.post("/api/v1/sandbox/compartments/{compartment_id}/signature-requests/{request_id}/cancel")
def cancel_request(request_id: UUID, context: MachineContext = Depends(require_machine("signature_requests:open"))):
    with SessionLocal.begin() as db:
        item = lookup_request(db, context, request_id, lock=True)
        if item.status == "completed":
            raise HTTPException(409, "Completed request cannot be cancelled")
        if item.status != "cancelled":
            item.status = "cancelled"
            audit(db, context, item, "enterprise.request.cancelled")
        return request_read(item)


class SessionInput(BaseModel):
    signer_id: UUID


@router.post("/api/v1/compartments/{compartment_id}/signature-requests/{request_id}/sessions")
@router.post("/api/v1/sandbox/compartments/{compartment_id}/signature-requests/{request_id}/sessions")
def create_session(request_id: UUID, payload: SessionInput, response: Response,
                   context: MachineContext = Depends(require_machine("signing_sessions:create"))):
    response.headers["Cache-Control"] = "no-store"
    with SessionLocal.begin() as db:
        item = lookup_request(db, context, request_id, lock=True)
        now = datetime.now(UTC)
        if item.status != "open" or utc(item.expires_at) <= now:
            raise HTTPException(409, "Signature request is not open")
        signer = next((signer for signer in item.signers if signer["id"] == str(payload.signer_id)), None)
        if signer is None:
            raise HTTPException(404, "Signer not found")
        if signer["status"] != "pending":
            raise HTTPException(409, "Signer is not pending")
        session = db.scalar(select(EnterpriseSigningSession).where(
            EnterpriseSigningSession.request_id == item.id,
            EnterpriseSigningSession.signer_id == payload.signer_id,
        ))
        secret = token_urlsafe(32)
        digest = sha256(secret.encode()).hexdigest()
        expiry = min(utc(item.expires_at), now + timedelta(minutes=15))
        if session is None:
            session = EnterpriseSigningSession(request_id=item.id, signer_id=payload.signer_id,
                digest=digest, expires_at=expiry)
            db.add(session)
        session.digest, session.expires_at, session.used_at = digest, expiry, None
        audit(db, context, item, "enterprise.signing_session.created")
        return {"session_token": secret, "expires_at": expiry,
                "document_sha256": item.document_sha256,
                "status": "awaiting_signer_consent", "identity_source": "integrator_declared"}
