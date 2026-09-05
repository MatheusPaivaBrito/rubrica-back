from fastapi import FastAPI

from eventing_api.bootstrap.routes import register_routes
from eventing_api.infrastructure.settings import settings
from shared_kernel.errors import register_exception_handlers


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, version="0.1.0")
    register_exception_handlers(app, service_name=settings.SERVICE_NAME)
    register_routes(app)
    return app
