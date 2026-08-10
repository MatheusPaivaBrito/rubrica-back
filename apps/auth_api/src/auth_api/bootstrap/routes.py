from fastapi import FastAPI

from auth_api.bootstrap.health import router as health_router
from auth_api.modules.access_control.ui_context_router import router as ui_context_router
from auth_api.modules.sessions.session_router import router as session_router
from auth_api.modules.users.user_router import router as user_router


def register_routes(app: FastAPI) -> None:
    app.include_router(health_router)
    app.include_router(session_router)
    app.include_router(ui_context_router)
    app.include_router(user_router)
