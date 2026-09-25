import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from core_api.infrastructure.settings import settings
from core_api.modules.signature_request.workflow_service import WorkflowError


def resolve_auth_user(email: str) -> UUID:
    endpoint = f"{settings.AUTH_API_URL.rstrip('/')}/users/internal/resolve?{urlencode({'email': email})}"
    request = Request(
        endpoint,
        headers={
            "X-Rubrica-Service": "core_api",
            "X-Rubrica-Service-Key": settings.CORE_INTERNAL_SERVICE_KEY,
        },
    )
    try:
        with urlopen(request, timeout=3) as response:
            return UUID(json.loads(response.read())["user_id"])
    except HTTPError as exc:
        if exc.code == 404:
            raise WorkflowError("The invited user does not exist or is inactive", 422) from exc
        raise WorkflowError("Auth service is unavailable", 503) from exc
    except (URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise WorkflowError("Auth service is unavailable", 503) from exc
