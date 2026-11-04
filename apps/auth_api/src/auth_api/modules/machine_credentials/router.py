"""Internal machine credential boundary, callable only by authenticated Core."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from auth_api.infrastructure.database.connection import SessionLocal
from auth_api.infrastructure.settings import settings
from auth_api.modules.machine_credentials.entity import MachineCredentialEntity
from auth_api.modules.machine_credentials.service import (
    CredentialError, authenticate_token, revoke_token, rotate_token,
)
from shared_kernel.security.service_tokens import verify_service_token


def require_core(
    x_rubrica_service: str = Header(default=""),
    x_rubrica_service_key: str = Header(default=""),
):
    if (x_rubrica_service != "core_api" or not settings.CORE_INTERNAL_SERVICE_KEY
            or not verify_service_token(x_rubrica_service_key, settings.CORE_INTERNAL_SERVICE_KEY)):
        raise HTTPException(403, "Service authentication failed")


router = APIRouter(prefix="/internal/machine-credentials", include_in_schema=False,
                   dependencies=[Depends(require_core)])


class BindingRequest(BaseModel):
    tenant_id: UUID
    integration_id: UUID
    environment: Literal["development", "staging", "production"]
    sandbox: bool
    subject: str = Field(min_length=1, max_length=255)


class RotationRequest(BindingRequest):
    scopes: frozenset[str]
    expires_at: datetime | None = None


class AuthenticationRequest(BaseModel):
    secret: SecretStr = Field(max_length=256)
    sandbox: bool
    permission: str = Field(max_length=80)


def validate_environment(environment: str):
    if environment != settings.ENVIRONMENT:
        raise HTTPException(403, "Environment mismatch")


@router.post("/rotate")
def rotate(payload: RotationRequest, response: Response):
    validate_environment(payload.environment)
    response.headers["Cache-Control"] = "no-store"
    try:
        with SessionLocal.begin() as db:
            # The Core admin boundary verifies membership, contract and binding.
            binding = db.scalar(select(MachineCredentialEntity).where(
                MachineCredentialEntity.integration_id == payload.integration_id,
                MachineCredentialEntity.environment == payload.environment,
                MachineCredentialEntity.sandbox == payload.sandbox,
            ))
            if binding is None:
                db.add(MachineCredentialEntity(
                    tenant_id=payload.tenant_id, integration_id=payload.integration_id,
                    environment=payload.environment, sandbox=payload.sandbox,
                ))
                db.flush()
            token = rotate_token(db, **payload.model_dump(), now=datetime.now(UTC))
        return {"public_id": token.public_id, "token": token.secret}
    except CredentialError as exc:
        raise HTTPException(422, str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(409, "Concurrent credential operation; retry") from exc


@router.post("/revoke", status_code=204)
def revoke(payload: BindingRequest):
    validate_environment(payload.environment)
    try:
        with SessionLocal.begin() as db:
            revoke_token(db, **payload.model_dump())
    except CredentialError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/introspect")
def introspect(payload: AuthenticationRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        with SessionLocal() as db:
            return authenticate_token(
                db, secret=payload.secret.get_secret_value(),
                environment=settings.ENVIRONMENT, sandbox=payload.sandbox,
                permission=payload.permission, now=datetime.now(UTC),
            )
    except CredentialError as exc:
        raise HTTPException(401, "Invalid machine credential") from exc
