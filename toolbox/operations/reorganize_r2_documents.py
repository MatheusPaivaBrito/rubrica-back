"""Move referenced R2 objects into tenant/account prefixes without data loss.

Dry-run is the default. ``--apply`` copies and verifies every destination before
updating database references. Source objects are retained unless
``--delete-source`` is explicitly supplied in a later verified run.
"""

import argparse
from hashlib import sha256
from io import BytesIO
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.document.document_entity import DocumentEntity, DocumentVersionEntity
from core_api.modules.document.storage import R2DocumentStorage, configured_document_storage, document_storage_scope
from core_api.modules.signature_request.signature_request_entity import SignatureEntity, SignatureRequestEntity
from core_api.modules.tenant.tenant_entity import TenantMemberEntity


def _account_id(members, tenant_id, email):
    member = members.get((tenant_id, email.strip().lower()))
    if member is not None and member.auth_user_uuid is not None:
        return member.auth_user_uuid
    return uuid5(NAMESPACE_URL, f"rubrica-account:{email.strip().lower()}")


def _target_key(*, old_key: str, tenant_id, account_id) -> str:
    if old_key.startswith("tenants/"):
        return old_key
    return f"{document_storage_scope(tenant_id, account_id)}/{old_key.rsplit('/', 1)[-1]}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Reorganize R2 documents by tenant and account.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--delete-source", action="store_true")
    args = parser.parse_args()
    if args.delete_source and not args.apply:
        parser.error("--delete-source requires --apply")

    storage = configured_document_storage(settings)
    if not isinstance(storage, R2DocumentStorage):
        raise SystemExit("DOCUMENT_STORAGE_PROVIDER must be r2")

    copied: list[tuple[str, str]] = []
    cleanup_candidates: dict[str, tuple[str, str]] = {}
    with SessionLocal.begin() as database:
        members = {
            (member.tenant_id, member.auth_user_id.lower()): member
            for member in database.scalars(
                select(TenantMemberEntity).where(TenantMemberEntity.deleted_at.is_(None))
            )
        }
        documents = {item.id: item for item in database.scalars(select(DocumentEntity))}
        versions = list(database.scalars(select(DocumentVersionEntity)))
        requests = {
            item.id: item for item in database.scalars(select(SignatureRequestEntity))
        }
        signatures = list(
            database.scalars(
                select(SignatureEntity).where(SignatureEntity.artifact_storage_key.is_not(None))
            )
        )

        references: list[tuple[object, str, str, str]] = []
        for version in versions:
            document = documents[version.document_id]
            target = _target_key(
                old_key=version.storage_key,
                tenant_id=document.tenant_id,
                account_id=_account_id(
                    members, document.tenant_id, version.created_by or document.created_by
                ),
            )
            references.append((version, "storage_key", version.sha256, target))
        for signature in signatures:
            request = requests[signature.signature_request_id]
            document = documents[request.document_id]
            target = _target_key(
                old_key=signature.artifact_storage_key,
                tenant_id=document.tenant_id,
                account_id=_account_id(members, document.tenant_id, document.created_by),
            )
            references.append((signature, "artifact_storage_key", signature.artifact_sha256, target))

        current_keys = {getattr(entity, field) for entity, field, _digest, _target in references}
        for _entity, _field, digest, target in references:
            if not target.startswith("tenants/"):
                continue
            legacy_key = target.rsplit("/", 1)[-1]
            if legacy_key not in current_keys:
                cleanup_candidates[legacy_key] = (target, digest)

        moves: dict[str, tuple[str, str]] = {}
        for entity, field, expected_digest, target in references:
            source = getattr(entity, field)
            if source == target:
                continue
            previous = moves.get(source)
            if previous is not None and previous != (target, expected_digest):
                raise RuntimeError(f"Conflicting destination for {source}")
            moves[source] = (target, expected_digest)

        print(f"[plan] objects={len(moves)} apply={args.apply} delete_source={args.delete_source}")
        if not args.apply:
            database.rollback()
            return

        for source, (target, expected_digest) in sorted(moves.items()):
            with storage.get(source) as current:
                content = current.read()
            if sha256(content).hexdigest() != expected_digest:
                raise RuntimeError(f"SHA-256 mismatch at source: {source}")
            try:
                storage.put_existing(target, BytesIO(content), sha256=expected_digest)
            except FileExistsError:
                pass
            with storage.get(target) as destination:
                if sha256(destination.read()).hexdigest() != expected_digest:
                    raise RuntimeError(f"SHA-256 mismatch at destination: {target}")
            copied.append((source, target))

        for entity, field, _digest, target in references:
            old_key = getattr(entity, field)
            if old_key != target:
                setattr(entity, field, target)
                if field == "storage_key" and isinstance(entity, DocumentVersionEntity):
                    document = documents[entity.document_id]
                    if document.storage_key == old_key:
                        document.storage_key = target

    if args.delete_source:
        for source, (target, expected_digest) in sorted(cleanup_candidates.items()):
            with storage.get(target) as destination:
                if sha256(destination.read()).hexdigest() != expected_digest:
                    raise RuntimeError(f"SHA-256 mismatch before source cleanup: {target}")
            storage.discard_uncommitted(source)
    print(
        f"[ok] copied={len(copied)} database_updated=True "
        f"sources_deleted={len(cleanup_candidates) if args.delete_source else 0}"
    )


if __name__ == "__main__":
    main()
