from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.document.document_entity import DocumentVersionEntity
from core_api.modules.document.storage import R2DocumentStorage, configured_document_storage
from core_api.modules.signature_request.signature_request_entity import SignatureEntity


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy local document objects to R2 without deleting the source"
    )
    parser.add_argument("--source", default=settings.DOCUMENT_STORAGE_PATH)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    storage = configured_document_storage(settings)
    if not isinstance(storage, R2DocumentStorage):
        raise SystemExit("DOCUMENT_STORAGE_PROVIDER must be r2")

    source = Path(args.source).resolve()
    with SessionLocal() as db:
        document_rows = db.execute(
            select(DocumentVersionEntity.storage_key, DocumentVersionEntity.sha256).distinct()
        ).all()
        artifact_rows = db.execute(
            select(SignatureEntity.artifact_storage_key, SignatureEntity.artifact_sha256).where(
                SignatureEntity.artifact_storage_key.is_not(None)
            )
        ).all()

    objects = {storage_key: digest for storage_key, digest in document_rows}
    for storage_key, digest in artifact_rows:
        if storage_key and digest:
            existing_digest = objects.get(storage_key)
            if existing_digest is not None and existing_digest != digest:
                raise SystemExit(f"Conflicting SHA-256 for storage key: {storage_key}")
            objects[storage_key] = digest

    checked = 0
    copied = 0
    for storage_key, expected_sha256 in sorted(objects.items()):
        if not storage_key.isalnum():
            raise SystemExit(f"Invalid storage key in database: {storage_key!r}")
        path = source / storage_key
        if not path.is_file():
            try:
                with storage.get(storage_key) as uploaded:
                    remote_sha256 = sha256(uploaded.read()).hexdigest()
            except FileNotFoundError as exc:
                raise SystemExit(f"Object missing locally and in R2: {storage_key}") from exc
            if remote_sha256 != expected_sha256:
                raise SystemExit(f"SHA-256 mismatch in R2: {storage_key}")
            checked += 1
            continue
        content = path.read_bytes()
        actual_sha256 = sha256(content).hexdigest()
        if actual_sha256 != expected_sha256:
            raise SystemExit(f"SHA-256 mismatch before copy: {storage_key}")
        checked += 1
        if not args.apply:
            continue
        with path.open("rb") as local_object:
            storage.put_existing(storage_key, stream=local_object)
        with storage.get(storage_key) as uploaded:
            if sha256(uploaded.read()).hexdigest() != expected_sha256:
                raise SystemExit(f"SHA-256 mismatch after copy: {storage_key}")
        copied += 1

    if args.apply:
        print(f"[ok] {checked} objects checked; {copied} copied and verified")
    else:
        print(f"[ok] {checked} objects checked and ready to copy")


if __name__ == "__main__":
    main()
