from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def read_http_json(url: str) -> tuple[int, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=3) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body) if body else None


def read_http_text(url: str) -> tuple[int, str]:
    request = Request(url, headers={"Accept": "text/plain"})
    with urlopen(request, timeout=3) as response:
        return response.status, response.read().decode("utf-8")


def provider_status(name: str, url: str, *, expect_json: bool = True) -> dict:
    try:
        if expect_json:
            status_code, payload = read_http_json(url)
        else:
            status_code, payload = read_http_text(url)
        return {
            "name": name,
            "status": "ok" if status_code < 500 else "degraded",
            "url": url,
            "http_status": status_code,
            "details": payload,
        }
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {"name": name, "status": "unavailable", "url": url, "error": str(exc)}
