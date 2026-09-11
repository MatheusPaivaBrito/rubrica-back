from auth_api.infrastructure.settings import Settings as AuthSettings
from core_api.infrastructure.settings import Settings as CoreSettings
from eventing_api.infrastructure.settings import Settings as EventingSettings
from observability_api.infrastructure.settings import ObservabilitySettings


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
    observability = ObservabilitySettings(_env_file=None, POSTGRES_PASSWORD_FILE=postgres)

    assert core.POSTGRES_PASSWORD == "database-secret"
    assert core.STRIPE_SECRET_KEY == "sk_test_secret"
    assert eventing.POSTGRES_PASSWORD == "database-secret"
    assert observability.POSTGRES_PASSWORD == "database-secret"
