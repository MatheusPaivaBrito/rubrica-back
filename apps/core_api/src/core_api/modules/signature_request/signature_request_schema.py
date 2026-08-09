from datetime import datetime

from pydantic import BaseModel, Field


class SignatureRequestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=80)



class SignatureRequestUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=80)



class SignatureRequestRead(BaseModel):
    id: str
    name: str
    code: str

    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
