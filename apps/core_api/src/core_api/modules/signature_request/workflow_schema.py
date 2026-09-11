from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

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
    document_id: UUID
    expires_at: datetime
    created_by: str = Field(min_length=1, max_length=255)


class SignatureRequestInput(BaseModel):
    document_id: UUID
    expires_at: datetime


class SignatureRequestRead(BaseModel):
    id: UUID
    document_id: UUID
    document_version: int
    document_sha256: str
    status: RequestStatus
    expires_at: datetime
    created_by: str
    created_at: datetime
    completed_at: datetime | None = None
    signer_count: int = 0
    signed_count: int = 0
    document_title: str = ""
    original_filename: str = ""


class SignerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    token_ttl_seconds: int = Field(default=604800, ge=300, le=2592000)


class SignerRead(BaseModel):
    id: UUID
    signature_request_id: UUID
    auth_user_id: str
    name: str
    email: str
    status: SignerStatus
    token_expires_at: datetime
    link_revoked_at: datetime | None = None
    signed_at: datetime | None = None


class SigningLinkRead(BaseModel):
    signing_url: str


class StampPosition(BaseModel):
    page: int = Field(ge=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    template: Literal["BR", "JP", "INTL"] = "INTL"
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    show_flag: bool = False
    template_version: Literal["rubrica-stamp-v2"] = "rubrica-stamp-v2"
    locale: Literal["pt-BR", "en", "ja-JP"] = "en"
    timezone: str = Field(default="UTC", min_length=1, max_length=80)


class ClientEvidence(BaseModel):
    platform: str = Field(default="unknown", max_length=120)
    language: str = Field(default="unknown", max_length=40)
    timezone: str = Field(default="unknown", max_length=80)
    screen_width: int | None = Field(default=None, ge=1, le=20000)
    screen_height: int | None = Field(default=None, ge=1, le=20000)


class GeolocationEvidence(BaseModel):
    status: str = Field(pattern=r"^(granted|denied|unavailable|timeout)$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_meters: float | None = Field(default=None, ge=0, le=1000000)


class SigningRead(BaseModel):
    request: SignatureRequestRead
    signer: SignerRead
    document_title: str
    original_filename: str
    stamp: StampPosition | None = None
    viewer_mode: str = Field(default="signer", pattern=r"^(signer|administrator)$")


class SignCommand(BaseModel):
    consent: bool
    consent_version: str = Field(pattern=r"^rubrica-evidence-v1$")
    stamp: StampPosition
    client: ClientEvidence
    geolocation: GeolocationEvidence


class SignatureEvidenceRead(BaseModel):
    signature_id: UUID
    signer_id: UUID
    request_id: UUID
    document_id: UUID
    document_version: int
    signed_at: datetime
    signer_name: str
    signer_email: str
    subject_hmac_sha256: str
    original_sha256: str
    evidence_sha256: str
    artifact_sha256: str
    evidence: dict[str, object]


class AuditEventRead(BaseModel):
    id: UUID
    occurred_at: datetime
    actor_type: str
    actor_id: str
    action: str
    entity_type: str
    entity_id: UUID
    correlation_id: UUID
    metadata_sanitized: dict[str, object]
