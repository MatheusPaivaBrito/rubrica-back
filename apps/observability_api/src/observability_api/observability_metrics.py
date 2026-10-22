from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from observability_api.infrastructure.settings import settings
from observability_api.modules.operational_memory.entities import (
    Incident,
    ObservabilitySource,
)


_metrics_engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=1,
    max_overflow=0,
    connect_args={"connect_timeout": 1},
)


def collect_business_metrics():
    success = GaugeMetricFamily(
        "rubrica_business_metrics_collection_success",
        "Indica se a coleta das metricas de negocio da API foi concluida.",
        labels=["service"],
    )
    sources = GaugeMetricFamily(
        "rubrica_observability_sources_total",
        "Fontes cadastradas na memoria operacional.",
        labels=["enabled"],
    )
    incidents = GaugeMetricFamily(
        "rubrica_observability_incidents_total",
        "Incidentes classificados por estado e severidade.",
        labels=["status", "severity"],
    )
    try:
        with Session(_metrics_engine) as session:
            for enabled, count in session.execute(
                select(ObservabilitySource.enabled, func.count()).group_by(
                    ObservabilitySource.enabled
                )
            ).all():
                sources.add_metric([str(bool(enabled)).lower()], count)
            for status, severity, count in session.execute(
                select(Incident.status, Incident.severity, func.count()).group_by(
                    Incident.status, Incident.severity
                )
            ).all():
                incidents.add_metric([str(status), str(severity)], count)
        success.add_metric(["observability_api"], 1)
        yield sources
        yield incidents
    except SQLAlchemyError:
        success.add_metric(["observability_api"], 0)
    yield success
