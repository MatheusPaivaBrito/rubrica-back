from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core_api.infrastructure.settings import settings
from core_api.modules.document.document_entity import DocumentEntity
from core_api.modules.signature_request.signature_request_entity import SignatureRequestEntity
from core_api.modules.tenant.tenant_entity import TenantEntity


_engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=1,
    max_overflow=0,
    connect_args={"connect_timeout": 1},
)


def collect_business_metrics():
    success = GaugeMetricFamily(
        "rubrica_business_metrics_collection_success",
        "Indica se a coleta de metricas de negocio foi concluida.",
        labels=["service"],
    )
    tenants = GaugeMetricFamily(
        "rubrica_tenants_total", "Tenants por tipo e estado.", labels=["kind", "status"]
    )
    documents = GaugeMetricFamily(
        "rubrica_documents_total", "Documentos por estado.", labels=["status"]
    )
    requests = GaugeMetricFamily(
        "rubrica_signature_requests_total",
        "Solicitacoes de assinatura por modo e estado.",
        labels=["mode", "status"],
    )
    try:
        with Session(_engine) as session:
            for kind, status, count in session.execute(
                select(TenantEntity.kind, TenantEntity.status, func.count())
                .where(TenantEntity.deleted_at.is_(None))
                .group_by(TenantEntity.kind, TenantEntity.status)
            ).all():
                tenants.add_metric([str(kind), str(status)], count)
            for status, count in session.execute(
                select(DocumentEntity.status, func.count())
                .where(DocumentEntity.deleted_at.is_(None))
                .group_by(DocumentEntity.status)
            ).all():
                documents.add_metric([str(status)], count)
            for mode, status, count in session.execute(
                select(SignatureRequestEntity.signature_mode, SignatureRequestEntity.status, func.count())
                .where(SignatureRequestEntity.deleted_at.is_(None))
                .group_by(SignatureRequestEntity.signature_mode, SignatureRequestEntity.status)
            ).all():
                requests.add_metric([str(mode), str(status)], count)
        success.add_metric(["core_api"], 1)
        yield tenants
        yield documents
        yield requests
    except SQLAlchemyError:
        success.add_metric(["core_api"], 0)
    yield success
