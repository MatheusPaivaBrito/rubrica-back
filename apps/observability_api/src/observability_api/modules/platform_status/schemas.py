from typing import Literal

from pydantic import BaseModel


class PlatformStatusResponse(BaseModel):
    status: Literal["available", "unavailable"]
    provider: Literal["grafana"] = "grafana"
    version: str | None = None
    reason: str | None = None
