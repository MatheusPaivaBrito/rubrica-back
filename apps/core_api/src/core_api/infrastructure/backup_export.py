from __future__ import annotations

import io
import json
import sys
import tarfile
from hashlib import sha256

from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.document.document_entity import DocumentVersionEntity
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.signature_request.signature_request_entity import SignatureEntity


def referenced_objects() -> dict[str, str]:
    objects: dict[str, str] = {}
    with SessionLocal() as database:
        for key, digest in database.execute(
            select(DocumentVersionEntity.storage_key, DocumentVersionEntity.sha256)
        ):
            objects[key] = digest
        for key, digest in database.execute(
            select(SignatureEntity.artifact_storage_key, SignatureEntity.artifact_sha256).where(
                SignatureEntity.artifact_storage_key.is_not(None)
            )
        ):
            if key and digest:
                objects[key] = digest
    return objects


def main() -> None:
    storage = configured_document_storage(settings)
    manifest: list[dict[str, object]] = []
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
        for key, expected_digest in sorted(referenced_objects().items()):
            with storage.get(key) as source:
                content = source.read()
            actual_digest = sha256(content).hexdigest()
            if actual_digest != expected_digest:
                raise RuntimeError(f"Stored object integrity check failed: {key}")
            info = tarfile.TarInfo(f"objects/{key}")
            info.size = len(content)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(content))
            manifest.append({"storage_key": key, "sha256": actual_digest, "size": len(content)})

        manifest_content = json.dumps(
            {"provider": settings.DOCUMENT_STORAGE_PROVIDER, "objects": manifest},
            ensure_ascii=True,
            sort_keys=True,
        ).encode("utf-8")
        manifest_info = tarfile.TarInfo("manifest.json")
        manifest_info.size = len(manifest_content)
        manifest_info.mode = 0o600
        archive.addfile(manifest_info, io.BytesIO(manifest_content))


if __name__ == "__main__":
    main()
