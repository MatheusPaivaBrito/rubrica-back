from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import Depends, Header, HTTPException, Request as FastAPIRequest, status

from core_api.infrastructure.settings import settings


@dataclass(frozen=True)
class AuthContext:
    subject: str
    roles: frozenset[str]
    permission_keys: frozenset[str]

    def allows(self, permission: str) -> bool:
        return "*" in self.permission_keys or permission in self.permission_keys


def _token(request: FastAPIRequest, authorization: str | None) -> str:
    return (authorization or "").removeprefix("Bearer ").strip() or request.cookies.get("access_token", "")


def _resolve_context(token: str) -> AuthContext:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    endpoint = f"{settings.AUTH_API_URL.rstrip('/')}/access-control/context"
    try:
        with urlopen(Request(endpoint, headers={"Authorization": f"Bearer {token}"}), timeout=3) as response:
            payload = json.loads(response.read())
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required") from exc
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth service is unavailable") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth service is unavailable") from exc
    return AuthContext(subject=str(payload["subject"]), roles=frozenset(payload.get("roles", [])), permission_keys=frozenset(payload.get("permission_keys", [])))


async def authenticated_context(request: FastAPIRequest, authorization: str | None = Header(default=None)) -> AuthContext:
    return _resolve_context(_token(request, authorization))


def require_permission(permission: str):
    async def dependency(context: AuthContext = Depends(authenticated_context)) -> AuthContext:
        if not context.allows(permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return context

    return dependency
