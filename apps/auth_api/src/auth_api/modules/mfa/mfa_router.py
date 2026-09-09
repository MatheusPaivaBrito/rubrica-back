from fastapi import APIRouter, Depends, HTTPException, status

from auth_api.modules.mfa.mfa_schema import (
    MfaCodeRequest,
    MfaConfirmResponse,
    MfaDisableResponse,
    MfaSetupResponse,
)
from auth_api.modules.mfa.mfa_service import MfaError, mfa_service
from auth_api.modules.sessions.session_router import require_authenticated_session
from auth_api.modules.sessions.session_schema import SessionRead


router = APIRouter(prefix="/auth/mfa", tags=["multi-factor authentication"])


@router.post("/setup", response_model=MfaSetupResponse)
async def setup_mfa(
    session: SessionRead = Depends(require_authenticated_session),
) -> MfaSetupResponse:
    secret, provisioning_uri = mfa_service.setup(session.subject)
    return MfaSetupResponse(secret=secret, provisioning_uri=provisioning_uri)


@router.post("/confirm", response_model=MfaConfirmResponse)
async def confirm_mfa(
    payload: MfaCodeRequest,
    session: SessionRead = Depends(require_authenticated_session),
) -> MfaConfirmResponse:
    try:
        codes = mfa_service.confirm(session.subject, payload.code)
    except MfaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return MfaConfirmResponse(recovery_codes=codes)


@router.delete("", response_model=MfaDisableResponse)
async def disable_mfa(
    payload: MfaCodeRequest,
    session: SessionRead = Depends(require_authenticated_session),
) -> MfaDisableResponse:
    try:
        mfa_service.disable(session.subject, payload.code)
    except MfaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return MfaDisableResponse()
