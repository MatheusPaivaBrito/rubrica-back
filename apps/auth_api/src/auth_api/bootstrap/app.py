from fastapi import FastAPI

from auth_api.bootstrap.routes import register_routes
from auth_api.infrastructure.settings import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
    )
    register_routes(app)
    return app
