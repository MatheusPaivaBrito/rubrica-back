from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from base64 import b64decode, b64encode
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator, model_validator

from core_api.infrastructure.settings import settings


def _normalized_png_data_url(value: str | None) -> str | None:
    if value is None:
        return None
    prefix = "data:image/png;base64,"
    if not value.startswith(prefix):
        raise ValueError("Image must be a base64 PNG data URL")
    try:
        content = b64decode(value[len(prefix):], validate=True)
        if len(content) > 256_000:
            raise ValueError("PNG exceeds 256 KB")
        with Image.open(BytesIO(content)) as source:
            source.verify()
        with Image.open(BytesIO(content)) as source:
            if source.width > 2048 or source.height > 2048 or source.width * source.height > 4_000_000:
                raise ValueError("PNG dimensions exceed the supported limit")
            normalized = source.convert("RGBA")
            output = BytesIO()
            normalized.save(output, format="PNG", optimize=True)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise ValueError("PNG image is invalid") from exc
    encoded = b64encode(output.getvalue()).decode("ascii")
    if len(encoded) > 400_000:
        raise ValueError("Normalized PNG exceeds the supported limit")
    return prefix + encoded


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


class ParticipantRole(StrEnum):
    PERSONAL_SIGNER = "personal_signer"
    EXTERNAL_SIGNER = "external_signer"
    COMPANY_REPRESENTATIVE = "company_representative"
    CORPORATE_SEAL = "corporate_seal"


class SignatureMode(StrEnum):
    EVIDENCE = "evidence"
    SERPRO_TIMESTAMP = "serpro_timestamp"
    SERPROID = "serproid"


class SignatureRequestCreate(BaseModel):
    document_id: UUID
    expires_at: datetime
    created_by: str = Field(min_length=1, max_length=255)


class SignatureRequestInput(BaseModel):
    document_id: UUID
    expires_at: datetime


class ReopenSignatureRequest(BaseModel):
    expires_at: datetime
    reason: str = Field(min_length=5, max_length=500)
    pending_signer_ids: list[UUID] = Field(default_factory=list, max_length=200)


class SignatureRequestRead(BaseModel):
    id: UUID
    document_id: UUID
    document_version: int
    document_sha256: str
    status: RequestStatus
    expires_at: datetime
    created_by: str
    created_at: datetime
    opened_at: datetime | None = None
    completed_at: datetime | None = None
    signer_count: int = 0
    signed_count: int = 0
    document_title: str = ""
    original_filename: str = ""
    signature_mode: SignatureMode = SignatureMode.EVIDENCE
    issuer_snapshot: dict[str, object] | None = None
    has_custom_stamp_placement: bool = False
    has_custom_stamp_branding: bool = False
    parent_request_id: UUID | None = None
    round_number: int = 1
    reopened_reason: str | None = None
    reopened_by: str | None = None
    reopened_at: datetime | None = None
    preserved_signature_count: int = 0
    child_request_id: UUID | None = None


class OpenSignatureRequest(BaseModel):
    signature_mode: SignatureMode

    @model_validator(mode="after")
    def require_trusted_timestamp(self) -> "OpenSignatureRequest":
        if settings.ENVIRONMENT.lower() == "production" and self.signature_mode == SignatureMode.EVIDENCE:
            raise ValueError("New signature requests require a SERPRO trusted timestamp")
        return self


class SignerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    preferred_locale: Literal["pt-BR", "en", "es", "ja-JP"] = "en"
    token_ttl_seconds: int = Field(default=604800, ge=300, le=2592000)
    participant_role: ParticipantRole = ParticipantRole.EXTERNAL_SIGNER
    represented_tenant_id: UUID | None = None

    @model_validator(mode="after")
    def validate_representation(self) -> "SignerCreate":
        represents_company = self.participant_role in {
            ParticipantRole.COMPANY_REPRESENTATIVE,
            ParticipantRole.CORPORATE_SEAL,
        }
        if represents_company != (self.represented_tenant_id is not None):
            raise ValueError("represented_tenant_id is required only for company representation")
        return self


class SignerRead(BaseModel):
    id: UUID
    signature_request_id: UUID
    auth_user_id: str
    name: str
    email: str
    preferred_locale: Literal["pt-BR", "en", "es", "ja-JP"] = "en"
    status: SignerStatus
    token_expires_at: datetime
    link_revoked_at: datetime | None = None
    signed_at: datetime | None = None
    identity_document_type: str | None = None
    identity_document_country: str | None = None
    identity_document_masked: str | None = None
    participant_role: ParticipantRole = ParticipantRole.EXTERNAL_SIGNER
    represented_tenant_id: UUID | None = None
    representation_snapshot: dict[str, object] | None = None
    signature_mode: SignatureMode = SignatureMode.SERPRO_TIMESTAMP


class SignerContactRead(BaseModel):
    name: str
    email: str


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
    locale: Literal["pt-BR", "en", "es", "ja-JP"] = "en"
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    signer_id: UUID | None = None
    width: float = Field(default=0.4, ge=0.15, le=0.8)
    height: float = Field(default=0.12, ge=0.06, le=0.35)
    order: int = Field(default=0, ge=0, le=1000)
    display_variant: Literal["full", "minimal", "drawn"] | None = None


class StampCustomization(BaseModel):
    template: Literal["standard", "business", "representative"] = "standard"
    display_variant: Literal["full", "minimal"] = "full"
    primary_color: str = Field(default="#187A66", pattern=r"^#[0-9A-Fa-f]{6}$")
    show_logo: bool = False
    logo_png_data_url: str | None = Field(default=None, max_length=400_000)
    require_drawn_signature: bool = False

    @field_validator("logo_png_data_url")
    @classmethod
    def validate_logo(cls, value: str | None) -> str | None:
        return _normalized_png_data_url(value)


class StampConfiguration(BaseModel):
    placements: list[StampPosition] = Field(default_factory=list, max_length=500)
    customization: StampCustomization | None = None
    signer_signature_modes: dict[UUID, Literal["serpro_timestamp", "serproid"]] = Field(default_factory=dict)


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
    account_country: str | None = None
    stamp: StampPosition | None = None
    viewer_mode: str = Field(default="signer", pattern=r"^(signer|administrator)$")
    issuer_snapshot: dict[str, object] | None = None
    stamp_positions: list[StampPosition] = Field(default_factory=list)
    stamp_customization: StampCustomization | None = None


class SignCommand(BaseModel):
    consent: bool
    consent_version: str = Field(pattern=r"^rubrica-evidence-v(?:1|2)$")
    stamp: StampPosition | None = None
    drawn_signature_png_data_url: str | None = Field(default=None, max_length=400_000)
    client: ClientEvidence
    geolocation: GeolocationEvidence

    @field_validator("drawn_signature_png_data_url")
    @classmethod
    def validate_drawn_signature(cls, value: str | None) -> str | None:
        return _normalized_png_data_url(value)


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
