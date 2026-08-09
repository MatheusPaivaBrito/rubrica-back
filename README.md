# Rubrica

Standalone backend project generated from the AtlasCore scaffold patterns.

This repository is intentionally independent from AtlasCore. It starts as a small
service-oriented backend foundation:

- `auth_api` for identity boundaries and future RBAC;
- `core_api` for business domains, including a sample CRUD module;
- required Redis runtime for Auth sessions, refresh tokens, device limits and security state;
- a local `shared_kernel` package;
- Docker Compose for local dependencies;
- Poetry project metadata;
- tests and a Makefile for day-to-day development.

Core now contains the first signature workflow: immutable document versions,
signature requests, individual signer links and an append-only audit trail.

## Signature workflow API

Files are sent as the raw request body (`application/octet-stream`); metadata is
provided as query parameters. This avoids loading multipart parsing into the
service and works well for direct object-storage uploads later.

- `POST/GET /documents` and `GET /documents/{id}`
- `POST /documents/{id}/versions`
- `GET /documents/{id}/download`
- `POST/GET /signature-requests` and `GET /signature-requests/{id}`
- `POST/GET /signature-requests/{id}/signers` and `POST /signature-requests/{id}/signers/{signer_id}/revoke`
- `POST /signature-requests/{id}/open` and `/cancel`
- `GET /signature-requests/{id}/audit`
- `GET /signing/{token}` and `POST /signing/{token}/view|sign|decline`

The local storage adapter writes opaque object keys under `.rubrica-storage` on
the host or a persistent `./data/documents` Docker volume. `DocumentStorage` is
the boundary to replace with S3/MinIO. Creating a signer returns `signing_url`
once; it contains the high-entropy invitation token, while only its SHA-256
digest is retained. The URL opens the future signing frontend; the recipient
must still log in with the invited email before viewing or signing.

The workflow persists metadata, versions, requests, signer token hashes,
signatures and audit events in the project's PostgreSQL database. File bytes use
the local storage adapter in development. Authenticated identity must still be
supplied by Auth: Core forwards the request's bearer token (or access cookie) to
Auth's `/access-control/context` contract. The client cannot choose its actor
identity. Run `make seed-auth` after setting `AUTH_SEED_ADMIN_PASSWORD` in
`.env` to create the local `signature_admin` user.

## Local Development

Prerequisites: Python 3.13 or 3.14, Poetry, and a Docker-compatible
daemon with Compose available. The scaffold does not install host tools
unless the optional bootstrap capability was explicitly selected.

```bash
cp .env.local.example .env
poetry install
make doctor
make migrate-all
make dev-all
```

`make dev-all` starts only the APIs selected for this project. Their
required local dependencies are started on demand by their matching
`ensure-*` target. Use `make compose-up` when you prefer every selected
container to be started together.

Run individual migrations when needed:

```bash
make migrate-core
make migrate-auth
```




## Checks

```bash
make test
make lint
```
