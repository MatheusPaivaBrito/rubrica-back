"""Measure chunked document encryption independently from R2 network latency."""

from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import shutil
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
import tracemalloc

from core_api.modules.document.storage import R2DocumentStorage


class _MemoryS3:
    def __init__(self) -> None:
        self._temporary = TemporaryDirectory(prefix="rubrica-crypto-benchmark-")
        self.root = Path(self._temporary.name)

    def _path(self, bucket: str, key: str) -> Path:
        return self.root / sha256(f"{bucket}/{key}".encode()).hexdigest()

    def put_object(self, *, Bucket, Key, Body, **_kwargs):
        path = self._path(Bucket, Key)
        source = Body if hasattr(Body, "read") else BytesIO(Body)
        with path.open("wb") as target:
            shutil.copyfileobj(source, target, length=256 * 1024)

    def get_object(self, *, Bucket, Key):
        return {"Body": self._path(Bucket, Key).open("rb")}

    def remove(self, bucket: str, key: str) -> None:
        self._path(bucket, key).unlink(missing_ok=True)


def _sample(size_mib: int) -> bytes:
    pattern = sha256(f"rubrica-benchmark:{size_mib}".encode()).digest()
    size = size_mib * 1024 * 1024
    return (pattern * ((size // len(pattern)) + 1))[:size]


def _measure(callback, repetitions: int) -> tuple[float, float]:
    durations: list[float] = []
    peaks: list[int] = []
    for _ in range(repetitions):
        tracemalloc.start()
        started = perf_counter()
        callback()
        durations.append(perf_counter() - started)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peaks.append(peak)
    return median(durations), max(peaks) / (1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Rubrica document encryption v2")
    parser.add_argument("--sizes-mib", default="1,10,25,50")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--chunk-mib", type=int, default=4)
    args = parser.parse_args()
    sizes = [int(value) for value in args.sizes_mib.split(",") if value]
    client = _MemoryS3()
    storage = R2DocumentStorage(
        endpoint="https://benchmark.invalid",
        access_key_id="benchmark",
        secret_access_key="benchmark",
        bucket="benchmark",
        encryption_key="rubrica-benchmark-root-key-with-at-least-32-bytes",
        encryption_chunk_bytes=args.chunk_mib * 1024 * 1024,
        client=client,
    )

    print("size_mib,operation,median_ms,peak_python_mib,throughput_mib_s")
    for size_mib in sizes:
        content = _sample(size_mib)
        key = (
            "tenants/benchmark/accounts/benchmark/documents/benchmark/versions/"
            f"object-{size_mib}"
        )

        def encrypt() -> None:
            client.remove(storage.bucket, key)
            storage.put_existing(key, BytesIO(content))

        encrypt_seconds, encrypt_peak = _measure(encrypt, args.repetitions)

        def decrypt() -> None:
            with storage.get(key) as stream:
                while stream.read(256 * 1024):
                    pass

        decrypt_seconds, decrypt_peak = _measure(decrypt, args.repetitions)
        for operation, seconds, peak in (
            ("encrypt", encrypt_seconds, encrypt_peak),
            ("decrypt", decrypt_seconds, decrypt_peak),
        ):
            print(
                f"{size_mib},{operation},{seconds * 1000:.2f},{peak:.2f},"
                f"{size_mib / seconds:.2f}"
            )


if __name__ == "__main__":
    main()
