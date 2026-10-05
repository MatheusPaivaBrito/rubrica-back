"""Apply current SERPRO timestamps to existing signed PDF artifacts.

Dry-run is the default. Existing artifacts are retained, and rows that already
contain trusted timestamp metadata are skipped, making the operation resumable.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.signature_request.serpro_timestamp_service import (
    apply_serpro_timestamp,
    timestamp_enabled,
)
from core_api.modules.signature_request.signature_request_entity import (
    AuditEventEntity,
    SignatureEntity,
)
from shared_kernel.time.datetime_service import DateTimeService


def _pending_signature_ids() -> list:
    with SessionLocal() as database:
        return list(
            database.scalars(
                select(SignatureEntity.id)
                .where(
                    SignatureEntity.artifact_storage_key.is_not(None),
                    SignatureEntity.artifact_sha256.is_not(None),
                    SignatureEntity.trusted_timestamp_json.is_(None),
                )
                .order_by(SignatureEntity.signed_at, SignatureEntity.id)
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply current SERPRO timestamps to existing signed artifacts."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--actor", default="system:serpro-timestamp-backfill")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be zero or greater")
    if args.apply and not timestamp_enabled():
        raise SystemExit("SERPRO timestamp is not configured")

    identifiers = _pending_signature_ids()
    if args.limit:
        identifiers = identifiers[: args.limit]
    print(f"[plan] pending={len(identifiers)} apply={args.apply} limit={args.limit or 'all'}")
    if not args.apply:
        return

    storage = configured_document_storage(settings)
    completed = 0
    for signature_id in identifiers:
        with SessionLocal() as database:
            signature = database.get(SignatureEntity, signature_id)
            if (
                signature is None
                or signature.trusted_timestamp_json is not None
                or not signature.artifact_storage_key
                or not signature.artifact_sha256
            ):
                continue
            source_key = signature.artifact_storage_key
            expected_digest = signature.artifact_sha256
            request_id = signature.signature_request_id

        with storage.get(source_key) as source:
            original = source.read()
        if sha256(original).hexdigest() != expected_digest:
            raise SystemExit(f"SHA-256 mismatch before timestamp: {signature_id}")

        stamped, timestamp_metadata = apply_serpro_timestamp(original)
        if timestamp_metadata is None:
            raise SystemExit("SERPRO did not produce timestamp metadata")
        stamped_digest = sha256(stamped).hexdigest()
        scope = source_key.rsplit("/", 1)[0] if "/" in source_key else None
        new_key, _ = storage.put(
            BytesIO(stamped),
            filename=f"rubrica-{request_id}-timestamped.pdf",
            sha256=stamped_digest,
            scope=scope,
        )
        with storage.get(new_key) as uploaded:
            if sha256(uploaded.read()).hexdigest() != stamped_digest:
                storage.discard_uncommitted(new_key)
                raise SystemExit(f"SHA-256 mismatch after timestamp: {signature_id}")

        try:
            with SessionLocal.begin() as database:
                signature = database.scalar(
                    select(SignatureEntity)
                    .where(SignatureEntity.id == signature_id)
                    .with_for_update()
                )
                if signature is None:
                    raise RuntimeError(f"Signature disappeared: {signature_id}")
                if signature.trusted_timestamp_json is not None:
                    storage.discard_uncommitted(new_key)
                    continue
                if (
                    signature.artifact_storage_key != source_key
                    or signature.artifact_sha256 != expected_digest
                ):
                    raise RuntimeError(f"Signature artifact changed: {signature_id}")
                signature.artifact_storage_key = new_key
                signature.artifact_sha256 = stamped_digest
                signature.trusted_timestamp_json = timestamp_metadata | {
                    "backfilled": True,
                    "original_signed_at": signature.signed_at.isoformat(),
                    "previous_artifact_sha256": expected_digest,
                }
                database.add(
                    AuditEventEntity(
                        signature_request_id=request_id,
                        occurred_at=DateTimeService.utc_now(),
                        actor_type="system",
                        actor_id=args.actor,
                        action="signature.timestamp_backfilled",
                        entity_type="signature",
                        entity_id=signature.id,
                        correlation_id=uuid4(),
                        metadata_sanitized={
                            "provider": "serpro-api-timestamp",
                            "previous_artifact_sha256": expected_digest,
                            "artifact_sha256": stamped_digest,
                        },
                    )
                )
        except Exception:
            storage.discard_uncommitted(new_key)
            raise
        completed += 1
        print(f"[ok] completed={completed}/{len(identifiers)} signature={signature_id}")

    print(f"[done] timestamped={completed} old_artifacts_retained=True")


if __name__ == "__main__":
    main()
