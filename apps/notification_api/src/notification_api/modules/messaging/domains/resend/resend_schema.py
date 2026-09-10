from pydantic import BaseModel, Field


class ResendEmailRequest(BaseModel):
    recipient: str = Field(min_length=3, max_length=255)
    subject: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=10000)
    idempotency_key: str = Field(min_length=8, max_length=180)
