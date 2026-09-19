"""Public contact form. Keep the recipient and Turnstile secret on the server."""

import re
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from core_api.infrastructure.settings import settings
from core_api.modules.billing.notification_client import BillingEmailDeliveryError, request_billing_email

router = APIRouter(prefix="/contact", tags=["contact"])


class ContactMessage(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    topic: str = Field(pattern="^(sales|support|privacy)$")
    message: str = Field(min_length=10, max_length=3000)
    turnstile_token: str = Field(min_length=1, max_length=2048)
    website: str = Field(default="", max_length=255)

    @field_validator("name", "message")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("invalid text")
        return value

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value):
            raise ValueError("invalid email")
        return value


@router.get("/config")
def contact_config() -> dict[str, str]:
    return {"turnstile_site_key": settings.CONTACT_TURNSTILE_SITE_KEY if settings.CONTACT_TURNSTILE_SECRET_KEY else ""}


@router.post("/messages", status_code=status.HTTP_202_ACCEPTED)
def submit_contact(message: ContactMessage) -> dict[str, str]:
    if not settings.CONTACT_TURNSTILE_SITE_KEY or not settings.CONTACT_TURNSTILE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Contact form unavailable")
    if message.website:
        return {"status": "accepted"}

    try:
        response = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": settings.CONTACT_TURNSTILE_SECRET_KEY, "response": message.turnstile_token},
            timeout=5.0,
        )
        response.raise_for_status()
        verification = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Verification unavailable") from exc
    if not verification.get("success"):
        raise HTTPException(status_code=400, detail="Verification failed")
    # The verified hostname must belong to this deployment, including www.
    expected_host = settings.PUBLIC_WEB_URL.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if settings.ENVIRONMENT == "production" and verification.get("hostname") not in {expected_host, f"www.{expected_host}"}:
        raise HTTPException(status_code=400, detail="Verification failed")

    body = f"Name: {message.name}\nEmail: {message.email}\nTopic: {message.topic}\n\n{message.message}"
    try:
        request_billing_email(
            recipient=settings.CONTACT_INBOX_EMAIL,
            subject=f"[Rubrica contact] {message.topic}",
            body=body,
            idempotency_key=f"contact-{uuid4().hex}",
        )
    except BillingEmailDeliveryError as exc:
        raise HTTPException(status_code=503, detail="Message delivery unavailable") from exc
    return {"status": "accepted"}
