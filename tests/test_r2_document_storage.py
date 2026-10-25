from io import BytesIO
from hashlib import sha256

import pytest
from botocore.exceptions import ClientError

from core_api.modules.document.storage import DocumentDecryptionError, R2DocumentStorage


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}
        self.lock_deletes = False

    def put_object(self, *, Bucket, Key, Body, ContentType, IfNoneMatch=None, Metadata=None):
        assert ContentType == "application/octet-stream"
        if IfNoneMatch == "*" and (Bucket, Key) in self.objects:
            raise ClientError(
                {
                    "Error": {"Code": "PreconditionFailed", "Message": "exists"},
                    "ResponseMetadata": {"HTTPStatusCode": 412},
                },
                "PutObject",
            )
        self.objects[(Bucket, Key)] = Body
        self.metadata[(Bucket, Key)] = Metadata or {}

    def get_object(self, *, Bucket, Key):
        try:
            content = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            ) from exc
        return {"Body": BytesIO(content)}

    def delete_object(self, *, Bucket, Key):
        if self.lock_deletes:
            raise ClientError(
                {
                    "Error": {"Code": "AccessDenied", "Message": "retained"},
                    "ResponseMetadata": {"HTTPStatusCode": 403},
                },
                "DeleteObject",
            )
        self.objects.pop((Bucket, Key), None)


def storage(*, encryption_key: str = "test-document-encryption-key-with-32-bytes") -> R2DocumentStorage:
    return R2DocumentStorage(
        endpoint="https://account.r2.cloudflarestorage.com",
        access_key_id="key-id",
        secret_access_key="secret",
        bucket="rubrica-documents",
        encryption_key=encryption_key,
        client=FakeS3Client(),
    )


def test_r2_storage_round_trip_and_discard_uncommitted() -> None:
    target = storage()
    digest = "a" * 64
    key, size = target.put(
        BytesIO(b"%PDF-content"), filename="contract.pdf", sha256=digest
    )

    assert size == 12
    assert target.get(key).read() == b"%PDF-content"
    assert target.client.metadata[(target.bucket, key)] == {
        "rubrica-encryption": "aes-256-gcm-v1",
        "rubrica-sha256": digest,
    }
    assert not target.client.objects[(target.bucket, key)].startswith(b"%PDF")

    target.discard_uncommitted(key)
    with pytest.raises(FileNotFoundError):
        target.get(key)


def test_r2_storage_uses_tenant_and_account_scope() -> None:
    target = storage()
    scope = "tenants/tenant123/accounts/account456/documents/document789/versions"

    key, _ = target.put(BytesIO(b"pdf"), filename="contract.pdf", scope=scope)

    assert key.startswith(f"{scope}/")
    assert target.get(key).read() == b"pdf"
    assert (target.bucket, key) in target.client.objects


def test_r2_storage_rejects_non_opaque_key() -> None:
    with pytest.raises(FileNotFoundError):
        storage().get("../document")

    with pytest.raises(FileNotFoundError):
        storage().get("tenants//accounts/account/files/file")


def test_r2_storage_can_preserve_key_during_migration() -> None:
    target = storage()
    assert target.put_existing("existing123", BytesIO(b"pdf")) == 3
    assert target.get("existing123").read() == b"pdf"


def test_r2_storage_never_overwrites_an_existing_key() -> None:
    target = storage()
    target.put_existing("existing123", BytesIO(b"original"))

    with pytest.raises(FileExistsError):
        target.put_existing("existing123", BytesIO(b"replacement"))

    assert target.get("existing123").read() == b"original"


def test_locked_orphan_cleanup_is_safe() -> None:
    target = storage()
    target.put_existing("orphan123", BytesIO(b"pdf"))
    target.client.lock_deletes = True

    target.discard_uncommitted("orphan123")

    assert target.get("orphan123").read() == b"pdf"


def test_r2_storage_rejects_tampered_ciphertext() -> None:
    target = storage()
    key, _ = target.put(BytesIO(b"%PDF-secret"), filename="secret.pdf")
    raw = target.client.objects[(target.bucket, key)]
    target.client.objects[(target.bucket, key)] = raw[:-1] + bytes([raw[-1] ^ 1])

    with pytest.raises(DocumentDecryptionError, match="authentication failed"):
        target.get(key)


def test_r2_storage_rejects_a_different_application_key() -> None:
    client = FakeS3Client()
    writer = R2DocumentStorage(
        endpoint="https://account.r2.cloudflarestorage.com",
        access_key_id="key-id",
        secret_access_key="secret",
        bucket="rubrica-documents",
        encryption_key="first-document-encryption-key-with-32-bytes",
        client=client,
    )
    reader = R2DocumentStorage(
        endpoint="https://account.r2.cloudflarestorage.com",
        access_key_id="key-id",
        secret_access_key="secret",
        bucket="rubrica-documents",
        encryption_key="second-document-encryption-key-with-32-bytes",
        client=client,
    )
    key, _ = writer.put(BytesIO(b"%PDF-secret"), filename="secret.pdf")

    with pytest.raises(DocumentDecryptionError):
        reader.get(key)


def test_legacy_plaintext_requires_explicit_migration_window() -> None:
    client = FakeS3Client()
    client.objects[("rubrica-documents", "legacy123")] = b"%PDF-legacy"
    compatible = R2DocumentStorage(
        endpoint="https://account.r2.cloudflarestorage.com",
        access_key_id="key-id",
        secret_access_key="secret",
        bucket="rubrica-documents",
        encryption_key="test-document-encryption-key-with-32-bytes",
        allow_legacy_plaintext=True,
        client=client,
    )
    strict = R2DocumentStorage(
        endpoint="https://account.r2.cloudflarestorage.com",
        access_key_id="key-id",
        secret_access_key="secret",
        bucket="rubrica-documents",
        encryption_key="test-document-encryption-key-with-32-bytes",
        allow_legacy_plaintext=False,
        client=client,
    )

    assert compatible.get("legacy123").read() == b"%PDF-legacy"
    with pytest.raises(DocumentDecryptionError, match="disabled"):
        strict.get("legacy123")


def test_legacy_object_migration_is_verified_and_idempotent() -> None:
    target = storage()
    plaintext = b"%PDF-legacy"
    digest = sha256(plaintext).hexdigest()
    target.client.objects[(target.bucket, "legacy123")] = plaintext

    assert target.migrate_legacy_object(
        "legacy123", expected_sha256=digest, apply=False
    ) == "legacy"
    assert target.client.objects[(target.bucket, "legacy123")] == plaintext
    assert target.migrate_legacy_object(
        "legacy123", expected_sha256=digest, apply=True
    ) == "migrated"
    assert not target.client.objects[(target.bucket, "legacy123")].startswith(b"%PDF")
    assert target.get("legacy123").read() == plaintext
    assert target.migrate_legacy_object(
        "legacy123", expected_sha256=digest, apply=True
    ) == "encrypted"
