from datetime import UTC, datetime, timedelta

from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth_api.infrastructure.settings import settings
from auth_api.modules.users.user_entity import UserEntity


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
    users = GaugeMetricFamily(
        "rubrica_users_total", "Usuarios cadastrados por estado.", labels=["state"]
    )
    created = GaugeMetricFamily(
        "rubrica_users_created_window",
        "Usuarios criados dentro de uma janela recente.",
        labels=["window"],
    )
    try:
        now = datetime.now(UTC)
        with Session(_engine) as session:
            for state, active in (("active", True), ("inactive", False)):
                count = session.scalar(
                    select(func.count())
                    .select_from(UserEntity)
                    .where(UserEntity.deleted_at.is_(None), UserEntity.is_active.is_(active))
                ) or 0
                users.add_metric([state], count)
            for label, delta in (("24h", timedelta(days=1)), ("7d", timedelta(days=7)), ("30d", timedelta(days=30))):
                count = session.scalar(
                    select(func.count())
                    .select_from(UserEntity)
                    .where(UserEntity.deleted_at.is_(None), UserEntity.created_at >= now - delta)
                ) or 0
                created.add_metric([label], count)
        success.add_metric(["auth_api"], 1)
        yield users
        yield created
    except SQLAlchemyError:
        success.add_metric(["auth_api"], 0)
    yield success
