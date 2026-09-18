from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth_api.modules.sessions.session_schema import SessionRead
from auth_api.modules.sessions.session_service import session_service
from auth_api.infrastructure.settings import settings
from shared_kernel.security.csrf import require_same_origin


ACCESS_TOKEN_COOKIE = "access_token"
bearer_scheme = HTTPBearer(auto_error=False)


def access_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    if credentials is not None:
        return credentials.credentials
    return request.cookies.get(ACCESS_TOKEN_COOKIE, "")


def require_authenticated_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> SessionRead:
    if credentials is None and request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_same_origin(request, settings.AUTH_PUBLIC_WEB_URL, settings.ENVIRONMENT)
    session = session_service.current_session(access_token(request, credentials))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return session
