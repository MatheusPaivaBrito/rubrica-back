from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.domains.meta.whatsapp.meta_connection_repository import (
    MetaConnectionRepository,
    MetaPhoneNumberConflictError,
    get_meta_connection_repository,
)
from notification_api.modules.messaging.domains.meta.whatsapp.meta_onboarding_schema import (
    CompleteMetaWhatsappSignup,
    MetaWhatsappConnectionView,
    MetaWhatsappSignupConfiguration,
    MetaWhatsappVerificationResult,
)
from notification_api.modules.messaging.domains.meta.whatsapp.meta_onboarding_service import (
    MetaOnboardingConfigurationError,
    MetaOnboardingRequestError,
    MetaWhatsappOnboardingService,
)
from shared_kernel.identifiers import Identifier
from shared_kernel.security.service_tokens import verify_service_token


router = APIRouter(
    prefix="/internal/meta/whatsapp",
    tags=["internal meta whatsapp onboarding"],
)


def require_internal_service(
    x_atlas_service: str | None = Header(default=None),
    x_atlas_service_key: str | None = Header(default=None),
) -> None:
    if (
        x_atlas_service != settings.NOTIFICATION_INTERNAL_SERVICE_NAME
        or not settings.NOTIFICATION_INTERNAL_SERVICE_KEY
        or not verify_service_token(
            x_atlas_service_key or "",
            settings.NOTIFICATION_INTERNAL_SERVICE_KEY,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service authentication failed",
        )


@router.get(
    "/signup-configuration",
    response_model=MetaWhatsappSignupConfiguration,
    dependencies=[Depends(require_internal_service)],
)
def get_signup_configuration() -> MetaWhatsappSignupConfiguration:
    return MetaWhatsappSignupConfiguration(
        enabled=bool(
            settings.META_APP_ID
            and settings.META_APP_SECRET
            and settings.META_SYSTEM_USER_ID
            and settings.META_WHATSAPP_ACCESS_TOKEN
            and settings.META_EMBEDDED_SIGNUP_CONFIG_ID
        ),
        app_id=settings.META_APP_ID,
        configuration_id=settings.META_EMBEDDED_SIGNUP_CONFIG_ID,
        graph_api_version=settings.META_GRAPH_API_VERSION,
    )


@router.post(
    "/connections",
    response_model=MetaWhatsappConnectionView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_service)],
)
def complete_signup(
    payload: CompleteMetaWhatsappSignup,
    repository: MetaConnectionRepository = Depends(get_meta_connection_repository),
) -> MetaWhatsappConnectionView:
    try:
        connection = MetaWhatsappOnboardingService(repository).complete_signup(payload)
    except MetaOnboardingConfigurationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except MetaOnboardingRequestError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except MetaPhoneNumberConflictError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "meta.whatsapp.phone_already_connected",
        ) from exc
    return MetaWhatsappConnectionView.model_validate(connection)


@router.get(
    "/connections/{tenant_id}",
    response_model=MetaWhatsappConnectionView,
    dependencies=[Depends(require_internal_service)],
)
def get_connection(
    tenant_id: Identifier,
    repository: MetaConnectionRepository = Depends(get_meta_connection_repository),
) -> MetaWhatsappConnectionView:
    connection = MetaWhatsappOnboardingService(repository).get_connection(tenant_id)
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    return MetaWhatsappConnectionView.model_validate(connection)


@router.post(
    "/connections/{tenant_id}/verify",
    response_model=MetaWhatsappVerificationResult,
    dependencies=[Depends(require_internal_service)],
)
def verify_connection(
    tenant_id: Identifier,
    repository: MetaConnectionRepository = Depends(get_meta_connection_repository),
) -> MetaWhatsappVerificationResult:
    service = MetaWhatsappOnboardingService(repository)
    try:
        connection = service.verify_connection(tenant_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except MetaOnboardingConfigurationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except MetaOnboardingRequestError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return MetaWhatsappVerificationResult(
        status="connected",
        verified=True,
        connection=MetaWhatsappConnectionView.model_validate(connection),
    )


@router.delete(
    "/connections/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal_service)],
)
def disconnect(
    tenant_id: Identifier,
    repository: MetaConnectionRepository = Depends(get_meta_connection_repository),
) -> Response:
    try:
        MetaWhatsappOnboardingService(repository).disconnect(tenant_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except MetaOnboardingConfigurationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except MetaOnboardingRequestError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
