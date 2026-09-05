from __future__ import annotations

import json
import os
import platform
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_run_id(prefix: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{_slug(prefix)}"


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def environment_metadata() -> dict[str, Any]:
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor() or "unknown",
        "logical_cpus": os.cpu_count(),
        "memory_bytes": _memory_bytes(),
        "runtime": {
            key: value
            for key in (
                "CORE_WEB_CONCURRENCY",
                "AUTH_WEB_CONCURRENCY",
                "EVENTING_WEB_CONCURRENCY",
                "NOTIFICATION_WEB_CONCURRENCY",
                "OBSERVABILITY_WEB_CONCURRENCY",
                "WORKERS",
            )
            if (value := os.getenv(key))
        },
    }


@dataclass(frozen=True)
class RunArtifacts:
    root: Path
    run_id: str

    @property
    def directory(self) -> Path:
        return self.root / self.run_id

    def prepare(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        return self.directory

    def write_json(self, name: str, payload: dict[str, Any]) -> Path:
        self.prepare()
        path = self.directory / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def write_text(self, name: str, content: str) -> Path:
        self.prepare()
        path = self.directory / name
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        return path


def _slug(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in normalized.split("-") if part) or "benchmark"


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _memory_bytes() -> int | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None
    return int(pages * page_size)
