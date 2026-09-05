from fastapi import APIRouter

from observability_api.infrastructure.providers import alloy_status, grafana_status, loki_status, sentry_status


router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "observability_api"}


@router.get("/ready")
async def readiness_check() -> dict:
    dependencies = {
        "loki": loki_status(),
        "grafana": grafana_status(),
        "sentry": sentry_status(),
        "alloy": alloy_status(),
    }
    required = (dependencies["loki"]["status"], dependencies["grafana"]["status"])
    if dependencies["alloy"]["status"] != "disabled":
        required = (*required, dependencies["alloy"]["status"])
    return {
        "status": "ready" if all(status == "ok" for status in required) else "degraded",
        "dependencies": dependencies,
    }
