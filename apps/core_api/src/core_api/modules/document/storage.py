from __future__ import annotations

from abc import ABC, abstractmethod
from base64 import b64decode, b64encode
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import struct
from tempfile import SpooledTemporaryFile
from time import perf_counter
from typing import BinaryIO, Literal
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from prometheus_client import Histogram


_ENCRYPTED_DOCUMENT_MAGIC_V1 = b"RUBRICA-DOC\x00\x01"
_ENCRYPTED_DOCUMENT_MAGIC_V2 = b"RUBRICA-DOC\x00\x02"
_AES_GCM_NONCE_BYTES = 12
_AES_GCM_TAG_BYTES = 16
_DEFAULT_ENCRYPTION_CHUNK_BYTES = 4 * 1024 * 1024
_MAX_ENCRYPTION_HEADER_BYTES = 16 * 1024
_SPOOL_MEMORY_BYTES = 8 * 1024 * 1024
_LENGTH = struct.Struct(">I")
_SCOPED_STORAGE_KEY = re.compile(
    r"^tenants/(?P<tenant>[A-Za-z0-9_-]+)/accounts/[A-Za-z0-9_-]+/"
    r"documents/(?P<document>[A-Za-z0-9_-]+)/(?:versions|signed-artifacts)/[A-Za-z0-9_-]+$"
)
_STORAGE_STAGE_DURATION = Histogram(
    "rubrica_document_storage_stage_duration_seconds",
    "Time spent in each low-cardinality document storage stage",
    ("operation", "stage"),
)


class DocumentDecryptionError(OSError):
    """Stored object is not authentic for the configured application key."""


def _read_exact(stream: BinaryIO, length: int) -> bytes:
    parts: list[bytes] = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise DocumentDecryptionError("Stored document is truncated")
        parts.append(chunk)
        remaining -= len(chunk)
    return b"".join(parts)


class _PrefixedReader(io.RawIOBase):
    """Restore bytes consumed while identifying a legacy plaintext object."""

    def __init__(self, prefix: bytes, source: BinaryIO) -> None:
        self._prefix = io.BytesIO(prefix)
        self._source = source

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        view = memoryview(buffer)
        first = self._prefix.read(len(view))
        view[:len(first)] = first
        if len(first) == len(view):
            return len(first)
        second = self._source.read(len(view) - len(first)) or b""
        view[len(first):len(first) + len(second)] = second
        return len(first) + len(second)

    def close(self) -> None:
        try:
            self._source.close()
        finally:
            super().close()


class _ObservedReader:
    """Measure R2 body transfer separately without exposing object identifiers."""

    def __init__(self, source: BinaryIO) -> None:
        self._source = source

    def read(self, size: int = -1) -> bytes:
        started = perf_counter()
        try:
            return self._source.read(size)
        finally:
            _STORAGE_STAGE_DURATION.labels(operation="read", stage="r2_transfer").observe(
                perf_counter() - started
            )

    def close(self) -> None:
        self._source.close()


class _ChunkDecryptReader(io.RawIOBase):
    """Incrementally authenticate and decrypt the v2 object format."""

    def __init__(
        self,
        *,
        source: BinaryIO,
        dek: bytes,
        storage_key: str,
        header_digest: bytes,
        chunk_size: int,
    ) -> None:
        self._source = source
        self._cipher = AESGCM(dek)
        self._storage_key = storage_key.encode("utf-8")
        self._header_digest = header_digest
        self._chunk_size = chunk_size
        self._chunk_index = 0
        self._buffer = bytearray()
        self._terminal_seen = False

    def readable(self) -> bool:
        return True

    def _aad(self, plaintext_length: int) -> bytes:
        return b"\x00".join(
            (
                b"rubrica-object-chunk-v2",
                self._storage_key,
                self._header_digest,
                self._chunk_index.to_bytes(8, "big"),
                plaintext_length.to_bytes(4, "big"),
            )
        )

    def _next_chunk(self) -> bytes:
        if self._terminal_seen:
            return b""
        encoded_length = self._source.read(_LENGTH.size)
        if not encoded_length:
            raise DocumentDecryptionError("Stored document has no authenticated terminator")
        if len(encoded_length) != _LENGTH.size:
            raise DocumentDecryptionError("Stored document is truncated")
        plaintext_length = _LENGTH.unpack(encoded_length)[0]
        if plaintext_length > self._chunk_size:
            raise DocumentDecryptionError("Stored document chunk exceeds its declared limit")
        nonce = _read_exact(self._source, _AES_GCM_NONCE_BYTES)
        ciphertext = _read_exact(self._source, plaintext_length + _AES_GCM_TAG_BYTES)
        try:
            started = perf_counter()
            plaintext = self._cipher.decrypt(nonce, ciphertext, self._aad(plaintext_length))
        except (InvalidTag, ValueError) as exc:
            raise DocumentDecryptionError("Stored document authentication failed") from exc
        finally:
            _STORAGE_STAGE_DURATION.labels(operation="read", stage="decrypt").observe(
                perf_counter() - started
            )
        self._chunk_index += 1
        if plaintext_length == 0:
            self._terminal_seen = True
            if self._source.read(1):
                raise DocumentDecryptionError("Stored document contains trailing bytes")
            return b""
        return plaintext

    def readinto(self, buffer) -> int:
        view = memoryview(buffer)
        while len(self._buffer) < len(view) and not self._terminal_seen:
            self._buffer.extend(self._next_chunk())
        length = min(len(view), len(self._buffer))
        view[:length] = self._buffer[:length]
        del self._buffer[:length]
        return length

    def close(self) -> None:
        try:
            self._source.close()
        finally:
            self._buffer.clear()
            super().close()


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
        encryption_key: str = "",
        allow_legacy_plaintext: bool = True,
        encryption_chunk_bytes: int = _DEFAULT_ENCRYPTION_CHUNK_BYTES,
        client=None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._root_key = sha256(encryption_key.encode("utf-8")).digest()
        self._allow_legacy_plaintext = allow_legacy_plaintext
        if encryption_chunk_bytes < 64 * 1024 or encryption_chunk_bytes > 16 * 1024 * 1024:
            raise ValueError("Document encryption chunk size must be between 64 KiB and 16 MiB")
        self._encryption_chunk_bytes = encryption_chunk_bytes
        self.client = client or boto3.client(
            "s3",
            endpoint_url=endpoint.rstrip("/"),
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    def _encrypt_v1(self, storage_key: str, plaintext: bytes) -> bytes:
        nonce = os.urandom(_AES_GCM_NONCE_BYTES)
        return _ENCRYPTED_DOCUMENT_MAGIC_V1 + nonce + AESGCM(self._root_key).encrypt(
            nonce,
            plaintext,
            storage_key.encode("utf-8"),
        )

    def _decrypt_v1(self, storage_key: str, content: bytes) -> bytes:
        offset = len(_ENCRYPTED_DOCUMENT_MAGIC_V1)
        nonce = content[offset:offset + _AES_GCM_NONCE_BYTES]
        ciphertext = content[offset + _AES_GCM_NONCE_BYTES:]
        try:
            return AESGCM(self._root_key).decrypt(
                nonce,
                ciphertext,
                storage_key.encode("utf-8"),
            )
        except (InvalidTag, ValueError) as exc:
            raise DocumentDecryptionError("Stored document authentication failed") from exc

    @staticmethod
    def _contexts(storage_key: str) -> tuple[str, str]:
        match = _SCOPED_STORAGE_KEY.fullmatch(storage_key)
        if match:
            return match.group("tenant"), match.group("document")
        # Historical unscoped objects remain isolated from every scoped tenant.
        return "legacy-unscoped", sha256(storage_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _derive(parent_key: bytes, *, purpose: bytes, context: str) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"rubrica-document-storage-v2",
            info=purpose + b"\x00" + context.encode("utf-8"),
        ).derive(parent_key)

    def _document_kek(self, storage_key: str) -> bytes:
        tenant_context, document_context = self._contexts(storage_key)
        tenant_key = self._derive(
            self._root_key,
            purpose=b"tenant-kek",
            context=tenant_context,
        )
        return self._derive(
            tenant_key,
            purpose=b"document-kek",
            context=document_context,
        )

    @staticmethod
    def _wrap_aad(storage_key: str) -> bytes:
        return b"rubrica-object-dek-v2\x00" + storage_key.encode("utf-8")

    def _encrypt_stream(self, storage_key: str, source: BinaryIO, destination: BinaryIO) -> int:
        dek = os.urandom(32)
        wrap_nonce = os.urandom(_AES_GCM_NONCE_BYTES)
        wrapped_dek = AESGCM(self._document_kek(storage_key)).encrypt(
            wrap_nonce,
            dek,
            self._wrap_aad(storage_key),
        )
        header = json.dumps(
            {
                "algorithm": "AES-256-GCM-CHUNKED",
                "chunk_size": self._encryption_chunk_bytes,
                "key_version": 1,
                "wrap_nonce": b64encode(wrap_nonce).decode("ascii"),
                "wrapped_dek": b64encode(wrapped_dek).decode("ascii"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(header) > _MAX_ENCRYPTION_HEADER_BYTES:
            raise ValueError("Document encryption header is too large")
        destination.write(_ENCRYPTED_DOCUMENT_MAGIC_V2)
        destination.write(_LENGTH.pack(len(header)))
        destination.write(header)
        header_digest = sha256(header).digest()
        cipher = AESGCM(dek)
        total = 0
        index = 0
        while chunk := source.read(self._encryption_chunk_bytes):
            total += len(chunk)
            nonce = os.urandom(_AES_GCM_NONCE_BYTES)
            aad = self._chunk_aad(storage_key, header_digest, index, len(chunk))
            destination.write(_LENGTH.pack(len(chunk)))
            destination.write(nonce)
            started = perf_counter()
            try:
                ciphertext = cipher.encrypt(nonce, chunk, aad)
            finally:
                _STORAGE_STAGE_DURATION.labels(operation="write", stage="encrypt").observe(
                    perf_counter() - started
                )
            destination.write(ciphertext)
            index += 1
        nonce = os.urandom(_AES_GCM_NONCE_BYTES)
        destination.write(_LENGTH.pack(0))
        destination.write(nonce)
        destination.write(cipher.encrypt(nonce, b"", self._chunk_aad(storage_key, header_digest, index, 0)))
        return total

    @staticmethod
    def _chunk_aad(
        storage_key: str,
        header_digest: bytes,
        index: int,
        plaintext_length: int,
    ) -> bytes:
        return b"\x00".join(
            (
                b"rubrica-object-chunk-v2",
                storage_key.encode("utf-8"),
                header_digest,
                index.to_bytes(8, "big"),
                plaintext_length.to_bytes(4, "big"),
            )
        )

    def _open_v2(self, storage_key: str, source: BinaryIO) -> BinaryIO:
        header_length = _LENGTH.unpack(_read_exact(source, _LENGTH.size))[0]
        if not 1 <= header_length <= _MAX_ENCRYPTION_HEADER_BYTES:
            raise DocumentDecryptionError("Stored document has an invalid encryption header")
        header_bytes = _read_exact(source, header_length)
        try:
            header = json.loads(header_bytes)
            if header.get("algorithm") != "AES-256-GCM-CHUNKED" or header.get("key_version") != 1:
                raise ValueError
            chunk_size = int(header["chunk_size"])
            if chunk_size < 64 * 1024 or chunk_size > 16 * 1024 * 1024:
                raise ValueError
            wrap_nonce = b64decode(header["wrap_nonce"], validate=True)
            wrapped_dek = b64decode(header["wrapped_dek"], validate=True)
            if len(wrap_nonce) != _AES_GCM_NONCE_BYTES:
                raise ValueError
            dek = AESGCM(self._document_kek(storage_key)).decrypt(
                wrap_nonce,
                wrapped_dek,
                self._wrap_aad(storage_key),
            )
        except (
            AttributeError,
            InvalidTag,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise DocumentDecryptionError("Stored document encryption header is invalid") from exc
        return io.BufferedReader(
            _ChunkDecryptReader(
                source=source,
                dek=dek,
                storage_key=storage_key,
                header_digest=sha256(header_bytes).digest(),
                chunk_size=chunk_size,
            ),
            buffer_size=min(chunk_size, 1024 * 1024),
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
        with SpooledTemporaryFile(max_size=_SPOOL_MEMORY_BYTES, mode="w+b") as encrypted:
            plaintext_size = self._encrypt_stream(storage_key, stream, encrypted)
            encrypted.seek(0)
            request = {
                "Bucket": self.bucket,
                "Key": self._object_key(storage_key),
                "Body": encrypted,
                "ContentType": "application/octet-stream",
                "IfNoneMatch": "*",
                "Metadata": {"rubrica-encryption": "aes-256-gcm-chunked-v2"},
            }
            if sha256:
                request["Metadata"]["rubrica-sha256"] = sha256
            try:
                started = perf_counter()
                try:
                    self.client.put_object(**request)
                finally:
                    _STORAGE_STAGE_DURATION.labels(
                        operation="write",
                        stage="r2_upload",
                    ).observe(perf_counter() - started)
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if code in {"PreconditionFailed", "412"} or status == 412:
                    raise FileExistsError(storage_key) from exc
                raise
        return plaintext_size

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
        source = _ObservedReader(response["Body"])
        magic = source.read(len(_ENCRYPTED_DOCUMENT_MAGIC_V2))
        if magic == _ENCRYPTED_DOCUMENT_MAGIC_V2:
            return self._open_v2(storage_key, source)
        if magic == _ENCRYPTED_DOCUMENT_MAGIC_V1:
            content = magic + source.read()
            source.close()
            return io.BytesIO(self._decrypt_v1(storage_key, content))
        if self._allow_legacy_plaintext:
            return io.BufferedReader(_PrefixedReader(magic, source))
        source.close()
        raise DocumentDecryptionError("Legacy plaintext document storage is disabled")

    def migrate_legacy_object(
        self,
        storage_key: str,
        *,
        expected_sha256: str,
        apply: bool = False,
    ) -> Literal["encrypted", "legacy", "migrated"]:
        """Verify one referenced object and optionally encrypt a legacy plaintext value."""
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
        raw = response["Body"]
        magic = raw.read(len(_ENCRYPTED_DOCUMENT_MAGIC_V2))
        already_v2 = magic == _ENCRYPTED_DOCUMENT_MAGIC_V2
        raw.close()
        digest = sha256()
        with self.get(storage_key) as current:
            with SpooledTemporaryFile(max_size=_SPOOL_MEMORY_BYTES, mode="w+b") as plaintext:
                while chunk := current.read(self._encryption_chunk_bytes):
                    digest.update(chunk)
                    plaintext.write(chunk)
                if digest.hexdigest() != expected_sha256:
                    raise DocumentDecryptionError(
                        "Stored document digest does not match the database"
                    )
                if already_v2:
                    return "encrypted"
                if not apply:
                    return "legacy"
                plaintext.seek(0)
                with SpooledTemporaryFile(max_size=_SPOOL_MEMORY_BYTES, mode="w+b") as encrypted:
                    self._encrypt_stream(storage_key, plaintext, encrypted)
                    encrypted.seek(0)
                    self.client.put_object(
                        Bucket=self.bucket,
                        Key=self._object_key(storage_key),
                        Body=encrypted,
                        ContentType="application/octet-stream",
                        Metadata={
                            "rubrica-encryption": "aes-256-gcm-chunked-v2",
                            "rubrica-sha256": expected_sha256,
                        },
                    )
        with self.get(storage_key) as migrated:
            verified = sha256()
            while chunk := migrated.read(self._encryption_chunk_bytes):
                verified.update(chunk)
            if verified.hexdigest() != expected_sha256:
                raise DocumentDecryptionError("Stored document verification failed after migration")
        return "migrated"

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
            encryption_key=settings.DOCUMENT_STORAGE_ENCRYPTION_KEY,
            allow_legacy_plaintext=settings.DOCUMENT_STORAGE_ALLOW_LEGACY_PLAINTEXT,
            encryption_chunk_bytes=settings.DOCUMENT_STORAGE_ENCRYPTION_CHUNK_BYTES,
        )
    return LocalDocumentStorage(Path(settings.DOCUMENT_STORAGE_PATH))
