import base64
from hashlib import sha256
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest

from core_api.infrastructure.settings import settings
from core_api.modules.signature_request import serproid_service
from core_api.modules.signature_request.workflow_schema import ClientEvidence, GeolocationEvidence, SignCommand, SignatureMode, StampPosition
from core_api.modules.signature_request.workflow_service import WorkflowError


def test_serpro_authorization_binds_one_signer_and_uses_pkce(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SERPROID_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "SERPROID_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "PUBLIC_WEB_URL", "https://rubricasignature.com")
    monkeypatch.setattr(serproid_service, "identity_summary", lambda *_args: SimpleNamespace(identifier_type="BR_CPF"))
    request_id, signer_id = uuid4(), uuid4()
    context = SimpleNamespace(
        request=SimpleNamespace(id=request_id, status="open", signer_count=1, signed_count=0, document_sha256="a" * 64, signature_mode=SignatureMode.SERPROID),
        signer=SimpleNamespace(id=signer_id, status="pending"),
    )
    monkeypatch.setattr(serproid_service.database_workflow_service, "signing_context", lambda *_args: context)

    class RedisStub:
        stored = None
        def set(self, key, data, *, ex, nx):
            assert ex == 600 and nx is True
            self.stored = (key, data)
            return True

    redis = RedisStub()
    monkeypatch.setattr(serproid_service, "_redis", lambda: redis)
    command = SignCommand(consent=True, consent_version="rubrica-evidence-v1", stamp=StampPosition(page=1, x=.5, y=.5), client=ClientEvidence(), geolocation=GeolocationEvidence(status="unavailable"))
    url = serproid_service.start_authorization("signing-token", "signer@example.com", command, "127.0.0.1", "test-browser")
    query = parse_qs(urlparse(url).query)
    assert query["scope"] == ["single_signature"]
    assert query["redirect_uri"] == ["https://rubricasignature.com/api/auth/serproid/callback"]
    assert query["code_challenge_method"] == ["S256"]
    assert redis.stored[0].endswith(query["state"][0])
    import json
    attempt = json.loads(redis.stored[1])
    expected = base64.urlsafe_b64encode(sha256(attempt["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [expected]
    assert attempt["request_id"] == str(request_id)
    assert attempt["signer_id"] == str(signer_id)
    assert attempt["document_sha256"] == "a" * 64

    context.request.signature_mode = SignatureMode.EVIDENCE
    with pytest.raises(WorkflowError, match="does not use Serpro ID"):
        serproid_service.start_authorization("signing-token", "signer@example.com", command, "127.0.0.1", "test-browser")


def test_serpro_callback_rejects_certificate_identity_mismatch(monkeypatch) -> None:
    import json
    monkeypatch.setattr(settings, "SERPROID_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "SERPROID_CLIENT_SECRET", "test-secret")
    request_id, signer_id = uuid4(), uuid4()
    command = SignCommand(consent=True, consent_version="rubrica-evidence-v1", stamp=StampPosition(page=1, x=.5, y=.5), client=ClientEvidence(), geolocation=GeolocationEvidence(status="unavailable"))
    attempt = {
        "token": "signing-token", "subject": "signer@example.com", "request_id": str(request_id),
        "signer_id": str(signer_id), "document_sha256": "a" * 64, "command": command.model_dump(mode="json"),
        "verifier": "verifier", "ip": "127.0.0.1", "agent": "test",
    }
    class RedisStub:
        def getdel(self, key):
            assert key.endswith("state-value")
            return json.dumps(attempt).encode()
    monkeypatch.setattr(serproid_service, "_redis", lambda: RedisStub())
    monkeypatch.setattr(serproid_service.database_workflow_service, "signing_context", lambda *_args: SimpleNamespace(
        request=SimpleNamespace(id=request_id, document_sha256="a" * 64), signer=SimpleNamespace(id=signer_id)))
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"scope": "single_signature", "authorized_identification_type": "CPF", "authorized_identification": "12345678909", "access_token": "token"}
    class Client:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def post(self, *_args, **_kwargs): return Response()
    monkeypatch.setattr(serproid_service.httpx, "Client", Client)
    monkeypatch.setattr(serproid_service, "identity_matches_certificate", lambda *_args: False)
    with pytest.raises(WorkflowError, match="does not match"):
        serproid_service.finish_authorization("state-value", "code", None, "signer@example.com")
