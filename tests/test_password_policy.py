import pytest
from pydantic import ValidationError

from auth_api.modules.accounts.account_schema import EmailVerification, PasswordReset


TOKEN = "a" * 32


@pytest.mark.parametrize("schema", [EmailVerification, PasswordReset])
def test_new_password_accepts_every_required_character_group(schema: type) -> None:
    payload = schema(token=TOKEN, new_password="Secure#2026")

    assert payload.new_password == "Secure#2026"


@pytest.mark.parametrize(
    "password",
    [
        "Short#1",
        "lowercase#1",
        "UPPERCASE#1",
        "NoNumber#",
        "NoSpecial2026",
        "Whitespace 2026",
    ],
)
@pytest.mark.parametrize("schema", [EmailVerification, PasswordReset])
def test_new_password_rejects_missing_requirements(schema: type, password: str) -> None:
    with pytest.raises(ValidationError):
        schema(token=TOKEN, new_password=password)
