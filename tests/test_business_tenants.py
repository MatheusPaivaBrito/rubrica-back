from uuid import uuid4

import pytest

from core_api.modules.signature_request.workflow_schema import ParticipantRole, SignerCreate
from core_api.modules.tenant.tenant_identity import (
    InvalidBusinessIdentifierError,
    normalize_cnpj,
    protect_cnpj,
)


def test_cnpj_is_validated_protected_and_masked() -> None:
    normalized = normalize_cnpj("11.222.333/0001-81")
    encrypted, lookup, masked = protect_cnpj(normalized)

    assert normalized == "11222333000181"
    assert normalized not in encrypted
    assert len(lookup) == 64
    assert masked == "••.•••.•••/••••-81"


def test_invalid_cnpj_is_rejected() -> None:
    with pytest.raises(InvalidBusinessIdentifierError):
        normalize_cnpj("11.111.111/1111-11")


def test_company_representative_requires_a_tenant() -> None:
    with pytest.raises(ValueError, match="represented_tenant_id"):
        SignerCreate(
            name="Representative",
            email="representative@example.com",
            participant_role=ParticipantRole.COMPANY_REPRESENTATIVE,
        )


def test_personal_signature_cannot_claim_a_represented_tenant() -> None:
    with pytest.raises(ValueError, match="represented_tenant_id"):
        SignerCreate(
            name="Person",
            email="person@example.com",
            participant_role=ParticipantRole.PERSONAL_SIGNER,
            represented_tenant_id=uuid4(),
        )


def test_corporate_seal_is_distinct_from_a_personal_signature() -> None:
    payload = SignerCreate(
        name="Organization seal",
        email="custodian@example.com",
        participant_role=ParticipantRole.CORPORATE_SEAL,
        represented_tenant_id=uuid4(),
    )
    assert payload.participant_role == ParticipantRole.CORPORATE_SEAL
