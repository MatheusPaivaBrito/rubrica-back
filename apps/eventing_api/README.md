# Eventing API

Eventing owns event intake, outbox persistence, event contract metadata and Kafka-facing runtime boundaries.

This generated service starts intentionally small, but it is not an in-memory placeholder:

- `/events` registers events into a persisted outbox;
- `/outbox` exposes pending/published/failed records;
- `/topics`, `/schemas` and `/streams` describe the eventing surface;
- `/projections` exposes outbox, auth-session and notification-delivery read models;
- Alembic owns the `event_outbox` table.
