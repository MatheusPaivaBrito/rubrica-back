from fastapi import APIRouter, Header, HTTPException, Request, status

from auth_api.modules.sessions.session_schema import UiContextResponse
from auth_api.modules.sessions.session_service import session_service


router = APIRouter(prefix="/access-control", tags=["access-control - query"])


@router.get("/ui-context", response_model=UiContextResponse)
async def get_ui_context(request: Request, authorization: str | None = Header(default=None)) -> UiContextResponse:
    token = (authorization or "").removeprefix("Bearer ").strip() or request.cookies.get("access_token", "")
    context = session_service.ui_context(token)
    if context is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return context


@router.get("/context", response_model=UiContextResponse)
async def get_service_context(request: Request, authorization: str | None = Header(default=None)) -> UiContextResponse:
    """Stable Auth/Core contract for protected Core API operations."""
    return await get_ui_context(request, authorization)
