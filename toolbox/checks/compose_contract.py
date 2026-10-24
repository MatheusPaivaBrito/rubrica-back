"""Validate security-relevant properties of rendered Compose JSON."""

from __future__ import annotations

import json
import sys


def validate(level: str, config: dict[str, object]) -> list[str]:
    services = config.get("services", {})
    if not isinstance(services, dict):
        return ["Compose configuration has no services mapping"]
    errors: list[str] = []
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
        forbidden = {"quick-tunnel", "seed"} & services.keys()
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
