from hmac import new as hmac_new
from uuid import UUID, uuid4

from auth_api.modules.sessions.session_service import SessionService
from core_api.infrastructure.settings import settings
from core_api.modules.signature_request.database_workflow_service import DatabaseSignatureWorkflowService
from core_api.modules.tenant.tenant_schema import TenantRead
from shared_kernel.identifiers import new_identifier
from shared_kernel.time.datetime_service import DateTimeService


def test_shared_identifiers_are_uuid4() -> None:
    identifier = new_identifier()

    assert isinstance(identifier, UUID)
    assert identifier.version == 4


def test_legacy_integer_user_id_maps_to_deterministic_uuid() -> None:
    assert SessionService._user_identifier("42") == UUID(int=42)
    current = uuid4()
    assert SessionService._user_identifier(current) == current


def test_legacy_signing_link_token_can_be_reconstructed_after_uuid_migration() -> None:
    migrated_request_id = UUID(int=42)
    nonce = "legacy-nonce"
    expected = hmac_new(settings.EVIDENCE_SECRET.encode(), b"rubrica-request:42:legacy-nonce", "sha256").hexdigest()

    assert DatabaseSignatureWorkflowService._request_token(migrated_request_id, nonce) == expected


def test_uuid_schema_serializes_as_uuid_string() -> None:
    identifier = uuid4()
    item = TenantRead(id=identifier, name="Tenant", slug="tenant", status="active", role="admin", created_at=DateTimeService.utc_now())

    assert item.model_dump(mode="json")["id"] == str(identifier)
