from pydantic import BaseModel, ConfigDict


class TwilioMessageResponse(BaseModel):
    sid: str
    status: str | None = None

    model_config = ConfigDict(extra="ignore")
