from fastapi import APIRouter, Depends, HTTPException, status

from auth_api.modules.mfa.mfa_schema import (
    MfaCodeRequest,
    MfaConfirmResponse,
    MfaDisableResponse,
    MfaReauthenticationRequest,
    MfaRecoveryCodesResponse,
    MfaSetupResponse,
    MfaStatusResponse,
)
from auth_api.modules.mfa.mfa_service import MfaError, mfa_service
from auth_api.modules.sessions.session_router import require_authenticated_session
from auth_api.modules.sessions.session_schema import SessionRead
from auth_api.modules.sessions.session_service import session_service


router = APIRouter(prefix="/auth/mfa", tags=["multi-factor authentication"])


@router.get("/status", response_model=MfaStatusResponse)
async def mfa_status(
    session: SessionRead = Depends(require_authenticated_session),
) -> MfaStatusResponse:
    enabled, required_by_policy, setup_required, remaining = mfa_service.status(session.subject)
    return MfaStatusResponse(
        enabled=enabled,
        required_by_policy=required_by_policy,
        setup_required=setup_required,
        recovery_codes_remaining=remaining,
    )


@router.post("/setup", response_model=MfaSetupResponse)
async def setup_mfa(
    session: SessionRead = Depends(require_authenticated_session),
) -> MfaSetupResponse:
    _enforce_rate_limit(session.subject, "setup", limit=5)
    secret, provisioning_uri = mfa_service.setup(session.subject)
    return MfaSetupResponse(secret=secret, provisioning_uri=provisioning_uri)


@router.post("/confirm", response_model=MfaConfirmResponse)
async def confirm_mfa(
    payload: MfaCodeRequest,
    session: SessionRead = Depends(require_authenticated_session),
) -> MfaConfirmResponse:
    _enforce_rate_limit(session.subject, "confirm")
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
    payload: MfaReauthenticationRequest,
    session: SessionRead = Depends(require_authenticated_session),
) -> MfaDisableResponse:
    _enforce_rate_limit(session.subject, "disable", limit=5)
    try:
        mfa_service.disable(session.subject, payload.password, payload.code)
    except MfaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return MfaDisableResponse()


@router.post("/recovery-codes", response_model=MfaRecoveryCodesResponse)
async def regenerate_recovery_codes(
    payload: MfaReauthenticationRequest,
    session: SessionRead = Depends(require_authenticated_session),
) -> MfaRecoveryCodesResponse:
    _enforce_rate_limit(session.subject, "recovery-codes", limit=5)
    try:
        codes = mfa_service.regenerate_recovery_codes(
            session.subject,
            payload.password,
            payload.code,
        )
    except MfaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return MfaRecoveryCodesResponse(recovery_codes=codes)


def _enforce_rate_limit(subject: str, operation: str, *, limit: int = 10) -> None:
    if not session_service.allow_mfa_operation(subject, operation, limit=limit):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many MFA attempts. Try again later",
        )
