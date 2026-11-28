from io import BytesIO
from hashlib import sha256
import os

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
        self.objects[(Bucket, Key)] = Body.read() if hasattr(Body, "read") else Body
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


def storage(
    *,
    encryption_key: str = "test-document-encryption-key-with-32-bytes",
    client=None,
    chunk_size: int = 64 * 1024,
) -> R2DocumentStorage:
    return R2DocumentStorage(
        endpoint="https://account.r2.cloudflarestorage.com",
        access_key_id="key-id",
        secret_access_key="secret",
        bucket="rubrica-documents",
        encryption_key=encryption_key,
        encryption_chunk_bytes=chunk_size,
        client=client or FakeS3Client(),
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
        "rubrica-encryption": "aes-256-gcm-chunked-v2",
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
        target.get(key).read()


def test_r2_storage_streams_multiple_authenticated_chunks() -> None:
    target = storage()
    content = b"%PDF-" + os.urandom(180_000)
    key, size = target.put(BytesIO(content), filename="large.pdf")

    with target.get(key) as stream:
        pieces = []
        while piece := stream.read(8191):
            pieces.append(piece)

    assert size == len(content)
    assert b"".join(pieces) == content


def test_r2_storage_rejects_truncated_object_at_chunk_boundary() -> None:
    target = storage()
    key, _ = target.put(BytesIO(b"%PDF-secret"), filename="secret.pdf")
    raw = target.client.objects[(target.bucket, key)]
    # Remove the authenticated terminal record, not merely bytes inside a chunk.
    target.client.objects[(target.bucket, key)] = raw[:-32]

    with pytest.raises(DocumentDecryptionError, match="truncated|terminator|authentication"):
        target.get(key).read()


def test_r2_storage_binds_ciphertext_to_tenant_and_document_path() -> None:
    client = FakeS3Client()
    target = storage(client=client)
    original = (
        "tenants/tenant-a/accounts/account-a/documents/document-a/versions/object-a"
    )
    moved = "tenants/tenant-b/accounts/account-a/documents/document-a/versions/object-a"
    target.put_existing(original, BytesIO(b"%PDF-secret"))
    client.objects[(target.bucket, moved)] = client.objects[(target.bucket, original)]

    with pytest.raises(DocumentDecryptionError):
        target.get(moved)


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


def test_v1_ciphertext_remains_readable_and_migrates_to_v2() -> None:
    target = storage()
    key = "legacy-v1"
    plaintext = b"%PDF-v1"
    digest = sha256(plaintext).hexdigest()
    target.client.objects[(target.bucket, key)] = target._encrypt_v1(key, plaintext)

    assert target.get(key).read() == plaintext
    assert target.migrate_legacy_object(
        key,
        expected_sha256=digest,
        apply=False,
    ) == "legacy"
    assert target.migrate_legacy_object(
        key,
        expected_sha256=digest,
        apply=True,
    ) == "migrated"
    assert target.client.objects[(target.bucket, key)].startswith(b"RUBRICA-DOC\x00\x02")
    assert target.get(key).read() == plaintext


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


def test_staging_clone_dry_run_and_apply_recover_legacy_then_encrypt(monkeypatch, tmp_path, capsys):

    from toolbox.operations import clone_r2_documents_to_staging as clone
    from toolbox.operations import encrypt_r2_documents as encrypt

    class CloneS3(FakeS3Client):
        def head_object(self, *, Bucket, Key):
            if (Bucket, Key) not in self.objects:
                raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
            return {"ContentLength": len(self.objects[Bucket, Key])}

        def put_object(self, *, Bucket, Key, Body, ContentType, ContentLength=None, **kwargs):
            if ContentType == "application/pdf":
                assert (Bucket, Key) not in self.objects
                content = Body.read()
                assert len(content) == ContentLength
                self.objects[Bucket, Key] = content
            else:
                super().put_object(Bucket=Bucket, Key=Key, Body=Body, ContentType=ContentType, **kwargs)

    source = CloneS3()
    destination = CloneS3()
    remote, legacy = b"%PDF-remote fixture", b"%PDF-legacy fixture"
    source.objects["prod", "original123"] = remote
    (tmp_path / "legacy123").write_bytes(legacy)
    references = {
        "original123": (sha256(remote).hexdigest(), frozenset({"document_version"})),
        "legacy123": (sha256(legacy).hexdigest(), frozenset({"signed_artifact"})),
    }
    arguments = ["clone", "--legacy-root", str(tmp_path)]
    for side, bucket in (("source", "prod"), ("destination", "rubrica-staging")):
        for option, value in (
            ("endpoint", f"https://{side}.test"), ("bucket", bucket),
            ("access-key-id", "fixture"), ("secret-access-key", "fixture"),
        ):
            secret = tmp_path / f"{side}-{option}"
            secret.write_text(value)
            arguments.extend([f"--{side}-{option}-file", str(secret)])

    monkeypatch.setattr(clone, "_client", lambda endpoint, *_: source if "source" in endpoint else destination)
    monkeypatch.setattr(clone, "_references", lambda: references)
    monkeypatch.setattr(clone, "_document_version_context", lambda: {})
    monkeypatch.setattr("sys.argv", arguments)
    clone.main()
    assert not destination.objects
    assert "recoverable_legacy=1" in capsys.readouterr().out

    monkeypatch.setattr("sys.argv", [*arguments, "--apply"])
    clone.main()
    assert "copied=2" in capsys.readouterr().out
    clone.main()
    assert "already_present=2" in capsys.readouterr().out
    assert source.objects == {("prod", "original123"): remote}

    target = storage(client=destination)
    target.bucket = "rubrica-staging"
    monkeypatch.setattr(encrypt, "configured_document_storage", lambda _: target)
    monkeypatch.setattr(encrypt, "_referenced_objects", lambda: {key: result[0] for key, result in references.items()})
    monkeypatch.setattr("sys.argv", ["encrypt"])
    encrypt.main()
    assert "2 legacy plaintext; 0 migrated" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["encrypt", "--apply"])
    encrypt.main()
    assert "2 migrated; 0 missing; 0 invalid" in capsys.readouterr().out
    assert target.get("original123").read() == remote
    assert target.get("legacy123").read() == legacy
    assert all(not value.startswith(b"%PDF") for value in destination.objects.values())
    encrypt.main()
    assert "2 already encrypted; 0 legacy plaintext; 0 migrated" in capsys.readouterr().out


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("already_encrypted", [False, True])
def test_migration_rejects_checksum_mismatch_and_preserves_object(apply, already_encrypted):
    target = storage()
    key = "document123"
    original = b"%PDF-unexpected-document"
    if already_encrypted:
        target.put_existing(key, BytesIO(original))
    else:
        target.client.objects[target.bucket, key] = original

    before = dict(target.client.objects)
    before_metadata = dict(target.client.metadata)
    with pytest.raises(DocumentDecryptionError):
        target.migrate_legacy_object(
            key,
            expected_sha256=sha256(b"%PDF-expected-document").hexdigest(),
            apply=apply,
        )

    assert target.client.objects == before
    assert target.client.metadata == before_metadata
