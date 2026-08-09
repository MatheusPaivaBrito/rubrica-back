from sqlalchemy import select

from auth_api.infrastructure.database.connection import SessionLocal
from auth_api.modules.access_control.access_control_entity import UserRoleEntity


ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "signature_admin": frozenset({"*"}),
    "signature_operator": frozenset({"documents:read", "documents:write", "signature_requests:read", "signature_requests:write", "audit:read"}),
    "signature_signer": frozenset({"signing:read", "signing:write"}),
    "signature_auditor": frozenset({"documents:read", "signature_requests:read", "audit:read"}),
}


class AccessControlService:
    def context_for_user(self, user_id: int) -> tuple[list[str], list[str]]:
        with SessionLocal() as database:
            roles = list(database.scalars(select(UserRoleEntity.role).where(UserRoleEntity.user_id == user_id).order_by(UserRoleEntity.role)).all())
        permissions = sorted({permission for role in roles for permission in ROLE_PERMISSIONS.get(role, frozenset())})
        return roles, permissions


access_control_service = AccessControlService()
