from fastapi import APIRouter, HTTPException, status

from auth_api.modules.accounts.account_schema import (
    AccountActionAccepted,
    EmailVerification,
    EmailVerificationRequest,
    PasswordRecoveryRequest,
    PasswordReset,
    PublicRegistration,
)
from auth_api.modules.accounts.account_service import (
    AccountConflictError,
    InvalidAccountTokenError,
    account_service,
)
from auth_api.modules.accounts.notification_client import AccountEmailDeliveryError
from auth_api.modules.accounts.tenant_client import TenantProvisioningError


router = APIRouter(prefix="/auth", tags=["account lifecycle"])


@router.post("/register", response_model=AccountActionAccepted, status_code=status.HTTP_202_ACCEPTED)
async def register(payload: PublicRegistration) -> AccountActionAccepted:
    try:
        account_service.register(payload)
    except AccountConflictError:
        pass
    except (AccountEmailDeliveryError, TenantProvisioningError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return AccountActionAccepted()


@router.post("/verify-email/request", response_model=AccountActionAccepted)
async def request_email_verification(
    payload: EmailVerificationRequest,
) -> AccountActionAccepted:
    try:
        account_service.request_email_verification(payload.email)
    except AccountEmailDeliveryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AccountActionAccepted()


@router.post("/verify-email", response_model=AccountActionAccepted)
async def verify_email(payload: EmailVerification) -> AccountActionAccepted:
    try:
        account_service.verify_email(payload.token)
    except InvalidAccountTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Verification token is invalid or expired",
        ) from exc
    return AccountActionAccepted()


@router.post("/password-recovery", response_model=AccountActionAccepted)
async def request_password_recovery(
    payload: PasswordRecoveryRequest,
) -> AccountActionAccepted:
    try:
        account_service.request_password_recovery(payload.email)
    except AccountEmailDeliveryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AccountActionAccepted()


@router.post("/password-reset", response_model=AccountActionAccepted)
async def reset_password(payload: PasswordReset) -> AccountActionAccepted:
    try:
        account_service.reset_password(payload.token, payload.new_password)
    except InvalidAccountTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Password reset token is invalid or expired",
        ) from exc
    return AccountActionAccepted()
