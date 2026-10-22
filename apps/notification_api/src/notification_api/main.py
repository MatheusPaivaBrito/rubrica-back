from fastapi import FastAPI

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.domains.resend.resend_router import (
    router as resend_router,
)
from shared_kernel.errors import register_exception_handlers
from shared_kernel.http import apply_request_correlation, apply_request_logging
from shared_kernel.observability import apply_metrics, apply_tracing


app = FastAPI(title=settings.APP_NAME, version="0.1.0")
apply_request_correlation(app, service_name=settings.SERVICE_NAME)
apply_request_logging(app, service_name=settings.SERVICE_NAME, environment=settings.ENVIRONMENT)
apply_metrics(app, service_name=settings.SERVICE_NAME)
apply_tracing(app, service_name=settings.SERVICE_NAME)
register_exception_handlers(app, service_name=settings.SERVICE_NAME)
app.include_router(resend_router)


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "notification_api"}


@app.get("/channels", tags=["channels"])
async def list_channels() -> dict[str, object]:
    return settings.channel_status()
