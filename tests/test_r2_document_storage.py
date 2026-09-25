from io import BytesIO

import pytest
from botocore.exceptions import ClientError

from core_api.modules.document.storage import R2DocumentStorage


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket, Key, Body, ContentType):
        assert ContentType == "application/pdf"
        self.objects[(Bucket, Key)] = Body

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
        self.objects.pop((Bucket, Key), None)


def storage() -> R2DocumentStorage:
    return R2DocumentStorage(
        endpoint="https://account.r2.cloudflarestorage.com",
        access_key_id="key-id",
        secret_access_key="secret",
        bucket="rubrica-documents",
        client=FakeS3Client(),
    )


def test_r2_storage_round_trip_and_delete() -> None:
    target = storage()
    key, size = target.put(BytesIO(b"%PDF-content"), filename="contract.pdf")

    assert size == 12
    assert target.get(key).read() == b"%PDF-content"

    target.delete(key)
    with pytest.raises(FileNotFoundError):
        target.get(key)


def test_r2_storage_rejects_non_opaque_key() -> None:
    with pytest.raises(FileNotFoundError):
        storage().get("../document")


def test_r2_storage_can_preserve_key_during_migration() -> None:
    target = storage()
    assert target.put_existing("existing123", BytesIO(b"pdf")) == 3
    assert target.get("existing123").read() == b"pdf"
