from urllib.parse import urlencode

from .base import CheckoutRequest, CheckoutResult


class FakeBillingProvider:
    name = "fake"

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        provider_id = f"fake-{request.external_reference}"
        query = urlencode({"provider_checkout": provider_id, "status": "pending"})
        return CheckoutResult(
            provider_id=provider_id,
            checkout_url=f"{request.back_url}{'&' if '?' in request.back_url else '?'}{query}",
            status="pending",
        )

    def get_payment(self, resource_id: str) -> dict:
        return {
            "id": resource_id,
            "status": "approved",
            "external_reference": resource_id.removeprefix("fake-"),
            "transaction_amount": 0,
            "currency_id": "BRL",
        }

    def get_subscription(self, resource_id: str) -> dict:
        return {
            "id": resource_id,
            "status": "authorized",
            "external_reference": resource_id.removeprefix("fake-"),
        }

    def cancel_subscription(self, resource_id: str) -> dict:
        return {"id": resource_id, "status": "cancelled"}
