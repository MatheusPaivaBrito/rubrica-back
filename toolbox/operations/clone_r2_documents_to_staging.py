"""Clone database-referenced production objects into the isolated staging bucket.

The source is strictly read-only in this process. Dry-run is the default, object
keys are never printed, and existing destination objects are never overwritten.
Run this only after restoring the production Core database into staging.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.document.document_entity import DocumentEntity, DocumentVersionEntity
from core_api.modules.signature_request.signature_request_entity import (
    SignatureEntity,
    SignatureRequestEntity,
)


def _secret(path: str) -> str:
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise SystemExit("A required R2 secret file is empty")
    return value


def _references() -> dict[str, tuple[str, frozenset[str]]]:
    with SessionLocal() as database:
        versions = database.execute(
            select(DocumentVersionEntity.storage_key, DocumentVersionEntity.sha256).distinct()
        ).all()
        signatures = database.execute(
            select(SignatureEntity.artifact_storage_key, SignatureEntity.artifact_sha256).where(
                SignatureEntity.artifact_storage_key.is_not(None)
            )
        ).all()
    references: dict[str, tuple[str, set[str]]] = {
        key: (digest, {"document_version"}) for key, digest in versions
    }
    for key, digest in signatures:
        if not key or not digest:
            continue
        previous = references.get(key)
        if previous is not None and previous[0] != digest:
            raise SystemExit("Conflicting digests exist for a referenced object")
        kinds = previous[1] if previous is not None else set()
        kinds.add("signed_artifact")
        references[key] = (digest, kinds)
    return {
        key: (digest, frozenset(kinds))
        for key, (digest, kinds) in references.items()
    }


def _document_version_context() -> dict[str, tuple[bool, bool, bool]]:
    """Return active/current/requested flags without exposing document metadata."""
    with SessionLocal() as database:
        versions = database.execute(
            select(
                DocumentVersionEntity.storage_key,
                DocumentVersionEntity.document_id,
                DocumentVersionEntity.version,
                DocumentEntity.deleted_at,
                DocumentEntity.version,
            ).join(DocumentEntity, DocumentEntity.id == DocumentVersionEntity.document_id)
        ).all()
        requested_versions = set(
            database.execute(
                select(
                    SignatureRequestEntity.document_id,
                    SignatureRequestEntity.document_version,
                ).distinct()
            ).all()
        )
    return {
        storage_key: (
            deleted_at is None,
            version == current_version,
            (document_id, version) in requested_versions,
        )
        for storage_key, document_id, version, deleted_at, current_version in versions
    }


def _client(endpoint: str, access_key_id: str, secret_access_key: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint.rstrip("/"),
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )


def _missing(client, *, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return False
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"NoSuchKey", "404", "NotFound"} or status == 404:
            return True
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clone referenced R2 documents into an isolated staging bucket"
    )
    parser.add_argument("--source-endpoint-file", required=True)
    parser.add_argument("--source-access-key-id-file", required=True)
    parser.add_argument("--source-secret-access-key-file", required=True)
    parser.add_argument("--source-bucket-file", required=True)
    parser.add_argument("--destination-endpoint-file", required=True)
    parser.add_argument("--destination-access-key-id-file", required=True)
    parser.add_argument("--destination-secret-access-key-file", required=True)
    parser.add_argument("--destination-bucket-file", required=True)
    parser.add_argument("--source-prefix", default="")
    parser.add_argument("--destination-prefix", default="")
    parser.add_argument("--legacy-root")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source_endpoint = _secret(args.source_endpoint_file)
    source_bucket = _secret(args.source_bucket_file)
    destination_endpoint = _secret(args.destination_endpoint_file)
    destination_bucket = _secret(args.destination_bucket_file)
    if (source_endpoint, source_bucket) == (destination_endpoint, destination_bucket):
        raise SystemExit("Source and destination R2 buckets must be different")
    if "staging" not in destination_bucket.lower():
        raise SystemExit("Destination bucket must be explicitly identified as staging")

    source = _client(
        source_endpoint,
        _secret(args.source_access_key_id_file),
        _secret(args.source_secret_access_key_file),
    )
    destination = _client(
        destination_endpoint,
        _secret(args.destination_access_key_id_file),
        _secret(args.destination_secret_access_key_file),
    )
    source_prefix = args.source_prefix.strip("/")
    destination_prefix = args.destination_prefix.strip("/")

    legacy_root = Path(args.legacy_root).resolve() if args.legacy_root else None
    checked = copied = existing = missing = recoverable_legacy = bytes_total = 0
    missing_versions = missing_artifacts = 0
    missing_active = missing_deleted = missing_current = missing_historical = 0
    missing_requested = missing_unrequested = 0
    references = _references()
    version_context = _document_version_context()
    for storage_key in sorted(references):
        expected_digest, kinds = references[storage_key]
        source_key = f"{source_prefix}/{storage_key}" if source_prefix else storage_key
        destination_key = (
            f"{destination_prefix}/{storage_key}" if destination_prefix else storage_key
        )
        checked += 1
        source_body = None
        source_metadata: dict[str, str] = {}
        source_content_type = "application/octet-stream"
        legacy_path: Path | None = None
        try:
            source_head = source.head_object(Bucket=source_bucket, Key=source_key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"NoSuchKey", "404", "NotFound"} or status == 404:
                if legacy_root is not None:
                    candidate = (legacy_root / storage_key).resolve()
                    if legacy_root in candidate.parents and candidate.is_file():
                        candidate_digest = sha256()
                        with candidate.open("rb") as legacy_source:
                            while chunk := legacy_source.read(1024 * 1024):
                                candidate_digest.update(chunk)
                        if candidate_digest.hexdigest() == expected_digest:
                            legacy_path = candidate
                            recoverable_legacy += 1
                if legacy_path is None:
                    missing += 1
                    missing_versions += int("document_version" in kinds)
                    missing_artifacts += int("signed_artifact" in kinds)
                    if "document_version" in kinds:
                        active, current, requested = version_context[storage_key]
                        missing_active += int(active)
                        missing_deleted += int(not active)
                        missing_current += int(current)
                        missing_historical += int(not current)
                        missing_requested += int(requested)
                        missing_unrequested += int(not requested)
                    continue
            else:
                raise
        if legacy_path is not None:
            size = legacy_path.stat().st_size
            source_content_type = "application/pdf"
        else:
            size = int(source_head["ContentLength"])
            source_content_type = source_head.get(
                "ContentType",
                "application/octet-stream",
            )
            source_metadata = source_head.get("Metadata", {})
        bytes_total += size
        if not _missing(destination, bucket=destination_bucket, key=destination_key):
            existing += 1
            continue
        if not args.apply:
            continue
        if legacy_path is not None:
            source_body = legacy_path.open("rb")
        else:
            response = source.get_object(Bucket=source_bucket, Key=source_key)
            source_body = response["Body"]
        try:
            destination.put_object(
                Bucket=destination_bucket,
                Key=destination_key,
                Body=source_body,
                ContentLength=size,
                ContentType=source_content_type,
                Metadata=source_metadata,
                IfNoneMatch="*",
            )
        finally:
            source_body.close()
        copied_head = destination.head_object(Bucket=destination_bucket, Key=destination_key)
        if int(copied_head["ContentLength"]) != size:
            raise SystemExit("Destination object size differs after copy")
        copied += 1

    mode = "apply" if args.apply else "dry-run"
    print(
        f"[ok] mode={mode}; referenced={checked}; copied={copied}; "
        f"already_present={existing}; missing_source={missing}; "
        f"recoverable_legacy={recoverable_legacy}; "
        f"missing_document_versions={missing_versions}; "
        f"missing_signed_artifacts={missing_artifacts}; bytes={bytes_total}"
    )
    if missing_versions:
        print(
            "[detail] missing versions: "
            f"active={missing_active}; deleted={missing_deleted}; "
            f"current={missing_current}; historical={missing_historical}; "
            f"used_by_requests={missing_requested}; unused={missing_unrequested}"
        )
    if missing:
        raise SystemExit("Referenced source objects are missing; clone is incomplete")


if __name__ == "__main__":
    main()
