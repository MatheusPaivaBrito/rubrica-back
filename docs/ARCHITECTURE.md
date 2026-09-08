# Rubrica Architecture

## Product boundary

Rubrica is a multi-tenant platform for authenticated electronic PDF signatures. It stores immutable document versions, coordinates signature requests, produces cumulative stamped PDFs and retains technical evidence. The product does not claim automatic legal validity; identity assurance, retention and country-specific rules require explicit policy and legal review.

## System map

```text
Browser / Angular
        |
        v
Production Nginx / local Web gateway
        |--------------------------|
        v                          v
    Auth API                    Core API
 PostgreSQL + Redis       PostgreSQL + document storage
                                   |
                 |-----------------|-----------------|
                 v                 v                 v
            Eventing API     Notification API  Observability API
             PostgreSQL         PostgreSQL          PostgreSQL
                 |
                 v
              Worker
```

Each API owns its database. No service reads another service's tables.

## Identifier policy

- Persisted entity identifiers use PostgreSQL UUID and Python `uuid.UUID`.
- SQLAlchemy entities generate UUIDv4 identifiers at the application boundary.
- Foreign keys use native UUID columns; counters such as document version, retry attempt and byte size remain integers.
- External provider IDs, e-mail subjects and opaque signing tokens are not entity IDs and remain strings.
- Incremental migrations convert legacy integer identifiers deterministically, preserving every relationship.
- API schemas expose UUID format while JSON representation remains a string, so the Angular transport stays compatible.
- UUID migrations are intentionally irreversible. Back up databases before production rollout.

## Auth API

Owns identities, password hashes, roles and revocable sessions.

- Database: `rubrica_auth`.
- Redis stores access/refresh session state and user-session indexes.
- Roles: `signature_admin`, `signature_operator`, `signature_auditor`, `signature_signer`.
- Core validates Auth-issued context; it never implements a second login.
- Government identifiers are sensitive identity attributes, not primary keys.

## Core API

Owns product state and the authoritative business audit trail.

### Tenants

`tenants` are workspaces. `tenant_members` links Auth subjects to a tenant role. Documents, administrative reads, requests, billing state and audit access are tenant-scoped.

### Documents

`documents` stores metadata and the current version. `document_versions` freezes filename, media type, storage key, SHA-256 and size for each immutable binary version. Binary content remains in `DocumentStorage`.

### Signature workflow

`signature_requests` freezes the chosen document version and hash. `signers` represents expected authenticated subjects. `signatures` records the act, evidence hash and generated artifact. A request-level opaque link locates the workflow but never replaces authentication.

The signed PDF contains cumulative visible stamps and Rubrica metadata. Core `audit_events` remains transactionally coupled to signature operations and is the authoritative signature ledger.

### Billing

Billing is intentionally plan-free. `billing_accounts` records only tenant commercial state and provider binding; `billing_events` provides an idempotent provider-event boundary. Plans, entitlements, subscriptions and checkout must be designed from Rubrica requirements before being introduced.

## Eventing API

Owns durable integration events and outbox delivery state in `rubrica_eventing`. Canonical contracts currently cover tenant creation, document upload, request opening and signature completion. Eventing does not replace Core audit evidence.

## Notification API

Owns delivery attempts in `rubrica_notification`. The active product channel is e-mail. Local development uses `local_ack`; a real provider key must be supplied in production. Slack and WhatsApp are outside the current scope.

## Observability API

Owns operational incidents, alert events and release markers in `rubrica_observability`. It integrates operational status with Loki, Grafana, Alloy and optional Sentry. Operational telemetry must not receive raw PDFs, signing tokens or complete government identifiers.

## Worker

The Worker is the execution boundary for future outbox relay and background jobs. It must be idempotent and must not become a second source of truth for signature state.

## Shared kernel

`packages/shared_kernel` contains narrow cross-service primitives: UUID identifiers, UTC/timezone helpers, HTTP conventions, service security and event envelopes. Business rules remain inside their owning app.

All persisted timestamps are timezone-aware UTC. Locale and timezone affect presentation only. Naive datetimes are interpreted as UTC at compatibility boundaries.

## Data and security invariants

- Every protected operation revalidates backend authorization.
- Tenant membership scopes administrative access.
- Document binaries are immutable per version and verified by SHA-256.
- Signing tokens are high-entropy, stored only as hashes and revocable.
- Signature and audit writes occur in the same Core transaction.
- Passwords and sensitive identity values never enter logs or events.
- Evidence fields use canonical names and UTC timestamps; localized UI never changes evidence meaning.
- Secrets, `.env`, `.atlas`, `.codex`, local storage and runtime data stay outside Git.

## Database migrations

Each persistent API owns an Alembic chain:

```bash
make migrate-core
make migrate-auth
make migrate-eventing
make migrate-notification
make migrate-observability
```

`make migrate-all` applies every chain. Production UUID rollout requires a verified backup and maintenance window because PostgreSQL rewrites identifier columns and rebuilds foreign keys.

## Deployment

Local Compose runs PostgreSQL, Redis, Core, Auth, Eventing, Notification, Observability and the Angular web gateway. Production Compose adds TLS/Nginx concerns. Kubernetes manifests provide the same service boundaries. Public traffic enters through the web gateway; databases are never public application endpoints.

## Near-term architecture work

1. Connect Core transactions to Eventing through a transactional outbox relay.
2. Implement account registration, e-mail verification and one-time password recovery.
3. Add explicit active-tenant selection for users belonging to multiple tenants.
4. Define international locale, identity and e-mail policies for `pt-BR`, `en` and `ja-JP`.
5. Design Rubrica plans and entitlements only after commercial requirements are confirmed.
