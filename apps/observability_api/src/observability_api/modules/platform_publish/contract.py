import json
import math
import re
from urllib.parse import urlsplit

from prometheus_client.parser import text_string_to_metric_families

INTERVAL = 30
DEADLINE = 90
MAX_BODY = 256 * 1024
MAX_NORMALIZED = 64 * 1024
MAX_SAMPLES = 1000
LABELS = {
    "method": set("GET POST PUT PATCH DELETE HEAD OPTIONS".split()),
    "route": {"/health", "/ready", "/metrics", "/internal/observability/platform/status"},
    "status_class": {f"{number}xx" for number in range(1, 6)},
    "status": set("open investigating acknowledged resolved closed".split()),
    "severity": set("info warning error critical".split()),
    "enabled": {"true", "false"},
    "le": set("0.005 0.01 0.025 0.05 0.075 0.1 0.25 0.5 0.75 1.0 2.5 5.0 7.5 10.0 +Inf".split()),
}


class ContractError(ValueError):
    pass


def configured(settings, *, query=False):
    fields = ("PLATFORM_TOKEN",)
    if settings.ENVIRONMENT not in {"staging", "production"} or settings.PLATFORM_ENVIRONMENT != settings.ENVIRONMENT:
        return False
    if settings.PLATFORM_PROJECT != "rubrica" or settings.PLATFORM_SERVICE != "observability_api":
        return False
    if any(not getattr(settings, name) or not getattr(settings, name+"_FILE") for name in fields):
        return False
    try:
        value = urlsplit(settings.PLATFORM_URL)
        return (value.scheme == "https" and value.hostname == "grafana.7f3a9c2e8b.stream"
            and value.port in {None, 443} and not value.username and not value.password and not value.query and not value.fragment
            and value.path.rstrip("/") == "")
    except ValueError:
        return False


def headers(settings, *, query=False):
    return {"Authorization": f"Bearer {settings.PLATFORM_TOKEN}", "Content-Type": "application/json"}


def encode(payload):
    body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    if len(body) > MAX_BODY:
        raise ContractError("body_limit")
    return body


def matches_scope(payload, settings):
    return (isinstance(payload, dict) and payload.get("contract_version") == 2 and payload.get("project") == settings.PLATFORM_PROJECT
        and payload.get("environment") == settings.PLATFORM_ENVIRONMENT
        and payload.get("services") == [settings.PLATFORM_SERVICE] and payload.get("authorized") is True)


def snapshot(text, settings):
    """Drop an incompatible family as a whole; never merge/rename series."""
    scope = {"project": settings.PLATFORM_PROJECT, "environment": settings.PLATFORM_ENVIRONMENT, "service": settings.PLATFORM_SERVICE}
    selected, known, normalized_size, discarded = [], set(), 0, 0
    for family in text_string_to_metric_families(text):
        if not family.name.startswith("rubrica_"):
            continue
        group, identities, size, invalid = [], set(), 0, False
        for sample in family.samples:
            if sample.name.endswith("_created"):
                continue
            labels, value = dict(sample.labels), sample.value
            if (not re.fullmatch(r"rubrica_[a-zA-Z0-9_:]{1,120}", sample.name) or len(sample.name) > 128
                or not math.isfinite(value) or len(labels) > 8 or any(
                    val != scope[key] if key in scope else key not in LABELS or val not in LABELS[key]
                    for key, val in labels.items())):
                invalid = True
                break
            imposed = scope | labels
            if len(imposed) > 8:
                invalid = True
                break
            encoded = ",".join(key+"="+json.dumps(val) for key, val in sorted(imposed.items()))
            identity = sample.name+"{"+encoded+"}"
            if identity in known:
                raise ContractError("duplicate_series")
            if identity in identities:
                invalid = True
                break
            identities.add(identity)
            size += len((identity+" "+repr(float(value))+"\n").encode())
            # Reserved labels bind the snapshot to its intended credential scope.
            group.append({"name": sample.name, "value": value, "labels": imposed})
        if invalid:
            discarded += 1
            continue
        selected.extend(group)
        known.update(identities)
        normalized_size += size
    if not selected or len(selected) > MAX_SAMPLES or normalized_size > MAX_NORMALIZED:
        raise ContractError("snapshot_limit")
    payload = {"service": settings.PLATFORM_SERVICE, "samples": selected}
    encode(payload)
    return payload, discarded
