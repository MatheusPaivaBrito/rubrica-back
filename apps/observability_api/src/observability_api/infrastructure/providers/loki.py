from __future__ import annotations

import time
from urllib.parse import urlencode

from observability_api.infrastructure.providers.http import provider_status, read_http_json
from observability_api.infrastructure.settings import settings


def loki_status() -> dict:
    return provider_status("loki", settings.LOKI_READY_URL, expect_json=False)


def query_loki(query: str, *, limit: int = 20, lookback_seconds: int = 900) -> dict:
    end = time.time_ns()
    start = end - (lookback_seconds * 1_000_000_000)
    params = urlencode(
        {
            "query": query,
            "limit": limit,
            "start": start,
            "end": end,
            "direction": "backward",
        }
    )
    _, payload = read_http_json(f"{settings.LOKI_URL}/loki/api/v1/query_range?{params}")
    return payload


def list_loki_labels() -> dict:
    _, payload = read_http_json(f"{settings.LOKI_URL}/loki/api/v1/labels")
    return payload
