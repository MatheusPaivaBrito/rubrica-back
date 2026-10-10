from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from asn1crypto import keys as asn1_keys
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.timestamps import DummyTimeStamper
from reportlab.pdfgen.canvas import Canvas

from core_api.infrastructure.settings import settings
from core_api.modules.signature_request import serpro_timestamp_service
from core_api.modules.signature_request.workflow_service import WorkflowError


TEST_POLICY = "1.3.6.1.4.1.4146.2.2"


def _dummy_tsa() -> tuple[DummyTimeStamper, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ACT SERPRO test")])
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=365))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert = asn1_x509.Certificate.load(certificate.public_bytes(serialization.Encoding.DER))
    private_key = asn1_keys.PrivateKeyInfo.load(key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ))
    return DummyTimeStamper(cert, private_key, fixed_dt=datetime(2026, 9, 21, 22, 0, tzinfo=timezone.utc)), certificate


def test_serpro_timestamp_is_embedded_fully_validated_and_reported(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_PROVIDER", "serpro")
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_CONSUMER_KEY", "consumer-key")
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_CONSUMER_SECRET", "consumer-secret")
    dummy, certificate = _dummy_tsa()
    trust_roots = tmp_path / "tsa-root.pem"
    trust_roots.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_TRUST_ROOTS_FILE", str(trust_roots))
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_ACCEPTED_POLICY_OIDS", TEST_POLICY)
    calls: list[str] = []

    class Response:
        def __init__(self, *, json_data=None, content=b""):
            self._json_data = json_data
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self._json_data

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            calls.append(url)
            if url.endswith("/token"):
                assert kwargs["headers"]["Authorization"].startswith("Basic ")
                return Response(json_data={"access_token": "access-token"})
            request = serpro_timestamp_service.tsp.TimeStampReq.load(kwargs["content"])
            response = await dummy.async_request_tsa_response(request)
            return Response(content=response.dump())

    monkeypatch.setattr(serpro_timestamp_service.httpx, "AsyncClient", Client)
    source = BytesIO()
    canvas = Canvas(source)
    canvas.drawString(40, 40, "Timestamped document")
    canvas.save()

    stamped, metadata = serpro_timestamp_service.apply_serpro_timestamp(source.getvalue())

    assert len(stamped) > len(source.getvalue())
    assert len(PdfFileReader(BytesIO(stamped)).embedded_signatures) == 1
    assert calls == [settings.SERPRO_TIMESTAMP_TOKEN_URL, f"{settings.SERPRO_TIMESTAMP_API_URL}/stamps-asn1"]
    assert metadata is not None
    assert metadata["provider"] == "serpro-api-timestamp"
    assert metadata["timestamp"] == "2026-09-21T22:00:00+00:00"
    assert metadata["hash_algorithm"] == "sha256"
    assert len(str(metadata["message_imprint"])) == 64
    assert len(str(metadata["token_sha256"])) == 64
    assert metadata["timestamp_response_base64"]
    assert metadata["validation"]["valid"] is True
    assert metadata["validation"]["trusted"] is True
    assert metadata["validation"]["revoked"] is False
    assert metadata["validation"]["coverage"] == "ENTIRE_FILE"
    assert metadata["validation"]["policy"] == TEST_POLICY

    validation = serpro_timestamp_service.validate_pdf_timestamp(
        stamped,
        trust_roots_file=str(trust_roots),
        accepted_policy_oids={TEST_POLICY},
        allow_fetching=True,
        revocation_mode="require",
    )
    assert validation["valid"] is True

    with pytest.raises(WorkflowError, match="changes after|integrity"):
        serpro_timestamp_service.validate_pdf_timestamp(
            stamped + b"\n% unauthorized incremental bytes\n",
            trust_roots_file=str(trust_roots),
            accepted_policy_oids={TEST_POLICY},
            allow_fetching=True,
            revocation_mode="require",
        )

    tampered = bytearray(stamped)
    protected_offset = max(8, stamped.find(b"Timestamped document"))
    tampered[protected_offset] ^= 1
    with pytest.raises(WorkflowError, match="malformed|integrity|trust validation"):
        serpro_timestamp_service.validate_pdf_timestamp(
            bytes(tampered),
            trust_roots_file=str(trust_roots),
            accepted_policy_oids={TEST_POLICY},
            allow_fetching=True,
            revocation_mode="require",
        )


def test_timestamp_rejects_unapproved_policy(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_PROVIDER", "serpro")
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_CONSUMER_KEY", "consumer-key")
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_CONSUMER_SECRET", "consumer-secret")
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_ACCEPTED_POLICY_OIDS", "1.2.3.4")
    _dummy, certificate = _dummy_tsa()
    trust_roots = tmp_path / "tsa-root.pem"
    trust_roots.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_TRUST_ROOTS_FILE", str(trust_roots))
    request = serpro_timestamp_service.tsp.TimeStampReq({
        "version": "v1",
        "message_imprint": {"hash_algorithm": {"algorithm": "sha256"}, "hashed_message": b"x" * 32},
        "nonce": 42,
        "cert_req": True,
    })
    dummy, _certificate = _dummy_tsa()
    response = dummy.request_tsa_response(request)
    with pytest.raises(WorkflowError, match="policy is not accepted"):
        serpro_timestamp_service._validate_tsa_response(request, response)

    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_ACCEPTED_POLICY_OIDS", TEST_POLICY)
    different_nonce = serpro_timestamp_service.tsp.TimeStampReq({
        "version": "v1",
        "message_imprint": request["message_imprint"],
        "nonce": 43,
        "cert_req": True,
    })
    with pytest.raises(WorkflowError, match="nonce does not match"):
        serpro_timestamp_service._validate_tsa_response(different_nonce, response)

    different_imprint = serpro_timestamp_service.tsp.TimeStampReq({
        "version": "v1",
        "message_imprint": {"hash_algorithm": {"algorithm": "sha256"}, "hashed_message": b"y" * 32},
        "nonce": 42,
        "cert_req": True,
    })
    with pytest.raises(WorkflowError, match="message imprint does not match"):
        serpro_timestamp_service._validate_tsa_response(different_imprint, response)


def test_fake_timestamp_provider_does_not_require_credentials(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_PROVIDER", "fake")
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_CONSUMER_KEY", "consumer-key")
    monkeypatch.setattr(settings, "SERPRO_TIMESTAMP_CONSUMER_SECRET", "consumer-secret")
    assert serpro_timestamp_service.apply_serpro_timestamp(b"pdf") == (b"pdf", None)
