import pytest
from fastapi import HTTPException

from auth_api.modules.users.passwords import hash_password, verify_password
from auth_api.modules.users.user_router import _cpf_digits


def test_cpf_is_validated_and_only_its_bcrypt_hash_needs_persistence() -> None:
    cpf = _cpf_digits("529.982.247-25")
    digest = hash_password(cpf)

    assert cpf == "52998224725"
    assert digest != cpf
    assert verify_password(cpf, digest)


def test_invalid_cpf_is_rejected() -> None:
    with pytest.raises(HTTPException, match="CPF inválido"):
        _cpf_digits("111.111.111-11")
