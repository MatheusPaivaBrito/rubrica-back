from auth_api.infrastructure.settings import Settings as AuthSettings
from core_api.infrastructure.settings import Settings as CoreSettings
from eventing_api.infrastructure.settings import Settings as EventingSettings


def _secret(tmp_path, name: str, value: str) -> str:
    path = tmp_path / name
    path.write_text(value, encoding="utf-8")
    return str(path)


def test_auth_production_secrets_are_loaded_before_validation(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DEBUG", raising=False)
    settings = AuthSettings(
        _env_file=None,
        ENVIRONMENT="production",
        POSTGRES_PASSWORD_FILE=_secret(tmp_path, "postgres", "database-secret"),
        NOTIFICATION_INTERNAL_SERVICE_KEY_FILE=_secret(tmp_path, "service", "service-secret"),
        AUTH_MFA_ENCRYPTION_KEY_FILE=_secret(tmp_path, "mfa", "m" * 48),
        AUTH_IDENTITY_ENCRYPTION_KEY_FILE=_secret(tmp_path, "identity", "i" * 48),
        AUTH_IDENTITY_HMAC_KEY_FILE=_secret(tmp_path, "hmac", "h" * 48),
    )

    assert settings.POSTGRES_PASSWORD == "database-secret"
    assert settings.NOTIFICATION_INTERNAL_SERVICE_KEY == "service-secret"
    assert settings.AUTH_MFA_ENCRYPTION_KEY == "m" * 48


def test_service_database_and_provider_secrets_are_loaded(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DEBUG", raising=False)
    postgres = _secret(tmp_path, "postgres", "database-secret")
    stripe = _secret(tmp_path, "stripe", "sk_test_secret")

    core = CoreSettings(
        _env_file=None,
        POSTGRES_PASSWORD_FILE=postgres,
        STRIPE_SECRET_KEY_FILE=stripe,
    )
    eventing = EventingSettings(_env_file=None, POSTGRES_PASSWORD_FILE=postgres)

    assert core.POSTGRES_PASSWORD == "database-secret"
    assert core.STRIPE_SECRET_KEY == "sk_test_secret"
    assert eventing.POSTGRES_PASSWORD == "database-secret"


def test_staging_core_and_workers_do_not_mount_or_load_turnstile(tmp_path, monkeypatch):
    from pathlib import Path
    import yaml
    from toolbox.checks.staging_readiness import REQUIRED_SECRETS
    root = Path(__file__).resolve().parents[1]
    staging = yaml.safe_load((root/"compose/staging.yml").read_text())["services"]
    shared = yaml.safe_load((root/"compose/services/core-api.yml").read_text())["services"]["production"]
    production = yaml.safe_load((root/"compose/production.yml").read_text())["services"]
    missing = tmp_path/"unavailable-turnstile"
    monkeypatch.setenv("CONTACT_TURNSTILE_SECRET_KEY_FILE", str(missing))
    monkeypatch.setenv("CONTACT_TURNSTILE_SECRET_KEY", "should-not-enable-staging")
    assert "contact_turnstile_secret_key" not in REQUIRED_SECRETS
    assert "contact_turnstile_secret_key" not in shared["secrets"]
    assert "CONTACT_TURNSTILE_SECRET_KEY_FILE" not in shared["environment"]
    for name in ("core-api", "enterprise-worker", "enterprise-sandbox-worker", "enterprise-maintenance"):
        config = staging[name]["environment"]
        assert config["CONTACT_TURNSTILE_SECRET_KEY_FILE"] == ""
        settings = CoreSettings(_env_file=None, ENVIRONMENT="staging",
                                TENANT_IDENTITY_ENCRYPTION_KEY="e"*48,
                                TENANT_IDENTITY_HMAC_KEY="h"*48, **config)
        assert settings.CONTACT_TURNSTILE_SECRET_KEY == settings.CONTACT_TURNSTILE_SITE_KEY == ""
        assert "contact_turnstile_secret_key" in production[name]["secrets"]
        assert production[name]["environment"]["CONTACT_TURNSTILE_SECRET_KEY_FILE"] == "/run/secrets/contact_turnstile_secret_key"


def test_production_still_requires_configured_turnstile_file(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        CoreSettings(_env_file=None, ENVIRONMENT="production",
                     CONTACT_TURNSTILE_SECRET_KEY_FILE=str(tmp_path/"missing-turnstile"))
