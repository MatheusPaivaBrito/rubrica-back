"""Versioned, secret-free transport contract; not a shared database model."""
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EnterpriseUsageFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    id: UUID
    source_id: UUID
    tenant_id: UUID
    integration_id: UUID
    compartment_id: UUID
    token_public_id: str = Field(min_length=1, max_length=64)
    environment: Literal["development", "staging", "production"]
    sandbox: bool
    kind: Literal["document.uploaded", "signature.completed", "download.completed", "download.partial", "api.request",
                  "storage.added", "storage.removed", "storage.exported"]
    units: int = Field(default=1, ge=0, le=1_000_000)
    bytes_count: int = Field(default=0, ge=0, le=1_000_000_000)
    billable: bool = False
    amount_minor: Literal[0] = 0
    currency: Literal["BRL"] = "BRL"
    price_version: Literal["enterprise-zero-v1"] = "enterprise-zero-v1"
    occurred_at: datetime
    status_code: int | None = Field(default=None, ge=100, le=599)
    duration_ms: float | None = Field(default=None, ge=0, le=86_400_000, allow_inf_nan=False)

    @field_validator("occurred_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("UTC-aware time required")
        return value.astimezone(UTC)

    def checksum(self):
        return sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True,
                                 separators=(",", ":")).encode()).hexdigest()

    @model_validator(mode="after")
    def valid_source(self):
        if self.id != uuid5(NAMESPACE_URL, f"rubrica.enterprise.{self.kind}:{self.source_id}"):
            raise ValueError("Usage ID must match the canonical source")
        if self.billable and (self.sandbox or self.kind != "signature.completed"):
            raise ValueError("Only live completed signatures are billable")
        return self
