"""Non-mutating v2 proof: authenticated status and a scoped metric-name query."""
import asyncio
import json
import math

import httpx

from observability_api.infrastructure.settings import settings
from observability_api.modules.platform_publish.contract import configured, encode, headers, matches_scope
from observability_api.modules.platform_publish.transport import exchange

METRIC = "rubrica_business_metrics_collection_success"


def fixed_query(config=settings):
    return {"metric": METRIC, "service": config.PLATFORM_SERVICE}


def metric_points(payload, config):
    if payload.get("status") != "success" or payload.get("project") != config.PLATFORM_PROJECT or payload.get("environment") != config.PLATFORM_ENVIRONMENT:
        raise ValueError("query_scope_mismatch")
    data = payload["data"]
    if data.get("resultType") != "vector" or len(data["result"]) > 1000:
        raise ValueError("invalid_vector")
    expected = {"project": config.PLATFORM_PROJECT, "environment": config.PLATFORM_ENVIRONMENT, "service": config.PLATFORM_SERVICE}
    points = []
    for series in data["result"]:
        if any(series["metric"].get(k) != v for k, v in expected.items()):
            raise ValueError("query_scope_mismatch")
        if series["metric"].get("__name__", METRIC) != METRIC:
            raise ValueError("query_metric_mismatch")
        stamp, value = series["value"]
        if isinstance(stamp, bool) or isinstance(value, bool):
            raise ValueError("invalid_value")
        stamp, value = float(stamp), float(value)
        if not math.isfinite(stamp) or not math.isfinite(value):
            raise ValueError("invalid_value")
        points.append((stamp, value))
    return points


def ingestion_proof(payload, config):
    if not matches_scope(payload, config) or payload.get("metric_prefix") != "rubrica_":
        raise ValueError("ingest_scope_mismatch")
    checks = payload["checks"]
    if not all(checks.get(k) is True for k in ("configured", "reachable", "authenticated", "authorized")):
        raise ValueError("invalid_checks")
    now = float(payload["server_time"])
    seen = float(payload["last_seen"])
    metric = payload["metrics"][config.PLATFORM_SERVICE]
    received, collected = float(metric["last_received"]), float(metric.get("last_collected", 0))
    expiry = payload.get("expires_at")
    if expiry is not None and float(expiry) <= now:
        raise ValueError("expired")
    if now <= 0 or not all(math.isfinite(x) for x in (now, seen, received, collected)):
        raise ValueError("invalid_clock")
    if type(metric.get("samples")) is not int or not 0 <= metric["samples"] <= 1000:
        raise ValueError("invalid_samples")
    recent = all(payload.get(k) is True for k in ("available", "receiving", "query_reachable", "operational"))
    recent = recent and checks.get("operational") is True and metric.get("fresh") is True and metric["samples"] > 0
    recent = recent and all(x > 0 and 0 <= now-x <= 90 for x in (seen, received, collected))
    return now, recent, {"heartbeat_age_seconds": max(0, now-seen), "snapshot_age_seconds": max(0, now-received),
        "collection_age_seconds": max(0, now-collected), "samples": metric["samples"]}


async def ensure(config=settings, *, client=None):
    report = {"project": "rubrica", "environment": config.PLATFORM_ENVIRONMENT, "service": "observability_api",
        "configured": False, "reachable": False, "authenticated": False, "authorized": False,
        "operational": False, "checks": {}, "reason": "configuration_incomplete"}
    if not configured(config):
        return report
    report["configured"] = True
    if client is None:
        async with httpx.AsyncClient(timeout=10, verify=True, follow_redirects=False, trust_env=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=1)) as remote:
            return await _ensure(remote, config, report)
    return await _ensure(client, config, report)


async def _ensure(client, config, report):
    base = config.PLATFORM_URL.rstrip("/")+"/ingest/v1"
    status = await exchange(client, "GET", base+"/status", headers(config), limit=65536)
    report["checks"]["ingestion"] = {"http_status": status.code, "reason": status.reason}
    report["reachable"] = status.code is not None
    if status.reason != "ok" or status.code != 200:
        report["reason"] = status.reason
        if status.reason == "access_denied":
            report["operator_action"] = "apply_stage_2_of_Platform_Infra_docs/PLATFORM_UPDATE.md"
        return report
    report["authenticated"] = True
    try:
        now, recent, summary = ingestion_proof(status.payload, config)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        report["reason"] = "ingest_scope_or_status_invalid"
        return report
    report["authorized"] = True
    query = await exchange(client, "POST", base+"/query", headers(config), body=encode(fixed_query(config)), limit=1024*1024)
    report["checks"]["prometheus_query"] = {"http_status": query.code, "reason": query.reason}
    if query.reason != "ok" or query.code != 200:
        report["reason"] = query.reason
        return report
    try:
        points = metric_points(query.payload, config)
        fresh = [(stamp, value) for stamp, value in points if value == 1 and -15 <= now-stamp <= 105]
        report["operational"] = bool(recent and fresh)
        report["checks"]["freshness"] = summary
        if fresh:
            report["checks"]["sample"] = {"value": 1, "timestamp": max(stamp for stamp, _ in fresh)}
        report["reason"] = "ok" if report["operational"] else "signals_missing_or_stale"
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        report["reason"] = "query_response_or_scope_invalid"
    return report


def main():
    result = asyncio.run(ensure())
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    raise SystemExit(0 if result["operational"] else 2)


if __name__ == "__main__":
    main()
