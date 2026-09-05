from observability_api.infrastructure.providers.http import provider_status
from observability_api.infrastructure.settings import settings


def grafana_status() -> dict:
    return provider_status("grafana", settings.GRAFANA_HEALTH_URL)
