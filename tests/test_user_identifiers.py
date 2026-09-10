import pytest
from pydantic import ValidationError

from auth_api.modules.accounts.account_schema import PublicRegistration
from auth_api.modules.users.user_identifier_service import (
    InvalidIdentifierError,
    masked_identifier,
    protect_identifier,
    validate_identifier,
)
from auth_api.modules.users.user_schema import UserCreate


def test_admin_user_can_be_created_without_government_identifier() -> None:
    payload = UserCreate(
        name="International Signer",
        email="signer@example.com",
        password="a-secure-password",
        preferred_locale="en",
    )

    assert payload.cpf is None
    assert payload.identity_document_type is None


def test_legacy_cpf_input_maps_to_international_identifier() -> None:
    payload = UserCreate(
        name="Brazilian Signer",
        email="br@example.com",
        cpf="529.982.247-25",
        password="a-secure-password",
    )

    assert payload.identity_document_type == "BR_CPF"
    assert payload.identity_document_country == "BR"
    assert payload.identity_document_value == "529.982.247-25"


def test_identifier_is_encrypted_masked_and_has_stable_lookup_hmac() -> None:
    normalized = validate_identifier("passport", "AB 123456")
    encrypted_a, lookup_a = protect_identifier(normalized)
    encrypted_b, lookup_b = protect_identifier(normalized)

    assert normalized == "AB123456"
    assert encrypted_a != normalized
    assert encrypted_a != encrypted_b
    assert lookup_a == lookup_b
    assert masked_identifier(normalized) == "••••3456"


def test_my_number_is_disabled_until_legal_review() -> None:
    with pytest.raises(InvalidIdentifierError, match="not enabled"):
        validate_identifier("JP_MY_NUMBER", "123456789012")


def test_partial_identity_document_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PublicRegistration(
            name="Incomplete Identity",
            email="identity@example.com",
            password="a-secure-password",
            preferred_locale="ja-JP",
            identity_document_type="PASSPORT",
        )
