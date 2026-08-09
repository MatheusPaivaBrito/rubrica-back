from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core_api.bootstrap.routes import register_routes
from core_api.infrastructure.settings import settings
from core_api.modules.signature_request.workflow_service import WorkflowError


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
    )
    register_routes(app)

    @app.exception_handler(WorkflowError)
    async def workflow_error_handler(_request: Request, exc: WorkflowError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    return app
