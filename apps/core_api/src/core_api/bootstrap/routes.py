from fastapi import FastAPI
from core_api.modules.enterprise.router import router as enterprise_router
from core_api.modules.enterprise.document_router import router as enterprise_document_router
from core_api.modules.enterprise.document_access import router as enterprise_document_access_router
from core_api.modules.enterprise.provider_router import router as enterprise_provider_router
from core_api.modules.enterprise.request_router import router as enterprise_request_router
from core_api.modules.enterprise.signing_router import router as enterprise_signing_router
from core_api.modules.enterprise.usage_router import router as enterprise_usage_router
from core_api.modules.enterprise.storage_calculator import router as enterprise_storage_router
from core_api.modules.enterprise import storage_migration_router  # noqa: F401
from core_api.modules.enterprise.lifecycle_router import router as enterprise_lifecycle_router

from core_api.bootstrap.health import router as health_router
from core_api.bootstrap.home import router as home_router
from core_api.bootstrap.ui_manifest import router as ui_manifest_router

from core_api.modules.document.document_router import router as document_router
from core_api.modules.contact.router import router as contact_router
from core_api.modules.billing.billing_router import router as billing_router
from core_api.modules.signature_request.signature_request_router import router as signature_request_router
from core_api.modules.signature_request.serproid_router import router as serproid_router
from core_api.modules.tenant.tenant_router import internal_router as internal_tenant_router
from core_api.modules.tenant.tenant_router import router as tenant_router

def register_routes(app: FastAPI) -> None:
    app.include_router(enterprise_lifecycle_router)
    app.include_router(enterprise_router)
    app.include_router(enterprise_document_router)
    app.include_router(enterprise_document_access_router)
    app.include_router(enterprise_provider_router)
    app.include_router(enterprise_request_router)
    app.include_router(enterprise_signing_router)
    app.include_router(enterprise_usage_router)
    app.include_router(enterprise_storage_router)
    app.include_router(home_router)
    app.include_router(health_router)
    app.include_router(ui_manifest_router)
    app.include_router(signature_request_router)
    app.include_router(serproid_router)
    app.include_router(document_router)
    app.include_router(contact_router)
    app.include_router(tenant_router)
    app.include_router(internal_tenant_router)
    app.include_router(billing_router)
