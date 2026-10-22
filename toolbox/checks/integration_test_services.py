from __future__ import annotations

import os
from urllib.parse import urlparse

from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"[error] {name} is required for integration tests")
    return value


def _loopback(name: str, host: str | None) -> str:
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(
            f"[error] {name} must point to an isolated loopback service, got {host!r}"
        )
    return host


def main() -> None:
    if _required("RUBRICA_DATABASE_TESTS") != "1":
        raise SystemExit("[error] RUBRICA_DATABASE_TESTS must equal 1")

    postgres_host = _loopback("POSTGRES_HOST", _required("POSTGRES_HOST"))
    postgres_port = int(_required("POSTGRES_PORT"))
    postgres_user = os.getenv("POSTGRES_USER", "rubrica")
    postgres_password = os.getenv("POSTGRES_PASSWORD", "rubrica")
    core_database = os.getenv("CORE_POSTGRES_DB", "rubrica_core")
    if not core_database.startswith("rubrica_"):
        raise SystemExit("[error] CORE_POSTGRES_DB is not an isolated Rubrica database")

    database_url = URL.create(
        "postgresql+psycopg",
        username=postgres_user,
        password=postgres_password,
        host=postgres_host,
        port=postgres_port,
        database=core_database,
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()

    redis_url = _required("RUBRICA_TEST_REDIS_URL")
    parsed_redis = urlparse(redis_url)
    _loopback("RUBRICA_TEST_REDIS_URL", parsed_redis.hostname)
    redis = Redis.from_url(redis_url, decode_responses=True)
    try:
        if not redis.ping():
            raise SystemExit("[error] isolated Redis did not answer PING")
    finally:
        redis.close()

    print("[ok] isolated PostgreSQL and Redis are ready for integration tests")


if __name__ == "__main__":
    main()
