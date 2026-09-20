import pytest

from auth_api.modules.users.user_identifier_service import (
    InvalidIdentifierError,
    validate_identifier,
)


def test_cpf_is_validated_and_normalized_for_protected_persistence() -> None:
    cpf = validate_identifier("BR_CPF", "529.982.247-25")
    assert cpf == "52998224725"


def test_invalid_cpf_is_rejected() -> None:
    with pytest.raises(InvalidIdentifierError, match="Invalid Brazilian CPF"):
        validate_identifier("BR_CPF", "111.111.111-11")


def test_cnpj_is_validated_and_normalized_for_protected_persistence() -> None:
    cnpj = validate_identifier("BR_CNPJ", "11.222.333/0001-81")
    assert cnpj == "11222333000181"


def test_invalid_cnpj_is_rejected() -> None:
    with pytest.raises(InvalidIdentifierError, match="Invalid Brazilian CNPJ"):
        validate_identifier("BR_CNPJ", "11.111.111/1111-11")
