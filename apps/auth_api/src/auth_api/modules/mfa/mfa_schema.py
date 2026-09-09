from pydantic import BaseModel, Field


class MfaSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaConfirmResponse(BaseModel):
    enabled: bool = True
    recovery_codes: list[str]


class MfaDisableResponse(BaseModel):
    enabled: bool = False
