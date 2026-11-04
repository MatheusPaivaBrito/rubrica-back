"""Only the trusted backup worker can attest destructive repository compaction."""
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.enterprise.completion_entity import EnterpriseClosure
from core_api.modules.enterprise.entities import EnterpriseIntegration
from core_api.modules.enterprise.lifecycle import utc
from shared_kernel.security.service_tokens import verify_service_token


def require_backup_worker(x_rubrica_service: str = Header(default=""), x_rubrica_service_key: str = Header(default="")):
    if (x_rubrica_service != "retention_worker" or not settings.CORE_INTERNAL_SERVICE_KEY
            or not verify_service_token(x_rubrica_service_key, settings.CORE_INTERNAL_SERVICE_KEY)):
        raise HTTPException(403, "Backup worker authentication failed")


router = APIRouter(prefix="/internal/enterprise/backup-retention", include_in_schema=False,
                   dependencies=[Depends(require_backup_worker)])


def repositories():
    return {value.strip() for value in settings.ENTERPRISE_BACKUP_REPOSITORIES.split(",") if value.strip()}


@router.get("/pending")
def pending():
    with SessionLocal() as db:
        rows = db.scalars(select(EnterpriseClosure).where(EnterpriseClosure.metadata_purged_at.is_not(None),
            EnterpriseClosure.backups_verified_at.is_(None), EnterpriseClosure.tenant_id.in_(
                select(EnterpriseIntegration.tenant_id).where(EnterpriseIntegration.environment == settings.ENVIRONMENT)))
            .order_by(EnterpriseClosure.metadata_purged_at).limit(100))
        return {"environment": settings.ENVIRONMENT, "repository_identities": sorted(repositories()),
                "closures": [{"closure_id": row.id, "barrier": utc(row.metadata_purged_at)} for row in rows]}


class BackupReceipt(BaseModel):
    environment: str
    repository_identity: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot_started_at: datetime
    oldest_retained_snapshot_at: datetime
    compacted_and_checked: bool
    local_archives_removed: bool
    current_objects_verified: bool

    @field_validator("snapshot_started_at", "oldest_retained_snapshot_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone-aware backup timestamp required")
        return utc(value)


def acknowledge(db, row, payload, *, now=None):
    now = now or datetime.now(UTC)
    if payload.environment != settings.ENVIRONMENT or payload.repository_identity not in repositories():
        raise HTTPException(403, "Backup inventory binding mismatch")
    if not (row.metadata_purged_at and row.objects_verified_at and payload.compacted_and_checked and payload.local_archives_removed and payload.current_objects_verified):
        raise HTTPException(409, "Physical and local archive removal must be verified")
    if min(payload.snapshot_started_at, payload.oldest_retained_snapshot_at) < utc(row.metadata_purged_at):
        raise HTTPException(409, "Pre-erasure backup copies remain")
    if max(payload.snapshot_started_at, payload.oldest_retained_snapshot_at) > now:
        raise HTTPException(422, "Backup proof cannot be in the future")
    receipts = dict((row.backup_receipt or {}).get("repositories", {}))
    receipts[payload.repository_identity] = payload.model_dump(mode="json")
    row.backup_receipt = {"repositories": receipts}
    if repositories() and repositories() <= receipts.keys():
        row.backups_verified_at = now
    return {"closure_id": row.id, "complete": row.backups_verified_at is not None}


@router.post("/{closure_id}/acknowledge")
def acknowledge_receipt(closure_id: UUID, payload: BackupReceipt):
    with SessionLocal.begin() as db:
        row = db.scalar(select(EnterpriseClosure).where(EnterpriseClosure.id == closure_id,
            EnterpriseClosure.tenant_id.in_(select(EnterpriseIntegration.tenant_id).where(
                EnterpriseIntegration.environment == settings.ENVIRONMENT))).with_for_update())
        if row is None:
            raise HTTPException(404, "Closure not found")
        return acknowledge(db, row, payload)
