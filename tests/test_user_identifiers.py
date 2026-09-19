import pytest
from pydantic import ValidationError

from auth_api.modules.accounts.account_schema import PublicRegistration
from auth_api.modules.users.user_identifier_service import (
    add_identifier,
    InvalidIdentifierError,
    masked_identifier,
    protect_identifier,
    validate_identifier,
)
from auth_api.modules.users.user_schema import UserCreate
from auth_api.modules.users.user_schema import UserIdentifierRead


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


def test_persisted_identifier_fields_never_contain_plaintext() -> None:
    class Database:
        item = None

        @classmethod
        def add(cls, item) -> None:
            cls.item = item

    raw_value = "AB 123456"
    item = add_identifier(
        Database(),
        user_id=None,
        issuing_country="br",
        identifier_type="passport",
        value=raw_value,
    )

    persisted_values = {
        item.normalized_value_encrypted,
        item.lookup_hmac,
        item.masked_display,
    }
    assert raw_value not in persisted_values
    assert "AB123456" not in persisted_values
    assert item.issuing_country == "BR"
    assert item.identifier_type == "PASSPORT"
    assert item.masked_display == "••••3456"
    assert item.normalized_value_encrypted.startswith("gAAAAA")
    assert len(item.lookup_hmac) == 64


def test_invalid_issuing_country_is_rejected_before_persistence() -> None:
    with pytest.raises(InvalidIdentifierError, match="Invalid issuing country"):
        add_identifier(
            object(),
            user_id=None,
            issuing_country="BŘ",
            identifier_type="passport",
            value="AB123456",
        )


def test_identifier_api_schema_exposes_only_masked_value() -> None:
    class StoredIdentifier:
        id = "94e00f3f-6084-4403-b58c-59cca9b079e5"
        issuing_country = "BR"
        identifier_type = "BR_CPF"
        masked_display = "•••••••4725"
        verification_status = "format_valid"
        normalized_value_encrypted = "ciphertext-must-stay-in-auth"
        lookup_hmac = "lookup-hmac-must-stay-in-auth"

    response = UserIdentifierRead.model_validate(
        StoredIdentifier(), from_attributes=True
    ).model_dump(mode="json")

    assert response["masked_display"] == "•••••••4725"
    assert "normalized_value_encrypted" not in response
    assert "lookup_hmac" not in response


def test_my_number_is_disabled_until_legal_review() -> None:
    with pytest.raises(InvalidIdentifierError, match="not enabled"):
        validate_identifier("JP_MY_NUMBER", "123456789012")


def test_partial_identity_document_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PublicRegistration(
            name="Incomplete Identity",
            email="identity@example.com",
            preferred_locale="ja-JP",
            identity_document_type="PASSPORT",
        )


def test_public_registration_does_not_accept_a_password() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PublicRegistration.model_validate(
            {
                "name": "New account",
                "email": "new@example.com",
                "password": "must-not-be-collected",
                "preferred_locale": "pt-BR",
            }
        )
