from fastapi import FastAPI
from observability_api.modules.enterprise_usage.routes import router as enterprise_usage_router

from observability_api.bootstrap.health import router as health_router
from observability_api.modules.platform_status.routes import router as platform_status_router


def register_routes(app: FastAPI) -> None:
    app.include_router(enterprise_usage_router)
    app.include_router(health_router)
    app.include_router(platform_status_router)
