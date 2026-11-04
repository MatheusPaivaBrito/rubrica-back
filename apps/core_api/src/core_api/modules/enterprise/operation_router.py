from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseRequest
from core_api.modules.enterprise.execution_entity import EnterpriseOperation
from core_api.modules.enterprise.machine_context import MachineContext
from core_api.modules.enterprise.router import binding

router = APIRouter(prefix="/enterprise/tenants/{tenant_id}", tags=["enterprise result recovery"])


def lookup(db, integration_id, identity=None):
    statement = select(EnterpriseOperation).join(EnterpriseRequest, EnterpriseRequest.id == EnterpriseOperation.request_id).join(
        EnterpriseCompartment, EnterpriseCompartment.id == EnterpriseRequest.compartment_id).where(
            EnterpriseCompartment.integration_id == integration_id)
    return statement.where(EnterpriseOperation.id == identity) if identity else statement


@router.get("/integrations/{integration_id}/operations")
def operations(tenant_id: UUID, integration_id: UUID, context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        binding(db, tenant_id, integration_id, context, recovery=True)
        return [{"id": item.id, "request_id": item.request_id, "signer_id": item.signer_id,
                 "status": item.status, "error_code": item.error_code} for item in db.scalars(
                     lookup(db, integration_id).order_by(EnterpriseOperation.updated_at.desc()).limit(50))]


@router.post("/integrations/{integration_id}/operations/{operation_id}/reconcile", status_code=202)
def reconcile(tenant_id: UUID, integration_id: UUID, operation_id: UUID,
              context: AuthContext = Depends(require_permission("documents:write"))):
    with SessionLocal() as db:
        integration = binding(db, tenant_id, integration_id, context)
        operation = db.scalar(lookup(db, integration_id, operation_id))
        if operation is None:
            raise HTTPException(404, "Provider operation not found")
        request = db.get(EnterpriseRequest, operation.request_id)
        machine = MachineContext(tenant_id, integration.id, request.compartment_id, "admin-recovery", integration.sandbox)
    from core_api.modules.enterprise.jobs import enqueue
    # No provider call: recover only a result already persisted at its fixed key.
    return enqueue(machine, "reconcile", {"operation_id": str(operation_id)}, str(operation_id))
