import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pyhanko.sign.signers.pdf_cms import SimpleSigner
from reportlab.pdfgen.canvas import Canvas

from core_api.modules.signature_request.serproid_service import _sign_pdf_with_serpro
from core_api.modules.signature_request.workflow_service import WorkflowError


def test_serpro_cms_is_embedded_and_wrong_certificate_is_rejected(tmp_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test signer")])
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_file = tmp_path / "key.pem"
    cert_file = tmp_path / "cert.pem"
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    signer = SimpleSigner.load(str(key_file), str(cert_file))
    pdf = BytesIO()
    canvas = Canvas(pdf)
    canvas.drawString(40, 40, "Document for certificate signing")
    canvas.save()

    class Response:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class Client:
        def post(self, _url, *, headers, json):
            assert headers["Authorization"] == "Bearer test-token"
            digest = base64.b64decode(json["hashes"][0]["hash"])
            with ThreadPoolExecutor(max_workers=1) as pool:
                signed = pool.submit(lambda: asyncio.run(signer.async_sign(digest, "sha256", use_pades=True))).result()
            return Response({"signatures": [{"id": "rubrica-pdf", "raw_signature": base64.b64encode(signed.dump()).decode()}]})

    der = certificate.public_bytes(serialization.Encoding.DER)
    result = asyncio.run(_sign_pdf_with_serpro(pdf.getvalue(), Client(), "test-token", der))
    assert result.startswith(b"%PDF-")
    assert len(result) > len(pdf.getvalue())
    with pytest.raises(WorkflowError, match="differs"):
        asyncio.run(_sign_pdf_with_serpro(pdf.getvalue(), Client(), "test-token", b"wrong certificate"))
