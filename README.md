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

## Verifying a signed PDF

New signed artifacts carry the visual stamps plus a `RubricaEvidenceJSON`
metadata entry containing the consented technical evidence for every signature.
Extract it and verify each evidence hash and the combined manifest with:

```bash
PYTHONPATH=apps/core_api/src:packages/shared_kernel/src poetry run python toolbox/verify_signed_pdf.py /path/to/signed.pdf
```

The command prints the PDF hash, Rubrica identifiers, original-document hash,
evidence manifest and the evidence captured for each signer. Artifacts created
before this metadata was introduced retain their original hashes and expose the
summary metadata only; they are not rewritten retroactively.

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

## Production with Cloudflare Tunnel

Production uses `docker-compose.prod.yml`, the frontend `Dockerfile.prod` and a
dedicated Cloudflare Tunnel. Cloudflare terminates HTTPS; Nginx is reachable only
inside the Compose network and does not occupy host ports 80/443.

```bash
cp .env.production.example .env.production
sudo install -d -m 700 -o root -g root /etc/rubrica/secrets
# Create every secret listed in docs/PRODUCTION_MVP_SETUP.md, including
# cloudflare_tunnel_token.
sudo chmod 600 /etc/rubrica/secrets/*

make production-up
make production-migrate
make production-seed
```

Create a dedicated remotely managed tunnel for Rubrica, configure the public
hostname to use the HTTP service `http://web:80`, and store its token in
`/etc/rubrica/secrets/cloudflare_tunnel_token`. Keep every application service
and database unexposed; the tunnel makes outbound connections to Cloudflare.

For subsequent deployments, keep the existing named volumes and run:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.production -f docker-compose.prod.yml exec auth-api alembic -c apps/auth_api/alembic.ini upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml exec core-api alembic -c apps/core_api/alembic.ini upgrade head
```

### Production backup and restore verification

Create a consistent backup of every Rubrica PostgreSQL database and the signed
document volume:

    make backup-production

The command writes an ignored, permission-restricted timestamped directory under
backups. Copy that directory to encrypted storage outside the application host.

Prove that a backup is restorable without touching production:

    make verify-backup path=backups/YYYYmmddTHHMMSSZ

Verification checks SHA-256 hashes, restores every database into a disposable
PostgreSQL container and checks that the document archive can be read. Run this
after the first deployment and periodically thereafter.
