from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class DocumentStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    ARCHIVED = "archived"


class DocumentCreate(BaseModel):
    organization_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=240)
    original_filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/octet-stream", min_length=1, max_length=160)
    created_by: str = Field(min_length=1, max_length=255)


class DocumentRead(BaseModel):
    id: str
    organization_id: str
    title: str
    original_filename: str
    content_type: str
    sha256: str
    version: int
    status: DocumentStatus
    created_by: str
    created_at: datetime
    updated_at: datetime


class DocumentVersionRead(BaseModel):
    document_id: str
    version: int
    original_filename: str
    content_type: str
    sha256: str
    size_bytes: int
    created_by: str
    created_at: datetime


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    status: DocumentStatus | None = None
