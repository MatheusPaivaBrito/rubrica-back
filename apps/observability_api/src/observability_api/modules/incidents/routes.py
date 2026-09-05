from fastapi import APIRouter
from pydantic import BaseModel, Field

from observability_api.infrastructure.providers import capture_incident, sentry_status
from shared_kernel.time import DateTimeService


router = APIRouter(prefix="/incidents", tags=["incidents"])


class IncidentCreate(BaseModel):
    service: str = Field(min_length=2, max_length=80)
    title: str = Field(min_length=3, max_length=180)
    level: str = Field(default="error", pattern="^(debug|info|warning|error|critical)$")
    trace_id: str | None = Field(default=None, max_length=120)
    path: str | None = Field(default=None, max_length=300)
    details: dict = Field(default_factory=dict)


@router.post("", summary="Capture an incident")
def capture(payload: IncidentCreate) -> dict:
    event_id = capture_incident(payload.title, level=payload.level, context=payload.model_dump())
    provider = sentry_status()
    return {
        "accepted": True,
        "provider": "sentry" if event_id else "local_ack",
        "provider_status": provider["status"],
        "sentry_event_id": event_id,
        "received_at": DateTimeService.utc_now().isoformat(),
    }


@router.get("/providers", summary="Show incident providers")
def incident_providers() -> dict:
    return {"providers": {"sentry": sentry_status()}}
