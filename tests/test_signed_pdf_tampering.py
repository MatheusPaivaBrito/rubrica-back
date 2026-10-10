import json
from hashlib import sha256
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from core_api.modules.signature_request.signed_pdf import canonical_json, evidence_sha256, generate_signed_pdf
from toolbox.verify_signed_pdf import EvidenceVerificationError, verify_signed_pdf


def _original_pdf() -> bytes:
    stream = BytesIO()
    canvas = Canvas(stream)
    canvas.drawString(40, 740, "Real Rubrica document fixture")
    canvas.save()
    return stream.getvalue()


def _evidence(signer: str, signer_id: str, signed_at: str) -> dict[str, object]:
    return {
        "schema": "rubrica-signature-evidence-v1",
        "consent": True,
        "consent_version": "rubrica-evidence-v1",
        "request_id": "10000000-0000-0000-0000-000000000001",
        "signer_id": signer_id,
        "document_id": "20000000-0000-0000-0000-000000000001",
        "document_version": 1,
        "original_sha256": sha256(_original_pdf()).hexdigest(),
        "subject_hmac_sha256": "a" * 64,
        "identity_binding_hmac_sha256": "b" * 64,
        "signer_name": signer,
        "signer_email": f"{signer.lower()}@example.com",
        "participant_role": "external_signer",
        "signed_at": signed_at,
        "stamp": {"page": 1, "x": 0.5, "y": 0.5, "locale": "pt-BR", "timezone": "UTC"},
    }


def _artifact(records: list[dict[str, object]]) -> bytes:
    stamped = []
    for record in records:
        stamped.append(record | {"evidence_sha256": evidence_sha256(record)})
    manifest = sha256("|".join(item["evidence_sha256"] for item in stamped).encode()).hexdigest()
    return generate_signed_pdf(
        _original_pdf(),
        stamps=stamped,
        metadata={
            "RubricaArtifactId": "30000000-0000-0000-0000-000000000001",
            "RubricaRequestId": "10000000-0000-0000-0000-000000000001",
            "RubricaDocumentId": "20000000-0000-0000-0000-000000000001",
            "RubricaDocumentVersion": "1",
            "RubricaOriginalSHA256": sha256(_original_pdf()).hexdigest(),
            "RubricaEvidenceManifestSHA256": manifest,
            "RubricaEvidenceJSON": canonical_json(stamped).decode(),
        },
    )


def _rewrite_metadata(pdf: bytes, **changes: str) -> bytes:
    reader = PdfReader(BytesIO(pdf))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    metadata = {str(key): str(value) for key, value in (reader.metadata or {}).items()}
    metadata.update({f"/{key.lstrip('/')}": value for key, value in changes.items()})
    writer.add_metadata(metadata)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_two_signer_evidence_package_verifies_independently() -> None:
    pdf = _artifact([
        _evidence("Alice", "40000000-0000-0000-0000-000000000001", "2026-10-10T10:00:00+00:00"),
        _evidence("Bruno", "40000000-0000-0000-0000-000000000002", "2026-10-10T10:05:00+00:00"),
    ])
    result = verify_signed_pdf(pdf)
    assert result["valid"] is True
    assert [item["signer_name"] for item in result["signatures"]] == ["Alice", "Bruno"]


def test_evidence_json_tampering_is_detected() -> None:
    pdf = _artifact([_evidence("Alice", "40000000-0000-0000-0000-000000000001", "2026-10-10T10:00:00+00:00")])
    metadata = PdfReader(BytesIO(pdf)).metadata
    evidence = json.loads(metadata["/RubricaEvidenceJSON"])
    evidence[0]["signer_name"] = "Mallory"
    tampered = _rewrite_metadata(pdf, RubricaEvidenceJSON=canonical_json(evidence).decode())
    with pytest.raises(EvidenceVerificationError, match="Invalid evidence hash"):
        verify_signed_pdf(tampered)


def test_evidence_hash_tampering_is_detected() -> None:
    pdf = _artifact([_evidence("Alice", "40000000-0000-0000-0000-000000000001", "2026-10-10T10:00:00+00:00")])
    metadata = PdfReader(BytesIO(pdf)).metadata
    evidence = json.loads(metadata["/RubricaEvidenceJSON"])
    evidence[0]["evidence_sha256"] = "0" * 64
    tampered = _rewrite_metadata(pdf, RubricaEvidenceJSON=canonical_json(evidence).decode())
    with pytest.raises(EvidenceVerificationError, match="Invalid evidence hash"):
        verify_signed_pdf(tampered)


def test_evidence_manifest_tampering_is_detected() -> None:
    pdf = _artifact([_evidence("Alice", "40000000-0000-0000-0000-000000000001", "2026-10-10T10:00:00+00:00")])
    tampered = _rewrite_metadata(pdf, RubricaEvidenceManifestSHA256="0" * 64)
    with pytest.raises(EvidenceVerificationError, match="Invalid Rubrica evidence manifest"):
        verify_signed_pdf(tampered)
