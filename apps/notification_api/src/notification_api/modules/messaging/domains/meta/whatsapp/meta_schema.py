from pydantic import BaseModel, ConfigDict, Field


class MetaMessageIdentifier(BaseModel):
    id: str

    model_config = ConfigDict(extra="ignore")


class MetaSendMessageResponse(BaseModel):
    messages: list[MetaMessageIdentifier] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class MetaWebhookMetadata(BaseModel):
    display_phone_number: str | None = None
    phone_number_id: str | None = None

    model_config = ConfigDict(extra="ignore")


class MetaWebhookText(BaseModel):
    body: str = ""

    model_config = ConfigDict(extra="ignore")


class MetaWebhookMedia(BaseModel):
    id: str
    mime_type: str | None = None
    sha256: str | None = None
    caption: str | None = None

    model_config = ConfigDict(extra="ignore")


class MetaMediaMetadata(BaseModel):
    url: str
    mime_type: str
    sha256: str | None = None
    file_size: int | None = None

    model_config = ConfigDict(extra="ignore")


class MetaWebhookStatus(BaseModel):
    id: str
    status: str
    timestamp: str | None = None
    recipient_id: str | None = None

    model_config = ConfigDict(extra="ignore")


class MetaWebhookProfile(BaseModel):
    name: str | None = None

    model_config = ConfigDict(extra="ignore")


class MetaWebhookContact(BaseModel):
    wa_id: str
    profile: MetaWebhookProfile | None = None

    model_config = ConfigDict(extra="ignore")


class MetaWebhookMessage(BaseModel):
    from_number: str = Field(alias="from")
    id: str
    timestamp: str | None = None
    type: str | None = None
    text: MetaWebhookText | None = None
    image: MetaWebhookMedia | None = None
    audio: MetaWebhookMedia | None = None

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class MetaWebhookValue(BaseModel):
    messaging_product: str | None = None
    metadata: MetaWebhookMetadata | None = None
    contacts: list[MetaWebhookContact] = Field(default_factory=list)
    messages: list[MetaWebhookMessage] = Field(default_factory=list)
    statuses: list[MetaWebhookStatus] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class MetaWebhookChange(BaseModel):
    field: str | None = None
    value: MetaWebhookValue

    model_config = ConfigDict(extra="ignore")


class MetaWebhookEntry(BaseModel):
    id: str | None = None
    changes: list[MetaWebhookChange] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class MetaWebhookPayload(BaseModel):
    object: str | None = None
    entry: list[MetaWebhookEntry] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")
