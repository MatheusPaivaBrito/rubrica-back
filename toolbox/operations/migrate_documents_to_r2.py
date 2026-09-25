from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.document.document_entity import DocumentVersionEntity
from core_api.modules.document.storage import R2DocumentStorage, configured_document_storage


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
        rows = db.execute(
            select(DocumentVersionEntity.storage_key, DocumentVersionEntity.sha256).distinct()
        ).all()

    checked = 0
    copied = 0
    for storage_key, expected_sha256 in rows:
        if not storage_key.isalnum():
            raise SystemExit(f"Invalid storage key in database: {storage_key!r}")
        path = source / storage_key
        if not path.is_file():
            raise SystemExit(f"Missing local object: {storage_key}")
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
