"""Clone database-referenced production objects into the isolated staging bucket.

The source is strictly read-only in this process. Dry-run is the default, object
keys are never printed, and existing destination objects are never overwritten.
Run this only after restoring the production Core database into staging.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.document.document_entity import DocumentVersionEntity
from core_api.modules.signature_request.signature_request_entity import SignatureEntity


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

    checked = copied = existing = missing = bytes_total = 0
    missing_versions = missing_artifacts = 0
    references = _references()
    for storage_key in sorted(references):
        _, kinds = references[storage_key]
        source_key = f"{source_prefix}/{storage_key}" if source_prefix else storage_key
        destination_key = (
            f"{destination_prefix}/{storage_key}" if destination_prefix else storage_key
        )
        checked += 1
        try:
            source_head = source.head_object(Bucket=source_bucket, Key=source_key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"NoSuchKey", "404", "NotFound"} or status == 404:
                missing += 1
                missing_versions += int("document_version" in kinds)
                missing_artifacts += int("signed_artifact" in kinds)
                continue
            raise
        size = int(source_head["ContentLength"])
        bytes_total += size
        if not _missing(destination, bucket=destination_bucket, key=destination_key):
            existing += 1
            continue
        if not args.apply:
            continue
        response = source.get_object(Bucket=source_bucket, Key=source_key)
        try:
            destination.put_object(
                Bucket=destination_bucket,
                Key=destination_key,
                Body=response["Body"],
                ContentLength=size,
                ContentType=source_head.get("ContentType", "application/octet-stream"),
                Metadata=source_head.get("Metadata", {}),
                IfNoneMatch="*",
            )
        finally:
            response["Body"].close()
        copied_head = destination.head_object(Bucket=destination_bucket, Key=destination_key)
        if int(copied_head["ContentLength"]) != size:
            raise SystemExit("Destination object size differs after copy")
        copied += 1

    mode = "apply" if args.apply else "dry-run"
    print(
        f"[ok] mode={mode}; referenced={checked}; copied={copied}; "
        f"already_present={existing}; missing_source={missing}; "
        f"missing_document_versions={missing_versions}; "
        f"missing_signed_artifacts={missing_artifacts}; bytes={bytes_total}"
    )
    if missing:
        raise SystemExit("Referenced source objects are missing; clone is incomplete")


if __name__ == "__main__":
    main()
