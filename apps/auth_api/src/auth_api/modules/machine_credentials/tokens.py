"""Auth-owned opaque machine credentials, separate from human sessions."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


SCOPES = frozenset({
    "documents:create", "documents:read", "documents:download",
    "signature_requests:create", "signature_requests:open",
    "signature_requests:read", "signing_sessions:create", "usage:read",
})


@dataclass(frozen=True)
class IssuedToken:
    public_id: str
    digest: str
    secret: str = field(repr=False)


def issue_token(*, environment: str, sandbox: bool) -> IssuedToken:
    if environment not in {"development", "staging", "production"}:
        raise ValueError("Unsupported enterprise environment")
    public_id = secrets.token_hex(16)
    mode = "sandbox" if sandbox else "live"
    secret = f"rubrica_{environment}_{mode}_{public_id}_{secrets.token_urlsafe(32)}"
    return IssuedToken(public_id, hashlib.sha256(secret.encode()).hexdigest(), secret)


@dataclass(frozen=True)
class IntegrationCredential:
    tenant_id: UUID
    integration_id: UUID
    compartment_id: UUID
    environment: str
    sandbox: bool
    digest: str = field(repr=False)
    scopes: frozenset[str]
    expires_at: datetime | None = None
    enabled: bool = True

    def authorize(
        self, *, secret: str, environment: str, sandbox: bool,
        permission: str, now: datetime,
    ) -> bool:
        if now.tzinfo is None:
            raise ValueError("Authorization requires timezone-aware time")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("Expiry requires timezone-aware time")
        return bool(
            self.enabled
            and self.environment == environment
            and self.sandbox == sandbox
            and permission in SCOPES
            and permission in self.scopes
            and (self.expires_at is None or now < self.expires_at)
            and hmac.compare_digest(
                self.digest, hashlib.sha256(secret.encode()).hexdigest()
            )
        )

    def permits_resource(
        self, *, tenant_id: UUID, integration_id: UUID, compartment_id: UUID,
    ) -> bool:
        return (
            self.tenant_id == tenant_id
            and self.integration_id == integration_id
            and self.compartment_id == compartment_id
        )
