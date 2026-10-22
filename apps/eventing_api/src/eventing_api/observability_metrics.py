from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from eventing_api.infrastructure.settings import settings
from eventing_api.modules.outbox.outbox_entity import OutboxEvent


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
    events = GaugeMetricFamily(
        "rubrica_outbox_events_total", "Eventos do outbox por estado.", labels=["status"]
    )
    try:
        with Session(_engine) as session:
            for status, count in session.execute(
                select(OutboxEvent.status, func.count()).group_by(OutboxEvent.status)
            ).all():
                events.add_metric([str(status)], count)
        success.add_metric(["eventing_api"], 1)
        yield events
    except SQLAlchemyError:
        success.add_metric(["eventing_api"], 0)
    yield success
