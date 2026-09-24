"""Validate login challenges server-side before checking credentials."""

from ipaddress import ip_address

import httpx
from fastapi import HTTPException

from auth_api.infrastructure.settings import settings


def login_turnstile_config() -> dict[str, str | bool]:
    configured = bool(settings.AUTH_TURNSTILE_SITE_KEY and settings.AUTH_TURNSTILE_SECRET_KEY)
    required = configured or settings.ENVIRONMENT.lower() in {"production", "prod"}
    return {"site_key": settings.AUTH_TURNSTILE_SITE_KEY if configured else "", "required": required}


def verify_turnstile(token: str | None, action: str, remote_ip: str | None = None) -> None:
    config = login_turnstile_config()
    if not config["required"]:
        return
    if not config["site_key"]:
        raise HTTPException(status_code=503, detail="Login verification is unavailable")
    if not token:
        raise HTTPException(status_code=400, detail="Login verification is required")

    data = {"secret": settings.AUTH_TURNSTILE_SECRET_KEY, "response": token}
    try:
        if remote_ip:
            data["remoteip"] = str(ip_address(remote_ip))
    except ValueError:
        pass
    try:
        response = httpx.post("https://challenges.cloudflare.com/turnstile/v0/siteverify", data=data, timeout=5.0)
        response.raise_for_status()
        verification = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Login verification is unavailable") from exc
    if not isinstance(verification, dict) or not verification.get("success") or verification.get("action") != action:
        raise HTTPException(status_code=400, detail="Login verification failed")
    if settings.ENVIRONMENT.lower() in {"production", "prod"}:
        expected_host = settings.AUTH_PUBLIC_WEB_URL.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        if verification.get("hostname") not in {expected_host, f"www.{expected_host}"}:
            raise HTTPException(status_code=400, detail="Login verification failed")


def verify_login_turnstile(token: str | None, remote_ip: str | None = None) -> None:
    verify_turnstile(token, "login", remote_ip)
