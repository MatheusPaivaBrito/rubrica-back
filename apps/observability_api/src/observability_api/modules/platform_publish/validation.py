"""Read-only live checks, including negative auth and scope tests. No ingestion writes."""
import asyncio
import json

import httpx

from observability_api.infrastructure.settings import settings
from observability_api.modules.platform_publish.contract import configured, encode, headers
from observability_api.modules.platform_publish.ensure import ensure, fixed_query
from observability_api.modules.platform_publish.transport import exchange


async def validate(config=settings, *, client=None):
    if client is None:
        async with httpx.AsyncClient(verify=True, follow_redirects=False, trust_env=False, timeout=10,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=1)) as remote:
            return await validate(config, client=remote)
    report = await ensure(config, client=client)
    if not configured(config) or not report["authorized"]:
        return report
    base = config.PLATFORM_URL.rstrip("/")+"/ingest/v1"
    checks = {}
    for name, auth in (("missing_credential", {}), ("invalid_credential", {"Authorization": "Bearer invalid-test-credential"})):
        result = await exchange(client, "GET", base+"/status", auth)
        checks[name] = result.code == 401 and result.reason == "credential_denied"
    for name, body in (("forged_scope", fixed_query(config) | {"environment": "foreign"}),
                       ("forged_service", fixed_query(config) | {"service": "foreign_service"}),
                       ("promql_rejected", {"metric": "sum(rubrica_metric)", "service": config.PLATFORM_SERVICE})):
        result = await exchange(client, "POST", base+"/query", headers(config), body=encode(body))
        checks[name] = result.code in {403, 422}
    report["checks"]["negative_tests"] = checks
    report["operational"] = report["operational"] and all(checks.values())
    if not all(checks.values()):
        report["reason"] = "negative_validation_failed"
    return report


def main():
    result = asyncio.run(validate())
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    raise SystemExit(0 if result["operational"] else 2)


if __name__ == "__main__":
    main()
