from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from shared_kernel.identifiers import Identifier


class CompleteMetaWhatsappSignup(BaseModel):
    tenant_id: Identifier
    authorization_code: str = Field(min_length=8, max_length=4096)
    waba_id: str = Field(pattern=r"^[0-9]+$", min_length=5, max_length=80)
    phone_number_id: str | None = Field(
        default=None,
        pattern=r"^[0-9]+$",
        min_length=5,
        max_length=80,
    )
    two_step_pin: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    redirect_uri: str | None = Field(default=None, max_length=2048)
    confirm_reassignment: bool = False


class MetaWhatsappConnectionView(BaseModel):
    id: Identifier
    tenant_id: Identifier
    status: Literal["connected", "disconnected", "verification_failed"]
    waba_id: str
    phone_number_id: str
    display_phone_number: str | None
    verified_name: str | None
    quality_rating: str | None
    connected_at: datetime
    last_verified_at: datetime | None
    disconnected_at: datetime | None

    model_config = {"from_attributes": True}


class MetaWhatsappSignupConfiguration(BaseModel):
    enabled: bool
    app_id: str | None
    configuration_id: str | None
    graph_api_version: str


class MetaWhatsappVerificationResult(BaseModel):
    status: Literal["connected", "verification_failed"]
    verified: bool
    connection: MetaWhatsappConnectionView
