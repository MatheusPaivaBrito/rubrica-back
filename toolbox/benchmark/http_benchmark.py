from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx

try:
    from .common import RunArtifacts, environment_metadata, percentile, utc_run_id
except ImportError:  # pragma: no cover - direct script execution
    from common import RunArtifacts, environment_metadata, percentile, utc_run_id


PayloadFactory = Callable[[int, str], dict[str, Any] | None]
ProgressCallback = Callable[[int, int | None], None]


class BenchmarkPreflightError(RuntimeError):
    def __init__(self, samples: list[RequestSample]) -> None:
        self.samples = samples
        failures = [sample for sample in samples if not sample.successful]
        status_counts = Counter(
            str(sample.status_code) if sample.status_code is not None else "transport_error"
            for sample in failures
        )
        error_samples = list(dict.fromkeys(sample.error for sample in failures if sample.error))[:3]
        self.status_counts = dict(sorted(status_counts.items()))
        self.error_samples = error_samples
        super().__init__(
            "benchmark target failed during warm-up; "
            "fix runtime, migrations and target availability before measuring"
        )

    def summary(self, config: BenchmarkConfig, *, run_id: str, started_at: datetime) -> dict[str, Any]:
        latencies = [sample.latency_ms for sample in self.samples]
        failed = sum(not sample.successful for sample in self.samples)
        return {
            "schema_version": 1,
            "run_id": run_id,
            "passed": False,
            "result": "FAIL",
            "phase": "warmup",
            "scenario": config.scenario,
            "name": config.name,
            "profile": config.profile,
            "target": {"method": config.method, "url": config.url},
            "configuration": asdict(config),
            "started_at": started_at.isoformat(),
            "duration_seconds": 0.0,
            "completed_requests": len(self.samples),
            "successful_requests": len(self.samples) - failed,
            "failed_requests": failed,
            "error_rate": round(failed / len(self.samples), 6) if self.samples else 0.0,
            "throughput_rps": 0.0,
            "latency_ms": {
                "p50": round(percentile(latencies, 0.50), 3),
                "p90": round(percentile(latencies, 0.90), 3),
                "p95": round(percentile(latencies, 0.95), 3),
                "p99": round(percentile(latencies, 0.99), 3),
                "max": round(max(latencies, default=0.0), 3),
            },
            "status_counts": self.status_counts,
            "error_samples": self.error_samples,
            "integrity": {
                "event_count_before": None,
                "event_count_after": None,
                "persisted_event_delta": None,
                "accepted_events_accounted_for": None,
            },
            "failure": {"phase": "warmup", "message": str(self)},
        }


class BenchmarkInterrupted(RuntimeError):
    def __init__(
        self,
        *,
        config: BenchmarkConfig,
        samples: list[RequestSample],
        run_id: str,
        started_at: datetime,
        elapsed_seconds: float,
        event_count_before: int | None,
    ) -> None:
        self.config = config
        self.samples = samples
        self.run_id = run_id
        self.started_at = started_at
        self.elapsed_seconds = elapsed_seconds
        self.event_count_before = event_count_before
        super().__init__("benchmark interrupted before the measurement completed")

    def summary(self) -> dict[str, Any]:
        summary = build_summary(
            self.config,
            self.samples,
            run_id=self.run_id,
            started_at=self.started_at,
            elapsed_seconds=self.elapsed_seconds,
            event_count_before=self.event_count_before,
            event_count_after=None,
        )
        summary.update(
            {
                "passed": False,
                "result": "FAIL",
                "phase": "interrupted",
                "failure": {"phase": "interrupted", "message": str(self)},
            }
        )
        return summary


@dataclass(frozen=True)
class BenchmarkConfig:
    name: str
    profile: str
    url: str
    method: str
    requests: int
    concurrency: int
    warmup: int
    duration_seconds: float
    timeout_seconds: float
    expected_statuses: tuple[int, ...]
    max_error_rate: float
    headers: dict[str, str]
    scenario: str
    event_count_url: str | None = None
    event_topic: str = "atlas.benchmark.events"
    progress_every: int = 1000


@dataclass(frozen=True)
class RequestSample:
    latency_ms: float
    status_code: int | None
    error: str | None

    @property
    def successful(self) -> bool:
        return self.error is None


async def run_benchmark(
    config: BenchmarkConfig,
    *,
    payload_factory: PayloadFactory | None = None,
    run_id: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    active_run_id = run_id or utc_run_id(config.name)
    samples: list[RequestSample] = []
    limits = httpx.Limits(
        max_connections=config.concurrency,
        max_keepalive_connections=config.concurrency,
    )
    timeout = httpx.Timeout(config.timeout_seconds)

    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True) as client:
        event_count_before = await _event_count(client, config) if config.scenario == "eventing" else None
        await _warm_up(client, config, payload_factory, active_run_id)
        started_at = datetime.now(UTC)
        started = time.perf_counter()

        try:
            if config.duration_seconds > 0:
                await _run_for_duration(
                    client, config, payload_factory, active_run_id, samples, progress_callback
                )
            else:
                await _run_fixed_iterations(
                    client, config, payload_factory, active_run_id, samples, progress_callback
                )
        except asyncio.CancelledError as exc:
            raise BenchmarkInterrupted(
                config=config,
                samples=samples,
                run_id=active_run_id,
                started_at=started_at,
                elapsed_seconds=time.perf_counter() - started,
                event_count_before=event_count_before,
            ) from exc

        elapsed = time.perf_counter() - started
        event_count_after = await _event_count(client, config) if config.scenario == "eventing" else None

    return build_summary(
        config,
        samples,
        run_id=active_run_id,
        started_at=started_at,
        elapsed_seconds=elapsed,
        event_count_before=event_count_before,
        event_count_after=event_count_after,
    )


def build_summary(
    config: BenchmarkConfig,
    samples: list[RequestSample],
    *,
    run_id: str,
    started_at: datetime,
    elapsed_seconds: float,
    event_count_before: int | None = None,
    event_count_after: int | None = None,
) -> dict[str, Any]:
    latencies = [sample.latency_ms for sample in samples]
    failures = [sample for sample in samples if not sample.successful]
    completed = len(samples)
    successful = completed - len(failures)
    error_rate = len(failures) / completed if completed else 1.0
    status_counts = Counter(str(sample.status_code) if sample.status_code is not None else "transport_error" for sample in samples)
    event_delta = None
    integrity_ok = None
    if event_count_before is not None and event_count_after is not None:
        event_delta = event_count_after - event_count_before
        integrity_ok = event_delta >= successful

    expected_completed = config.requests if config.duration_seconds <= 0 else completed
    passed = (
        completed == expected_completed
        and error_rate <= config.max_error_rate
        and integrity_ok is not False
    )
    result = "FAIL"
    if passed:
        result = "PASS_WITH_WARNINGS" if failures else "PASS"
    return {
        "schema_version": 1,
        "run_id": run_id,
        "passed": passed,
        "result": result,
        "scenario": config.scenario,
        "name": config.name,
        "profile": config.profile,
        "target": {"method": config.method, "url": config.url},
        "configuration": asdict(config),
        "started_at": started_at.isoformat(),
        "duration_seconds": round(elapsed_seconds, 6),
        "completed_requests": completed,
        "successful_requests": successful,
        "failed_requests": len(failures),
        "error_rate": round(error_rate, 6),
        "throughput_rps": round(completed / elapsed_seconds, 3) if elapsed_seconds > 0 else 0.0,
        "latency_ms": {
            "p50": round(percentile(latencies, 0.50), 3),
            "p90": round(percentile(latencies, 0.90), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
            "max": round(max(latencies, default=0.0), 3),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "error_samples": [sample.error for sample in failures[:10] if sample.error],
        "integrity": {
            "event_count_before": event_count_before,
            "event_count_after": event_count_after,
            "persisted_event_delta": event_delta,
            "accepted_events_accounted_for": integrity_ok,
        },
    }


def render_report(summary: dict[str, Any], metadata: dict[str, Any]) -> str:
    latency = summary["latency_ms"]
    integrity = summary["integrity"]
    return f"""# Benchmark Report

- Run: `{summary['run_id']}`
- Result: `{summary.get('result') or ('PASS' if summary['passed'] else 'FAIL')}`
- Phase: `{summary.get('phase', 'measurement')}`
- Scenario: `{summary['scenario']}`
- Profile: `{summary['profile']}`
- Target: `{summary['target']['method']} {summary['target']['url']}`
- Git commit: `{metadata.get('git_commit') or 'unknown'}`

## Throughput

| Metric | Value |
| --- | ---: |
| Completed | {summary['completed_requests']} |
| Successful | {summary['successful_requests']} |
| Failed | {summary['failed_requests']} |
| Error rate | {summary['error_rate']:.4%} |
| Duration | {summary['duration_seconds']:.3f} s |
| Throughput | {summary['throughput_rps']:.3f} req/s |

## Latency

| Percentile | Milliseconds |
| --- | ---: |
| p50 | {latency['p50']:.3f} |
| p90 | {latency['p90']:.3f} |
| p95 | {latency['p95']:.3f} |
| p99 | {latency['p99']:.3f} |
| max | {latency['max']:.3f} |

## Integrity

- Event count before: `{integrity['event_count_before']}`
- Event count after: `{integrity['event_count_after']}`
- Persisted delta: `{integrity['persisted_event_delta']}`
- Accepted events accounted for: `{integrity['accepted_events_accounted_for']}`

This report describes one local run. It is not a production capacity claim.
"""


async def _run_fixed_iterations(
    client: httpx.AsyncClient,
    config: BenchmarkConfig,
    payload_factory: PayloadFactory | None,
    run_id: str,
    samples: list[RequestSample],
    progress_callback: ProgressCallback | None = None,
) -> None:
    queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(config.requests):
        queue.put_nowait(index)

    completed = 0

    async def worker() -> None:
        nonlocal completed
        while True:
            try:
                index = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            samples.append(await _request(client, config, payload_factory, index, run_id))
            completed += 1
            _report_progress(progress_callback, completed, config.requests, config.progress_every)

    await asyncio.gather(*(worker() for _ in range(config.concurrency)))


async def _run_for_duration(
    client: httpx.AsyncClient,
    config: BenchmarkConfig,
    payload_factory: PayloadFactory | None,
    run_id: str,
    samples: list[RequestSample],
    progress_callback: ProgressCallback | None = None,
) -> None:
    deadline = time.perf_counter() + config.duration_seconds
    index = 0
    index_lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal index
        while time.perf_counter() < deadline:
            async with index_lock:
                current_index = index
                index += 1
            samples.append(await _request(client, config, payload_factory, current_index, run_id))
            _report_progress(progress_callback, len(samples), None, config.progress_every)

    await asyncio.gather(*(worker() for _ in range(config.concurrency)))


async def _warm_up(
    client: httpx.AsyncClient,
    config: BenchmarkConfig,
    payload_factory: PayloadFactory | None,
    run_id: str,
) -> None:
    if config.warmup <= 0:
        return

    queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(config.warmup):
        queue.put_nowait(-index - 1)

    samples: list[RequestSample] = []

    async def worker() -> None:
        while True:
            try:
                index = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            samples.append(
                await _request(client, config, payload_factory, index, f"warmup-{run_id}")
            )

    worker_count = min(config.concurrency, config.warmup)
    await asyncio.gather(*(worker() for _ in range(worker_count)))

    if any(not sample.successful for sample in samples):
        raise BenchmarkPreflightError(samples)


def _report_progress(
    callback: ProgressCallback | None,
    completed: int,
    total: int | None,
    every: int,
) -> None:
    if callback is None or every <= 0:
        return
    if completed % every == 0 or total is not None and completed == total:
        callback(completed, total)


async def _request(
    client: httpx.AsyncClient,
    config: BenchmarkConfig,
    payload_factory: PayloadFactory | None,
    index: int,
    run_id: str,
) -> RequestSample:
    payload = payload_factory(index, run_id) if payload_factory else None
    started = time.perf_counter()
    try:
        response = await client.request(
            config.method,
            config.url,
            headers=config.headers,
            json=payload,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        if response.status_code not in config.expected_statuses:
            return RequestSample(
                latency_ms=latency_ms,
                status_code=response.status_code,
                error=f"unexpected HTTP {response.status_code}: {response.text[:200]}",
            )
        return RequestSample(latency_ms=latency_ms, status_code=response.status_code, error=None)
    except httpx.HTTPError as exc:
        return RequestSample(
            latency_ms=(time.perf_counter() - started) * 1000,
            status_code=None,
            error=f"{exc.__class__.__name__}: {exc}",
        )


async def _event_count(client: httpx.AsyncClient, config: BenchmarkConfig) -> int | None:
    if config.event_count_url:
        summary_url = config.event_count_url
    else:
        parsed = urlsplit(config.url)
        summary_url = urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                "/projections/outbox-summary",
                "",
                "",
            )
        )
    try:
        response = await client.get(summary_url)
        response.raise_for_status()
        payload = response.json()
        return int(payload.get("by_event_type", {}).get("core.book_created", 0))
    except (httpx.HTTPError, TypeError, ValueError):
        return None


def eventing_payload(index: int, run_id: str, *, topic: str = "atlas.benchmark.events") -> dict[str, Any]:
    event_id = uuid4()
    return {
        "event_type": "core.book_created",
        "source": "core_api",
        "actor_type": "service",
        "actor_id": "atlas_benchmark",
        "data": {
            "book_id": str(event_id),
            "title": f"Benchmark Book {index}",
            "isbn": None,
            "shelf_id": None,
        },
        "topic": topic,
        "version": 1,
        "correlation_id": f"{run_id}-{index}",
    }


def parse_headers(values: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for value in values:
        if ":" not in value:
            raise ValueError(f"invalid header {value!r}; expected 'Name: Value'")
        name, content = value.split(":", maxsplit=1)
        headers[name.strip()] = content.strip()
    return headers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a reproducible Atlas HTTP benchmark.")
    parser.add_argument("--name", default="http")
    parser.add_argument("--scenario", choices=("http", "eventing"), default="http")
    parser.add_argument("--profile", default="development-diagnostic")
    parser.add_argument("--url", required=True)
    parser.add_argument("--method", default="GET")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--duration-seconds", type=float, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=10)
    parser.add_argument("--expected-status", default="200")
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--header", action="append", default=[])
    parser.add_argument("--output-root", default=".artifacts/benchmarks")
    parser.add_argument("--run-id")
    parser.add_argument("--event-count-url")
    parser.add_argument("--event-topic", default="atlas.benchmark.events")
    parser.add_argument("--progress-every", type=int, default=1000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.requests < 1:
        raise SystemExit("--requests must be at least 1")
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be at least 1")
    if not 0 <= args.max_error_rate <= 1:
        raise SystemExit("--max-error-rate must be between 0 and 1")
    if args.progress_every < 0:
        raise SystemExit("--progress-every cannot be negative")

    config = BenchmarkConfig(
        name=args.name,
        profile=args.profile,
        url=args.url,
        method=args.method.upper(),
        requests=args.requests,
        concurrency=args.concurrency,
        warmup=args.warmup,
        duration_seconds=args.duration_seconds,
        timeout_seconds=args.timeout_seconds,
        expected_statuses=tuple(int(value) for value in args.expected_status.split(",")),
        max_error_rate=args.max_error_rate,
        headers=parse_headers(args.header),
        scenario=args.scenario,
        event_count_url=args.event_count_url,
        event_topic=args.event_topic,
        progress_every=args.progress_every,
    )
    payload_factory: PayloadFactory | None = None
    if config.scenario == "eventing":

        def payload_factory(index: int, run_id: str) -> dict[str, Any]:
            return eventing_payload(index, run_id, topic=config.event_topic)

    active_run_id = args.run_id or utc_run_id(config.name)
    started_at = datetime.now(UTC)

    def progress(completed: int, total: int | None) -> None:
        suffix = f"/{total}" if total is not None else "+"
        print(f"[progress] {completed}{suffix} requests completed", file=sys.stderr, flush=True)

    try:
        summary = asyncio.run(
            run_benchmark(
                config,
                payload_factory=payload_factory,
                run_id=active_run_id,
                progress_callback=progress,
            )
        )
    except BenchmarkInterrupted as exc:
        summary = exc.summary()
        metadata = environment_metadata()
        artifacts = RunArtifacts(Path(args.output_root), summary["run_id"])
        artifacts.write_json("metadata.json", metadata)
        artifacts.write_json("summary.json", summary)
        report_path = artifacts.write_text("report.md", render_report(summary, metadata))
        print(
            json.dumps(
                {
                    "run_id": summary["run_id"],
                    "passed": False,
                    "result": "FAIL",
                    "phase": "interrupted",
                    "completed": summary["completed_requests"],
                    "message": str(exc),
                    "report": str(report_path),
                },
                indent=2,
            )
        )
        return 130
    except BenchmarkPreflightError as exc:
        summary = exc.summary(config, run_id=active_run_id, started_at=started_at)
        metadata = environment_metadata()
        artifacts = RunArtifacts(Path(args.output_root), active_run_id)
        artifacts.write_json("metadata.json", metadata)
        artifacts.write_json("summary.json", summary)
        report_path = artifacts.write_text("report.md", render_report(summary, metadata))
        print(
            json.dumps(
            {
                    "run_id": active_run_id,
                    "passed": False,
                    "result": "FAIL",
                    "phase": "warmup",
                    "message": str(exc),
                    "status_counts": exc.status_counts,
                    "error_samples": exc.error_samples,
                    "report": str(report_path),
                },
                indent=2,
            )
        )
        return 2
    metadata = environment_metadata()
    artifacts = RunArtifacts(Path(args.output_root), summary["run_id"])
    artifacts.write_json("metadata.json", metadata)
    artifacts.write_json("summary.json", summary)
    report_path = artifacts.write_text("report.md", render_report(summary, metadata))

    print(json.dumps({
        "run_id": summary["run_id"],
        "passed": summary["passed"],
        "completed": summary["completed_requests"],
        "failed": summary["failed_requests"],
        "rps": summary["throughput_rps"],
        "p95_ms": summary["latency_ms"]["p95"],
        "report": str(report_path),
    }, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
