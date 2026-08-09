from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    session_id: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=20)


class SessionRead(BaseModel):
    session_id: str
    subject: str


class LogoutResponse(BaseModel):
    logged_out: bool = True


class UiContextResponse(BaseModel):
    version: int = 1
    subject: str
    roles: list[str] = Field(default_factory=lambda: ["project_user"])
    permission_keys: list[str]
    capability_hash: str
