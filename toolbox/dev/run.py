"""Run Rubrica application processes bare metal with coordinated shutdown."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT.parent / "rubrica-front"
PYTHONPATH = ":".join((
    ".", "apps/auth_api/src", "apps/core_api/src", "apps/eventing_api/src",
    "apps/notification_api/src", "apps/observability_api/src", "packages/shared_kernel/src",
))
APPS = (
    ("core", "core_api.main:app", "CORE_API_DEV_PORT", "8100"),
    ("auth", "auth_api.main:app", "AUTH_API_DEV_PORT", "8101"),
    ("eventing", "eventing_api.main:app", "EVENTING_API_DEV_PORT", "8102"),
    ("notification", "notification_api.main:app", "NOTIFICATION_API_DEV_PORT", "8103"),
    ("observability", "observability_api.main:app", "OBSERVABILITY_API_DEV_PORT", "8104"),
)


def fail(message: str) -> None:
    raise SystemExit(f"[error] {message}")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def main() -> None:
    env_file = ROOT / os.environ.get("DEV_ENV_FILE", ".env")
    if not env_file.is_file():
        fail(f"{env_file.name} is missing; run 'make dev-bootstrap' or copy .env.example")
    if not (ROOT / ".venv").exists() or shutil.which("poetry") is None:
        fail("Poetry environment is missing; run 'poetry install'")
    if not FRONTEND.joinpath("node_modules").exists() or shutil.which("npm") is None:
        fail(f"frontend dependencies are missing in {FRONTEND}; run 'npm ci'")

    env = {**read_env(env_file), **os.environ}
    env["PYTHONPATH"] = PYTHONPATH
    env.setdefault("DOCUMENT_STORAGE_PATH", str(ROOT / ".runtime" / "documents"))
    env.setdefault("STRIPE_WEBHOOK_SECRET_FILE", str(ROOT / ".runtime" / "stripe" / "stripe_webhook_secret"))
    Path(env["DOCUMENT_STORAGE_PATH"]).mkdir(parents=True, exist_ok=True)
    processes: list[subprocess.Popen[bytes]] = []
    commands = [
        ["poetry", "run", "uvicorn", module, "--host", "127.0.0.1", "--port", env.get(port_var, default), "--reload"]
        for _, module, port_var, default in APPS
    ]
    commands.append(["npm", "start"])

    def stop(*_: object) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        for command in commands[:-1]:
            processes.append(subprocess.Popen(command, cwd=ROOT, env=env))
        processes.append(subprocess.Popen(commands[-1], cwd=FRONTEND, env=env))
        while True:
            for index, process in enumerate(processes):
                exit_code = process.poll()
                if exit_code is not None:
                    name = APPS[index][0] if index < len(APPS) else "frontend"
                    if exit_code:
                        fail(f"{name} development process exited with status {exit_code}")
                    return
            time.sleep(0.25)
    finally:
        stop()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
