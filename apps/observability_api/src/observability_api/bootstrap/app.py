from fastapi import FastAPI

from observability_api.bootstrap.routes import register_routes
from observability_api.infrastructure.providers import configure_sentry
from observability_api.infrastructure.settings import settings
from shared_kernel.errors import register_exception_handlers
from shared_kernel.http import apply_cors, apply_request_correlation, apply_request_logging


def create_app() -> FastAPI:
    configure_sentry()
    app = FastAPI(
        title="Observability API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        swagger_ui_parameters={
            "docExpansion": "none",
            "filter": True,
            "defaultModelsExpandDepth": -1,
            "displayRequestDuration": True,
        },
    )
    apply_request_correlation(app, service_name=settings.SERVICE_NAME)
    apply_request_logging(app, service_name=settings.SERVICE_NAME, environment=settings.ENVIRONMENT)
    apply_cors(app, settings.CORS_CONFIG)
    register_exception_handlers(app, service_name=settings.SERVICE_NAME)
    register_routes(app)
    return app
