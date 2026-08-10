from typing import Literal

from pydantic import BaseModel, Field


UserRole = Literal["signature_operator", "signature_signer", "signature_auditor"]


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    email: str = Field(min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    cpf: str = Field(min_length=11, max_length=14)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = "signature_signer"


class UserRead(BaseModel):
    id: str
    name: str
    email: str
    role: UserRole
    is_active: bool
