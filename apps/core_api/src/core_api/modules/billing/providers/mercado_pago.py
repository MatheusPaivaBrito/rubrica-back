from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal

import httpx

from core_api.modules.billing.billing_errors import (
    BillingConfigurationError,
    BillingProviderError,
    BillingSignatureError,
)

from .base import CheckoutRequest, CheckoutResult


class MercadoPagoProvider:
    name = "mercado_pago"

    def __init__(
        self,
        *,
        access_token: str,
        webhook_secret: str,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self.access_token = access_token
        self.webhook_secret = webhook_secret
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _require_access_token(self) -> None:
        if not self.access_token:
            raise BillingConfigurationError(
                "Mercado Pago access token is not configured"
            )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        self._require_access_token()
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                json=json,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BillingProviderError("Mercado Pago request failed") from exc
        if not isinstance(data, dict):
            raise BillingProviderError("Mercado Pago returned an invalid response")
        return data

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        frequency_type = "months" if request.interval == "month" else "years"
        amount = Decimal(request.amount_cents) / Decimal(100)
        data = self._request(
            "POST",
            "/preapproval",
            idempotency_key=request.idempotency_key,
            json={
                "reason": request.reason,
                "external_reference": request.external_reference,
                "payer_email": request.payer_email,
                "auto_recurring": {
                    "frequency": 1,
                    "frequency_type": frequency_type,
                    "transaction_amount": float(amount),
                    "currency_id": request.currency,
                },
                "back_url": request.back_url,
                "notification_url": request.notification_url,
                "status": "pending",
            },
        )
        provider_id = str(data.get("id") or "")
        checkout_url = str(data.get("init_point") or "")
        if not provider_id or not checkout_url:
            raise BillingProviderError("Mercado Pago did not return a checkout URL")
        return CheckoutResult(
            provider_id=provider_id,
            checkout_url=checkout_url,
            status=str(data.get("status") or "pending"),
        )

    def get_payment(self, resource_id: str) -> dict:
        return self._request("GET", f"/v1/payments/{resource_id}")

    def get_subscription(self, resource_id: str) -> dict:
        return self._request("GET", f"/preapproval/{resource_id}")

    def cancel_subscription(self, resource_id: str) -> dict:
        return self._request(
            "PUT", f"/preapproval/{resource_id}", json={"status": "cancelled"}
        )

    def validate_webhook_signature(
        self,
        *,
        x_signature: str | None,
        x_request_id: str | None,
        data_id: str,
    ) -> None:
        if not self.webhook_secret:
            raise BillingConfigurationError(
                "Mercado Pago webhook secret is not configured"
            )
        values: dict[str, str] = {}
        for part in (x_signature or "").split(","):
            key, separator, value = part.partition("=")
            if separator:
                values[key.strip()] = value.strip()
        timestamp = values.get("ts")
        signature = values.get("v1")
        if not timestamp or not signature or not x_request_id:
            raise BillingSignatureError("Invalid Mercado Pago webhook signature")
        manifest = f"id:{data_id.lower()};request-id:{x_request_id};ts:{timestamp};"
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"),
            manifest.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise BillingSignatureError("Invalid Mercado Pago webhook signature")
