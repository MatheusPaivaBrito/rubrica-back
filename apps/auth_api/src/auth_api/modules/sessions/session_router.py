from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from auth_api.modules.sessions.session_schema import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RefreshRequest,
    SessionRead,
)
from auth_api.modules.sessions.session_service import session_service


router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, response: Response) -> LoginResponse:
    authenticated = session_service.login(payload)
    if authenticated is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    _set_auth_cookies(response, authenticated)
    return authenticated


@router.post("/auth/refresh", response_model=LoginResponse)
async def refresh(payload: RefreshRequest, request: Request, response: Response) -> LoginResponse:
    token = payload.refresh_token or request.cookies.get("refresh_token", "")
    authenticated = session_service.refresh(token)
    if authenticated is None:
        _clear_auth_cookies(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is invalid")
    _set_auth_cookies(response, authenticated)
    return authenticated


@router.get("/sessions/me", response_model=SessionRead, tags=["sessions - query"])
async def get_current_session(request: Request, authorization: str | None = Header(default=None)) -> SessionRead:
    session = session_service.current_session(_access_token(request, authorization))
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return session


@router.post("/auth/logout", response_model=LogoutResponse, tags=["sessions - command"])
async def logout(request: Request, response: Response, authorization: str | None = Header(default=None)) -> LogoutResponse:
    session_service.logout(_access_token(request, authorization))
    _clear_auth_cookies(response)
    return LogoutResponse()


@router.post("/auth/logout-all", response_model=LogoutResponse, tags=["sessions - command"])
async def logout_all(request: Request, response: Response, authorization: str | None = Header(default=None)) -> LogoutResponse:
    if not session_service.logout_all(_access_token(request, authorization)):
        _clear_auth_cookies(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    _clear_auth_cookies(response)
    return LogoutResponse()


def _bearer_token(authorization: str | None) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


def _access_token(request: Request, authorization: str | None) -> str:
    return _bearer_token(authorization) or request.cookies.get("access_token", "")


def _set_auth_cookies(response: Response, payload: LoginResponse) -> None:
    response.set_cookie("access_token", payload.access_token, httponly=True, samesite="lax", path="/")
    response.set_cookie("refresh_token", payload.refresh_token, httponly=True, samesite="lax", path="/")


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
