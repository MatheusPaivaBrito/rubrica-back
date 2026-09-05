from datetime import datetime

from pydantic import BaseModel, Field


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class TenantRead(BaseModel):
    id: int
    name: str
    slug: str
    status: str
    role: str
    created_at: datetime


class TenantMemberCreate(BaseModel):
    auth_user_id: str = Field(min_length=3, max_length=255)
    role: str = Field(default="member", pattern=r"^(admin|member|auditor)$")
