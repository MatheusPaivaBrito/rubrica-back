from typing import Literal

from pydantic import BaseModel, Field


class InlineEmailImage(BaseModel):
    content: str = Field(min_length=1, max_length=2_000_000)
    filename: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._-]+$")
    content_id: str = Field(min_length=1, max_length=127, pattern=r"^[A-Za-z0-9._-]+$")
    content_type: Literal["image/png", "image/jpeg", "image/gif"]


class ResendEmailRequest(BaseModel):
    recipient: str = Field(min_length=3, max_length=255)
    subject: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=10000)
    html: str | None = Field(default=None, min_length=1, max_length=100_000)
    inline_images: list[InlineEmailImage] = Field(default_factory=list, max_length=3)
    idempotency_key: str = Field(min_length=8, max_length=180)
