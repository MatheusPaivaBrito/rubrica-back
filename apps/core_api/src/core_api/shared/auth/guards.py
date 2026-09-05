from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core_api.infrastructure.settings import settings
from core_api.shared.auth.client import AuthIntrospectionResponse, auth_introspection_client


ACCESS_TOKEN_COOKIE = "access_token"
bearer_scheme = HTTPBearer(auto_error=False)


class CoreAuthGuard:
    @staticmethod
    def _access_token(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None,
    ) -> str | None:
        if credentials is not None:
            return credentials.credentials
        return request.cookies.get(ACCESS_TOKEN_COOKIE)

    def require_authenticated_user(self):
        if not settings.CORE_AUTH_ENABLED:
            return None

        def dependency(
            request: Request,
            credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
        ) -> AuthIntrospectionResponse:
            token = self._access_token(request, credentials)
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                )
            response = auth_introspection_client.introspect(access_token=token)
            if not response.active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                )
            return response

        return Depends(dependency)

    def route_dependencies(self) -> list[object]:
        dependency = self.require_authenticated_user()
        return [dependency] if dependency is not None else []


core_auth_guard = CoreAuthGuard()
