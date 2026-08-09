from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def service_url(url_env: str, port_env: str, default_port: str) -> str:
    configured = os.getenv(url_env)
    if configured:
        return configured.rstrip("/")
    return f"http://localhost:{os.getenv(port_env, default_port)}"


def request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            return response.status, _decode_json(body)
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise SystemExit(f"{method} {url} failed with {exc.code}: {body}") from exc
    except URLError as exc:
        raise SystemExit(f"{method} {url} failed: {exc.reason}") from exc


def print_result(label: str, status_code: int, body: Any) -> None:
    print(f"[ok] {label}: HTTP {status_code}")
    print(json.dumps(body, indent=2, sort_keys=True))


def _decode_json(body: str) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body
