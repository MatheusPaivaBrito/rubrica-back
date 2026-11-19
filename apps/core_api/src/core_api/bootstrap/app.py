from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core_api.bootstrap.routes import register_routes
from core_api.infrastructure.settings import settings
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.observability_metrics import collect_business_metrics
from shared_kernel.http import apply_request_correlation, apply_request_logging
from shared_kernel.observability import apply_metrics, apply_tracing


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
    )
    apply_request_correlation(app, service_name=settings.SERVICE_NAME)
    apply_request_logging(app, service_name=settings.SERVICE_NAME, environment=settings.ENVIRONMENT)
    apply_metrics(app, service_name=settings.SERVICE_NAME, collectors=(collect_business_metrics,))
    apply_tracing(app, service_name=settings.SERVICE_NAME)
    register_routes(app)

    @app.exception_handler(WorkflowError)
    async def workflow_error_handler(_request: Request, exc: WorkflowError) -> JSONResponse:
        content: dict[str, object] = {"detail": str(exc)}
        if exc.code:
            content["code"] = exc.code
        content.update(exc.context)
        return JSONResponse(status_code=exc.status_code, content=content)

    return app
