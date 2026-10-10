"""Extract and verify the evidence embedded in a Rubrica signed PDF."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from core_api.modules.signature_request.signed_pdf import evidence_sha256


class EvidenceVerificationError(ValueError):
    """Raised when an embedded Rubrica evidence package is inconsistent."""


def verify_signed_pdf(content: bytes) -> dict[str, object]:
    metadata = PdfReader(BytesIO(content), strict=True).metadata or {}
    encoded_evidence = metadata.get("/RubricaEvidenceJSON")
    if not encoded_evidence:
        raise EvidenceVerificationError(
            "This PDF does not contain the full Rubrica evidence package."
        )

    try:
        evidence = json.loads(encoded_evidence)
    except (TypeError, json.JSONDecodeError) as exc:
        raise EvidenceVerificationError("Rubrica evidence JSON is malformed.") from exc
    if not isinstance(evidence, list) or not evidence:
        raise EvidenceVerificationError("Rubrica evidence package is empty or invalid.")

    verified_hashes: list[str] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise EvidenceVerificationError("Rubrica evidence entry is invalid.")
        stored_hash = str(item.get("evidence_sha256", ""))
        payload = {key: value for key, value in item.items() if key != "evidence_sha256"}
        calculated_hash = evidence_sha256(payload)
        if stored_hash != calculated_hash:
            raise EvidenceVerificationError(
                f"Invalid evidence hash for signer {item.get('signer_id', 'unknown')}."
            )
        verified_hashes.append(stored_hash)

    calculated_manifest = sha256("|".join(verified_hashes).encode()).hexdigest()
    stored_manifest = str(metadata.get("/RubricaEvidenceManifestSHA256", ""))
    if calculated_manifest != stored_manifest:
        raise EvidenceVerificationError("Invalid Rubrica evidence manifest hash.")

    return {
        "valid": True,
        "pdf_sha256": sha256(content).hexdigest(),
        "artifact_id": metadata.get("/RubricaArtifactId"),
        "request_id": metadata.get("/RubricaRequestId"),
        "document_id": metadata.get("/RubricaDocumentId"),
        "document_version": metadata.get("/RubricaDocumentVersion"),
        "original_sha256": metadata.get("/RubricaOriginalSHA256"),
        "evidence_manifest_sha256": stored_manifest,
        "signatures": evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Rubrica signed PDF")
    args = parser.parse_args()

    try:
        result = verify_signed_pdf(args.pdf.read_bytes())
    except EvidenceVerificationError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
