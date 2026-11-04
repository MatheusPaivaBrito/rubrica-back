from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, select

from observability_api.infrastructure.database.connection import SessionLocal
from observability_api.infrastructure.settings import settings
from observability_api.modules.enterprise_usage.entity import EnterpriseUsageRecord
from shared_kernel.enterprise_usage import EnterpriseUsageFact
from shared_kernel.security.service_tokens import verify_service_token


def require_core(x_rubrica_service: str = Header(default=""), x_rubrica_service_key: str = Header(default="")):
    if (x_rubrica_service != "core_api" or not settings.OBSERVABILITY_INTERNAL_SERVICE_KEY
            or not verify_service_token(x_rubrica_service_key, settings.OBSERVABILITY_INTERNAL_SERVICE_KEY)):
        raise HTTPException(403, "Invalid internal service credentials")


router = APIRouter(prefix="/internal/observability/enterprise", dependencies=[Depends(require_core)], include_in_schema=False)


class UsageBatch(BaseModel):
    events: list[EnterpriseUsageFact] = Field(min_length=1, max_length=100)


def ingest(db, facts):
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    for fact in facts:
        if fact.environment != settings.ENVIRONMENT:
            raise HTTPException(403, "Usage environment mismatch")
        if fact.billable and (fact.sandbox or fact.kind != "signature.completed"):
            raise HTTPException(422, "Invalid billable usage")
        data = fact.model_dump(exclude={"schema_version", "source_id", "currency", "price_version"})
        db.execute(insert(EnterpriseUsageRecord).values(**data, checksum=fact.checksum(),
            payload=fact.model_dump(mode="json")).on_conflict_do_nothing(index_elements=["id"]))
        checksum = db.scalar(select(EnterpriseUsageRecord.checksum).where(EnterpriseUsageRecord.id == fact.id))
        if checksum != fact.checksum():
            raise HTTPException(409, "Usage event already exists with different content")
    return {"accepted": [str(fact.id) for fact in facts]}


@router.post("/events")
def receive_batch(payload: UsageBatch):
    with SessionLocal.begin() as db:
        return ingest(db, payload.events)


def summary(db, *, tenant_id, integration_id, sandbox, compartment_id=None):
    record = EnterpriseUsageRecord
    start = datetime.now(UTC) - timedelta(days=30)
    filters = [record.tenant_id == tenant_id, record.integration_id == integration_id,
               record.sandbox == sandbox, record.environment == settings.ENVIRONMENT, record.occurred_at >= start]
    if compartment_id is not None:
        filters.append(record.compartment_id == compartment_id)
    columns = [
        func.coalesce(func.sum(case((record.kind == "signature.completed", record.units), else_=0)), 0).label("signatures"),
        func.coalesce(func.sum(case((record.billable.is_(True), record.units), else_=0)), 0).label("billable_signatures"),
        func.coalesce(func.sum(case((record.kind == "document.uploaded", record.bytes_count), else_=0)), 0).label("uploaded_bytes"),
        func.coalesce(func.sum(case((record.kind.in_(["download.completed", "download.partial"]), record.bytes_count), else_=0)), 0).label("downloaded_bytes"),
        func.coalesce(func.sum(case((record.kind == "api.request", record.units), else_=0)), 0).label("requests"),
        func.coalesce(func.sum(case((and_(record.kind == "api.request", record.status_code >= 400), record.units), else_=0)), 0).label("errors"),
        func.coalesce(func.sum(case((record.status_code == 429, record.units), else_=0)), 0).label("rate_limited"),
        func.avg(case((record.kind == "api.request", record.duration_ms), else_=None)).label("average_duration_ms"),
        func.coalesce(func.sum(record.amount_minor), 0).label("amount_minor"),
    ]
    totals = dict(db.execute(select(*columns).where(*filters)).mappings().one())
    tokens = [dict(row) for row in db.execute(select(record.token_public_id, *columns).where(*filters)
        .group_by(record.token_public_id).order_by(record.token_public_id).limit(100)).mappings()]
    return {"source": "observability_projection", "window_start": start, "sandbox": sandbox,
            "totals": totals, "tokens": tokens, "token_list_limit": 100, "currency": "BRL"}


@router.get("/summary")
def get_summary(tenant_id: UUID, integration_id: UUID, sandbox: bool, compartment_id: UUID | None = None):
    with SessionLocal() as db:
        return summary(db, tenant_id=tenant_id, integration_id=integration_id, sandbox=sandbox, compartment_id=compartment_id)
