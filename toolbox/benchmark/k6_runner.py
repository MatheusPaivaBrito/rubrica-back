from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit, urlunsplit

try:
    from .common import RunArtifacts, environment_metadata, utc_run_id
    from .k6_result import failed_k6_summary, normalize_k6_summary, render_k6_report
except ImportError:  # pragma: no cover - direct script execution
    from common import RunArtifacts, environment_metadata, utc_run_id
    from k6_result import failed_k6_summary, normalize_k6_summary, render_k6_report


SCENARIO_DEFAULTS = {
    "core-public": ("GET", "http://localhost:8100/items"),
    "core-protected": ("POST", "http://localhost:8100/items"),
    "core-gateway": ("GET", "http://localhost:8180/core/items"),
    "eventing-outbox": ("POST", "http://localhost:8102/events"),
    "notification-local": ("POST", "http://localhost:8103/messaging/email/messages"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run and normalize a generated Atlas k6 scenario.")
    parser.add_argument("--scenario", choices=tuple(SCENARIO_DEFAULTS), required=True)
    parser.add_argument("--mode", choices=("smoke", "load", "stress", "soak"), default="smoke")
    parser.add_argument("--profile", default="generated-k6")
    parser.add_argument("--runtime", choices=("auto", "local", "docker"), default="auto")
    parser.add_argument("--target-url")
    parser.add_argument("--auth-url", default="http://localhost:8101")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--rate", type=int, default=25)
    parser.add_argument("--duration", default="30s")
    parser.add_argument("--preallocated-vus", type=int, default=25)
    parser.add_argument("--max-vus", type=int, default=100)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--p95-ms", type=int, default=1000)
    parser.add_argument("--output-root", default=".artifacts/benchmarks")
    parser.add_argument("--run-id")
    parser.add_argument("--allow-remote-target", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _validate_args(args)
    method, default_target = SCENARIO_DEFAULTS[args.scenario]
    target_url = args.target_url or default_target
    _ensure_safe_target(target_url, allow_remote=args.allow_remote_target)
    _ensure_safe_target(args.auth_url, allow_remote=args.allow_remote_target)

    run_id = args.run_id or utc_run_id(f"k6-{args.scenario}")
    output_root = Path(args.output_root)
    artifacts = RunArtifacts(output_root, run_id)
    artifacts.prepare()
    runtime = _resolve_runtime(args.runtime)
    raw_host_path = artifacts.directory / "k6-summary.json"
    provider_output_path = artifacts.directory / "k6-output.txt"
    script_path = Path("performance/k6/scenarios") / f"{args.scenario}.js"
    if not script_path.exists():
        raise SystemExit(f"k6 scenario is unavailable in this project: {script_path}")

    configuration = {
        "provider": "k6",
        "mode": args.mode,
        "scenario": args.scenario,
        "profile": args.profile,
        "method": method,
        "target_url": target_url,
        "auth_url": args.auth_url,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "rate": args.rate,
        "duration": args.duration,
        "preallocated_vus": args.preallocated_vus,
        "max_vus": args.max_vus,
        "max_error_rate": args.max_error_rate,
        "p95_ms": args.p95_ms,
        "load_model": _load_model(args.mode),
    }
    metadata = environment_metadata()
    metadata.update(
        {
            "benchmark_provider": "k6",
            "benchmark_runtime": runtime,
            "manifest_fingerprint": _manifest_fingerprint(Path(".atlas/manifest.json")),
        }
    )
    artifacts.write_json("metadata.json", metadata)

    env = _k6_environment(
        args,
        target_url=_docker_url(target_url) if runtime == "docker" else target_url,
        auth_url=_docker_url(args.auth_url) if runtime == "docker" else args.auth_url,
        raw_summary=(
            f"/artifacts/{run_id}/k6-summary.json"
            if runtime == "docker"
            else str(raw_host_path.resolve())
        ),
        run_id=run_id,
    )
    command = _command(runtime, script_path=script_path, env=env)
    result = subprocess.run(command, capture_output=True, text=True, env=_process_env(runtime, env))
    provider_output_path.write_text(
        f"$ {' '.join(_redacted_command(command))}\n\n"
        f"STDOUT\n{result.stdout}\n\nSTDERR\n{result.stderr}\n",
        encoding="utf-8",
    )

    if raw_host_path.exists():
        try:
            raw = json.loads(raw_host_path.read_text(encoding="utf-8"))
            summary = normalize_k6_summary(
                raw,
                run_id=run_id,
                scenario=args.scenario,
                profile=args.profile,
                configuration=configuration,
                process_exit_code=result.returncode,
                raw_output_path=str(raw_host_path),
            )
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            summary = failed_k6_summary(
                run_id=run_id,
                scenario=args.scenario,
                profile=args.profile,
                configuration=configuration,
                phase="normalization",
                message=f"could not normalize k6 summary: {exc}",
                process_exit_code=result.returncode,
                raw_output_path=str(raw_host_path),
            )
    else:
        message = (result.stderr or result.stdout or "k6 produced no summary").strip()
        summary = failed_k6_summary(
            run_id=run_id,
            scenario=args.scenario,
            profile=args.profile,
            configuration=configuration,
            phase="execution",
            message=message[:1000],
            process_exit_code=result.returncode,
            raw_output_path=str(raw_host_path),
        )

    artifacts.write_json("summary.json", summary)
    report_path = artifacts.write_text("report.md", render_k6_report(summary, metadata))
    print(
        json.dumps(
            {
                "run_id": run_id,
                "provider": "k6",
                "runtime": runtime,
                "scenario": args.scenario,
                "result": summary["result"],
                "requests": summary["completed_requests"],
                "rps": summary["throughput_rps"],
                "p95_ms": summary["latency_ms"]["p95"],
                "report": str(report_path),
            },
            indent=2,
        )
    )
    return 0 if summary["passed"] else 1


def _validate_args(args: argparse.Namespace) -> None:
    positive = {
        "--requests": args.requests,
        "--concurrency": args.concurrency,
        "--rate": args.rate,
        "--preallocated-vus": args.preallocated_vus,
        "--max-vus": args.max_vus,
        "--p95-ms": args.p95_ms,
    }
    for name, value in positive.items():
        if value < 1:
            raise SystemExit(f"{name} must be at least 1")
    if args.max_vus < args.preallocated_vus:
        raise SystemExit("--max-vus cannot be lower than --preallocated-vus")
    if not 0 <= args.max_error_rate <= 1:
        raise SystemExit("--max-error-rate must be between 0 and 1")


def _resolve_runtime(requested: str) -> str:
    if requested == "local":
        if shutil.which("k6") is None:
            raise SystemExit("k6 is not installed; use --runtime docker or install k6")
        return "local"
    if requested == "docker":
        _require_docker_compose()
        return "docker"
    if shutil.which("k6"):
        return "local"
    _require_docker_compose()
    return "docker"


def _require_docker_compose() -> None:
    if shutil.which("docker") is None:
        raise SystemExit("neither k6 nor Docker is available")
    result = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit("Docker Compose is unavailable and local k6 is not installed")
    if not Path("docker-compose.benchmark.yml").exists():
        raise SystemExit("docker-compose.benchmark.yml is missing")


def _command(runtime: str, *, script_path: Path, env: dict[str, str]) -> list[str]:
    if runtime == "local":
        return ["k6", "run", "--summary-mode=full", str(script_path)]

    command = [
        "docker",
        "compose",
        "-f",
        "docker-compose.benchmark.yml",
        "--profile",
        "benchmark",
        "run",
        "--rm",
    ]
    for key, value in sorted(env.items()):
        command.extend(["-e", f"{key}={value}"])
    command.extend(["k6", "run", "--summary-mode=full", f"/scripts/scenarios/{script_path.name}"])
    return command


def _process_env(runtime: str, env: dict[str, str]) -> dict[str, str] | None:
    if runtime == "docker":
        return None
    return {**os.environ, **env}


def _redacted_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    for argument in command:
        if argument.startswith("K6_AUTH_PASSWORD="):
            redacted.append("K6_AUTH_PASSWORD=<redacted>")
        else:
            redacted.append(argument)
    return redacted


def _k6_environment(
    args: argparse.Namespace,
    *,
    target_url: str,
    auth_url: str,
    raw_summary: str,
    run_id: str,
) -> dict[str, str]:
    environment = {
        "ATLAS_K6_MODE": args.mode,
        "ATLAS_K6_RUN_ID": run_id,
        "ATLAS_K6_RAW_SUMMARY": raw_summary,
        "TARGET_URL": target_url,
        "AUTH_URL": auth_url,
        "K6_REQUESTS": str(args.requests),
        "K6_CONCURRENCY": str(args.concurrency),
        "K6_RATE": str(args.rate),
        "K6_DURATION": args.duration,
        "K6_PREALLOCATED_VUS": str(args.preallocated_vus),
        "K6_MAX_VUS": str(args.max_vus),
        "K6_MAX_ERROR_RATE": str(args.max_error_rate),
        "K6_P95_MS": str(args.p95_ms),
    }
    for key in ("K6_AUTH_EMAIL", "K6_AUTH_PASSWORD"):
        value = os.getenv(key)
        if value:
            environment[key] = value
    return environment


def _ensure_safe_target(url: str, *, allow_remote: bool) -> None:
    parsed = urlsplit(url)
    local_hosts = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SystemExit(f"invalid benchmark target URL: {url}")
    if parsed.hostname not in local_hosts and not allow_remote:
        raise SystemExit(
            f"refusing non-local benchmark target {parsed.hostname!r}; "
            "pass --allow-remote-target only with explicit authorization"
        )


def _docker_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return url
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit(
        (
            parsed.scheme,
            f"host.docker.internal{port}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def _manifest_fingerprint(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _load_model(mode: str) -> str:
    return {
        "smoke": "shared-iterations",
        "load": "constant-arrival-rate",
        "stress": "ramping-arrival-rate",
        "soak": "constant-vus",
    }[mode]


if __name__ == "__main__":
    raise SystemExit(main())
