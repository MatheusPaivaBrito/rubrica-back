import sentry_sdk

from observability_api.infrastructure.settings import settings


def configure_sentry() -> None:
    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT,
            traces_sample_rate=0.0,
        )


def sentry_status() -> dict:
    if settings.SENTRY_DSN:
        return {"name": "sentry", "status": "configured", "mode": "external_dsn"}
    return {
        "name": "sentry",
        "status": "not_configured",
        "mode": "external_dsn",
        "reason": "Set SENTRY_DSN to send captured incidents to Sentry.",
    }


def capture_incident(message: str, *, level: str, context: dict) -> str | None:
    if not settings.SENTRY_DSN:
        return None
    with sentry_sdk.push_scope() as scope:
        scope.set_level(level)
        scope.set_context("incident", context)
        event_id = sentry_sdk.capture_message(message)
    return str(event_id) if event_id else None
