from fastapi import APIRouter
from sqlalchemy import text

from observability_api.infrastructure.database.connection import engine
from observability_api.infrastructure.settings import settings


router = APIRouter(tags=["system"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.SERVICE_NAME}


@router.get("/ready")
def readiness_check() -> dict[str, object]:
    database = _database_status()
    return {
        "status": "ready" if database["status"] == "ok" else "degraded",
        "service": settings.SERVICE_NAME,
        "database": settings.OBSERVABILITY_POSTGRES_DB,
        "dependencies": {"database": database},
    }


def _database_status() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return {"status": "unavailable"}
    return {"status": "ok", "database": settings.OBSERVABILITY_POSTGRES_DB}
