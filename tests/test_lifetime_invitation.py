from types import SimpleNamespace

import pytest

from auth_api.modules.accounts.account_schema import PublicRegistration
from auth_api.modules.accounts.account_service import AccountConflictError
from toolbox.seeds.lifetime_invitation import invalid_document_message, invite, main


class DatabaseStub:
    def __init__(self, user) -> None:
        self.user = user

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def scalar(self, _statement):
        return self.user


def registration() -> PublicRegistration:
    return PublicRegistration(
        name="Selected Person",
        email="selected@example.com",
        preferred_locale="en",
        identity_document_type="PASSPORT",
        identity_document_country="US",
        identity_document_value="A1234567",
    )


def test_invitation_uses_account_activation_without_staff_password(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        "toolbox.seeds.lifetime_invitation.account_service.register",
        lambda payload: captured.update(payload=payload),
    )

    assert invite(registration()) == "created"
    assert "password" not in captured["payload"].model_dump()


def test_pending_invitation_resends_activation(monkeypatch) -> None:
    def conflict(_payload) -> None:
        raise AccountConflictError

    monkeypatch.setattr(
        "toolbox.seeds.lifetime_invitation.account_service.register",
        conflict,
    )
    monkeypatch.setattr(
        "toolbox.seeds.lifetime_invitation.SessionLocal",
        lambda: DatabaseStub(
            SimpleNamespace(is_active=False, email_verified=False)
        ),
    )
    captured = {}
    monkeypatch.setattr(
        "toolbox.seeds.lifetime_invitation.account_service.request_email_verification",
        lambda email: captured.update(email=email),
    )

    assert invite(registration()) == "verification_resent"
    assert captured == {"email": "selected@example.com"}


def test_active_account_is_not_silently_recreated(monkeypatch) -> None:
    def conflict(_payload) -> None:
        raise AccountConflictError

    monkeypatch.setattr(
        "toolbox.seeds.lifetime_invitation.account_service.register",
        conflict,
    )
    monkeypatch.setattr(
        "toolbox.seeds.lifetime_invitation.SessionLocal",
        lambda: DatabaseStub(SimpleNamespace(is_active=True, email_verified=True)),
    )

    with pytest.raises(ValueError, match="active account"):
        invite(registration())


def test_invalid_cnpj_message_explains_required_digits() -> None:
    message = invalid_document_message("BR_CNPJ")

    assert "14 digitos" in message
    assert "digitos verificadores" in message


def test_command_reports_invalid_cnpj_without_traceback(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "lifetime_invitation.py",
            "--name",
            "Selected Company",
            "--email",
            "company@example.com",
            "--locale",
            "pt-BR",
            "--document-type",
            "BR_CNPJ",
            "--document-country",
            "BR",
        ],
    )
    monkeypatch.setattr(
        "toolbox.seeds.lifetime_invitation.getpass", lambda _prompt: "1122233300018"
    )

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 2
    assert "CNPJ invalido" in capsys.readouterr().err
