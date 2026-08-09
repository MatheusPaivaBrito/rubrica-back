from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from typing import Callable, Iterable


SERVICE_TARGETS = {
    "core_api": "migrate-core",
    "auth_api": "migrate-auth",
    "eventing_api": "migrate-eventing",
    "notification_api": "migrate-notification",
    "observability_api": "migrate-observability",
}

SERVICE_LABELS = {
    "core_api": "Core",
    "auth_api": "Auth",
    "eventing_api": "Eventing",
    "notification_api": "Notification",
    "observability_api": "Observability",
}

_REVISION_PATTERN = re.compile(r"^([0-9A-Za-z_]+)(?:\s+\([^)]*\))?$")
_DATABASE_ENV_KEYS = {
    "DEBUG",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_HOST_PORT",
    "POSTGRES_DB",
    "CORE_POSTGRES_DB",
    "AUTH_POSTGRES_DB",
    "EVENTING_POSTGRES_DB",
    "NOTIFICATION_POSTGRES_DB",
    "OBSERVABILITY_POSTGRES_DB",
    "DATABASE_URL",
    "CORE_DATABASE_URL",
    "AUTH_DATABASE_URL",
    "EVENTING_DATABASE_URL",
    "NOTIFICATION_DATABASE_URL",
    "OBSERVABILITY_DATABASE_URL",
}


@dataclass(frozen=True)
class MigrationStatus:
    service: str
    label: str
    target: str
    state: str
    current: tuple[str, ...] = ()
    heads: tuple[str, ...] = ()
    detail: str | None = None

    @property
    def pending(self) -> bool:
        return self.state == "pending"


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _detail(output: str, fallback: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return (lines[-1] if lines else fallback)[:300]


def discover_migration_services(project_root: Path) -> tuple[str, ...]:
    return tuple(
        service
        for service in SERVICE_TARGETS
        if (project_root / "apps" / service / "alembic.ini").is_file()
    )


def _revisions(output: str) -> tuple[str, ...]:
    revisions = []
    for raw_line in output.splitlines():
        match = _REVISION_PATTERN.fullmatch(raw_line.strip())
        if match:
            revisions.append(match.group(1))
    return tuple(sorted(set(revisions)))


def _pythonpath(project_root: Path, service: str) -> str:
    paths = [
        str(project_root / "apps" / service / "src"),
        str(project_root / "packages" / "shared_kernel" / "src"),
    ]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    return os.pathsep.join(paths)


def _read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _project_environment(project_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in _DATABASE_ENV_KEYS:
        env.pop(key, None)
    for filename in (".env", ".env.local.example", ".env.example"):
        values = _read_env(project_root / filename)
        if values:
            env.update(values)
            break
    return env


def _alembic(
    project_root: Path,
    service: str,
    command: str,
    *,
    runner: Runner,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    env = _project_environment(project_root)
    env["PYTHONPATH"] = _pythonpath(project_root, service)
    return runner(
        (
            "poetry",
            "run",
            "alembic",
            "-c",
            f"apps/{service}/alembic.ini",
            command,
        ),
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def inspect_migration(
    project_root: Path,
    service: str,
    *,
    runner: Runner = subprocess.run,
    timeout: float = 10.0,
) -> MigrationStatus:
    if service not in SERVICE_TARGETS:
        raise ValueError(f"Unsupported migration service: {service}")

    config = project_root / "apps" / service / "alembic.ini"
    if not config.is_file():
        raise ValueError(f"Migration config not found for {service}")

    base = {
        "service": service,
        "label": SERVICE_LABELS[service],
        "target": SERVICE_TARGETS[service],
    }
    try:
        heads_result = _alembic(project_root, service, "heads", runner=runner, timeout=timeout)
        if heads_result.returncode != 0:
            detail = _detail(heads_result.stderr or heads_result.stdout, "Unable to read Alembic heads")
            return MigrationStatus(**base, state="error", detail=detail)

        heads = _revisions(heads_result.stdout)
        current_result = _alembic(project_root, service, "current", runner=runner, timeout=timeout)
        if current_result.returncode != 0:
            detail = _detail(current_result.stderr or current_result.stdout, "Database is unavailable")
            return MigrationStatus(
                **base,
                state="unavailable",
                heads=heads,
                detail=detail,
            )

        current = _revisions(current_result.stdout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return MigrationStatus(**base, state="unavailable", detail=str(exc))

    state = "up_to_date" if current == heads else "pending"
    return MigrationStatus(**base, state=state, current=current, heads=heads)


def inspect_project_migrations(
    project_root: Path,
    *,
    runner: Runner = subprocess.run,
    timeout: float = 10.0,
) -> tuple[MigrationStatus, ...]:
    return tuple(
        inspect_migration(project_root, service, runner=runner, timeout=timeout)
        for service in discover_migration_services(project_root)
    )


def migrate_service(
    project_root: Path,
    service: str,
    *,
    runner: Runner = subprocess.run,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    if service not in discover_migration_services(project_root):
        raise ValueError(f"Migration service is not available in this project: {service}")
    return runner(
        ("make", SERVICE_TARGETS[service]),
        cwd=project_root,
        env=_project_environment(project_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def has_pending_migrations(statuses: Iterable[MigrationStatus]) -> bool:
    return any(status.pending for status in statuses)
