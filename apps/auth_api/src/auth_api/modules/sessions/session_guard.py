from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth_api.modules.sessions.session_schema import SessionRead
from auth_api.modules.sessions.session_service import session_service


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
    session = session_service.current_session(access_token(request, credentials))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return session
