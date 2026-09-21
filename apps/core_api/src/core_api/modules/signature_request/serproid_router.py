from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
import httpx

from core_api.infrastructure.auth_context import AuthContext, authenticated_context
from core_api.infrastructure.settings import settings
from core_api.modules.signature_request.serproid_service import finish_authorization, start_authorization
from core_api.modules.signature_request.workflow_schema import SignCommand
from core_api.modules.signature_request.workflow_service import WorkflowError

router = APIRouter(tags=["certificate signatures"])


@router.get("/signing/serproid/config")
def serproid_config() -> dict[str, bool]:
    return {"enabled": bool(settings.SERPROID_CLIENT_ID and settings.SERPROID_CLIENT_SECRET)}


@router.post("/signing/links/{token}/serproid/start")
def start_serproid_signing(
    token: str,
    command: SignCommand,
    request: Request,
    context: AuthContext = Depends(authenticated_context),
) -> dict[str, str]:
    return {"authorization_url": start_authorization(
        token, context.subject, command,
        request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown"),
        request.headers.get("user-agent", "unknown"),
    )}


@router.get("/api/auth/serproid/callback", include_in_schema=False)
def serproid_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
    context: AuthContext = Depends(authenticated_context),
) -> RedirectResponse:
    if len(state) < 32 or len(state) > 128:
        raise WorkflowError("Invalid Serpro ID state", 400)
    try:
        token = finish_authorization(state, code, error, context.subject)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise WorkflowError("Serpro ID returned an invalid or unavailable response", 502) from exc
    outcome = "denied" if error or not code else "success"
    response = RedirectResponse(f"/signing/{token}?serproid={outcome}", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
