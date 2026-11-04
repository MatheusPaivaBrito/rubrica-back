from typing import Literal
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.enterprise.entities import EnterpriseProvider
from core_api.modules.enterprise.provider_vault import encrypt_configuration
from core_api.modules.enterprise.router import require_enterprise
from core_api.modules.tenant.tenant_service import tenant_service

router = APIRouter(prefix="/enterprise/tenants/{tenant_id}/providers", tags=["enterprise providers"])


class TimestampConfiguration(BaseModel):
    consumer_key: SecretStr = Field(min_length=1, max_length=512)
    consumer_secret: SecretStr = Field(min_length=1, max_length=1024)


class SerproIDConfiguration(BaseModel):
    client_id: UUID
    client_secret: SecretStr = Field(min_length=1, max_length=1024)
    environment: Literal["production", "homologation"]


def save_configuration(tenant_id, sandbox, provider, configuration, context):
    try:
        with SessionLocal.begin() as db:
            require_enterprise(db, tenant_id, context)
            item = db.scalar(select(EnterpriseProvider).where(
                EnterpriseProvider.tenant_id == tenant_id,
                EnterpriseProvider.provider == provider,
                EnterpriseProvider.sandbox == sandbox,
            ).with_for_update())
            version = item.version + 1 if item else 1
            encrypted = encrypt_configuration(tenant_id, provider, sandbox, version, configuration)
            if item is None:
                item = EnterpriseProvider(tenant_id=tenant_id, provider=provider,
                    sandbox=sandbox, encrypted_configuration=encrypted, updated_by=context.subject)
                db.add(item)
            item.version = version
            item.encrypted_configuration = encrypted
            item.updated_by = context.subject
            item.status = "configured_unverified"
            item.deleted_at = None
            tenant_service._audit(db, tenant_id, context.subject, "enterprise.provider.updated",
                {"provider": provider, "sandbox": sandbox, "version": version})
            return {"provider": provider, "sandbox": sandbox, "version": version,
                    "status": item.status}
    except IntegrityError as exc:
        raise HTTPException(409, "Concurrent provider update; retry") from exc


@router.put("/serpro-timestamp")
def put_timestamp(tenant_id: UUID, payload: TimestampConfiguration, sandbox: bool = Query(default=False),
                  context: AuthContext = Depends(require_permission("documents:write"))):
    return save_configuration(tenant_id, sandbox, "serpro_timestamp", {
        "consumer_key": payload.consumer_key.get_secret_value(),
        "consumer_secret": payload.consumer_secret.get_secret_value(),
    }, context)


@router.put("/serproid")
def put_serproid(tenant_id: UUID, payload: SerproIDConfiguration, sandbox: bool = Query(default=False),
                context: AuthContext = Depends(require_permission("documents:write"))):
    return save_configuration(tenant_id, sandbox, "serproid", {
        "client_id": str(payload.client_id), "client_secret": payload.client_secret.get_secret_value(),
        "environment": payload.environment,
    }, context)


@router.get("")
def list_providers(tenant_id: UUID, sandbox: bool = Query(default=False),
                   context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        require_enterprise(db, tenant_id, context)
        return [{"provider": item.provider, "sandbox": item.sandbox,
                 "version": item.version, "status": item.status, "updated_at": item.updated_at}
                for item in db.scalars(select(EnterpriseProvider).where(
                    EnterpriseProvider.tenant_id == tenant_id, EnterpriseProvider.sandbox == sandbox,
                    EnterpriseProvider.deleted_at.is_(None)))]


@router.delete("/{provider}", status_code=204)
def remove_provider(tenant_id: UUID, provider: Literal["serpro_timestamp", "serproid"],
                    sandbox: bool = Query(default=False),
                    context: AuthContext = Depends(require_permission("documents:write"))):
    with SessionLocal.begin() as db:
        require_enterprise(db, tenant_id, context)
        item = db.scalar(select(EnterpriseProvider).where(
            EnterpriseProvider.tenant_id == tenant_id, EnterpriseProvider.provider == provider,
            EnterpriseProvider.sandbox == sandbox,
        ).with_for_update())
        if item is not None and item.deleted_at is None:
            item.encrypted_configuration = ""
            item.deleted_at = datetime.now(UTC)
            item.status = "removed"
            item.version += 1
            tenant_service._audit(db, tenant_id, context.subject, "enterprise.provider.removed",
                {"provider": provider, "sandbox": sandbox, "version": item.version})
