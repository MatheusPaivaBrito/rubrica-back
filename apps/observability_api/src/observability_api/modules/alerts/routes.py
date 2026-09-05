from fastapi import APIRouter
from pydantic import BaseModel, Field


router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertEvent(BaseModel):
    service: str = Field(min_length=2, max_length=80)
    rule_code: str = Field(min_length=2, max_length=80)
    severity: str = Field(default="warning", pattern="^(info|warning|error|critical)$")
    message: str = Field(min_length=3, max_length=300)


@router.get("/rules", summary="List starter alert rules")
def list_rules() -> dict:
    return {
        "rules": [
            {"code": "api_error_rate", "provider": "grafana", "enabled": True},
            {"code": "provider_unavailable", "provider": "observability_api", "enabled": True},
        ]
    }


@router.post("/events", summary="Accept an alert event")
def accept_event(payload: AlertEvent) -> dict:
    return {"accepted": True, "service": payload.service, "rule_code": payload.rule_code, "severity": payload.severity}
