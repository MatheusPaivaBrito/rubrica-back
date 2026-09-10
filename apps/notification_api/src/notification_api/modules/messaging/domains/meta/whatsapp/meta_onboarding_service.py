from __future__ import annotations

from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import orjson

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.domains.meta.whatsapp.meta_connection_entity import (
    MetaWhatsappConnection,
)
from notification_api.modules.messaging.domains.meta.whatsapp.meta_connection_repository import (
    MetaConnectionRepository,
    MetaPhoneNumberConflictError,
)
from notification_api.modules.messaging.domains.meta.whatsapp.meta_onboarding_schema import (
    CompleteMetaWhatsappSignup,
)
from shared_kernel.identifiers import Identifier


class MetaOnboardingConfigurationError(RuntimeError):
    pass


class MetaOnboardingRequestError(RuntimeError):
    pass


class MetaWhatsappOnboardingService:
    def __init__(self, repository: MetaConnectionRepository) -> None:
        self._repository = repository

    def complete_signup(
        self,
        payload: CompleteMetaWhatsappSignup,
    ) -> MetaWhatsappConnection:
        if payload.phone_number_id:
            self._ensure_reassignment_allowed(payload, payload.phone_number_id)
        access_token = self._exchange_authorization_code(
            payload.authorization_code,
            payload.redirect_uri,
        )
        discovered_phone_number = payload.phone_number_id is None
        phone_number_id = payload.phone_number_id or self._discover_phone_number_id(
            payload.waba_id, access_token
        )
        if not payload.phone_number_id:
            self._ensure_reassignment_allowed(payload, phone_number_id)
        if not discovered_phone_number:
            self._validate_phone_belongs_to_waba(
                payload.waba_id,
                phone_number_id,
                access_token,
            )
        system_token = self._require_system_access_token()
        self._assign_system_user(payload.waba_id, system_token)
        self._subscribe_app(payload.waba_id, access_token)
        if payload.two_step_pin:
            self._register_phone_number(
                phone_number_id,
                payload.two_step_pin,
                access_token,
            )
        phone = self._get_phone_number(phone_number_id, system_token)

        existing = self._repository.get_by_tenant(payload.tenant_id)
        connection = existing or MetaWhatsappConnection(tenant_id=payload.tenant_id)
        connection.waba_id = payload.waba_id
        connection.phone_number_id = phone_number_id
        connection.display_phone_number = _optional_text(
            phone.get("display_phone_number")
        )
        connection.verified_name = _optional_text(phone.get("verified_name"))
        connection.quality_rating = _optional_text(phone.get("quality_rating"))
        connection.status = "connected"
        connection.connected_at = datetime.now(UTC)
        connection.last_verified_at = datetime.now(UTC)
        connection.disconnected_at = None
        return self._repository.assign(
            connection,
            confirm_reassignment=payload.confirm_reassignment,
        )

    def _ensure_reassignment_allowed(
        self,
        payload: CompleteMetaWhatsappSignup,
        phone_number_id: str,
    ) -> None:
        conflicting = self._repository.get_connected_by_phone_number_id(
            phone_number_id
        )
        if (
            conflicting is not None
            and conflicting.tenant_id != payload.tenant_id
            and not payload.confirm_reassignment
        ):
            raise MetaPhoneNumberConflictError()

    def _discover_phone_number_id(self, waba_id: str, token: str) -> str:
        result = self._graph_request(
            "GET",
            f"/{waba_id}/phone_numbers",
            token=token,
            query={"fields": "id"},
        )
        phone_ids = [
            str(item["id"])
            for item in result.get("data", [])
            if isinstance(item, dict) and item.get("id") is not None
        ]
        if len(phone_ids) != 1:
            raise MetaOnboardingRequestError(
                "Selected WABA must contain exactly one phone number"
            )
        return phone_ids[0]

    def get_connection(self, tenant_id: Identifier) -> MetaWhatsappConnection | None:
        return self._repository.get_by_tenant(tenant_id)

    def verify_connection(self, tenant_id: Identifier) -> MetaWhatsappConnection:
        connection = self._require_connection(tenant_id)
        token = self._require_system_access_token()
        try:
            phone = self._get_phone_number(connection.phone_number_id, token)
        except MetaOnboardingRequestError:
            connection.status = "verification_failed"
            connection.last_verified_at = datetime.now(UTC)
            self._repository.save(connection)
            raise
        connection.display_phone_number = _optional_text(
            phone.get("display_phone_number")
        )
        connection.verified_name = _optional_text(phone.get("verified_name"))
        connection.quality_rating = _optional_text(phone.get("quality_rating"))
        connection.status = "connected"
        connection.last_verified_at = datetime.now(UTC)
        return self._repository.save(connection)

    def disconnect(self, tenant_id: Identifier) -> MetaWhatsappConnection:
        connection = self._require_connection(tenant_id)
        if connection.status == "connected":
            token = self._require_system_access_token()
            self._graph_request(
                "DELETE",
                f"/{connection.waba_id}/subscribed_apps",
                token=token,
            )
        connection.status = "disconnected"
        connection.disconnected_at = datetime.now(UTC)
        return self._repository.save(connection)

    def _require_connection(self, tenant_id: Identifier) -> MetaWhatsappConnection:
        connection = self._repository.get_by_tenant(tenant_id)
        if connection is None:
            raise LookupError("Meta WhatsApp connection was not found")
        return connection

    def _exchange_authorization_code(
        self,
        code: str,
        redirect_uri: str | None,
    ) -> str:
        if not settings.META_APP_ID or not settings.META_APP_SECRET:
            raise MetaOnboardingConfigurationError(
                "Meta app id and app secret are required"
            )
        query = {
            "client_id": settings.META_APP_ID,
            "client_secret": settings.META_APP_SECRET,
            "code": code,
        }
        if redirect_uri:
            query["redirect_uri"] = redirect_uri
        result = self._request_json(
            Request(
                "https://graph.facebook.com/"
                f"{settings.META_GRAPH_API_VERSION}/oauth/access_token?"
                f"{urlencode(query)}",
                method="GET",
            )
        )
        token = result.get("access_token")
        if not isinstance(token, str) or not token:
            raise MetaOnboardingRequestError(
                "Meta authorization response did not include an access token"
            )
        return token

    def _get_phone_number(self, phone_number_id: str, token: str) -> dict[str, object]:
        return self._graph_request(
            "GET",
            f"/{phone_number_id}",
            token=token,
            query={
                "fields": "id,display_phone_number,verified_name,quality_rating"
            },
        )

    def _validate_phone_belongs_to_waba(
        self,
        waba_id: str,
        phone_number_id: str,
        token: str,
    ) -> None:
        result = self._graph_request(
            "GET",
            f"/{waba_id}/phone_numbers",
            token=token,
            query={"fields": "id"},
        )
        phone_ids = {
            str(item.get("id"))
            for item in result.get("data", [])
            if isinstance(item, dict) and item.get("id") is not None
        }
        if phone_number_id not in phone_ids:
            raise MetaOnboardingRequestError(
                "Meta phone number does not belong to the selected WABA"
            )

    def _assign_system_user(self, waba_id: str, token: str) -> None:
        if not settings.META_SYSTEM_USER_ID:
            raise MetaOnboardingConfigurationError(
                "Meta system user id is required"
            )
        self._graph_request(
            "POST",
            f"/{waba_id}/assigned_users",
            token=token,
            query={
                "user": settings.META_SYSTEM_USER_ID,
                "tasks": '["MANAGE"]',
            },
        )

    def _subscribe_app(self, waba_id: str, token: str) -> None:
        self._graph_request("POST", f"/{waba_id}/subscribed_apps", token=token)

    def _register_phone_number(
        self,
        phone_number_id: str,
        pin: str,
        token: str,
    ) -> None:
        self._graph_request(
            "POST",
            f"/{phone_number_id}/register",
            token=token,
            payload={"messaging_product": "whatsapp", "pin": pin},
        )

    def _require_system_access_token(self) -> str:
        if not settings.META_WHATSAPP_ACCESS_TOKEN:
            raise MetaOnboardingConfigurationError(
                "Meta system user access token is required"
            )
        return settings.META_WHATSAPP_ACCESS_TOKEN

    def _graph_request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        query: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        url = (
            "https://graph.facebook.com/"
            f"{settings.META_GRAPH_API_VERSION}{path}"
        )
        if query:
            url = f"{url}?{urlencode(query)}"
        request = Request(
            url,
            data=orjson.dumps(payload) if payload is not None else None,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        return self._request_json(request)

    def _request_json(self, request: Request) -> dict[str, object]:
        try:
            with urlopen(request, timeout=10.0) as response:
                raw = response.read()
        except HTTPError as exc:
            raise MetaOnboardingRequestError(_safe_meta_error(exc)) from exc
        except (OSError, URLError) as exc:
            raise MetaOnboardingRequestError("Meta Graph API is unavailable") from exc
        try:
            result = orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            raise MetaOnboardingRequestError(
                "Meta Graph API returned an invalid response"
            ) from exc
        if not isinstance(result, dict):
            raise MetaOnboardingRequestError(
                "Meta Graph API returned an invalid response"
            )
        return result


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None and value != "" else None


def _safe_meta_error(exc: HTTPError) -> str:
    try:
        payload = orjson.loads(exc.read())
    except (orjson.JSONDecodeError, TypeError, ValueError):
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return f"Meta Graph API rejected the request (HTTP {exc.code}, code {code})"
