from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError


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
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def put(self, stream: BinaryIO, *, filename: str) -> tuple[str, int]:
        del filename
        key = uuid4().hex
        destination = self.root / key
        size = 0
        destination.touch(mode=0o600, exist_ok=False)
        with destination.open("wb") as output:
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


class R2DocumentStorage(DocumentStorage):
    """Private Cloudflare R2 storage accessed through its S3-compatible API."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        prefix: str = "documents",
        client=None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client or boto3.client(
            "s3",
            endpoint_url=endpoint.rstrip("/"),
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    def put(self, stream: BinaryIO, *, filename: str) -> tuple[str, int]:
        del filename
        storage_key = uuid4().hex
        return storage_key, self.put_existing(storage_key, stream)

    def put_existing(self, storage_key: str, stream: BinaryIO) -> int:
        """Store a known opaque key. Reserved for the one-time local migration."""
        self._validate_key(storage_key)
        content = stream.read()
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._object_key(storage_key),
            Body=content,
            ContentType="application/pdf",
        )
        return len(content)

    def get(self, storage_key: str) -> BinaryIO:
        self._validate_key(storage_key)
        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=self._object_key(storage_key),
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise FileNotFoundError(storage_key) from exc
            raise
        from io import BytesIO

        return BytesIO(response["Body"].read())

    def delete(self, storage_key: str) -> None:
        self._validate_key(storage_key)
        self.client.delete_object(Bucket=self.bucket, Key=self._object_key(storage_key))

    def _object_key(self, storage_key: str) -> str:
        return f"{self.prefix}/{storage_key}" if self.prefix else storage_key

    @staticmethod
    def _validate_key(storage_key: str) -> None:
        if not storage_key.isalnum():
            raise FileNotFoundError(storage_key)


def configured_document_storage(settings) -> DocumentStorage:
    if settings.DOCUMENT_STORAGE_PROVIDER == "r2":
        return R2DocumentStorage(
            endpoint=settings.R2_DOCUMENTS_ENDPOINT,
            access_key_id=settings.R2_DOCUMENTS_ACCESS_KEY_ID,
            secret_access_key=settings.R2_DOCUMENTS_SECRET_ACCESS_KEY,
            bucket=settings.R2_DOCUMENTS_BUCKET,
            prefix=settings.R2_DOCUMENTS_PREFIX,
        )
    return LocalDocumentStorage(Path(settings.DOCUMENT_STORAGE_PATH))
