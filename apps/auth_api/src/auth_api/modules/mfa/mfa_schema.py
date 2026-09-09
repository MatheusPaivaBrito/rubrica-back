from pydantic import BaseModel, Field


class MfaSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaReauthenticationRequest(MfaCodeRequest):
    password: str = Field(min_length=8, max_length=128)


class MfaConfirmResponse(BaseModel):
    enabled: bool = True
    recovery_codes: list[str]


class MfaDisableResponse(BaseModel):
    enabled: bool = False


class MfaStatusResponse(BaseModel):
    enabled: bool
    required_by_policy: bool
    setup_required: bool
    recovery_codes_remaining: int


class MfaRecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]
