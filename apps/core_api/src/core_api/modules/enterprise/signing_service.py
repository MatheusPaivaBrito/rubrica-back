"""Evidence-only signer sessions; a machine token never completes consent."""

from datetime import UTC, datetime
from hashlib import sha256
from hmac import new as hmac_new
from io import BytesIO
import json
import re
from uuid import uuid4

from fastapi import HTTPException
from pypdf import PdfReader
from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.enterprise.document_access import lookup_document, require_available
from core_api.modules.enterprise.storage_access import open_copy
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseProvider, EnterpriseRequest, EnterpriseSignature, EnterpriseSigningSession
from core_api.modules.enterprise.machine_context import AuthClaims, authorize_binding
from core_api.modules.enterprise.request_router import audit, utc
from core_api.modules.signature_request.signed_pdf import generate_signed_pdf
from core_api.modules.enterprise.storage_settings import for_mode
from core_api.modules.enterprise.usage import record_usage, reserve_signature, reserve_storage


def resolve_session(db, secret, sandbox, *, lock=False):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", secret):
        raise HTTPException(401, "Invalid signing session")
    digest = sha256(secret.encode()).hexdigest()
    session = db.scalar(select(EnterpriseSigningSession).where(
        EnterpriseSigningSession.digest == digest, EnterpriseSigningSession.deleted_at.is_(None),
    ).execution_options(populate_existing=True))
    if session is None:
        raise HTTPException(401, "Invalid signing session")
    if lock:
        # Match purge order: contract -> request, including provider work.
        preflight = db.get(EnterpriseRequest, session.request_id)
        if preflight:
            compartment = db.get(EnterpriseCompartment, preflight.compartment_id)
            from core_api.modules.enterprise.entities import EnterpriseIntegration
            integration = db.get(EnterpriseIntegration, compartment.integration_id) if compartment else None
            if integration:
                from core_api.modules.enterprise.lifecycle import lock_operational
                lock_operational(db, integration.tenant_id)
    statement = select(EnterpriseRequest).where(EnterpriseRequest.id == session.request_id,
                                             EnterpriseRequest.deleted_at.is_(None))
    item = db.scalar(statement.with_for_update() if lock else statement)
    if item is None:
        raise HTTPException(401, "Invalid signing session")
    # Re-read after acquiring the request lock: a replacement session may have won.
    db.refresh(session)
    if session.digest != digest or utc(session.expires_at) <= datetime.now(UTC):
        raise HTTPException(401, "Signing session expired or replaced")
    compartment = db.get(EnterpriseCompartment, item.compartment_id)
    if compartment is None:
        raise HTTPException(401, "Invalid signing session")
    from core_api.modules.enterprise.entities import EnterpriseIntegration
    integration = db.get(EnterpriseIntegration, compartment.integration_id)
    if integration is None or integration.sandbox != sandbox:
        raise HTTPException(401, "Invalid signing session")
    context = authorize_binding(db, AuthClaims(
        tenant_id=integration.tenant_id, integration_id=integration.id,
        public_id=item.token_public_id, environment=settings.ENVIRONMENT,
        sandbox=sandbox, scopes=frozenset(),
    ), compartment.id)
    if utc(item.expires_at) <= datetime.now(UTC) or item.status not in {"open", "completed"}:
        raise HTTPException(409, "Signature request is not open")
    signer = next((signer for signer in item.signers if signer["id"] == str(session.signer_id)), None)
    if signer is None:
        raise HTTPException(401, "Invalid signing session")
    return context, item, signer, session


def sign_evidence(secret, sandbox, command, *, ip_address, user_agent, certificate_signer=None,
                  provider_evidence=None, expected_input_hash=None):
    if not command.consent:
        raise HTTPException(422, "Explicit signer consent is required")
    if command.consent_version != "rubrica-enterprise-evidence-v1":
        raise HTTPException(422, "Unsupported consent version")
    storage = configured_document_storage(for_mode(settings, sandbox))
    artifact_key = None
    try:
        with SessionLocal.begin() as db:
            context, item, signer, session = resolve_session(db, secret, sandbox, lock=True)
            if command.document_sha256 != item.document_sha256:
                raise HTTPException(409, "Signer consent document hash mismatch")
            existing = db.scalar(select(EnterpriseSignature).where(
                EnterpriseSignature.request_id == item.id, EnterpriseSignature.signer_id == session.signer_id))
            stamp = signer.get("stamp") or (command.stamp.model_dump(mode="json") if command.stamp else None)
            if existing is not None and session.used_at is not None:
                if existing.evidence.get("stamp") != stamp:
                    raise HTTPException(409, "Consumed session cannot change signature position")
                return signature_read(existing, sandbox)
            if session.used_at is not None or signer["status"] != "pending" or item.status != "open":
                raise HTTPException(409, "Signer session has already been consumed")
            mode = signer["signature_mode"]
            if not sandbox and mode == "serproid" and certificate_signer is None:
                raise HTTPException(409, "This session requires provider authorization")
            if certificate_signer is not None and mode != "serproid":
                raise HTTPException(409, "Unexpected certificate authorization")
            document = lookup_document(db, context, item.document_id)
            reserve_signature(db, context)
            require_available(document)
            if document.sha256 != item.document_sha256:
                raise HTTPException(409, "Frozen document hash mismatch")
            latest = db.scalar(select(EnterpriseSignature).where(
                EnterpriseSignature.request_id == item.id,
            ).order_by(EnterpriseSignature.signed_at.desc(), EnterpriseSignature.id.desc()).limit(1))
            _, digest, _ = ((latest.artifact_storage_key, latest.artifact_sha256, latest.artifact_size)
                if latest else (document.storage_key, document.sha256, document.size_bytes))
            if expected_input_hash is not None and digest != expected_input_hash:
                raise HTTPException(409, "Artifact changed during provider authorization; restart authorization")
            with open_copy(db, context, "artifact" if latest else "original", latest or document,
                           storage_factory=configured_document_storage) as stream:
                original = stream.read()
            if stamp is None:
                raise HTTPException(422, "A signature position is required")
            if stamp.get("display_variant") == "drawn":
                raise HTTPException(422, "Drawn enterprise signatures are not available yet")
            if stamp["page"] > len(PdfReader(BytesIO(original)).pages):
                raise HTTPException(422, "Signature page is outside the document")
            now = datetime.now(UTC)
            evidence = {"schema": command.consent_version, "tenant_id": str(context.tenant_id),
                "integration_id": str(context.integration_id), "compartment_id": str(context.compartment_id),
                "request_id": str(item.id), "signer_id": signer["id"], "external_id": signer["external_id"],
                "signer_name": signer["name"], "signer_email": signer["email"],
                "identity_source": "integrator_declared", "authentication_method": "restricted_bearer_session",
                "consent": True, "signed_at": now.isoformat(), "document_sha256": item.document_sha256,
                "input_artifact_sha256": digest, "signature_mode": mode,
                "provider_configuration_version": signer.get("provider_version"),
                "stamp": stamp, "sandbox": sandbox, "simulated": sandbox,
                "ip_address": ip_address, "user_agent": user_agent[:1000],
                "token_public_id": item.token_public_id}
            canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
            evidence_hash = sha256(canonical).hexdigest()
            stamp_record = evidence | {"evidence_sha256": evidence_hash}
            if sandbox:
                stamp_record["signer_name"] = f"SIMULAÇÃO — {signer['name']}"
            artifact = generate_signed_pdf(original, stamps=[stamp_record],
                metadata={"RubricaEnterpriseRequest": str(item.id), "RubricaEvidenceSHA256": evidence_hash,
                          "RubricaSandbox": str(sandbox).lower(), "RubricaIdentitySource": "integrator_declared"})
            if not sandbox and mode != "evidence":
                from core_api.modules.enterprise.provider_vault import load_configuration
                config = load_configuration(db, context.tenant_id, mode, False,
                                            expected_version=signer["provider_version"])
                if mode == "serpro_timestamp":
                    from core_api.modules.signature_request.serpro_timestamp_service import apply_serpro_timestamp
                    artifact, provider_evidence = apply_serpro_timestamp(artifact,
                        credentials=(config["consumer_key"], config["consumer_secret"]))
                    if provider_evidence is None:
                        raise HTTPException(503, "Tenant timestamp was not issued")
                elif certificate_signer is not None:
                    artifact = certificate_signer(artifact)
                current_provider = db.scalar(select(EnterpriseProvider).where(
                    EnterpriseProvider.tenant_id == context.tenant_id,
                    EnterpriseProvider.provider == mode, EnterpriseProvider.sandbox.is_(False),
                    EnterpriseProvider.version == signer["provider_version"],
                    EnterpriseProvider.deleted_at.is_(None),
                ).with_for_update())
                if current_provider is not None:
                    current_provider.status = "verified_by_signature"
            artifact_hash = sha256(artifact).hexdigest()
            signature_id = uuid4()
            reserve_storage(db, context, len(artifact))
            mode = "sandbox" if sandbox else "live"
            artifact_key, artifact_size = storage.put(BytesIO(artifact), filename="signed.pdf", sha256=artifact_hash,
                scope=f"tenants/{context.tenant_id}/enterprise/{mode}/{context.integration_id}/{context.compartment_id}/{signature_id}")
            signature = EnterpriseSignature(id=signature_id, request_id=item.id, signer_id=session.signer_id,
                signed_at=now, evidence=evidence, evidence_sha256=evidence_hash,
                evidence_hmac=hmac_new(settings.EVIDENCE_SECRET.encode(), canonical, "sha256").hexdigest(),
                provider_evidence=provider_evidence,
                artifact_storage_key=artifact_key, artifact_sha256=artifact_hash, artifact_size=artifact_size)
            db.add(signature)
            record_usage(db, context, "signature.completed", signature_id, bytes_count=artifact_size, now=now)
            session.used_at = now
            item.signers = [entry | {"status": "signed"} if entry["id"] == signer["id"] else entry for entry in item.signers]
            if all(entry["status"] == "signed" for entry in item.signers):
                item.status = "completed"
            audit(db, context, item, "enterprise.signature.completed")
            db.flush()
            return signature_read(signature, sandbox)
    except Exception:
        if artifact_key:
            storage.discard_uncommitted(artifact_key)
        raise


def signature_read(item, sandbox):
    return {"signature_id": item.id, "request_id": item.request_id, "signer_id": item.signer_id,
            "signed_at": item.signed_at, "artifact_sha256": item.artifact_sha256,
            "evidence_sha256": item.evidence_sha256, "sandbox": sandbox, "simulated": sandbox}
