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

Enterprise machine credentials also belong exclusively to Auth API:
`modules/machine_credentials` owns token generation, digests, expiry, scopes,
rotation/revocation and authentication, with its own audit in the Auth database.
Core owns integrations and compartments and authorizes access to product resources.
Cross-service identifiers are opaque UUID references, never cross-database foreign
keys. Administrative credential operations require an authenticated authorization
boundary; internal primitives are not public endpoints. Auth never imports Core
modules or reads its membership tables to authorize token administration.

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

Enterprise API resources live in `modules/enterprise`, separately from interactive
document tables. Core owns compartment-scoped intake, quarantine/scanning, request
state, restricted signer sessions, immutable signature facts and encrypted tenant
provider configurations. Long-lived machine credentials remain exclusively in Auth.
Provider credentials are injected per tenant; changing global settings per request
is prohibited. Sandbox signatures are visibly marked simulations and cannot call
real providers. Deployments must configure a trusted ClamAV endpoint before clearing
intake and a certificate trust bundle before enabling enterprise SerproID execution.
Enterprise quotas are persisted per tenant and mode, with separate API rate buckets
and storage/signing counters. Sandbox uses its own storage namespace/key and execution
slots. Legacy namespace references remain readable after the usage migration.
Current-copy retention scheduling is described below; complete internal retention
and dedicated processing workers remain pending.

Core transactionally records immutable enterprise usage facts and a telemetry outbox.
A bounded background relay sends a versioned, secret-free contract to Observability,
which stores an idempotent projection in its own database. It never reads Core tables.
Failure of the projection/relay does not block signing; canonical financial facts
remain in Core. Operational samples are best effort. All current prices are explicitly
zero and versioned; sandbox usage cannot become billable by changing tokens.

Enterprise storage destinations are owned by Core and immutable after creation.
Customer S3 credentials are encrypted with tenant, mode, deployment environment
and destination UUID bound as authenticated data; APIs never return them. Official
S3/R2 HTTPS endpoints are permitted; other exact hostnames require operator approval
through `ENTERPRISE_S3_ALLOWED_HOSTS`. Every operation resolves public addresses,
pins the actual connection to an address and verifies TLS with the original
hostname. Redirects and environment proxies are disabled. Transfer byte/time
budgets bound responses; SigV4 signs the exact object path and known content hash.

Migration records, per-document state and per-object receipts survive retries.
An optional policy enrolls future uploads/requests, freezing a destination on each
new job. A bounded background poller (`ENTERPRISE_STORAGE_WORKER_ENABLED`) processes
jobs with row locks, waits for terminal signature requests and verifies originals,
all signed artifacts and evidence JSON. Copying to S3 is conditional and successful
only after the destination bytes match SHA-256 and size. Independent delivery needs
a completed server stream and a separate administrator acknowledgement of durable
storage; this acknowledgement is a customer assertion, not remote storage proof.
Migration itself preserves Rubrica copies. A separate confirmed administrator
action commits per-copy removal intents before a worker touches storage. The worker
rechecks the complete manifest/terminal requests and current S3 bytes (or the
explicit independent-delivery acknowledgement). Strict storage deletion must
confirm absence; denial, Bucket Lock and inconclusive HEAD responses remain pending.
Copy flags, quota changes, immutable storage.removed facts and audit commit together.
If the process dies after physical deletion, the committed intent survives and the
idempotent retry reconciles the same fact once. Retry has bounded exponential
backoff. Compartment-before-intent lock order permits an administrator to explicitly
replace a pending intent's receipt with a newly verified migration after credential
rotation, retaining the canonical removal ID.

Authorized reads prefer a retained verified Rubrica copy. After confirmed removal
(or an absent source with a committed intent), they can read a tenant/mode-scoped
verified S3 receipt, checking all bytes before returning plaintext. Local integrity
failures never silently fall back. Independent-only exports return 410 after copy
removal. No customer storage URL/credential is exposed. Starting another signature
request is blocked while removal is pending or the original is external-only.
Explicit S3 restoration writes fresh Rubrica keys through the configured encrypted
storage backend, verifies them and commits counters/storage.added facts atomically;
failed restorations roll back references/counters and attempt cleanup of new copies.
No existing customer objects are removed by this operation.

Schema 0038 adds only durable intents and indexes, with no object mutations.
Removal affects current logical document/artifact copies, not metadata, evidence,
provider credentials, bucket-version history or backups. Full internal retention,
distributed worker/resource isolation and end-to-end
PostgreSQL/provider tests remain required before external commercial release.

Enterprise lifecycle (schema 0039) derives operational access from billing and an
explicit contractual cutoff on every call, regardless of the background poller.
The recovery deadline is fixed at suspension plus 30 days. Auth still owns token
secrets; Core rejects all operational calls and token rotation while suspended.
Human administrators retain scoped export/migration access during recovery,
including after downgrade, and can cancel open requests without erasing completed
signatures. Payment/contract regularization is persisted in the billing transaction
before the deadline so delayed projection cannot purge already regularized data.

The lifecycle poller projects states/notices, expires requests, relays administrator
emails through notification_api with idempotency/retries, and dispatches signed
webhooks. Optional current-copy purge commits intents before deletion and rechecks
the contract under the account lock. Writers use account-before-resource order.
Confirmed absence and counter/event changes commit together, with retry after a
crash. Customer-owned destinations are never deleted. Closure (Core 0040/Auth 0014)
additionally erases API metadata, provider/job secrets and managed orphan objects,
and retires Auth credentials idempotently. Final completion requires receipts from
every registered backup repository; deleting current objects alone is never proof
of backup erasure. `ENTERPRISE_RETENTION_PURGE_ENABLED`
defaults false until operational validation; it does not prolong authorization or
promise data recovery after the deadline. Recontracting starts an explicit empty
contract after verified closure. See [Enterprise operations](enterprise-api-operations.md)
for backup compaction, deployment and independent security release gates.

Webhook outbox records are transactional, unique per endpoint/event and secret-free.
Delivery is at least once/unordered, bounded to 16 KiB and operator-approved HTTPS
hosts with public DNS pinning, original TLS hostname and no redirects/proxies.
HMAC authenticates `timestamp + '.' + exact_body`; event ID and key version are
headers, and receivers enforce a five-minute timestamp window plus ID deduplication.
Retries retain event ID/body for 24 hours; permanent rejection or exhausted window
enters a failed queue with audited manual replay. Endpoint URL changes require
explicit disable and stop the old queue. Live/sandbox/environment bindings are
checked again before transport. Secrets are encrypted and shown only on rotation.

The storage calculator reads a coherent quota/journal snapshot and integrates
logical bytes above the shared tenant allowance over time. Decimal GB is
1,000,000,000 bytes and GB/month uses a fixed 30-day contractual cycle anchored on
the billing account. Downloads and external exports do not add stored bytes; only
confirmed source removal will reduce them. Sandbox has separate counters and no
commercial fee. Current tariffs/estimates are zero; this is a usage estimate, not
an invoice or retroactive debt.

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

R2 objects are encrypted by the Core with versioned envelope encryption before
upload. Root, tenant and document contexts wrap a random per-object DEK; document
bytes use chunked AES-256-GCM so reads can be authenticated and streamed with
bounded memory. Tenant/document/storage-key context is authenticated, and direct
R2 or backup access exposes only opaque ciphertext. Tenant authorization is
enforced before object lookup, and the plaintext SHA-256 stored
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

### Enterprise execution and public contract (0041)

Enterprise scan/consent return durable 202 jobs. Dedicated Core-owned live/sandbox
workers execute isolated child processes, with distributed tenant/global leases and
resource/deadline fencing. Embedded development uses the same child runner. A paid
provider intent precedes the network and a verified artifact checkpoint precedes the
business commit; uncertainty never permits reissuing a paid act. Independent queues,
API-token/tenant budgets and administrator budgets bound admission.

Public `/docs` contains only the API contract, fictional examples and no credentials.
Nginx proxies it to Core; service-worker navigation excludes docs/API callbacks.
See [Enterprise operations](enterprise-api-operations.md) for deployment, backup
barriers, incident recovery and release gates.
