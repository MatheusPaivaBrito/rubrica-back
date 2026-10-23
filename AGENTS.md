# Rúbrica backend — operational contract

## Environments

- `make dev`: frontend and all Rubrica APIs run bare metal with hot reload. It validates `.env` but never starts or repairs infrastructure.
- `make dev-docker`: starts the default Docker dependencies, then runs the applications bare metal. Select dependencies with `make dev-docker services=postgres,redis,loki`.
- `make staging-*`: relaxed remote full-Docker topology using `.env.staging`, staging-only Docker Secrets and a Quick Tunnel; Stripe CLI/test providers are opt-in.
- `make production-*`: server-only flow using `.env.production`, `/etc/rubrica/secrets`, R2 and Cloudflare Tunnel.

Never use `.env.production`, production secrets, production buckets or production providers in dev/staging. Never run seed, MkDocs, Stripe CLI or Quick Tunnel in production.

## Canonical workflow

Run `make help` before suggesting commands. Use `make dev-bootstrap` once, then `make dev` or `make dev-docker`. Migrations and seed are explicit through `dev-migrate` and `dev-seed`. `staging-bootstrap` applies migrations and the staging-authorized test seed before starting and smoking the stack; `staging-up` does neither. Staging must pass `staging-ensure` and `staging-smoke` before production work.

Production changes require `production-ensure`, explicit migrations and `production-up`. `production-provider-check` is non-paid/non-mutating; paid or externally mutating probes require explicit user authorization.

## Safety

- Secrets never belong in Git or environment files.
- Dev files use local storage outside Git; staging uses a Docker volume; production uses R2.
- Do not remove volumes or reset databases without explicit authorization and resolved targets.
- Prefer Docker without `sudo` in development when the user can access the daemon.
- Platform Infra is optional for dev telemetry tests and integrated in production; its failure must not block core product flows.
- Before commit/push: validate Compose contracts, Ruff/tests, frontend lint/tests and the relevant smoke.
