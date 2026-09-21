LOCAL_ENV_FILE ?= .env
PRODUCTION_ENV_FILE ?= .env.production
-include $(LOCAL_ENV_FILE)
export

GATEWAY_HOST_PORT ?= 7171



KIND ?= kind
KUBECTL ?= kubectl
K8S_KIND_CLUSTER ?= rubrica
K8S_NAMESPACE ?= rubrica

TEST_PYTHONPATH = .:apps/auth_api/src:apps/core_api/src:apps/eventing_api/src:apps/notification_api/src:apps/worker/src:packages/shared_kernel/src
TEST_ENV = env -u DEBUG
LOCAL_COMPOSE_FILE ?= compose/local.yml
PRODUCTION_COMPOSE_FILE ?= compose/production.yml
LOCAL_COMPOSE = docker compose --env-file $(LOCAL_ENV_FILE) -f $(LOCAL_COMPOSE_FILE)
PRODUCTION_COMPOSE = docker compose --env-file $(PRODUCTION_ENV_FILE) -f $(PRODUCTION_COMPOSE_FILE)
BACKUP_ROOT ?= backups

.PHONY: help doctor test lint docs-build local-config local-start local-up local-up-stripe local-down local-logs local-rebuild compose-up compose-down bootstrap stripe-up stripe-logs migrate migrate-core revision-core migrate-auth revision-auth migrate-eventing migrate-notification migrate-all seed-auth invite-lifetime grant-lifetime revoke-lifetime production-config production-up production-down production-logs production-migrate production-seed production-invite-lifetime production-grant-lifetime production-revoke-lifetime backup backup-production backup-production-offsite verify-backup smoke smoke-all smoke-core-generator

help:
	@echo "Rubrica"
	@echo "============================================================"
	@echo "Local Docker"
	@echo "  make local-up            Build and start the local stack"
	@echo "  make local-up-stripe     Build local stack and start Stripe webhook forwarding"
	@echo "  make local-down          Stop the local stack"
	@echo "  make local-logs          Follow local service logs"
	@echo "  make local-rebuild       Rebuild and recreate the local stack"
	@echo "  make stripe-up           Start the optional local Stripe listener"
	@echo ""
	@echo "Checks"

	@echo "  make doctor              Validate local project prerequisites"
	@echo "  make test                Run tests"
	@echo "  make lint                Run Ruff"
	@echo ""
	@echo "Smoke scripts"
	@echo "  make smoke-core-generator Verify the empty Core manifest before adding a domain"
	@echo "  make smoke-all            Run every generated smoke script"

	@echo ""
	@echo "Runtime"
	@echo "  make compose-up          Alias for local-up"
	@echo "  make compose-down        Alias for local-down"
	@echo "  make bootstrap           Start local containers, migrate and seed Auth"
	@echo "  make production-config  Validate the production Compose and secrets"
	@echo "  make production-up      Build and start the production stack"
	@echo "  make production-migrate Apply every production migration"
	@echo "  sudo make production-invite-lifetime name='...' email=... document_type=BR_CPF document_country=BR locale=pt-BR actor=EMAIL reason='...'"
	@echo "  sudo make production-grant-lifetime tenant_id=UUID actor=EMAIL reason='...'"
	@echo "  sudo make production-revoke-lifetime tenant_id=UUID actor=EMAIL reason='...'"
	@echo "  make backup-production  Back up all databases and signed documents"
	@echo "  make backup-production-offsite  Back up and upload encrypted copy to B2"
	@echo "  make verify-backup path=backups/TIMESTAMP"


	@echo ""
	@echo "Project host endpoints"
	@echo "  Gateway    http://localhost:$(GATEWAY_HOST_PORT)"
	@echo ""
	@echo "Database"
	@echo "  Postgres and Redis are available only inside the Compose network"
	@echo "  make migrate             Run Core and Auth database migrations"
	@echo "  make migrate-all         Alias for make migrate"
	@echo "  make migrate-core           Run Core Alembic migrations"
	@echo "  make revision-core msg=create_domain"
	@echo "  make migrate-auth           Run Auth Alembic migrations"
	@echo "  make seed-auth              Create the local signature administrator"
	@echo "  make invite-lifetime name='...' email=... document_type=BR_CPF document_country=BR locale=pt-BR actor=EMAIL reason='...'"
	@echo "  make grant-lifetime tenant_id=UUID actor=EMAIL reason='...'"
	@echo "  make revoke-lifetime tenant_id=UUID actor=EMAIL reason='...'"
	@echo "  make revision-auth msg=create_users"



test:
	PYTHONPATH=$(TEST_PYTHONPATH) $(TEST_ENV) poetry run pytest

lint:
	PYTHONPATH=$(TEST_PYTHONPATH) poetry run ruff check .

docs-build:
	poetry run mkdocs build --strict



doctor:
	@command -v poetry >/dev/null 2>&1 || (echo "[error] Poetry is not installed"; exit 1)
	@command -v docker >/dev/null 2>&1 || (echo "[error] Docker is not installed"; exit 1)
	@test -f "$(LOCAL_ENV_FILE)" || (echo "[error] $(LOCAL_ENV_FILE) is missing; copy .env.example to $(LOCAL_ENV_FILE)"; exit 1)
	@poetry check >/dev/null
	@docker compose version >/dev/null
	@docker info >/dev/null 2>&1 || (echo "[error] Docker daemon is unavailable; start Docker Engine or another compatible daemon"; exit 1)
	@$(LOCAL_COMPOSE) --profile gateway config --quiet

	@echo "[ok] Poetry, Docker Compose, environment and project metadata are ready"

local-config:
	$(LOCAL_COMPOSE) --profile gateway config --quiet

local-start: local-config
	$(LOCAL_COMPOSE) --profile gateway up -d --wait

local-up: local-config
	$(LOCAL_COMPOSE) --profile gateway up -d --build --wait

local-up-stripe: local-config
	$(LOCAL_COMPOSE) --profile gateway --profile stripe up -d --build --wait

local-down:
	$(LOCAL_COMPOSE) --profile "*" down --remove-orphans

local-logs:
	$(LOCAL_COMPOSE) --profile gateway logs -f --tail=100

local-rebuild:
	$(LOCAL_COMPOSE) --profile gateway up -d --build --force-recreate --wait

stripe-up:
	$(LOCAL_COMPOSE) --profile stripe up -d stripe-cli

stripe-logs:
	$(LOCAL_COMPOSE) --profile stripe logs -f --tail=100 stripe-cli

migrate-core: local-start
	$(LOCAL_COMPOSE) exec -T core-api alembic -c apps/core_api/alembic.ini upgrade head

revision-core:
	@test -n "$(msg)" || (echo "Usage: make revision-core msg=create_domain"; exit 2)
	$(LOCAL_COMPOSE) exec -T core-api alembic -c apps/core_api/alembic.ini revision --autogenerate -m "$(msg)"

migrate-auth: local-start
	$(LOCAL_COMPOSE) exec -T auth-api alembic -c apps/auth_api/alembic.ini upgrade head

migrate-eventing: local-start
	$(LOCAL_COMPOSE) exec -T eventing-api alembic -c apps/eventing_api/alembic.ini upgrade head

migrate-notification: local-start
	$(LOCAL_COMPOSE) exec -T notification-api alembic -c apps/notification_api/alembic.ini upgrade head

revision-auth:
	@test -n "$(msg)" || (echo "Usage: make revision-auth msg=create_users"; exit 2)
	$(LOCAL_COMPOSE) exec -T auth-api alembic -c apps/auth_api/alembic.ini revision --autogenerate -m "$(msg)"

migrate: migrate-core migrate-auth migrate-eventing migrate-notification
	@echo "[ok] Selected database migrations are current"

migrate-all: migrate

seed-auth: migrate-auth
	$(LOCAL_COMPOSE) exec -T auth-api python toolbox/seeds/auth_admin.py

invite-lifetime: migrate
	@test -n "$(name)" -a -n "$(email)" -a -n "$(document_type)" -a -n "$(document_country)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: make invite-lifetime name='Full name' email=EMAIL document_type=BR_CPF document_country=BR locale=pt-BR actor=EMAIL reason='business reason'"; exit 2)
	$(LOCAL_COMPOSE) exec auth-api python toolbox/seeds/lifetime_invitation.py --name "$(name)" --email "$(email)" --document-type "$(document_type)" --document-country "$(document_country)" --locale "$(or $(locale),en)"
	$(LOCAL_COMPOSE) exec -T core-api python toolbox/seeds/lifetime_account.py grant --owner-email "$(email)" --actor "$(actor)" --reason "$(reason)"

grant-lifetime: migrate-core
	@test -n "$(tenant_id)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: make grant-lifetime tenant_id=UUID actor=EMAIL reason='business reason'"; exit 2)
	$(LOCAL_COMPOSE) exec -T core-api python toolbox/seeds/lifetime_account.py grant --tenant-id "$(tenant_id)" --actor "$(actor)" --reason "$(reason)"

revoke-lifetime: migrate-core
	@test -n "$(tenant_id)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: make revoke-lifetime tenant_id=UUID actor=EMAIL reason='business reason'"; exit 2)
	$(LOCAL_COMPOSE) exec -T core-api python toolbox/seeds/lifetime_account.py revoke --tenant-id "$(tenant_id)" --actor "$(actor)" --reason "$(reason)"





compose-up: local-up

bootstrap: compose-up migrate seed-auth
	@echo "[ok] Rubrica is ready at http://localhost:7171"

compose-down: local-down

production-config:
	$(PRODUCTION_COMPOSE) config --quiet
	@web_context="$$( $(PRODUCTION_COMPOSE) config --format json | python3 -c 'import json, sys; print(json.load(sys.stdin)["services"]["web"]["build"]["context"])' )"; \
		test -f "$$web_context/Dockerfile.prod" || (echo "[error] Frontend not found at $$web_context; set RUBRICA_WEB_CONTEXT=../../rubrica-front in $(PRODUCTION_ENV_FILE)"; exit 1)

production-up: production-config
	$(PRODUCTION_COMPOSE) up -d --build --wait

production-down:
	$(PRODUCTION_COMPOSE) down

production-logs:
	$(PRODUCTION_COMPOSE) logs -f --tail=100

production-migrate:
	$(PRODUCTION_COMPOSE) exec -T auth-api alembic -c apps/auth_api/alembic.ini upgrade head
	$(PRODUCTION_COMPOSE) exec -T core-api alembic -c apps/core_api/alembic.ini upgrade head
	$(PRODUCTION_COMPOSE) exec -T eventing-api alembic -c apps/eventing_api/alembic.ini upgrade head
	$(PRODUCTION_COMPOSE) exec -T notification-api alembic -c apps/notification_api/alembic.ini upgrade head

production-seed:
	$(PRODUCTION_COMPOSE) exec -T auth-api python toolbox/seeds/auth_admin.py

production-invite-lifetime: production-migrate
	@test -n "$(name)" -a -n "$(email)" -a -n "$(document_type)" -a -n "$(document_country)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: sudo make production-invite-lifetime name='Full name' email=EMAIL document_type=BR_CPF document_country=BR locale=pt-BR actor=EMAIL reason='business reason'"; exit 2)
	$(PRODUCTION_COMPOSE) exec auth-api python toolbox/seeds/lifetime_invitation.py --name "$(name)" --email "$(email)" --document-type "$(document_type)" --document-country "$(document_country)" --locale "$(or $(locale),en)"
	$(PRODUCTION_COMPOSE) exec -T core-api python toolbox/seeds/lifetime_account.py grant --owner-email "$(email)" --actor "$(actor)" --reason "$(reason)"

production-grant-lifetime: production-migrate
	@test -n "$(tenant_id)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: make production-grant-lifetime tenant_id=UUID actor=EMAIL reason='business reason'"; exit 2)
	$(PRODUCTION_COMPOSE) exec -T core-api python toolbox/seeds/lifetime_account.py grant --tenant-id "$(tenant_id)" --actor "$(actor)" --reason "$(reason)"

production-revoke-lifetime: production-migrate
	@test -n "$(tenant_id)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: make production-revoke-lifetime tenant_id=UUID actor=EMAIL reason='business reason'"; exit 2)
	$(PRODUCTION_COMPOSE) exec -T core-api python toolbox/seeds/lifetime_account.py revoke --tenant-id "$(tenant_id)" --actor "$(actor)" --reason "$(reason)"

backup:
	COMPOSE_FILE=$(LOCAL_COMPOSE_FILE) ENV_FILE=$(LOCAL_ENV_FILE) toolbox/operations/backup.sh $(BACKUP_ROOT)

backup-production:
	COMPOSE_FILE=$(PRODUCTION_COMPOSE_FILE) ENV_FILE=$(PRODUCTION_ENV_FILE) COMPOSE_PROJECT_NAME=rubrica-prod toolbox/operations/backup.sh $(BACKUP_ROOT)

backup-production-offsite:
	COMPOSE_FILE=$(PRODUCTION_COMPOSE_FILE) ENV_FILE=$(PRODUCTION_ENV_FILE) COMPOSE_PROJECT_NAME=rubrica-prod BACKUP_ROOT=$(BACKUP_ROOT) toolbox/operations/offsite_backup.sh create

verify-backup:
	@test -n "$(path)" || (echo "Usage: make verify-backup path=backups/TIMESTAMP"; exit 2)
	toolbox/operations/verify_backup.sh "$(path)"

smoke:
	@$(MAKE) --no-print-directory smoke-all

smoke-all:
	@$(MAKE) --no-print-directory smoke-core-generator
smoke-core-generator:
	poetry run python toolbox/smoke/core_generator.py
