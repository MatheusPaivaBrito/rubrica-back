from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


RUN_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
MEMORY_VALUE = re.compile(r"^(?P<value>[\d.]+)\s*(?P<unit>[KMGT]?i?B)$", re.IGNORECASE)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    return payload


def _timestamp(run_id: str) -> str:
    raw = run_id.split("Z-", maxsplit=1)[0] + "Z"
    try:
        return datetime.strptime(raw, RUN_TIMESTAMP_FORMAT).strftime("%m-%d %H:%M:%S")
    except ValueError:
        return raw[:14]


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


def _short(value: Any, width: int) -> str:
    text = str(value or "-")
    if len(text) <= width:
        return text
    return text[: max(1, width - 1)] + "~"


def _result(summary: dict[str, Any]) -> str:
    explicit = summary.get("result")
    if explicit in {"PASS", "PASS_WITH_WARNINGS", "FAIL"}:
        return str(explicit)
    if not summary.get("passed"):
        return "FAIL"
    if _integer(summary.get("failed_requests")) > 0:
        return "PASS_WITH_WARNINGS"
    return "PASS"


def _provider(summary: dict[str, Any]) -> str:
    return str(summary.get("provider") or "native")


def _human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def _memory_mib(raw: str) -> float:
    used = raw.split("/", maxsplit=1)[0].strip()
    match = MEMORY_VALUE.match(used)
    if not match:
        return 0.0
    value = float(match.group("value"))
    unit = match.group("unit").lower()
    factors = {
        "b": 1 / (1024 * 1024),
        "kb": 1000 / (1024 * 1024),
        "kib": 1 / 1024,
        "mb": 1_000_000 / (1024 * 1024),
        "mib": 1,
        "gb": 1_000_000_000 / (1024 * 1024),
        "gib": 1024,
        "tb": 1_000_000_000_000 / (1024 * 1024),
        "tib": 1024 * 1024,
    }
    return value * factors.get(unit, 0.0)


def _format_mib(value: float) -> str:
    if value >= 1024:
        return f"{value / 1024:.2f} GiB"
    return f"{value:.2f} MiB"


def _size_bytes(raw: str) -> float:
    match = MEMORY_VALUE.match(raw.strip())
    if not match:
        return 0.0
    value = float(match.group("value"))
    unit = match.group("unit").lower()
    factors = {
        "b": 1,
        "kb": 1000,
        "kib": 1024,
        "mb": 1_000_000,
        "mib": 1024**2,
        "gb": 1_000_000_000,
        "gib": 1024**3,
        "tb": 1_000_000_000_000,
        "tib": 1024**4,
    }
    return value * factors.get(unit, 0.0)


def _io_pair(raw: str) -> tuple[float, float]:
    parts = raw.split("/", maxsplit=1)
    if len(parts) != 2:
        return 0.0, 0.0
    return _size_bytes(parts[0]), _size_bytes(parts[1])


def _table(headers: list[str], rows: Iterable[Iterable[Any]], align_right: set[int]) -> list[str]:
    normalized = [[str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in normalized:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def format_row(row: list[str]) -> str:
        cells = []
        for index, cell in enumerate(row):
            cells.append(cell.rjust(widths[index]) if index in align_right else cell.ljust(widths[index]))
        return "  ".join(cells)

    separator = "  ".join("-" * width for width in widths)
    return [format_row(headers), separator, *(format_row(row) for row in normalized)]


def _resource_rows(csv_paths: list[Path]) -> tuple[list[list[str]], list[list[str]], list[str]]:
    samples: dict[str, list[tuple[float, float, int, float, float, float, float]]] = defaultdict(list)
    errors: list[str] = []
    for path in csv_paths:
        try:
            with path.open(encoding="utf-8", newline="") as stream:
                for row in csv.DictReader(stream):
                    name = row.get("name", "").strip()
                    if not name:
                        continue
                    cpu = _number(row.get("cpu", "0").rstrip("%"))
                    memory = _memory_mib(row.get("memory", ""))
                    pids = _integer(row.get("pids"))
                    network_rx, network_tx = _io_pair(row.get("net_io", ""))
                    block_read, block_write = _io_pair(row.get("block_io", ""))
                    samples[name].append(
                        (cpu, memory, pids, network_rx, network_tx, block_read, block_write)
                    )
        except (OSError, csv.Error, ValueError) as exc:
            errors.append(f"{path}: {exc}")

    rows = []
    io_rows = []
    for name, values in sorted(samples.items()):
        cpu_values = [sample[0] for sample in values]
        memory_values = [sample[1] for sample in values]
        pid_values = [sample[2] for sample in values]
        rows.append(
            [
                _short(name, 28),
                str(len(values)),
                f"{sum(cpu_values) / len(cpu_values):.2f}%",
                f"{max(cpu_values):.2f}%",
                _format_mib(max(memory_values)),
                str(max(pid_values)),
            ]
        )
        io_rows.append(
            [
                _short(name, 28),
                _human_bytes(int(max(sample[3] for sample in values))),
                _human_bytes(int(max(sample[4] for sample in values))),
                _human_bytes(int(max(sample[5] for sample in values))),
                _human_bytes(int(max(sample[6] for sample in values))),
            ]
        )
    return rows, io_rows, errors


def _latest_metadata(summary_paths: list[Path]) -> tuple[str | None, dict[str, Any] | None]:
    for summary_path in reversed(summary_paths):
        metadata_path = summary_path.with_name("metadata.json")
        if not metadata_path.exists():
            continue
        try:
            return summary_path.parent.name, _read_json(metadata_path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return None, None


def render_summary(root: Path, *, limit: int = 0) -> str:
    summary_paths = sorted(root.glob("*/summary.json"))
    csv_paths = sorted(root.glob("resources-*.csv"))
    summaries: list[dict[str, Any]] = []
    read_errors: list[str] = []
    for path in summary_paths:
        try:
            summaries.append(_read_json(path))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            read_errors.append(f"{path}: {exc}")

    http_runs = [summary for summary in summaries if "latency_ms" in summary]
    kafka_runs = [summary for summary in summaries if summary.get("scenario") == "kafka-raw-producer"]
    if limit > 0:
        http_runs = http_runs[-limit:]
        kafka_runs = kafka_runs[-limit:]

    lines = ["ATLASCORE BENCHMARK SUMMARY", "=" * 132]
    result_counts = {
        result: sum(_result(summary) == result for summary in summaries)
        for result in ("PASS", "PASS_WITH_WARNINGS", "FAIL")
    }
    provider_counts: dict[str, int] = defaultdict(int)
    for summary in summaries:
        provider_counts[_provider(summary)] += 1
    provider_text = ", ".join(
        f"{provider}={count}" for provider, count in sorted(provider_counts.items())
    ) or "none"
    lines.extend(
        [
            f"Artifacts: {root}",
            (
                f"Runs: {len(summaries)} total | {len(http_runs)} HTTP/Eventing shown | "
                f"{len(kafka_runs)} Kafka shown | {result_counts['PASS']} PASS | "
                f"{result_counts['PASS_WITH_WARNINGS']} WARN | {result_counts['FAIL']} FAIL"
            ),
            f"Providers: {provider_text}",
            (
                f"Files: {len(summary_paths)} summary.json | "
                f"{len(list(root.glob('*/report.md')))} report.md | "
                f"{len(list(root.glob('*/kafka-producer.txt')))} Kafka logs | "
                f"{len(csv_paths)} resource CSV"
            ),
        ]
    )

    metadata_run, metadata = _latest_metadata(summary_paths)
    if metadata:
        memory_bytes = _integer(metadata.get("memory_bytes"))
        runtime = metadata.get("runtime") or {}
        runtime_text = ", ".join(f"{key}={value}" for key, value in sorted(runtime.items())) or "not captured"
        lines.extend(
            [
                "",
                "LATEST ENVIRONMENT",
                "-" * 132,
                f"Run: {metadata_run}",
                (
                    f"Git: {metadata.get('git_commit') or '-'} | Python: {metadata.get('python') or '-'} | "
                    f"CPUs: {metadata.get('logical_cpus') or '-'} | RAM: {_human_bytes(memory_bytes)}"
                ),
                f"Runtime: {runtime_text}",
            ]
        )

    lines.extend(["", "HTTP AND EVENTING RUNS", "-" * 132])
    if http_runs:
        rows = []
        for summary in http_runs:
            config = summary.get("configuration") or {}
            latency = summary.get("latency_ms") or {}
            rows.append(
                [
                    _timestamp(str(summary.get("run_id", "-"))),
                    _short(_provider(summary), 8),
                    _short(summary.get("name") or summary.get("scenario"), 18),
                    _short(summary.get("profile"), 18),
                    _result(summary),
                    str(_integer(summary.get("completed_requests"))),
                    str(_integer(config.get("concurrency"))),
                    str(_integer(config.get("warmup", config.get("requests")))),
                    f"{_number(summary.get('throughput_rps')):.2f}",
                    f"{_number(latency.get('p50')):.2f}",
                    f"{_number(latency.get('p95')):.2f}",
                    f"{_number(latency.get('p99')):.2f}",
                    str(_integer(summary.get("failed_requests"))),
                    f"{_number(summary.get('duration_seconds')):.2f}",
                ]
            )
        lines.extend(
            _table(
                [
                    "UTC",
                    "PROVIDER",
                    "SCENARIO",
                    "PROFILE",
                    "RESULT",
                    "REQ",
                    "C",
                    "WARM/REQ",
                    "RPS",
                    "P50",
                    "P95",
                    "P99",
                    "ERR",
                    "SEC",
                ],
                rows,
                {5, 6, 7, 8, 9, 10, 11, 12, 13},
            )
        )
    else:
        lines.append("No HTTP/Eventing summaries found.")

    eventing_runs = [summary for summary in http_runs if summary.get("scenario") == "eventing"]
    if eventing_runs:
        lines.extend(["", "EVENTING INTEGRITY", "-" * 132])
        rows = []
        for summary in eventing_runs:
            integrity = summary.get("integrity") or {}
            rows.append(
                [
                    _timestamp(str(summary.get("run_id", "-"))),
                    str(_integer(summary.get("successful_requests"))),
                    str(_integer(integrity.get("persisted_event_delta"))),
                    "YES" if integrity.get("accepted_events_accounted_for") else "NO",
                ]
            )
        lines.extend(_table(["UTC", "ACCEPTED", "PERSISTED", "ACCOUNTED"], rows, {1, 2}))

    lines.extend(["", "KAFKA RAW PRODUCER RUNS", "-" * 132])
    if kafka_runs:
        rows = []
        for summary in kafka_runs:
            config = summary.get("configuration") or {}
            producer = summary.get("producer") or {}
            rows.append(
                [
                    _timestamp(str(summary.get("run_id", "-"))),
                    _result(summary),
                    str(_integer(config.get("partitions"))),
                    _human_bytes(_integer(config.get("record_size"))),
                    str(_integer(config.get("records"))),
                    f"{_number(producer.get('records_per_second')):.2f}",
                    f"{_number(producer.get('megabytes_per_second')):.2f}",
                    f"{_number(producer.get('average_latency_ms')):.2f}",
                    f"{_number(producer.get('max_latency_ms')):.2f}",
                    f"{_number(summary.get('duration_seconds')):.2f}",
                ]
            )
        lines.extend(
            _table(
                ["UTC", "RESULT", "PART", "SIZE", "RECORDS", "REC/S", "MB/S", "AVG MS", "MAX MS", "SEC"],
                rows,
                {2, 4, 5, 6, 7, 8, 9},
            )
        )
    else:
        lines.append("No Kafka summaries found.")

    resource_rows, resource_io_rows, resource_errors = _resource_rows(csv_paths)
    lines.extend(["", "CONTAINER RESOURCE PEAKS", "-" * 132])
    if resource_rows:
        lines.extend(
            _table(
                ["CONTAINER", "SAMPLES", "AVG CPU", "PEAK CPU", "PEAK RAM", "MAX PIDS"],
                resource_rows,
                {1, 2, 3, 4, 5},
            )
        )
        lines.append(f"Source: {len(csv_paths)} resource CSV file(s), aggregated by container.")
    else:
        lines.append("No resource CSV samples found.")

    if resource_io_rows:
        lines.extend(["", "CONTAINER I/O MAX COUNTERS", "-" * 132])
        lines.extend(
            _table(
                ["CONTAINER", "NET RX", "NET TX", "BLOCK READ", "BLOCK WRITE"],
                resource_io_rows,
                {1, 2, 3, 4},
            )
        )
        lines.append("Docker I/O counters are cumulative maxima, not per-second rates.")

    noteworthy = [
        summary
        for summary in http_runs
        if _result(summary) != "PASS"
    ]
    lines.extend(["", "FAILURES AND WARNINGS", "-" * 132])
    if not noteworthy and not read_errors and not resource_errors:
        lines.append("No failures, request errors or unreadable artifacts in the displayed runs.")
    for summary in noteworthy:
        status_counts = json.dumps(summary.get("status_counts") or {}, sort_keys=True)
        errors = summary.get("error_samples") or []
        sample = _short(errors[0] if errors else "threshold not met", 100)
        lines.append(
            f"- {summary.get('run_id')}: failed={_integer(summary.get('failed_requests'))}; "
            f"statuses={status_counts}; sample={sample}"
        )
    for error in [*read_errors, *resource_errors]:
        lines.append(f"- unreadable artifact: {error}")

    lines.extend(
        [
            "",
            "NOTES",
            "-" * 132,
            "- HTTP latency values are milliseconds. Kafka throughput is the raw producer baseline.",
            "- Provider identifies the native Atlas runner or the optional k6 adapter.",
            "- PASS_WITH_WARNINGS means configured thresholds passed but requests, checks or iterations warned.",
            "- Resource peaks aggregate every resources-*.csv file; they are not attributed to one run.",
            "- Use BENCHMARK_LIMIT=20 to show only the latest 20 HTTP/Eventing and Kafka runs.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize AtlasCore benchmark artifacts in the terminal.")
    parser.add_argument("--root", default=".artifacts/benchmarks")
    parser.add_argument("--limit", type=int, default=0, help="latest runs per category; 0 shows all")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    if args.limit < 0:
        raise SystemExit("limit cannot be negative")
    print(render_summary(root, limit=args.limit), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
