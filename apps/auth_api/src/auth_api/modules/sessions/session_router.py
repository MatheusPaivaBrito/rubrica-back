from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security, status
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse

from auth_api.infrastructure.security import access_token, bearer_auth
from auth_api.modules.sessions.session_schema import (
    LoginRequest,
    LoginResponse,
    BrowserLoginResponse,
    LogoutResponse,
    RefreshRequest,
    SessionRead,
    MfaChallengeRequest,
    MfaChallengeResponse,
)
from auth_api.modules.sessions.session_service import session_service
from auth_api.modules.sessions.turnstile import login_turnstile_config, verify_login_turnstile
from auth_api.infrastructure.settings import settings
from shared_kernel.security.csrf import require_same_origin


router = APIRouter(tags=["auth"])


@router.get("/auth/turnstile/config")
async def turnstile_config() -> dict[str, str | bool]:
    return login_turnstile_config()


async def require_authenticated_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
) -> SessionRead:
    if credentials is None and request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_same_origin(request, settings.AUTH_PUBLIC_WEB_URL, settings.ENVIRONMENT)
    session = session_service.current_session(access_token(request, credentials))
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return session


async def require_mfa_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_auth),
) -> SessionRead:
    session = await require_authenticated_session(request, credentials)
    context = session_service.ui_context(access_token(request, credentials))
    if context is None or context.mfa_setup_required:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Configure MFA before accessing Rubrica")
    return session


@router.post("/auth/login", response_model=BrowserLoginResponse | MfaChallengeResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
) -> LoginResponse | MfaChallengeResponse:
    verify_login_turnstile(payload.turnstile_token, request.headers.get("x-real-ip") or (request.client.host if request.client else None))
    authenticated = session_service.login(payload)
    if authenticated is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if isinstance(authenticated, LoginResponse):
        _set_auth_cookies(response, authenticated)
    return authenticated


@router.post("/auth/mfa/challenge", response_model=BrowserLoginResponse)
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


@router.post("/auth/refresh", response_model=BrowserLoginResponse)
async def refresh(payload: RefreshRequest, request: Request, response: Response) -> LoginResponse | JSONResponse:
    if payload.refresh_token is None:
        require_same_origin(request, settings.AUTH_PUBLIC_WEB_URL, settings.ENVIRONMENT)
    token = payload.refresh_token or request.cookies.get("refresh_token", "")
    authenticated = session_service.refresh(token)
    if authenticated is None:
        rejected = JSONResponse(status_code=401, content={"detail": "Refresh token is invalid"})
        _clear_auth_cookies(rejected)
        return rejected
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
