from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import re
from typing import BinaryIO
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError


class DocumentStorage(ABC):
    @abstractmethod
    def put(
        self, stream: BinaryIO, *, filename: str, sha256: str | None = None,
        scope: str | None = None,
    ) -> tuple[str, int]: ...

    @abstractmethod
    def get(self, storage_key: str) -> BinaryIO: ...

    @abstractmethod
    def discard_uncommitted(self, storage_key: str) -> None:
        """Best-effort cleanup for an object whose database transaction failed."""
        ...


class LocalDocumentStorage(DocumentStorage):
    """Development backend. Keys are opaque and paths never derive from user input."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def put(
        self, stream: BinaryIO, *, filename: str, sha256: str | None = None,
        scope: str | None = None,
    ) -> tuple[str, int]:
        del filename, sha256
        key = f"{scope.strip('/')}/{uuid4().hex}" if scope else uuid4().hex
        validate_storage_key(key)
        destination = self.root / key
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        size = 0
        destination.touch(mode=0o600, exist_ok=False)
        with destination.open("wb") as output:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                output.write(chunk)
        destination.chmod(0o400)
        return key, size

    def get(self, storage_key: str) -> BinaryIO:
        validate_storage_key(storage_key)
        return (self.root / storage_key).open("rb")

    def discard_uncommitted(self, storage_key: str) -> None:
        validate_storage_key(storage_key)
        destination = self.root / storage_key
        if destination.exists():
            destination.chmod(0o600)
            destination.unlink()


class R2DocumentStorage(DocumentStorage):
    """Private Cloudflare R2 storage accessed through its S3-compatible API."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        prefix: str = "",
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

    def put(
        self, stream: BinaryIO, *, filename: str, sha256: str | None = None,
        scope: str | None = None,
    ) -> tuple[str, int]:
        del filename
        storage_key = f"{scope.strip('/')}/{uuid4().hex}" if scope else uuid4().hex
        return storage_key, self.put_existing(storage_key, stream, sha256=sha256)

    def put_existing(
        self, storage_key: str, stream: BinaryIO, *, sha256: str | None = None
    ) -> int:
        """Store a known opaque key. Reserved for the one-time local migration."""
        self._validate_key(storage_key)
        content = stream.read()
        request = {
            "Bucket": self.bucket,
            "Key": self._object_key(storage_key),
            "Body": content,
            "ContentType": "application/pdf",
            "IfNoneMatch": "*",
        }
        if sha256:
            request["Metadata"] = {"rubrica-sha256": sha256}
        try:
            self.client.put_object(**request)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"PreconditionFailed", "412"} or status == 412:
                raise FileExistsError(storage_key) from exc
            raise
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

    def discard_uncommitted(self, storage_key: str) -> None:
        self._validate_key(storage_key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._object_key(storage_key))
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"AccessDenied", "InvalidRequest", "403"} or status == 403:
                # Bucket Lock can retain an orphan created before a failed DB commit.
                return
            raise

    def _object_key(self, storage_key: str) -> str:
        return f"{self.prefix}/{storage_key}" if self.prefix else storage_key

    @staticmethod
    def _validate_key(storage_key: str) -> None:
        validate_storage_key(storage_key)


_STORAGE_KEY = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$")


def validate_storage_key(storage_key: str) -> None:
    if len(storage_key) > 240 or not _STORAGE_KEY.fullmatch(storage_key):
        raise FileNotFoundError(storage_key)


def document_version_storage_scope(tenant_id, account_id, document_id) -> str:
    return (
        f"tenants/{tenant_id}/accounts/{account_id}/documents/"
        f"{document_id}/versions"
    )


def signed_artifact_storage_scope(tenant_id, account_id, document_id) -> str:
    return (
        f"tenants/{tenant_id}/accounts/{account_id}/documents/"
        f"{document_id}/signed-artifacts"
    )


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
