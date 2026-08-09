from __future__ import annotations

import os
import socket
import subprocess
import sys
from collections.abc import Iterable


Dependency = tuple[str, str, int, str]

DEPENDENCIES: dict[str, list[Dependency]] = {'core': [('Core Postgres', 'POSTGRES_HOST', 5435, 'postgres')], 'auth': [('Auth Postgres', 'POSTGRES_HOST', 5435, 'postgres'), ('Auth Redis', 'REDIS_HOST', 6381, 'redis')]}


def _env(name: str, default: str) -> str:
    return os.getenv(name) or default


def _can_connect(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def _dependencies_for(service: str) -> list[Dependency]:
    if service == "all":
        merged: list[Dependency] = []
        seen: set[tuple[str, int, str]] = set()
        for dependencies in DEPENDENCIES.values():
            for name, host_env, port, compose_service in dependencies:
                key = (host_env, port, compose_service)
                if key not in seen:
                    seen.add(key)
                    merged.append((name, host_env, port, compose_service))
        return merged
    return DEPENDENCIES.get(service, [])


def _start_compose(services: Iterable[str]) -> None:
    selected = sorted(set(services))
    if not selected:
        return
    print("[compose] docker compose up -d %s" % " ".join(selected))
    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait", "--wait-timeout", "90", *selected],
        check=True,
    )


def main() -> int:
    service = sys.argv[1] if len(sys.argv) > 1 else "all"
    dependencies = _dependencies_for(service)
    if not dependencies:
        print("[ok] %s has no selected runtime dependencies" % service)
        return 0
    if _env("ATLAS_SKIP_INFRA_ENSURE", "0") in ('1', 'true', 'True'):
        print("[skip] Runtime dependency checks disabled by ATLAS_SKIP_INFRA_ENSURE")
        return 0

    missing: list[Dependency] = []
    for name, host_env, port, compose_service in dependencies:
        host = _env(host_env, "localhost")
        if _can_connect(host, port):
            print("[ok] %s accepting TCP connections at %s:%s" % (name, host, port))
        else:
            print("[missing] %s is not accepting TCP connections at %s:%s" % (name, host, port))
            missing.append((name, host_env, port, compose_service))

    if missing and _env("ATLAS_AUTO_COMPOSE", "1") not in ('0', 'false', 'False'):
        _start_compose(item[3] for item in missing)
        still_missing = []
        for name, host_env, port, compose_service in missing:
            host = _env(host_env, "localhost")
            if _can_connect(host, port):
                print("[ok] %s became available at %s:%s" % (name, host, port))
            else:
                still_missing.append(name)
        if still_missing:
            print("[error] Missing runtime dependencies after compose start: %s" % ", ".join(still_missing))
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
