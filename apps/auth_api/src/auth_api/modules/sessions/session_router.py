from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security, status
from fastapi.security import HTTPAuthorizationCredentials

from auth_api.infrastructure.security import access_token, bearer_auth
from auth_api.modules.sessions.session_schema import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RefreshRequest,
    SessionRead,
    MfaChallengeRequest,
    MfaChallengeResponse,
)
from auth_api.modules.sessions.session_service import session_service
from auth_api.infrastructure.settings import settings


router = APIRouter(tags=["auth"])


async def require_authenticated_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
) -> SessionRead:
    session = session_service.current_session(access_token(request, credentials))
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return session


@router.post("/auth/login", response_model=LoginResponse | MfaChallengeResponse)
async def login(
    payload: LoginRequest,
    response: Response,
) -> LoginResponse | MfaChallengeResponse:
    authenticated = session_service.login(payload)
    if authenticated is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if isinstance(authenticated, LoginResponse):
        _set_auth_cookies(response, authenticated)
    return authenticated


@router.post("/auth/mfa/challenge", response_model=LoginResponse)
async def complete_mfa_challenge(
    payload: MfaChallengeRequest,
    response: Response,
) -> LoginResponse:
    authenticated = session_service.complete_mfa_challenge(
        payload.mfa_ticket,
        payload.code,
    )
    if authenticated is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA challenge is invalid or expired",
        )
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
async def get_current_session(session: SessionRead = Depends(require_authenticated_session)) -> SessionRead:
    return session


@router.post("/auth/logout", response_model=LogoutResponse, tags=["sessions - command"])
async def logout(
    request: Request,
    response: Response,
    _session: SessionRead = Depends(require_authenticated_session),
) -> LogoutResponse:
    session_service.logout(access_token(request))
    _clear_auth_cookies(response)
    return LogoutResponse()


@router.post("/auth/logout-all", response_model=LogoutResponse, tags=["sessions - command"])
async def logout_all(
    request: Request,
    response: Response,
    _session: SessionRead = Depends(require_authenticated_session),
) -> LogoutResponse:
    session_service.logout_all(access_token(request))
    _clear_auth_cookies(response)
    return LogoutResponse()


def _set_auth_cookies(response: Response, payload: LoginResponse) -> None:
    secure = settings.ENVIRONMENT.lower() in {"production", "prod"}
    response.set_cookie(
        "access_token",
        payload.access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=settings.AUTH_ACCESS_TTL_SECONDS,
        path="/",
    )
    response.set_cookie(
        "refresh_token",
        payload.refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=settings.AUTH_SESSION_TTL_SECONDS,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
