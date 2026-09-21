from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO

import httpx
from asn1crypto import tsp
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign.signers import PdfTimeStamper
from pyhanko.sign.timestamps import TimeStamper

from core_api.infrastructure.settings import settings
from core_api.modules.signature_request.workflow_service import WorkflowError


def timestamp_enabled() -> bool:
    return bool(settings.SERPRO_TIMESTAMP_CONSUMER_KEY and settings.SERPRO_TIMESTAMP_CONSUMER_SECRET)


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


def apply_serpro_timestamp(pdf: bytes) -> tuple[bytes, dict[str, object] | None]:
    if not timestamp_enabled():
        return pdf, None
    timestamper = SerproTimeStamper()
    output = BytesIO()
    try:
        PdfTimeStamper(timestamper).timestamp_pdf(
            IncrementalPdfFileWriter(BytesIO(pdf)),
            md_algorithm="sha256",
            bytes_reserved=32768,
            output=output,
        )
    except WorkflowError:
        raise
    except Exception as exc:
        raise WorkflowError("Could not apply the SERPRO timestamp", 502) from exc
    if timestamper.last_response is None:
        raise WorkflowError("SERPRO did not return a timestamp", 502)
    return output.getvalue(), _timestamp_metadata(timestamper.last_response)
