from fastapi import APIRouter

from observability_api.infrastructure.providers import grafana_status, loki_status, sentry_status
from observability_api.infrastructure.settings import settings


router = APIRouter(prefix="/dashboards", tags=["dashboards"])


@router.get("/providers", summary="List observability providers")
def list_providers() -> dict:
    return {
        "providers": {
            "loki": {"url": settings.LOKI_URL, "ready_url": settings.LOKI_READY_URL},
            "grafana": {"url": settings.GRAFANA_URL, "health_url": settings.GRAFANA_HEALTH_URL},
            "sentry": {"configured": bool(settings.SENTRY_DSN)},
        }
    }


@router.get("/providers/health", summary="Check observability providers")
def provider_health() -> dict:
    return {"providers": {"loki": loki_status(), "grafana": grafana_status(), "sentry": sentry_status()}}
