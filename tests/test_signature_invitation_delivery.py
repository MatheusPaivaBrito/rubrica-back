from core_api.modules.signature_request import notification_client


def test_local_fixture_invitation_does_not_call_external_provider(monkeypatch) -> None:
    monkeypatch.setattr(notification_client.settings, "ENVIRONMENT", "development")

    def unexpected_post(*args, **kwargs):
        raise AssertionError("local fixture email reached the external provider")

    monkeypatch.setattr(notification_client.httpx, "post", unexpected_post)

    notification_client.send_signature_invitation(
        recipient="local.empresa.membro@example.local",
        signer_name="Membro Empresa Local",
        document_title="Contrato local",
        signing_url="http://localhost:7171/sign/example",
        locale="pt-BR",
        idempotency_key="local-test",
    )


def test_production_does_not_skip_dot_local_recipient(monkeypatch) -> None:
    monkeypatch.setattr(notification_client.settings, "ENVIRONMENT", "production")
    calls: list[str] = []

    class Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

    def record_post(*args, **kwargs):
        calls.append(kwargs["json"]["recipient"])
        return Response()

    monkeypatch.setattr(notification_client.httpx, "post", record_post)

    notification_client.send_signature_invitation(
        recipient="fixture@example.local",
        signer_name="Fixture",
        document_title="Production check",
        signing_url="https://rubricasignature.com/sign/example",
        locale="en",
        idempotency_key="production-test",
    )

    assert calls == ["fixture@example.local"]
