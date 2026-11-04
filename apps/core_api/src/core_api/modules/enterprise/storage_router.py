"""Tenant-scoped immutable destinations: credentials never leave the vault."""
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import select

from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.enterprise.provider_vault import decrypt_configuration, encrypt_configuration
from core_api.modules.enterprise.router import require_storage_access as require_enterprise
from core_api.modules.enterprise.s3_destination import S3Destination, endpoint_host
from core_api.modules.enterprise.storage_entities import StorageDestination
from core_api.modules.tenant.tenant_service import tenant_service

router = APIRouter(prefix="/enterprise/tenants/{tenant_id}/storage", tags=["enterprise storage"])


class S3Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(max_length=512)
    bucket: str = Field(min_length=3, max_length=63, pattern=r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$")
    region: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9-]+$")
    prefix: str = Field(default="", max_length=120, pattern=r"^[a-zA-Z0-9/_-]*$")
    access_key_id: SecretStr = Field(min_length=1, max_length=512)
    secret_access_key: SecretStr = Field(min_length=1, max_length=1024)
    session_token: SecretStr | None = Field(default=None, min_length=1, max_length=8192)

    @model_validator(mode="after")
    def validate_endpoint(self):
        endpoint_host(self.endpoint)
        if ".." in self.bucket:
            raise ValueError("Invalid bucket name")
        return self

    def plaintext(self):
        return {name: value.get_secret_value() if isinstance(value, SecretStr) else value
                for name, value in self.__dict__.items() if value is not None}


class DestinationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160, pattern=r"\S")
    kind: Literal["rubrica", "s3", "independent"]
    configuration: S3Configuration | None = None

    @model_validator(mode="after")
    def correct_configuration(self):
        if (self.kind == "s3") != (self.configuration is not None):
            raise ValueError("Only S3 destinations require configuration")
        return self


def destination_read(item):
    return {"id": item.id, "name": item.name, "kind": item.kind, "sandbox": item.sandbox,
            "validated_at": item.validated_at, "created_at": item.created_at}


def destination_for(db, tenant_id, destination_id, sandbox):
    item = db.scalar(select(StorageDestination).where(
        StorageDestination.id == destination_id, StorageDestination.tenant_id == tenant_id,
        StorageDestination.sandbox == sandbox, StorageDestination.deleted_at.is_(None)))
    if item is None:
        raise HTTPException(404, "Storage destination not found")
    return item


def adapter_for(item):
    if item.kind != "s3" or item.sandbox:
        raise HTTPException(409, "External storage is unavailable in sandbox")
    config = decrypt_configuration(item.tenant_id, f"storage:{item.id}", item.sandbox, 1,
                                   item.encrypted_configuration)
    return S3Destination(config)


@router.post("/destinations", status_code=201)
def create_destination(tenant_id: UUID, payload: DestinationCreate, sandbox: bool = Query(default=False),
                       context: AuthContext = Depends(require_permission("documents:write"))):
    with SessionLocal.begin() as db:
        require_enterprise(db, tenant_id, context)
        if sandbox and payload.kind == "s3":
            raise HTTPException(409, "Sandbox does not contact external storage")
        item = StorageDestination(id=uuid4(), tenant_id=tenant_id, name=payload.name.strip(),
            kind=payload.kind, sandbox=sandbox, created_by=context.subject)
        if payload.configuration:
            item.encrypted_configuration = encrypt_configuration(tenant_id, f"storage:{item.id}", sandbox, 1,
                                                                payload.configuration.plaintext())
        else:
            item.validated_at = datetime.now(UTC)
        db.add(item)
        db.flush()
        tenant_service._audit(db, tenant_id, context.subject, "enterprise.storage.destination.created",
                              {"destination_id": str(item.id), "kind": item.kind, "sandbox": sandbox})
        return destination_read(item)


@router.get("/destinations")
def list_destinations(tenant_id: UUID, sandbox: bool = Query(default=False),
                      context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        require_enterprise(db, tenant_id, context)
        return [destination_read(item) for item in db.scalars(select(StorageDestination).where(
            StorageDestination.tenant_id == tenant_id, StorageDestination.sandbox == sandbox,
            StorageDestination.deleted_at.is_(None)).order_by(StorageDestination.created_at).limit(100))]


@router.post("/destinations/{destination_id}/validate")
def validate_destination(tenant_id: UUID, destination_id: UUID, sandbox: bool = Query(default=False),
                         context: AuthContext = Depends(require_permission("documents:write"))):
    with SessionLocal.begin() as db:
        require_enterprise(db, tenant_id, context)
        item = destination_for(db, tenant_id, destination_id, sandbox)
        if item.kind == "s3":
            adapter = adapter_for(item)
            prefix = adapter.configuration["prefix"].strip("/")
            key = f"{prefix + '/' if prefix else ''}rubrica/{tenant_id}/probes/{item.id}.txt"
            content = b"Rubrica storage validation v1\n"
            adapter.ensure_object(key, sha256(content).hexdigest(), len(content), "application/octet-stream",
                                  lambda: BytesIO(content))
            adapter.delete_probe(key)
        item.validated_at = datetime.now(UTC)
        tenant_service._audit(db, tenant_id, context.subject, "enterprise.storage.destination.validated",
                              {"destination_id": str(item.id), "sandbox": sandbox})
        return destination_read(item)
