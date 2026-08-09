from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


bearer_auth = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


def access_token(request: Request, credentials: HTTPAuthorizationCredentials | None = None) -> str:
    if credentials is not None:
        return credentials.credentials
    authorization = request.headers.get("authorization", "")
    return authorization.removeprefix("Bearer ").strip() or request.cookies.get("access_token", "")
