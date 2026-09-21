"""One-use Serpro ID authorisation and certificate signing for a frozen PDF."""

import asyncio
import base64
import json
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from secrets import token_urlsafe
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from asn1crypto import cms
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers
from pyhanko.sign.signers.pdf_cms import ExternalSigner
from pyhanko.sign.signers.pdf_signer import PdfTBSDocument
from pyhanko.sign.validation import async_validate_pdf_signature
from redis import Redis

from core_api.infrastructure.settings import settings
from core_api.modules.signature_request.database_workflow_service import database_workflow_service
from core_api.modules.signature_request.identity_client import identity_matches_certificate, identity_summary
from core_api.modules.signature_request.workflow_schema import RequestStatus, SignCommand, SignerStatus
from core_api.modules.signature_request.workflow_service import WorkflowError

STATE_PREFIX = "rubrica:serproid:state:"


def _serpro_base() -> str:
    host = "hom.serproid.serpro.gov.br" if settings.SERPROID_ENVIRONMENT == "homologation" else "serproid.serpro.gov.br"
    return f"https://{host}/oauth/v0/oauth"


def _redirect_uri() -> str:
    return f"{settings.PUBLIC_WEB_URL.rstrip('/')}/api/auth/serproid/callback"


def _redis() -> Redis:
    return Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=3, socket_timeout=3)


def _configured() -> None:
    if not settings.SERPROID_CLIENT_ID or not settings.SERPROID_CLIENT_SECRET:
        raise WorkflowError("Serpro ID is not configured", 503)


def start_authorization(token: str, subject: str, command: SignCommand, ip: str, agent: str) -> str:
    _configured()
    if not command.consent:
        raise WorkflowError("Explicit consent is required", 400)
    if identity_summary(subject).identifier_type not in {"BR_CPF", "BR_CNPJ"}:
        raise WorkflowError("A Brazilian CPF or CNPJ is required for Serpro ID signing", 409)
    context = database_workflow_service.signing_context(token, subject)
    if context.request.status != RequestStatus.OPEN or context.signer.status not in {SignerStatus.PENDING, SignerStatus.VIEWED}:
        raise WorkflowError("Signature request is not open", 409)
    if context.request.signer_count - context.request.signed_count != 1:
        raise WorkflowError("Certificate signing must be the final signature on this PDF", 409)
    state = token_urlsafe(32)
    verifier = token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    attempt = {
        "token": token,
        "subject": subject,
        "request_id": str(context.request.id),
        "signer_id": str(context.signer.id),
        "document_sha256": context.request.document_sha256,
        "command": command.model_dump(mode="json"),
        "verifier": verifier,
        "ip": ip,
        "agent": agent[:1000],
    }
    if not _redis().set(STATE_PREFIX + state, json.dumps(attempt), ex=600, nx=True):
        raise WorkflowError("Unable to begin Serpro ID authorization", 503)
    query = urlencode({
        "response_type": "code",
        "client_id": settings.SERPROID_CLIENT_ID,
        "redirect_uri": _redirect_uri(),
        "scope": "single_signature",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return f"{_serpro_base()}/authorize?{query}"


def finish_authorization(state: str, code: str | None, error: str | None, subject: str) -> str:
    _configured()
    raw = _redis().getdel(STATE_PREFIX + state)
    if raw is None:
        raise WorkflowError("Serpro ID authorization expired or was already used", 400)
    attempt = json.loads(raw)
    if attempt["subject"] != subject:
        raise WorkflowError("Serpro ID authorization belongs to another user", 403)
    if error or not code:
        return attempt["token"]
    context = database_workflow_service.signing_context(attempt["token"], subject)
    if (str(context.request.id) != attempt["request_id"] or
            str(context.signer.id) != attempt["signer_id"] or
            context.request.document_sha256 != attempt["document_sha256"]):
        raise WorkflowError("The document or signer changed during authorization", 409)
    with httpx.Client(timeout=15.0) as client:
        response = client.post(f"{_serpro_base()}/token", data={
            "grant_type": "authorization_code",
            "client_id": settings.SERPROID_CLIENT_ID,
            "client_secret": settings.SERPROID_CLIENT_SECRET,
            "code": code,
            "code_verifier": attempt["verifier"],
            "redirect_uri": _redirect_uri(),
        })
        response.raise_for_status()
        authorization = response.json()
        if authorization.get("scope") != "single_signature":
            raise WorkflowError("Serpro ID did not grant signing permission", 403)
        identity_type = {"CPF": "BR_CPF", "CNPJ": "BR_CNPJ"}.get(authorization.get("authorized_identification_type"))
        identifier = authorization.get("authorized_identification", "")
        if not identity_type or not identity_matches_certificate(subject, identity_type, identifier):
            raise WorkflowError("Certificate identity does not match the Rubrica signer", 403)
        access_token = authorization.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise WorkflowError("Serpro ID did not return a signing token", 502)
        cert_response = client.get(f"{_serpro_base()}/certificate-discovery", headers={"Authorization": f"Bearer {access_token}"})
        cert_response.raise_for_status()
        certificates = cert_response.json().get("certificates", [])
        if len(certificates) != 1:
            raise WorkflowError("Serpro ID returned an unexpected certificate set", 502)
        encoded_certificate = certificates[0]["certificate"].encode()
        certificate = (
            x509.load_pem_x509_certificate(encoded_certificate)
            if b"-----BEGIN CERTIFICATE-----" in encoded_certificate
            else x509.load_der_x509_certificate(base64.b64decode(encoded_certificate, validate=True))
        )
        now = datetime.now(timezone.utc)
        if not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc:
            raise WorkflowError("Serpro ID certificate is outside its validity period", 403)
        cert_fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
        info = {"provider": "serproid", "format": "PAdES-CMS", "certificate_sha256": cert_fingerprint,
                "identifier_type": identity_type, "identifier_last4": identifier[-4:]}

        def sign_pdf(unsigned_pdf: bytes) -> bytes:
            return asyncio.run(_sign_pdf_with_serpro(unsigned_pdf, client, access_token, certificate.public_bytes(Encoding.DER)))

        database_workflow_service.sign(
            attempt["token"], subject, True, SignCommand.model_validate(attempt["command"]).stamp,
            consent_version=attempt["command"]["consent_version"],
            client=SignCommand.model_validate(attempt["command"]).client,
            geolocation=SignCommand.model_validate(attempt["command"]).geolocation,
            ip_address=attempt["ip"], user_agent=attempt["agent"],
            certificate_signer=sign_pdf, certificate_info=info,
        )
    return attempt["token"]


async def _sign_pdf_with_serpro(unsigned_pdf: bytes, client: httpx.Client, access_token: str, certificate_der: bytes) -> bytes:
    writer = IncrementalPdfFileWriter(BytesIO(unsigned_pdf))
    pdf_signer = signers.PdfSigner(
        signers.PdfSignatureMetadata(field_name=f"RubricaSerproID{uuid4().hex}", md_algorithm="sha256",
                                     subfilter=fields.SigSeedSubFilter.PADES),
        signer=ExternalSigner(signing_cert=None, cert_registry=None, signature_value=256),
    )
    digest, _tbs, output = await pdf_signer.async_digest_doc_for_signing(writer, bytes_reserved=131072)
    response = client.post(
        f"{_serpro_base()}/signature",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"hashes": [{"id": "rubrica-pdf", "alias": "Rubrica PDF", "hash": base64.b64encode(digest.document_digest).decode(),
                         "hash_algorithm": "2.16.840.1.101.3.4.2.1", "signature_format": "CMS"}]},
    )
    response.raise_for_status()
    signatures = response.json().get("signatures", [])
    if len(signatures) != 1 or signatures[0].get("id") != "rubrica-pdf":
        raise WorkflowError("Serpro ID returned an unexpected signature", 502)
    raw = signatures[0].get("raw_signature", "")
    if not isinstance(raw, str) or not raw:
        raise WorkflowError("Serpro ID did not return a CMS signature", 502)
    if "-----BEGIN" in raw:
        raw = "".join(line for line in raw.splitlines() if not line.startswith("-----"))
    cms_data = base64.b64decode(raw, validate=True)
    cms_object = cms.ContentInfo.load(cms_data)
    if cms_object["content_type"].native != "signed_data":
        raise WorkflowError("Serpro ID returned a non-CMS signature", 502)
    await PdfTBSDocument.async_finish_signing(output, digest, cms_object)
    result = output.getvalue()
    signatures_in_pdf = PdfFileReader(BytesIO(result)).embedded_signatures
    if len(signatures_in_pdf) != 1:
        raise WorkflowError("PDF does not contain the expected certificate signature", 502)
    if signatures_in_pdf[0].signer_cert.dump() != certificate_der:
        raise WorkflowError("Signed PDF certificate differs from the authorized certificate", 502)
    verification = await async_validate_pdf_signature(signatures_in_pdf[0])
    if not verification.intact or not verification.valid:
        raise WorkflowError("Certificate signature failed PDF verification", 502)
    return result
