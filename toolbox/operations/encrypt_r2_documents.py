"""Verify and encrypt every R2 object referenced by the application database.

Dry-run is the default. Existing encrypted objects are authenticated and legacy
plaintext objects are only overwritten when ``--apply`` is explicitly supplied.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.document.document_entity import DocumentVersionEntity
from core_api.modules.document.storage import R2DocumentStorage, configured_document_storage
from core_api.modules.signature_request.signature_request_entity import SignatureEntity


def _referenced_objects() -> dict[str, str]:
    with SessionLocal() as database:
        document_rows = database.execute(
            select(DocumentVersionEntity.storage_key, DocumentVersionEntity.sha256).distinct()
        ).all()
        signature_rows = database.execute(
            select(SignatureEntity.artifact_storage_key, SignatureEntity.artifact_sha256).where(
                SignatureEntity.artifact_storage_key.is_not(None)
            )
        ).all()
    objects = {key: digest for key, digest in document_rows}
    for key, digest in signature_rows:
        if not key or not digest:
            continue
        existing = objects.get(key)
        if existing is not None and existing != digest:
            raise SystemExit(f"Conflicting SHA-256 values for storage key: {key}")
        objects[key] = digest
    return objects


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Encrypt database-referenced R2 documents with AES-256-GCM"
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    storage = configured_document_storage(settings)
    if not isinstance(storage, R2DocumentStorage):
        raise SystemExit("DOCUMENT_STORAGE_PROVIDER must be r2")

    checked = migrated = legacy = encrypted = 0
    for storage_key, digest in sorted(_referenced_objects().items()):
        state = storage.migrate_legacy_object(
            storage_key,
            expected_sha256=digest,
            apply=args.apply,
        )
        checked += 1
        migrated += int(state == "migrated")
        legacy += int(state == "legacy")
        encrypted += int(state == "encrypted")

    print(
        f"[ok] {checked} referenced objects verified; "
        f"{encrypted} already encrypted; {legacy} legacy plaintext; {migrated} migrated"
    )


if __name__ == "__main__":
    main()
