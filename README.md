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
identity. After `make dev-migrate`, run `make dev-seed` to create the local
logins: Free, Essential, Professional (3 members), and Team (6 members).
Administrators count toward those totals. The seed requires an explicit local
or development environment and opt-in, confirms email and exempts only these
fixtures from MFA. Passwords use `LOCAL_TEST_ACCOUNT_PASSWORD`. Rerunning it
preserves billing tests and suspended memberships. See
[Compose architecture](compose/ARCHITECTURE.md#operações-manuais-alembic-e-seed)
for logins and manual migration commands. `make dev-bootstrap` prepares the
dependencies, migrates, seeds these accounts and starts the applications bare metal.

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

## Environments

The normal editing loop runs the Angular frontend and internal APIs bare metal
with hot reload. Docker is used only for dependencies such as PostgreSQL,
Redis, Kafka or Loki. Python 3.13/3.14, Poetry, Node/npm and the project
dependencies must already be installed.

```bash
cp .env.example .env
poetry install
npm --prefix ../rubrica-front ci
make doctor
make dev-docker
```

`make dev` starts no infrastructure and uses exactly the endpoints in `.env`.
`make dev-docker` starts the default PostgreSQL and Redis containers, waits for
readiness, and then starts the same bare-metal applications. Dependencies and
optional tools can be selected explicitly:

```bash
make dev-docker services=postgres,redis,loki
make docs
make telemetry-up
```

First-time initialization and data changes remain explicit:

```bash
make dev-bootstrap
make dev-migrate
make dev-seed
```

Staging is the first fully containerized environment. It uses separate config,
Docker Secrets and named volumes, never development or production data:

```bash
make staging-secrets-init
make staging-bootstrap
make staging-smoke
```

See [AGENTS.md](AGENTS.md) and `make help` for the complete contract.




## Checks

```bash
make test
make lint
```

## Production with Cloudflare Tunnel

Production uses `compose/production.yml`, the frontend `Dockerfile.prod` and a
dedicated Cloudflare Tunnel. Cloudflare terminates HTTPS; Nginx is reachable only
inside the Compose network and does not occupy host ports 80/443.

```bash
cp .env.production.example .env.production
sudo install -d -m 700 -o root -g root /etc/rubrica/secrets
# Create every secret listed in docs/PRODUCTION_MVP_SETUP.md, including
# cloudflare_tunnel_token.
sudo chmod 600 /etc/rubrica/secrets/*

make production-ensure
make production-migrate
make production-up
```

Create a dedicated remotely managed tunnel for Rubrica, configure the public
hostname to use the HTTP service `http://web:80`, and store its token in
`/etc/rubrica/secrets/cloudflare_tunnel_token`. Keep every application service
and database unexposed; the tunnel makes outbound connections to Cloudflare.

For subsequent deployments, keep the existing named volumes and run:

```bash
make production-ensure
make production-migrate
make production-up
```

### Production backup and restore verification

Cloudflare R2 setup, automatic encrypted backups and private document storage
are documented in [docs/CLOUDFLARE_R2.md](docs/CLOUDFLARE_R2.md).

Create a consistent backup of every Rubrica PostgreSQL database and every
referenced document from the configured storage provider (local or R2):

    make backup-all environment=production

Back up only databases or one application database:

    make backup-database environment=production database=all
    make backup-database environment=production database=auth

Valid database aliases are `core`, `auth`, `eventing`, and `notification`.
Back up only files with:

    make backup-files environment=production

The command writes an ignored, permission-restricted timestamped directory under
backups. Copy that directory to encrypted storage outside the application host.

Prove that a backup is restorable without touching production:

    make verify-backup path=backups/YYYYmmddTHHMMSSZ

Verification checks SHA-256 hashes, restores every database into a disposable
PostgreSQL container and checks that the document archive can be read. Run this
after the first deployment and periodically thereafter.
