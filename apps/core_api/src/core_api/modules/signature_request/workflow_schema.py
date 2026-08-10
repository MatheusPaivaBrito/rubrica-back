from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RequestStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class SignerStatus(StrEnum):
    PENDING = "pending"
    VIEWED = "viewed"
    SIGNED = "signed"
    DECLINED = "declined"
    EXPIRED = "expired"


class SignatureRequestCreate(BaseModel):
    document_id: str
    expires_at: datetime
    created_by: str = Field(min_length=1, max_length=255)


class SignatureRequestInput(BaseModel):
    document_id: str
    expires_at: datetime


class SignatureRequestRead(BaseModel):
    id: str
    document_id: str
    document_version: int
    document_sha256: str
    status: RequestStatus
    expires_at: datetime
    created_by: str
    created_at: datetime
    completed_at: datetime | None = None
    signer_count: int = 0
    signed_count: int = 0
    signing_url: str = ""


class SignerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    token_ttl_seconds: int = Field(default=604800, ge=300, le=2592000)


class SignerRead(BaseModel):
    id: str
    signature_request_id: str
    auth_user_id: str
    name: str
    email: str
    status: SignerStatus
    token_expires_at: datetime
    link_revoked_at: datetime | None = None
    signed_at: datetime | None = None


class SignerCreated(SignerRead):
    signing_url: str


class SigningRead(BaseModel):
    request: SignatureRequestRead
    signer: SignerRead
    document_title: str
    original_filename: str


class SignCommand(BaseModel):
    consent: bool


class AuditEventRead(BaseModel):
    id: str
    occurred_at: datetime
    actor_type: str
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    correlation_id: str
    metadata_sanitized: dict[str, object]
