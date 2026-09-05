from fastapi import FastAPI

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.domains.email.email_router import router as email_router
from notification_api.modules.messaging.domains.slack.slack_router import router as slack_router
from notification_api.modules.messaging.domains.whatsapp.whatsapp_router import router as whatsapp_router
from shared_kernel.errors import register_exception_handlers


app = FastAPI(title=settings.APP_NAME, version="0.1.0")
register_exception_handlers(app, service_name=settings.SERVICE_NAME)
app.include_router(email_router)
app.include_router(slack_router)
app.include_router(whatsapp_router)


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "notification_api"}


@app.get("/channels", tags=["channels"])
async def list_channels() -> dict[str, object]:
    return settings.channel_status()
