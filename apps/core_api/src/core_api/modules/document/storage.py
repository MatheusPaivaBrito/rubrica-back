from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4


class DocumentStorage(ABC):
    @abstractmethod
    def put(self, stream: BinaryIO, *, filename: str) -> tuple[str, int]: ...

    @abstractmethod
    def get(self, storage_key: str) -> BinaryIO: ...

    @abstractmethod
    def delete(self, storage_key: str) -> None: ...


class LocalDocumentStorage(DocumentStorage):
    """Development backend. Keys are opaque and paths never derive from user input."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, stream: BinaryIO, *, filename: str) -> tuple[str, int]:
        del filename
        key = uuid4().hex
        destination = self.root / key
        size = 0
        with destination.open("xb") as output:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                output.write(chunk)
        return key, size

    def get(self, storage_key: str) -> BinaryIO:
        if not storage_key.isalnum():
            raise FileNotFoundError(storage_key)
        return (self.root / storage_key).open("rb")

    def delete(self, storage_key: str) -> None:
        if storage_key.isalnum():
            (self.root / storage_key).unlink(missing_ok=True)
