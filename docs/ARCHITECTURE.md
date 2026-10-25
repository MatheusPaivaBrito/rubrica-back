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

## Repository and working context

- `rubrica-back` is the canonical repository for APIs, workers, migrations, Compose files, operational commands and this architecture document.
- `rubrica-front` is the Angular application. Its normal development loop is bare metal with hot reload and is orchestrated by the backend Makefile.
- The active product specification is `.codex/rubrica-document-datatables/references/feature-spec.md`. It records confirmed requirements, implementation status and acceptance criteria; Part 12 is the authority for environment workflows.
- Before changing a contract, verify the current implementation, Makefile and rendered Compose configuration. Historical checkpoints are not architectural authority.
- Local `.env`, production configuration, secrets, document storage and runtime data stay outside Git. Never copy credentials between environments.

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
- MFA TOTP is available and mandatory for administrator/operator policy. Secrets are encrypted, recovery codes are one-time hashes, challenges are rate-limited and the same TOTP step cannot be replayed.
- MFA provisioning QR codes are generated locally; TOTP secrets, provisioning URIs and recovery codes never enter logs, events, metrics or administrative responses.

### Locale and identity

- Supported product locales are `pt-BR`, `en`, `es` and `ja-JP`; explicit user choice wins over browser preference.
- Locale, country and identity document are independent. Never infer citizenship, residence or identifier type from language, IP or timezone.
- Government identifiers are collected only for a concrete purpose, stored protected and exposed masked. Format validation does not prove identity.
- Japanese My Number remains disabled unless a documented purpose, retention policy, access controls and legal review explicitly authorize it.
- Timestamps are stored in timezone-aware UTC. Locale and timezone affect presentation, never canonical evidence.

## Core API

Owns product state and the authoritative business audit trail.

### Tenants

`tenants` are workspaces. `tenant_members` links Auth subjects to a tenant role. Documents, administrative reads, requests, billing state and audit access are tenant-scoped.

Tenants can be personal or business. A business tenant protects and masks its CNPJ and may have multiple members; authorization always combines the Auth capability, active tenant membership and the local tenant role. Public account/tenant slugs are opaque locators, never authorization.

Business signatures distinguish a person signing for themselves from a person explicitly representing an organization. Membership alone never implies representation. Issuer and representation data are frozen as masked snapshots when a request is opened. Corporate seals remain unavailable until an appropriate organizational credential provider and legal/security policy exist.

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

Notification is an internal authenticated boundary. Provider calls must preserve idempotency, use the recipient locale and never leak secrets or full identity values. Resend is the only real e-mail provider in the current MVP; optional channels must not load or block startup.

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
- A provider change may alter only the physical destination. Hashing, authorization, PDF validation, evidence, retention semantics and artifact identity remain consistent.
- Core `audit_events` is the authoritative, transactionally coupled business/signature ledger. Eventing carries integration facts; Observability carries operational telemetry. Neither replaces audit evidence.

## Database migrations

Each persistent API owns an Alembic chain:

```bash
make migrate-core
make migrate-auth
make migrate-eventing
make migrate-notification
```

`make migrate-all` applies every chain. Production UUID rollout requires a verified backup and maintenance window because PostgreSQL rewrites identifier columns and rebuilds foreign keys.

## Environments and operation

The three environment levels are deliberately distinct. Do not infer one mode from a generic command or reuse another level's configuration.

### Development

`make dev` validates `.env` and starts the Angular frontend and all Rubrica APIs bare metal with hot reload. It uses exactly the configured dependency endpoints and never starts Docker, applies migrations, runs seed or repairs infrastructure.

`make dev-docker` starts only the selected external dependencies in Docker, waits for readiness and then runs the product applications bare metal. The default dependencies are PostgreSQL and Redis; optional selections use `services=postgres,redis,loki`. Containers publish only to loopback.

`make dev-bootstrap` is the explicit first-time setup. Migrations and seed remain explicit through `make dev-migrate` and `make dev-seed`. Local documents use `LocalDocumentStorage` in persistent, Git-ignored storage that normal shutdown commands do not remove. Platform Infra, MkDocs, Stripe CLI and Quick Tunnel are optional tools and never prerequisites for the core development loop.

### Staging

Staging is the first fully containerized product topology and uses its own configuration, Docker Secrets and private R2 bucket. `make staging-bootstrap` prepares migrations/authorized test data and runs smoke checks; `make staging-up` only starts an already prepared stack. Staging validates images, entrypoints, networks, healthchecks, gateway behavior and encrypted document storage without sharing production credentials or objects.

Staging must not consume development or production configuration, production providers, the operational R2 bucket or implicit local seed. Run `staging-ensure` and `staging-smoke` before treating the topology as verified.

### Production

Production uses `.env.production`, secrets rooted at `/etc/rubrica/secrets`, private R2 document storage and a permanent Cloudflare Tunnel. Only the gateway receives ingress; databases, Redis, APIs, observability and documentation expose no host ports.

`production-ensure` is passive and preparatory: it validates configuration, secret metadata, providers, networks and rendered isolation without starting services or making paid calls. Migrations and startup are explicit through `production-migrate` and `production-up`; `production-bootstrap` is reserved for first installation or controlled recovery. Seed, MkDocs, Stripe CLI and Quick Tunnel are prohibited.

Provider checks distinguish configured, reachable and operational states. E-mail sends, signatures, paid timestamps and other externally mutating probes always require a separate command and explicit authorization.

### Storage and telemetry

```text
Development     -> LocalDocumentStorage -> persistent local directory
Staging         -> R2DocumentStorage    -> encrypted isolated staging bucket
Production      -> R2DocumentStorage    -> encrypted private operational bucket
Automated tests -> LocalDocumentStorage -> isolated temporary directory
```

R2 objects are encrypted by the Core with AES-256-GCM before upload. Tenant
authorization is enforced before object lookup, and the plaintext SHA-256 stored
in PostgreSQL is verified after authenticated decryption. Cloud storage operators
can list and download ciphertext but cannot interpret document contents without
the application encryption key.

The Platform Infra stack is external to Rubrica. It is optional and safely degradable in development/staging tests and continuously integrated in production; telemetry failure must never block authentication, signing, migrations or essential readiness.

## Near-term architecture work

1. Connect Core transactions to Eventing through a transactional outbox relay.
2. Complete provider and end-to-end verification for registration, e-mail verification, password recovery and MFA in each applicable environment.
3. Finish multi-tenant navigation and entitlement/downgrade flows without weakening tenant isolation or historical evidence.
4. Complete the file lifecycle audit covering local/R2 integrity, retention, backup, migration and tested restoration.
5. Keep plans and entitlements driven by confirmed Rubrica commercial requirements; do not import generic billing behavior from another product.
