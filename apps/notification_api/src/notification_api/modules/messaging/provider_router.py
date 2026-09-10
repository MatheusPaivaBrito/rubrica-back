from fastapi import APIRouter, Header, HTTPException, status

from notification_api.infrastructure.providers import provider_catalog, verify_provider
from notification_api.infrastructure.settings import settings
from shared_kernel.security.service_tokens import verify_service_token


router = APIRouter(prefix="/internal/providers", tags=["internal providers"])


def _authorize(service_name: str | None, service_key: str | None) -> None:
    if (
        service_name not in settings.NOTIFICATION_INTERNAL_ALLOWED_SERVICES
        or not settings.NOTIFICATION_INTERNAL_SERVICE_KEY
        or not verify_service_token(
            service_key or "",
            settings.NOTIFICATION_INTERNAL_SERVICE_KEY,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service authentication failed",
        )


@router.get("")
def list_providers(
    x_atlas_service: str | None = Header(default=None),
    x_atlas_service_key: str | None = Header(default=None),
) -> dict[str, dict[str, object]]:
    _authorize(x_atlas_service, x_atlas_service_key)
    return provider_catalog()


@router.post("/{provider_name}/verify")
def verify_provider_credentials(
    provider_name: str,
    x_atlas_service: str | None = Header(default=None),
    x_atlas_service_key: str | None = Header(default=None),
) -> dict[str, object]:
    _authorize(x_atlas_service, x_atlas_service_key)
    return verify_provider(provider_name)
