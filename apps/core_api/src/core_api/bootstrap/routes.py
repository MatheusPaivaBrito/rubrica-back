from fastapi import FastAPI

from core_api.bootstrap.health import router as health_router
from core_api.bootstrap.home import router as home_router
from core_api.bootstrap.ui_manifest import router as ui_manifest_router

from core_api.modules.document.document_router import router as document_router
from core_api.modules.billing.billing_router import router as billing_router
from core_api.modules.signature_request.signature_request_router import router as signature_request_router
from core_api.modules.tenant.tenant_router import internal_router as internal_tenant_router
from core_api.modules.tenant.tenant_router import router as tenant_router

def register_routes(app: FastAPI) -> None:
    app.include_router(home_router)
    app.include_router(health_router)
    app.include_router(ui_manifest_router)
    app.include_router(signature_request_router)
    app.include_router(document_router)
    app.include_router(tenant_router)
    app.include_router(internal_tenant_router)
    app.include_router(billing_router)
