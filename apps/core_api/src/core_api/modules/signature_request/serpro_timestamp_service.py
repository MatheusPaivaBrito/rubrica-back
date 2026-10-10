from __future__ import annotations

import asyncio
import base64
from hashlib import sha256
from io import BytesIO

import httpx
from asn1crypto import tsp
from pyhanko import keys
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.signers import PdfTimeStamper
from pyhanko.sign.timestamps import TimeStamper
from pyhanko.sign.validation import async_validate_pdf_timestamp
from pyhanko_certvalidator import ValidationContext

from core_api.infrastructure.settings import settings
from core_api.modules.signature_request.workflow_service import WorkflowError


def timestamp_enabled() -> bool:
    return bool(
        settings.SERPRO_TIMESTAMP_PROVIDER == "serpro"
        and settings.SERPRO_TIMESTAMP_CONSUMER_KEY
        and settings.SERPRO_TIMESTAMP_CONSUMER_SECRET
        and settings.SERPRO_TIMESTAMP_TRUST_ROOTS_FILE
        and _accepted_policy_oids()
    )


def _accepted_policy_oids() -> set[str]:
    return {
        value.strip()
        for value in settings.SERPRO_TIMESTAMP_ACCEPTED_POLICY_OIDS.split(",")
        if value.strip()
    }


def _timestamp_info(response: tsp.TimeStampResp):
    token = response["time_stamp_token"]
    if token.native is None:
        raise WorkflowError("SERPRO did not return a timestamp token", 502)
    return token["content"]["encap_content_info"]["content"].parsed


def _validate_tsa_response(req: tsp.TimeStampReq, response: tsp.TimeStampResp) -> None:
    status = response["status"]["status"].native
    if status not in {"granted", "granted_with_mods"}:
        raise WorkflowError(f"SERPRO rejected the timestamp request ({status})", 502)
    info = _timestamp_info(response)
    requested_imprint = req["message_imprint"]
    returned_imprint = info["message_imprint"]
    if requested_imprint.dump() != returned_imprint.dump():
        raise WorkflowError("SERPRO timestamp message imprint does not match the request", 502)
    requested_nonce = req["nonce"].native
    returned_nonce = info["nonce"].native
    if requested_nonce is None or returned_nonce != requested_nonce:
        raise WorkflowError("SERPRO timestamp nonce does not match the request", 502)
    policy = str(info["policy"].native)
    if policy not in _accepted_policy_oids():
        raise WorkflowError("SERPRO timestamp policy is not accepted", 502)


class SerproTimeStamper(TimeStamper):
    def __init__(self) -> None:
        super().__init__(include_nonce=True)
        self.last_response: tsp.TimeStampResp | None = None

    async def async_request_tsa_response(self, req: tsp.TimeStampReq) -> tsp.TimeStampResp:
        basic = base64.b64encode(
            f"{settings.SERPRO_TIMESTAMP_CONSUMER_KEY}:{settings.SERPRO_TIMESTAMP_CONSUMER_SECRET}".encode()
        ).decode()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                token_response = await client.post(
                    settings.SERPRO_TIMESTAMP_TOKEN_URL,
                    headers={"Authorization": f"Basic {basic}"},
                    data={"grant_type": "client_credentials"},
                )
                token_response.raise_for_status()
                access_token = token_response.json()["access_token"]
                stamp_response = await client.post(
                    f"{settings.SERPRO_TIMESTAMP_API_URL.rstrip('/')}/stamps-asn1",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/timestamp-query",
                        "Accept": "application/timestamp-reply",
                    },
                    content=req.dump(),
                )
                stamp_response.raise_for_status()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise WorkflowError("SERPRO timestamp service is unavailable", 502) from exc
        try:
            response = tsp.TimeStampResp.load(stamp_response.content)
        except (ValueError, TypeError) as exc:
            raise WorkflowError("SERPRO returned an invalid timestamp response", 502) from exc
        _validate_tsa_response(req, response)
        self.last_response = response
        return response


def _timestamp_metadata(response: tsp.TimeStampResp) -> dict[str, object]:
    token = response["time_stamp_token"]
    info = token["content"]["encap_content_info"]["content"].parsed
    authority = "ACT SERPRO"
    certificates = token["content"]["certificates"]
    if certificates:
        certificate = certificates[0].chosen
        authority = certificate.subject.human_friendly
    imprint = info["message_imprint"]
    return {
        "provider": "serpro-api-timestamp",
        "authority": authority,
        "format": "RFC 3161 / PAdES DocTimeStamp",
        "timestamp": info["gen_time"].native.isoformat(),
        "policy": info["policy"].native,
        "serial_number": str(info["serial_number"].native),
        "hash_algorithm": imprint["hash_algorithm"]["algorithm"].native,
        "message_imprint": imprint["hashed_message"].native.hex(),
        "token_sha256": sha256(token.dump()).hexdigest(),
        "timestamp_response_base64": base64.b64encode(response.dump()).decode(),
    }


def _load_trust_roots(path: str | None = None):
    trust_file = path or settings.SERPRO_TIMESTAMP_TRUST_ROOTS_FILE
    if not trust_file:
        raise WorkflowError("SERPRO timestamp trust roots are not configured", 503)
    try:
        with open(trust_file, "rb") as stream:
            roots = list(keys.load_certs_from_pemder_data(stream.read()))
    except (OSError, ValueError) as exc:
        raise WorkflowError("SERPRO timestamp trust roots could not be loaded", 503) from exc
    if not roots:
        raise WorkflowError("SERPRO timestamp trust roots are empty", 503)
    return roots


async def _async_validate_pdf_timestamp(
    pdf: bytes,
    *,
    trust_roots_file: str | None = None,
    accepted_policy_oids: set[str] | None = None,
    allow_fetching: bool = True,
    revocation_mode: str = "require",
) -> dict[str, object]:
    try:
        signatures = PdfFileReader(BytesIO(pdf), strict=True).embedded_signatures
    except Exception as exc:
        raise WorkflowError("Timestamped PDF is malformed", 409) from exc
    timestamps = [item for item in signatures if item.sig_object_type == "/DocTimeStamp"]
    if not timestamps:
        raise WorkflowError("PDF does not contain a document timestamp", 409)
    timestamp = timestamps[-1]
    try:
        info = timestamp.signed_data["encap_content_info"]["content"].parsed
        policy = str(info["policy"].native)
        validation_time = info["gen_time"].native
    except Exception as exc:
        raise WorkflowError("PDF timestamp token is malformed", 409) from exc
    policies = accepted_policy_oids if accepted_policy_oids is not None else _accepted_policy_oids()
    if not policies or policy not in policies:
        raise WorkflowError("PDF timestamp policy is not accepted", 409)
    context = ValidationContext(
        trust_roots=_load_trust_roots(trust_roots_file),
        best_signature_time=validation_time,
        allow_fetching=allow_fetching,
        revocation_mode=revocation_mode,
        retroactive_revinfo=True,
    )
    try:
        status = await async_validate_pdf_timestamp(timestamp, validation_context=context)
    except Exception as exc:
        raise WorkflowError("PDF timestamp trust validation failed", 409) from exc
    coverage = getattr(status.coverage, "name", str(status.coverage))
    if not status.intact or not status.valid:
        raise WorkflowError("PDF timestamp integrity validation failed", 409)
    if not status.trusted:
        raise WorkflowError("PDF timestamp certificate chain is not trusted", 409)
    if status.revoked:
        raise WorkflowError("PDF timestamp certificate chain is revoked", 409)
    if coverage != "ENTIRE_FILE":
        raise WorkflowError("PDF contains changes after the document timestamp", 409)
    if status.md_algorithm.lower().replace("-", "") != "sha256":
        raise WorkflowError("PDF timestamp uses an unsupported digest algorithm", 409)
    validity = status.signing_cert["tbs_certificate"]["validity"]
    not_before = validity["not_before"].native
    not_after = validity["not_after"].native
    if not not_before <= validation_time <= not_after:
        raise WorkflowError("PDF timestamp was issued outside the TSA certificate validity period", 409)
    path = status.validation_path
    return {
        "valid": True,
        "intact": status.intact,
        "trusted": status.trusted,
        "revoked": status.revoked,
        "coverage": coverage,
        "policy": policy,
        "timestamp": status.timestamp.isoformat(),
        "hash_algorithm": status.md_algorithm,
        "tsa_certificate_sha256": status.signing_cert.sha256.hex(),
        "validation_path_length": len(path) if path is not None else 0,
        "revocation_mode": revocation_mode,
    }


def validate_pdf_timestamp(
    pdf: bytes,
    *,
    trust_roots_file: str | None = None,
    accepted_policy_oids: set[str] | None = None,
    allow_fetching: bool = True,
    revocation_mode: str = "require",
) -> dict[str, object]:
    return asyncio.run(
        _async_validate_pdf_timestamp(
            pdf,
            trust_roots_file=trust_roots_file,
            accepted_policy_oids=accepted_policy_oids,
            allow_fetching=allow_fetching,
            revocation_mode=revocation_mode,
        )
    )


def apply_serpro_timestamp(pdf: bytes) -> tuple[bytes, dict[str, object] | None]:
    if not timestamp_enabled():
        return pdf, None
    timestamper = SerproTimeStamper()
    output = BytesIO()
    try:
        asyncio.run(
            PdfTimeStamper(timestamper).async_timestamp_pdf(
                IncrementalPdfFileWriter(BytesIO(pdf)),
                md_algorithm="sha256",
                bytes_reserved=32768,
                output=output,
            )
        )
    except WorkflowError:
        raise
    except Exception as exc:
        raise WorkflowError("Could not apply the SERPRO timestamp", 502) from exc
    if timestamper.last_response is None:
        raise WorkflowError("SERPRO did not return a timestamp", 502)
    stamped_pdf = output.getvalue()
    validation = validate_pdf_timestamp(stamped_pdf)
    metadata = _timestamp_metadata(timestamper.last_response)
    metadata["validation"] = validation
    return stamped_pdf, metadata
