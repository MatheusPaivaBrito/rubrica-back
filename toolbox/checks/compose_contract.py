"""Validate security-relevant properties of rendered Compose JSON."""

from __future__ import annotations

import json
import sys


def validate(level: str, config: dict[str, object]) -> list[str]:
    services = config.get("services", {})
    if not isinstance(services, dict):
        return ["Compose configuration has no services mapping"]
    errors: list[str] = []
    core = services.get("core-api", {})
    for name in ("enterprise-worker", "enterprise-sandbox-worker", "enterprise-maintenance"):
        worker = services.get(name)
        if worker is None:
            continue
        if not worker.get("read_only") or "ALL" not in worker.get("cap_drop", []):
            errors.append(f"enterprise worker must be read-only and drop all capabilities: {name}")
        if not worker.get("tmpfs") or not worker.get("mem_limit") or not worker.get("pids_limit"):
            errors.append(f"enterprise worker requires bounded temporary storage, memory and PIDs: {name}")
        worker_env, core_env = worker.get("environment", {}), core.get("environment", {})
        for key in ("DOCUMENT_STORAGE_PROVIDER", "R2_DOCUMENTS_PREFIX", "DOCUMENT_STORAGE_ENCRYPTION_KEY_FILE",
                    "R2_DOCUMENTS_BUCKET_FILE", "SERPRO_TIMESTAMP_TRUST_ROOTS_FILE"):
            if worker_env.get(key) != core_env.get(key):
                errors.append(f"enterprise worker configuration differs from Core ({key}): {name}")
    if level == "production":
        forbidden = {"docs", "stripe-cli", "seed", "kafka", "loki"} & services.keys()
        if forbidden:
            errors.append(f"production contains forbidden services: {', '.join(sorted(forbidden))}")
        for name, service in services.items():
            if service.get("ports"):
                errors.append(f"production service publishes host ports: {name}")
        if "cloudflared" not in services or "gateway" not in services:
            errors.append("production requires cloudflared and gateway")
    elif level == "staging":
        for name in ("core-api", "enterprise-worker", "enterprise-sandbox-worker", "enterprise-maintenance"):
            service = services.get(name, {})
            if service.get("environment", {}).get("CONTACT_TURNSTILE_SECRET_KEY_FILE"):
                errors.append(f"staging must not load a Turnstile secret: {name}")
            for secret in service.get("secrets", []):
                source = secret.get("source") if isinstance(secret, dict) else secret
                if source == "contact_turnstile_secret_key":
                    errors.append(f"staging must not mount the Turnstile secret: {name}")
        forbidden = {"quick-tunnel", "stripe-cli", "seed"} & services.keys()
        if forbidden:
            errors.append(f"staging contains forbidden services: {', '.join(sorted(forbidden))}")
        for name, service in services.items():
            if name != "gateway" and service.get("ports"):
                errors.append(f"only staging gateway may publish a host port: {name}")
        for required in ("gateway", "cloudflared"):
            if required not in services:
                errors.append(f"remote staging requires service: {required}")
    else:
        errors.append(f"unknown Compose contract: {level}")
    return errors


def main() -> int:
    level = sys.argv[1] if len(sys.argv) > 1 else ""
    config = json.load(sys.stdin)
    errors = validate(level, config)
    for error in errors:
        print(f"[error] {error}")
    if errors:
        return 2
    print(f"[ok] {level} Compose isolation contract is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
