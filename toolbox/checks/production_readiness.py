from __future__ import annotations

import stat
import sys
from pathlib import Path


REQUIRED_PRICE_IDS = (
    "STRIPE_PRICE_ESSENTIAL_MONTHLY_BRL",
    "STRIPE_PRICE_ESSENTIAL_ANNUAL_BRL",
    "STRIPE_PRICE_PROFESSIONAL_MONTHLY_BRL",
    "STRIPE_PRICE_PROFESSIONAL_ANNUAL_BRL",
    "STRIPE_PRICE_TEAM_MONTHLY_BRL",
    "STRIPE_PRICE_TEAM_ANNUAL_BRL",
)
REQUIRED_SECRETS = (
    "postgres_password",
    "auth_seed_admin_password",
    "auth_mfa_encryption_key",
    "auth_identity_encryption_key",
    "auth_identity_hmac_key",
    "notification_internal_service_key",
    "core_internal_service_key",
    "resend_api_key",
    "evidence_secret",
    "tenant_identity_encryption_key",
    "tenant_identity_hmac_key",
    "stripe_secret_key",
    "stripe_webhook_secret",
    "contact_turnstile_secret_key",
    "serproid_client_secret",
    "cloudflare_tunnel_token",
    "r2_documents_endpoint",
    "r2_documents_access_key_id",
    "r2_documents_secret_access_key",
    "r2_documents_bucket",
)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def main() -> int:
    env_path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env.production")
    if not env_path.is_file():
        print(f"[error] {env_path} is missing; copy .env.production.example first")
        return 2
    values = read_env(env_path)
    errors: list[str] = []
    if values.get("ENVIRONMENT") != "production":
        errors.append("ENVIRONMENT must be production")
    domain = values.get("RUBRICA_DOMAIN", "")
    if not domain or "://" in domain or "/" in domain:
        errors.append("RUBRICA_DOMAIN must be a hostname without scheme or path")
    turnstile_site_key = values.get("CONTACT_TURNSTILE_SITE_KEY", "")
    if not turnstile_site_key or turnstile_site_key in {"replace_me", "site_key_replace_me"}:
        errors.append(
            "CONTACT_TURNSTILE_SITE_KEY must contain the production Turnstile site key"
        )
    for key in REQUIRED_PRICE_IDS:
        value = values.get(key, "")
        if not value.startswith("price_") or value == "price_replace_me":
            errors.append(f"{key} must contain a live Stripe Price ID")
    secrets_dir = Path(values.get("SECRETS_DIR", "/etc/rubrica/secrets"))
    for name in REQUIRED_SECRETS:
        path = secrets_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"missing or empty secret file: {path}")
            continue
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            errors.append(f"secret file must not be accessible by group/others: {path}")
    if errors:
        for error in errors:
            print(f"[error] {error}")
        return 2
    print("[ok] Production environment, Stripe prices and secret files are ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
