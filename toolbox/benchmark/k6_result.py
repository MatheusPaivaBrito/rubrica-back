from __future__ import annotations

from typing import Any


def normalize_k6_summary(
    raw: dict[str, Any],
    *,
    run_id: str,
    scenario: str,
    profile: str,
    configuration: dict[str, Any],
    process_exit_code: int,
    raw_output_path: str,
) -> dict[str, Any]:
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    request_values = _metric_values(metrics, "http_reqs")
    duration_values = _metric_values(metrics, "http_req_duration")
    failure_values = _metric_values(metrics, "http_req_failed")
    iteration_values = _metric_values(metrics, "iterations")
    dropped_values = _metric_values(metrics, "dropped_iterations")
    check_values = _metric_values(metrics, "checks")

    completed = _integer(request_values.get("count"))
    error_rate = _number(failure_values.get("rate"))
    failed = _counter_failures(failure_values, completed=completed, rate=error_rate)
    successful = max(0, completed - failed)
    dropped = _integer(dropped_values.get("count"))
    threshold_failures = _threshold_failures(metrics)
    check_failures = _integer(check_values.get("fails"))

    warnings: list[str] = []
    if failed:
        warnings.append(f"{failed} HTTP request(s) failed")
    if check_failures:
        warnings.append(f"{check_failures} k6 check(s) failed")
    if dropped:
        warnings.append(f"{dropped} iteration(s) were dropped")

    if process_exit_code != 0 or threshold_failures:
        result = "FAIL"
    elif warnings:
        result = "PASS_WITH_WARNINGS"
    else:
        result = "PASS"

    duration_seconds = _duration_seconds(raw, duration_values)
    iterations = _integer(iteration_values.get("count"))
    return {
        "schema_version": 1,
        "provider": "k6",
        "run_id": run_id,
        "passed": result != "FAIL",
        "result": result,
        "scenario": scenario,
        "name": f"k6-{scenario}",
        "profile": profile,
        "target": {
            "method": configuration.get("method", "GET"),
            "url": configuration.get("target_url"),
        },
        "configuration": configuration,
        "duration_seconds": round(duration_seconds, 6),
        "completed_requests": completed,
        "successful_requests": successful,
        "failed_requests": failed,
        "error_rate": round(error_rate, 6),
        "throughput_rps": round(_number(request_values.get("rate")), 3),
        "iterations": iterations,
        "dropped_iterations": dropped,
        "latency_ms": {
            "min": round(_number(duration_values.get("min")), 3),
            "average": round(_number(duration_values.get("avg")), 3),
            "p50": round(
                _number(duration_values.get("med", duration_values.get("p(50)"))),
                3,
            ),
            "p90": round(_number(duration_values.get("p(90)")), 3),
            "p95": round(_number(duration_values.get("p(95)")), 3),
            "p99": round(_number(duration_values.get("p(99)")), 3),
            "max": round(_number(duration_values.get("max")), 3),
        },
        "status_counts": {
            "successful": successful,
            "failed": failed,
        },
        "checks": {
            "passes": _integer(check_values.get("passes")),
            "fails": check_failures,
            "rate": round(_number(check_values.get("rate")), 6),
        },
        "thresholds": {
            "passed": not threshold_failures,
            "failures": threshold_failures,
        },
        "warnings": warnings,
        "error_samples": [*threshold_failures, *warnings][:10],
        "provider_exit_code": process_exit_code,
        "raw_provider_output": raw_output_path,
        "integrity": {
            "event_count_before": None,
            "event_count_after": None,
            "persisted_event_delta": None,
            "accepted_events_accounted_for": None,
        },
    }


def failed_k6_summary(
    *,
    run_id: str,
    scenario: str,
    profile: str,
    configuration: dict[str, Any],
    phase: str,
    message: str,
    process_exit_code: int,
    raw_output_path: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider": "k6",
        "run_id": run_id,
        "passed": False,
        "result": "FAIL",
        "phase": phase,
        "scenario": scenario,
        "name": f"k6-{scenario}",
        "profile": profile,
        "target": {
            "method": configuration.get("method", "GET"),
            "url": configuration.get("target_url"),
        },
        "configuration": configuration,
        "duration_seconds": 0.0,
        "completed_requests": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "error_rate": 1.0,
        "throughput_rps": 0.0,
        "iterations": 0,
        "dropped_iterations": 0,
        "latency_ms": {
            "min": 0.0,
            "average": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
        },
        "status_counts": {},
        "checks": {"passes": 0, "fails": 0, "rate": 0.0},
        "thresholds": {"passed": False, "failures": [message]},
        "warnings": [],
        "error_samples": [message],
        "provider_exit_code": process_exit_code,
        "raw_provider_output": raw_output_path,
        "integrity": {
            "event_count_before": None,
            "event_count_after": None,
            "persisted_event_delta": None,
            "accepted_events_accounted_for": None,
        },
    }


def render_k6_report(summary: dict[str, Any], metadata: dict[str, Any]) -> str:
    latency = summary["latency_ms"]
    thresholds = summary["thresholds"]
    warnings = summary.get("warnings") or []
    warning_lines = "\n".join(f"- {warning}" for warning in warnings) or "- None"
    threshold_lines = (
        "\n".join(f"- {failure}" for failure in thresholds.get("failures", []))
        or "- All configured thresholds passed"
    )
    return f"""# k6 Benchmark Report

- Run: `{summary['run_id']}`
- Provider: `k6`
- Result: `{summary['result']}`
- Scenario: `{summary['scenario']}`
- Profile: `{summary['profile']}`
- Target: `{summary['target']['method']} {summary['target']['url']}`
- Runtime: `{metadata.get('benchmark_runtime', 'unknown')}`
- Git commit: `{metadata.get('git_commit') or 'unknown'}`
- Manifest fingerprint: `{metadata.get('manifest_fingerprint') or 'unavailable'}`

## Workload

| Metric | Value |
| --- | ---: |
| Requests | {summary['completed_requests']} |
| Successful | {summary['successful_requests']} |
| Failed | {summary['failed_requests']} |
| Iterations | {summary['iterations']} |
| Dropped iterations | {summary['dropped_iterations']} |
| Duration | {summary['duration_seconds']:.3f} s |
| Throughput | {summary['throughput_rps']:.3f} req/s |

## Latency

| Metric | Milliseconds |
| --- | ---: |
| min | {latency['min']:.3f} |
| average | {latency['average']:.3f} |
| p50 | {latency['p50']:.3f} |
| p90 | {latency['p90']:.3f} |
| p95 | {latency['p95']:.3f} |
| p99 | {latency['p99']:.3f} |
| max | {latency['max']:.3f} |

## Thresholds

{threshold_lines}

## Warnings

{warning_lines}

This is a local diagnostic result, not a production capacity claim.
"""


def _metric_values(metrics: dict[str, Any], name: str) -> dict[str, Any]:
    metric = metrics.get(name)
    if not isinstance(metric, dict):
        return {}
    values = metric.get("values")
    return values if isinstance(values, dict) else {}


def _threshold_failures(metrics: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for metric_name, metric in metrics.items():
        if not isinstance(metric, dict):
            continue
        thresholds = metric.get("thresholds")
        if not isinstance(thresholds, dict):
            continue
        for expression, result in thresholds.items():
            if isinstance(result, dict) and result.get("ok") is False:
                failures.append(f"{metric_name}: {expression}")
    return sorted(failures)


def _counter_failures(values: dict[str, Any], *, completed: int, rate: float) -> int:
    if "passes" in values:
        return _integer(values.get("passes"))
    if "fails" in values and _integer(values.get("fails")) <= completed:
        return _integer(values.get("fails"))
    return min(completed, max(0, round(completed * rate)))


def _duration_seconds(raw: dict[str, Any], duration_values: dict[str, Any]) -> float:
    state = raw.get("state")
    if isinstance(state, dict):
        test_run_duration_ms = _number(state.get("testRunDurationMs"))
        if test_run_duration_ms:
            return test_run_duration_ms / 1000
    return _number(duration_values.get("count")) / 1000


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
