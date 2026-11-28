from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from auth_api.bootstrap.routes import register_routes
from auth_api.infrastructure.settings import settings
from auth_api.observability_metrics import collect_business_metrics
from shared_kernel.http import apply_request_correlation, apply_request_logging
from shared_kernel.observability import apply_metrics, apply_tracing


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={
            "detail": [{key: item[key] for key in ("type", "loc", "msg")} for item in error.errors()],
        })

    apply_request_correlation(app, service_name=settings.SERVICE_NAME)
    apply_request_logging(app, service_name=settings.SERVICE_NAME, environment=settings.ENVIRONMENT)
    apply_metrics(app, service_name=settings.SERVICE_NAME, collectors=(collect_business_metrics,))
    apply_tracing(app, service_name=settings.SERVICE_NAME)
    register_routes(app)
    return app
