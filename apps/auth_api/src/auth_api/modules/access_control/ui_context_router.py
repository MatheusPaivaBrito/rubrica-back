from fastapi import APIRouter, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials

from auth_api.infrastructure.security import access_token, bearer_auth
from auth_api.modules.sessions.session_schema import UiContextResponse
from auth_api.modules.sessions.session_service import session_service


router = APIRouter(prefix="/access-control", tags=["access-control - query"])


@router.get("/ui-context", response_model=UiContextResponse)
async def get_ui_context(request: Request, credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth)) -> UiContextResponse:
    context = session_service.ui_context(access_token(request, credentials))
    if context is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return context


@router.get("/context", response_model=UiContextResponse)
async def get_service_context(request: Request, credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth)) -> UiContextResponse:
    """Stable Auth/Core contract for protected Core API operations."""
    return await get_ui_context(request, credentials)
