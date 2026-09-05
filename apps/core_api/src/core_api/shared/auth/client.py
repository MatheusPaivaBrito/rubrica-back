from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import orjson
from fastapi import HTTPException, status
from pydantic import BaseModel

from core_api.infrastructure.settings import settings


SERVICE_NAME_HEADER = "X-Atlas-Service"
SERVICE_KEY_HEADER = "X-Atlas-Service-Key"


class AuthIntrospectionResponse(BaseModel):
    active: bool
    session_id: str
    subject: str


class AuthIntrospectionClient:
    def introspect(self, *, access_token: str) -> AuthIntrospectionResponse:
        request = Request(
            f"{settings.AUTH_API_INTERNAL_URL.rstrip('/')}/"
            f"{settings.AUTH_INTROSPECTION_PATH.lstrip('/')}",
            data=b"{}",
            headers={
                "Authorization": f"Bearer {access_token}",
                SERVICE_NAME_HEADER: settings.SERVICE_NAME,
                SERVICE_KEY_HEADER: settings.CORE_TO_AUTH_SERVICE_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=settings.AUTH_INTROSPECTION_TIMEOUT_SECONDS) as response:
                raw_content = response.read()
        except HTTPError as exc:
            if exc.code == status.HTTP_401_UNAUTHORIZED:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth authorization service is unavailable",
            ) from exc
        except URLError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth authorization service is unavailable",
            ) from exc

        try:
            return AuthIntrospectionResponse.model_validate(orjson.loads(raw_content))
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth authorization service returned an invalid response",
            ) from exc


auth_introspection_client = AuthIntrospectionClient()
