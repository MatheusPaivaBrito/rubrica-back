"""Enterprise OAuth state is bound to one signer session and tenant config version."""

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import new as hmac_new
import re
from secrets import token_urlsafe
from urllib.parse import urlencode

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding
from fastapi import HTTPException
import httpx
from sqlalchemy import select
from pyhanko_certvalidator import ValidationContext
from core_api.modules.signature_request.serpro_timestamp_service import _load_trust_roots

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.enterprise.entities import EnterpriseAuthorization, EnterpriseSignature
from core_api.modules.enterprise.provider_vault import decrypt_configuration, encrypt_configuration, load_configuration
from core_api.modules.enterprise.request_router import utc
from core_api.modules.enterprise.signing_service import resolve_session, sign_evidence
from core_api.modules.enterprise.signing_router import ConsentCommand
from core_api.modules.signature_request.serproid_service import _sign_pdf_with_serpro


def provider_base(config):
    host = "hom.serproid.serpro.gov.br" if config["environment"] == "homologation" else "serproid.serpro.gov.br"
    return f"https://{host}/oauth/v0/oauth"


def redirect_uri():
    return f"{settings.PUBLIC_WEB_URL.rstrip('/')}/api/v1/serproid/callback"


def start(secret, sandbox, command, *, ip_address, user_agent):
    if sandbox:
        raise HTTPException(409, "Sandbox provider signatures use simulated consent")
    if not settings.ENTERPRISE_SERPROID_TRUST_ROOTS_FILE:
        raise HTTPException(503, "Enterprise certificate trust roots are not configured")
    _load_trust_roots(settings.ENTERPRISE_SERPROID_TRUST_ROOTS_FILE)
    if not command.consent or command.consent_version != "rubrica-enterprise-evidence-v1":
        raise HTTPException(422, "Explicit signer consent with supported version required")
    with SessionLocal.begin() as db:
        context, item, signer, session = resolve_session(db, secret, False, lock=True)
        if signer["signature_mode"] != "serproid" or signer["status"] != "pending" or session.used_at is not None:
            raise HTTPException(409, "Signer does not require SerproID authorization")
        if command.document_sha256 != item.document_sha256:
            raise HTTPException(409, "Signer consent document hash mismatch")
        stamp = signer.get("stamp") or (command.stamp.model_dump(mode="json") if command.stamp else None)
        if stamp is None or stamp.get("display_variant") == "drawn":
            raise HTTPException(422, "A supported signature position is required")
        config = load_configuration(db, context.tenant_id, "serproid", False, expected_version=signer["provider_version"])
        latest = db.scalar(select(EnterpriseSignature).where(EnterpriseSignature.request_id == item.id)
            .order_by(EnterpriseSignature.signed_at.desc(), EnterpriseSignature.id.desc()).limit(1))
        state, verifier = token_urlsafe(32), token_urlsafe(64)
        attempt = {"session_secret": secret, "command": command.model_dump(mode="json"),
            "provider_version": signer["provider_version"], "verifier": verifier,
            "input_sha256": latest.artifact_sha256 if latest else item.document_sha256,
            "ip_address": ip_address, "user_agent": user_agent[:1000]}
        db.add(EnterpriseAuthorization(tenant_id=context.tenant_id, session_id=session.id,
            state_digest=sha256(state.encode()).hexdigest(), sandbox=False,
            expires_at=min(utc(session.expires_at), datetime.now(UTC) + timedelta(minutes=10)),
            encrypted_attempt=encrypt_configuration(context.tenant_id, "serproid-authorization", False, 1, attempt)))
        challenge = base64.urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        query = urlencode({"response_type": "code", "client_id": config["client_id"],
            "redirect_uri": redirect_uri(), "scope": "single_signature", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"})
        return {"authorization_url": f"{provider_base(config)}/authorize?{query}"}


def consume_attempt(state):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", state):
        raise HTTPException(400, "Invalid provider authorization state")
    with SessionLocal.begin() as db:
        item = db.scalar(select(EnterpriseAuthorization).where(
            EnterpriseAuthorization.state_digest == sha256(state.encode()).hexdigest(),
            EnterpriseAuthorization.deleted_at.is_(None),
        ).with_for_update())
        if item is None or item.consumed_at is not None or utc(item.expires_at) <= datetime.now(UTC):
            raise HTTPException(400, "Provider authorization expired or consumed")
        attempt = decrypt_configuration(item.tenant_id, "serproid-authorization", False, 1, item.encrypted_attempt)
        item.consumed_at = datetime.now(UTC)
        item.encrypted_attempt = ""
        return item.tenant_id, attempt


def finish(state, code, error):
    tenant_id, attempt = consume_attempt(state)
    if error or not code:
        return {"status": "authorization_denied"}
    # Revalidate session, tenant contract and provider version after consuming state.
    with SessionLocal() as db:
        context, _, signer, _ = resolve_session(db, attempt["session_secret"], False)
        if context.tenant_id != tenant_id or signer["signature_mode"] != "serproid":
            raise HTTPException(403, "Provider authorization context mismatch")
        config = load_configuration(db, tenant_id, "serproid", False, expected_version=attempt["provider_version"])
    base = provider_base(config)
    try:
        with httpx.Client(timeout=30) as client:
            result = client.post(f"{base}/token", data={"grant_type": "authorization_code",
                "client_id": config["client_id"], "client_secret": config["client_secret"],
                "code": code, "code_verifier": attempt["verifier"], "redirect_uri": redirect_uri()})
            result.raise_for_status()
            authorization = result.json()
            if authorization.get("scope") != "single_signature":
                raise HTTPException(403, "Provider did not grant signing permission")
            access_token = authorization.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise HTTPException(502, "Provider did not return a signing token")
            result = client.get(f"{base}/certificate-discovery", headers={"Authorization": f"Bearer {access_token}"})
            result.raise_for_status()
            certificates = result.json().get("certificates", [])
            if len(certificates) != 1:
                raise HTTPException(502, "Provider returned an unexpected certificate set")
            encoded = certificates[0]["certificate"].encode()
            certificate = (x509.load_pem_x509_certificate(encoded) if b"-----BEGIN CERTIFICATE-----" in encoded
                else x509.load_der_x509_certificate(base64.b64decode(encoded, validate=True)))
            if not certificate.not_valid_before_utc <= datetime.now(UTC) <= certificate.not_valid_after_utc:
                raise HTTPException(403, "Provider certificate is outside its validity period")
            identifier_type = authorization.get("authorized_identification_type")
            identifier = authorization.get("authorized_identification", "")
            if identifier_type not in {"CPF", "CNPJ"} or not isinstance(identifier, str) or not identifier:
                raise HTTPException(403, "Provider did not identify the certificate holder")
            provider_evidence = {"provider": "serproid", "certificate_sha256": certificate.fingerprint(hashes.SHA256()).hex(),
                "identity_source": "serproid_authorized_certificate", "identifier_type": identifier_type,
                "identifier_last4": identifier[-4:],
                "identifier_hmac": hmac_new(settings.EVIDENCE_SECRET.encode(),
                    f"{tenant_id}:{identifier_type}:{identifier}".encode(), "sha256").hexdigest()}

            def certificate_signer(pdf):
                if not settings.ENTERPRISE_SERPROID_TRUST_ROOTS_FILE:
                    raise HTTPException(503, "Enterprise certificate trust roots are not configured")
                validation = ValidationContext(
                    trust_roots=_load_trust_roots(settings.ENTERPRISE_SERPROID_TRUST_ROOTS_FILE),
                    allow_fetching=True, revocation_mode="require")
                return asyncio.run(_sign_pdf_with_serpro(pdf, client, access_token,
                    certificate.public_bytes(Encoding.DER), base_url=base,
                    validation_context=validation, require_trusted=True))

            return sign_evidence(attempt["session_secret"], False, ConsentCommand.model_validate(attempt["command"]),
                ip_address=attempt["ip_address"], user_agent=attempt["user_agent"],
                certificate_signer=certificate_signer, provider_evidence=provider_evidence,
                expected_input_hash=attempt["input_sha256"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, "SerproID authorization or signing failed") from exc
