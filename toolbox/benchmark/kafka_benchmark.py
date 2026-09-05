from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

try:
    from .common import RunArtifacts, environment_metadata, utc_run_id
except ImportError:  # pragma: no cover - direct script execution
    from common import RunArtifacts, environment_metadata, utc_run_id


PRODUCER_RESULT = re.compile(
    r"(?P<records>\d+) records sent, (?P<records_per_second>[\d.]+) records/sec "
    r"\((?P<megabytes_per_second>[\d.]+) MB/sec\), (?P<average_latency_ms>[\d.]+) ms avg latency, "
    r"(?P<max_latency_ms>[\d.]+) ms max latency"
)


def run_kafka_benchmark(
    *,
    compose_service: str,
    bootstrap_server: str,
    records: int,
    record_size: int,
    partitions: int,
    topic: str,
    keep_topic: bool,
    output_root: Path,
    run_id: str,
) -> dict[str, Any]:
    artifacts = RunArtifacts(output_root, run_id)
    artifacts.prepare()
    _run(
        compose_service,
        [
            "/opt/kafka/bin/kafka-topics.sh",
            "--bootstrap-server",
            bootstrap_server,
            "--create",
            "--if-not-exists",
            "--topic",
            topic,
            "--partitions",
            str(partitions),
            "--replication-factor",
            "1",
        ],
    )
    started = time.perf_counter()
    producer = _run(
        compose_service,
        [
            "/opt/kafka/bin/kafka-producer-perf-test.sh",
            "--topic",
            topic,
            "--num-records",
            str(records),
            "--record-size",
            str(record_size),
            "--throughput",
            "-1",
            "--producer-props",
            f"bootstrap.servers={bootstrap_server}",
            "acks=all",
        ],
    )
    elapsed = time.perf_counter() - started
    combined_output = "\n".join(part for part in (producer.stdout, producer.stderr) if part).strip()
    parsed = parse_producer_output(combined_output)
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "passed": producer.returncode == 0 and parsed.get("records") == records,
        "scenario": "kafka-raw-producer",
        "topic": topic,
        "configuration": {
            "records": records,
            "record_size": record_size,
            "partitions": partitions,
            "replication_factor": 1,
            "acks": "all",
            "bootstrap_server": bootstrap_server,
        },
        "duration_seconds": round(elapsed, 6),
        "producer": parsed,
    }
    artifacts.write_json("metadata.json", environment_metadata())
    artifacts.write_json("summary.json", summary)
    artifacts.write_text("kafka-producer.txt", combined_output)
    artifacts.write_text("report.md", render_report(summary))

    if not keep_topic:
        _run(
            compose_service,
            [
                "/opt/kafka/bin/kafka-topics.sh",
                "--bootstrap-server",
                bootstrap_server,
                "--delete",
                "--topic",
                topic,
            ],
            check=False,
        )
    return summary


def parse_producer_output(output: str) -> dict[str, int | float | str]:
    matches = list(PRODUCER_RESULT.finditer(output))
    if not matches:
        return {"raw_result": output.splitlines()[-1] if output else ""}
    values = matches[-1].groupdict()
    return {
        "records": int(values["records"]),
        "records_per_second": float(values["records_per_second"]),
        "megabytes_per_second": float(values["megabytes_per_second"]),
        "average_latency_ms": float(values["average_latency_ms"]),
        "max_latency_ms": float(values["max_latency_ms"]),
    }


def render_report(summary: dict[str, Any]) -> str:
    producer = summary["producer"]
    return f"""# Kafka Benchmark Report

- Run: `{summary['run_id']}`
- Result: `{'PASS' if summary['passed'] else 'FAIL'}`
- Topic: `{summary['topic']}`
- Records: `{summary['configuration']['records']}`
- Record size: `{summary['configuration']['record_size']} bytes`
- Partitions: `{summary['configuration']['partitions']}`
- Acknowledgements: `{summary['configuration']['acks']}`
- Records/s: `{producer.get('records_per_second', 'unparsed')}`
- MB/s: `{producer.get('megabytes_per_second', 'unparsed')}`
- Average latency: `{producer.get('average_latency_ms', 'unparsed')} ms`
- Maximum latency: `{producer.get('max_latency_ms', 'unparsed')} ms`

This is the raw broker producer baseline. It does not measure Eventing HTTP,
Postgres outbox persistence or consumer processing.
"""


def _run(service: str, command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "exec", "-T", service, *command],
        check=check,
        capture_output=True,
        text=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Kafka's raw producer performance baseline.")
    parser.add_argument("--compose-service", default="kafka")
    parser.add_argument("--bootstrap-server", default="localhost:29092")
    parser.add_argument("--records", type=int, default=50000)
    parser.add_argument("--record-size", type=int, default=1024)
    parser.add_argument("--partitions", type=int, default=3)
    parser.add_argument("--topic")
    parser.add_argument("--keep-topic", action="store_true")
    parser.add_argument("--output-root", default=".artifacts/benchmarks")
    parser.add_argument("--run-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if min(args.records, args.record_size, args.partitions) < 1:
        raise SystemExit("records, record-size and partitions must be at least 1")
    run_id = args.run_id or utc_run_id("kafka-raw")
    topic = args.topic or f"atlas.benchmark.{run_id.lower()}"
    try:
        summary = run_kafka_benchmark(
            compose_service=args.compose_service,
            bootstrap_server=args.bootstrap_server,
            records=args.records,
            record_size=args.record_size,
            partitions=args.partitions,
            topic=topic,
            keep_topic=args.keep_topic,
            output_root=Path(args.output_root),
            run_id=run_id,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Kafka benchmark failed: {exc}") from exc
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
