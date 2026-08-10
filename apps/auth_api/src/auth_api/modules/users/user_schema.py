from typing import Literal

from pydantic import BaseModel, Field


UserRole = Literal["signature_operator", "signature_signer", "signature_auditor"]


class UserCreate(BaseModel):
    email: str = Field(min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = "signature_signer"


class UserRead(BaseModel):
    id: str
    email: str
    role: UserRole
    is_active: bool
