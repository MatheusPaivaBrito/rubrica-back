from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


bearer_auth = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


def access_token(request: Request, credentials: HTTPAuthorizationCredentials | None = None) -> str:
    if credentials is not None:
        return credentials.credentials
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token if scheme.lower() == "bearer" and token else request.cookies.get("access_token", "")
