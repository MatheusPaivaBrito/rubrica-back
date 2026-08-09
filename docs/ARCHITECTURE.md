# Generated Architecture

This project was generated from AtlasCore patterns. It is a starting
point, not a final business application.

## Service Boundaries

Each API owns its own application package under `apps/`.

- `core_api` owns business domains.
- `auth_api` owns identity, users, sessions and future RBAC.
- messaging APIs are optional and should be added only when the
  project needs async/event-driven flows.

## Auth Starter

The generated Auth boundary is intentionally compact. It keeps users
in its own Postgres database and revocable opaque sessions in Redis.
Its public routes are:

- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `POST /auth/logout-all`
- `GET /sessions/me`
- `GET /access-control/ui-context`

Enable the optional Auth example seed when local credentials are
useful. It creates `admin@example.local` with password
`AtlasAdmin123!`; remove or rotate this account before production.

## Database Ownership

APIs should not share tables. When Core and Auth are generated, each
one receives its own database settings and Alembic folder.

- Core uses `CORE_POSTGRES_DB`.
- Auth uses `AUTH_POSTGRES_DB`.

Docker Compose includes a small Postgres initialization script that
creates multiple local databases from `POSTGRES_MULTIPLE_DATABASES`.

## Alembic Per API

Run migrations per API:

```bash
make migrate-core
make migrate-auth
```

Create revisions per API:

```bash
make revision-core msg=create_domain
make revision-auth msg=create_users
```

Alembic discovers entities through each API database loader:

- `core_api.infrastructure.database.loader`
- `auth_api.infrastructure.database.loader`

## Vertical Domains

Domains should keep their local files together:

```text
modules/<your_domain>/
  <entity>_entity.py
  <entity>_schema.py
  <entity>_service.py
  <entity>_router.py
```

Shared behavior belongs in `packages/shared_kernel`. Domain-specific
business decisions stay inside the domain.

## Creating The First Domain

The initial Core migration is intentionally empty. The first relational
domain owns the first business table and the following Alembic revision.
