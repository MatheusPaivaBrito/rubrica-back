from __future__ import annotations

import stat
import sys
from pathlib import Path

from toolbox.checks.production_readiness import read_env


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_ROOT = ROOT / "compose"

REQUIRED_SECRETS = (
    "postgres_password", "auth_seed_admin_password", "auth_mfa_encryption_key",
    "auth_identity_encryption_key", "auth_identity_hmac_key",
    "notification_internal_service_key", "core_internal_service_key", "resend_api_key",
    "evidence_secret", "tenant_identity_encryption_key", "tenant_identity_hmac_key",
    "stripe_secret_key", "stripe_webhook_secret", "contact_turnstile_secret_key",
    "serproid_client_secret", "platform_grafana_service_token",
    "observability_internal_service_key", "cloudflare_tunnel_token",
    "serpro_timestamp_consumer_secret", "serpro_timestamp_trust_roots.pem",
)

R2_SECRETS = (
    "r2_documents_endpoint", "r2_documents_access_key_id",
    "r2_documents_secret_access_key", "r2_documents_bucket",
    "document_storage_encryption_key",
)


def staging_secrets_dir(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (COMPOSE_ROOT / path).resolve()


def main() -> int:
    env_path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env.staging")
    if not env_path.is_file():
        print(f"[error] {env_path} is missing; copy .env.staging.example first")
        return 2
    values = read_env(env_path)
    errors: list[str] = []
    if values.get("ENVIRONMENT") != "staging":
        errors.append("ENVIRONMENT must be staging")
    if values.get("DOCUMENT_STORAGE_PROVIDER") != "r2":
        errors.append("staging must use isolated R2 document storage")
    if values.get("BILLING_PROVIDER") not in {"fake", "stripe"}:
        errors.append("staging BILLING_PROVIDER must be fake or stripe")
    if values.get("PUBLIC_WEB_URL") != "https://staging.rubricasignature.com":
        errors.append("staging PUBLIC_WEB_URL must use https://staging.rubricasignature.com")
    if values.get("SIGNING_APP_URL") != "https://staging.rubricasignature.com/signing":
        errors.append("staging SIGNING_APP_URL must use the stable staging hostname")
    secrets_dir = staging_secrets_dir(values.get("SECRETS_DIR", "../.secrets/staging"))
    required_secrets = REQUIRED_SECRETS + R2_SECRETS
    for name in required_secrets:
        path = secrets_dir / name
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            errors.append(f"missing or empty staging secret: {path}")
        elif stat.S_IMODE(path.stat().st_mode) & 0o077:
            errors.append(f"staging secret must use mode 0600: {path}")
    for error in errors:
        print(f"[error] {error}")
    if errors:
        return 2
    print("[ok] staging environment and Docker Secrets are ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
