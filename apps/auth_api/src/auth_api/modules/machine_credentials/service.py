"""Internal Auth primitives. Callers must verify administrative grants first.

Not exposed by a router until the authenticated Core authorization boundary exists.
No imports or database reads from Core are permitted here.
"""

from datetime import UTC, datetime
from dataclasses import dataclass
import hashlib
import hmac
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from auth_api.modules.machine_credentials.entity import (
    MachineCredentialAuditEntity, MachineCredentialEntity,
)
from auth_api.modules.machine_credentials.tokens import SCOPES, IssuedToken, issue_token


class CredentialError(ValueError):
    pass


@dataclass(frozen=True)
class MachineContext:
    tenant_id: UUID
    integration_id: UUID
    public_id: str
    environment: str
    sandbox: bool
    scopes: frozenset[str]


def authenticate_token(
    database: Session, *, secret: str, environment: str,
    sandbox: bool, permission: str, now: datetime,
) -> MachineContext:
    """Read current binding on every call; never trust claims in token text."""
    if now.tzinfo is None:
        raise CredentialError("Timezone-aware timestamps required")
    match = re.fullmatch(
        r"rubrica_(development|staging|production)_(live|sandbox)_([0-9a-f]{32})_([A-Za-z0-9_-]{43})",
        secret,
    )
    if match is None or permission not in SCOPES:
        raise CredentialError("Invalid machine credential")
    credential = database.scalar(select(MachineCredentialEntity).where(
        MachineCredentialEntity.public_id == match[3],
        MachineCredentialEntity.environment == environment,
        MachineCredentialEntity.sandbox == sandbox,
        MachineCredentialEntity.enabled.is_(True),
        MachineCredentialEntity.deleted_at.is_(None),
    ).execution_options(populate_existing=True))
    expiry = credential.expires_at if credential is not None else None
    # SQLite loses timezone information; persisted timestamps are canonical UTC.
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if (
        credential is None
        or not credential.digest
        or not hmac.compare_digest(credential.digest, hashlib.sha256(secret.encode()).hexdigest())
        or (expiry is not None and now >= expiry)
        or permission not in credential.scopes
    ):
        raise CredentialError("Invalid machine credential")
    return MachineContext(
        tenant_id=credential.tenant_id, integration_id=credential.integration_id,
        public_id=credential.public_id, environment=credential.environment,
        sandbox=credential.sandbox, scopes=frozenset(credential.scopes),
    )


def revoke_token(
    database: Session, *, tenant_id: UUID, integration_id: UUID,
    environment: str, sandbox: bool, subject: str,
) -> None:
    """Erase the active verifier without disabling the integration binding."""
    credential = database.scalar(select(MachineCredentialEntity).where(
        MachineCredentialEntity.tenant_id == tenant_id,
        MachineCredentialEntity.integration_id == integration_id,
        MachineCredentialEntity.environment == environment,
        MachineCredentialEntity.sandbox == sandbox,
        MachineCredentialEntity.deleted_at.is_(None),
    ).with_for_update())
    if credential is None:
        raise CredentialError("Credential binding not found")
    if credential.digest is None:
        return
    database.add(MachineCredentialAuditEntity(
        tenant_id=tenant_id, integration_id=integration_id,
        public_id=credential.public_id, actor=subject, action="revoked",
    ))
    credential.digest = None
    credential.public_id = None
    credential.scopes = []
    credential.expires_at = None
    database.flush()


def rotate_token(
    database: Session, *, tenant_id: UUID, integration_id: UUID, subject: str,
    environment: str, sandbox: bool, scopes: frozenset[str],
    expires_at: datetime | None, now: datetime,
) -> IssuedToken:
    """Rotate an existing authorization binding; caller owns commit."""
    if now.tzinfo is None or (expires_at is not None and expires_at.tzinfo is None):
        raise CredentialError("Timezone-aware timestamps required")
    if not scopes or not scopes <= SCOPES:
        raise CredentialError("Explicit supported API permissions required")
    if expires_at is not None and expires_at <= now:
        raise CredentialError("Token expiry must be in the future")
    credential = database.scalar(select(MachineCredentialEntity).where(
        MachineCredentialEntity.integration_id == integration_id,
        MachineCredentialEntity.tenant_id == tenant_id,
        MachineCredentialEntity.environment == environment,
        MachineCredentialEntity.sandbox == sandbox,
        MachineCredentialEntity.deleted_at.is_(None),
    ).with_for_update())
    if credential is None:
        raise CredentialError("Credential binding not found")
    if not credential.enabled:
        raise CredentialError("Credential binding is disabled")
    token = issue_token(environment=environment, sandbox=sandbox)
    credential.public_id = token.public_id
    credential.digest = token.digest
    credential.scopes = sorted(scopes)
    credential.expires_at = expires_at
    credential.rotated_at = now
    credential.rotated_by = subject
    database.add(MachineCredentialAuditEntity(
        tenant_id=tenant_id, integration_id=integration_id,
        public_id=token.public_id, actor=subject, action="rotated",
    ))
    database.flush()
    return token
