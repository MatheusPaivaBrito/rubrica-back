"""Start an explicit, allow-listed set of development dependencies."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ALLOWED = {"postgres", "redis", "kafka", "loki", "docs", "stripe-cli", "quick-tunnel"}
DEFAULT = ("postgres", "redis")
PROFILES = {"stripe-cli": "stripe", "quick-tunnel": "quick-tunnel"}


def parse_services(value: str) -> tuple[str, ...]:
    services = tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    if not services:
        raise ValueError("at least one development service is required")
    unknown = sorted(set(services) - ALLOWED)
    if unknown:
        raise ValueError(
            f"unknown dev service(s): {', '.join(unknown)}; allowed: {', '.join(sorted(ALLOWED))}"
        )
    return services


def main() -> None:
    requested = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].strip() else ",".join(DEFAULT)
    try:
        services = parse_services(requested)
    except ValueError as exc:
        raise SystemExit(f"[error] {exc}") from exc
    env_file = os.environ.get("DEV_ENV_FILE", ".env")
    profiles = tuple(dict.fromkeys(PROFILES[service] for service in services if service in PROFILES))
    if "stripe-cli" in services:
        (Path(__file__).resolve().parents[2] / ".runtime" / "stripe").mkdir(parents=True, exist_ok=True)
    profile_args = [argument for profile in profiles for argument in ("--profile", profile)]
    command = [
        "docker", "compose", "--env-file", env_file, "-f", "compose/dev-dependencies.yml",
        *profile_args, "up", "-d", "--wait", *services,
    ]
    subprocess.run(command, check=True)
    print(f"[ok] development dependencies ready: {', '.join(services)}")


if __name__ == "__main__":
    main()
