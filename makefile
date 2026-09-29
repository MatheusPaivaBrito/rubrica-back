LOCAL_ENV_FILE ?= .env
PRODUCTION_ENV_FILE ?= .env.production
-include $(LOCAL_ENV_FILE)
export

GATEWAY_HOST_PORT ?= 7171
LOCAL_TEST_ACCOUNT_PASSWORD ?= RubricaLocal123!



KIND ?= kind
KUBECTL ?= kubectl
K8S_KIND_CLUSTER ?= rubrica
K8S_NAMESPACE ?= rubrica

TEST_PYTHONPATH = .:apps/auth_api/src:apps/core_api/src:apps/eventing_api/src:apps/notification_api/src:apps/worker/src:packages/shared_kernel/src
TEST_ENV = env -u DEBUG
LOCAL_COMPOSE_FILE ?= compose/local.yml
PRODUCTION_COMPOSE_FILE ?= compose/production.yml
PRODUCTION_R2_COMPOSE_FILE ?= compose/features/r2-documents.yml
LOCAL_COMPOSE = docker compose --env-file $(LOCAL_ENV_FILE) -f $(LOCAL_COMPOSE_FILE)
PRODUCTION_COMPOSE = docker compose --env-file $(PRODUCTION_ENV_FILE) -f $(PRODUCTION_COMPOSE_FILE) -f $(PRODUCTION_R2_COMPOSE_FILE)
LOCAL_MAINTENANCE = $(LOCAL_COMPOSE) -f compose/services/alembic.yml
LOCAL_SEED = $(LOCAL_COMPOSE) -f compose/services/seed.yml
PRODUCTION_MAINTENANCE = $(PRODUCTION_COMPOSE) -f compose/services/alembic.yml -f compose/services/alembic-production.yml
BACKUP_ROOT ?= backups

.PHONY: help doctor test lint docs docs-build local-config local-start local-up local-up-stripe local-down local-reset local-logs local-rebuild compose-up compose-down bootstrap stripe-up stripe-logs migrate migrate-core revision-core migrate-auth revision-auth migrate-eventing migrate-notification migrate-all seed-auth seed-local-users invite-lifetime create-lifetime-tenant grant-lifetime revoke-lifetime reset-mfa production-config production-up production-down production-logs production-migrate production-seed production-invite-lifetime production-create-lifetime-tenant production-grant-lifetime production-revoke-lifetime production-reset-mfa production-organize-r2-documents backup backup-all backup-database backup-files backup-production backup-production-offsite backup-r2 backup-r2-init backup-r2-check verify-backup smoke smoke-all smoke-core-generator

help:
	@echo "Rubrica"
	@echo "============================================================"
	@echo "Local Docker"
	@echo "  make local-up            Build and start the local stack"
	@echo "  make local-up-stripe     Build local stack and start Stripe webhook forwarding"
	@echo "  make local-down          Stop the local stack"
	@echo "  make local-reset         Delete local database volumes, migrate, seed and start again"
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
	@echo "  make bootstrap           Migrate, seed local plan accounts, then start the stack"
	@echo "  make production-config  Validate the production Compose and secrets"
	@echo "  make production-up      Build and start the production stack"
	@echo "  make production-migrate Apply every production migration"
	@echo "  sudo make production-invite-lifetime name='...' email=... document_type=BR_CPF document_country=BR locale=pt-BR actor=EMAIL reason='...'"
	@echo "  sudo make production-create-lifetime-tenant owner_email=... member_email=... legal_name='...' actor=EMAIL reason='...'"
	@echo "  sudo make production-grant-lifetime tenant_id=UUID actor=EMAIL reason='...'"
	@echo "  sudo make production-revoke-lifetime tenant_id=UUID actor=EMAIL reason='...'"
	@echo "  sudo make production-reset-mfa email=EMAIL actor=EMAIL reason='...'"
	@echo "  sudo make production-organize-r2-documents [apply=1] [delete_source=1]"
	@echo "  make backup-all [environment=production]"
	@echo "  make backup-database database=all|core|auth|eventing|notification [environment=production]"
	@echo "  make backup-files [environment=production]"
	@echo "  make backup-production  Alias for backup-all environment=production"
	@echo "  sudo make backup-r2       Back up production databases and upload encrypted copy to R2"
	@echo "  sudo make backup-r2-init  Initialize the encrypted R2 backup repository once"
	@echo "  sudo make backup-r2-check Check the encrypted R2 backup repository"
	@echo "  make backup-production-offsite  Alias for backup-r2"
	@echo "  make verify-backup path=backups/TIMESTAMP"


	@echo ""
	@echo "Project host endpoints"
	@echo "  Gateway    http://localhost:$(GATEWAY_HOST_PORT)"
	@echo ""
	@echo "Database"
	@echo "  Postgres and Redis are available only inside the Compose network"
	@echo "  make migrate             Run all four databases in a one-shot container"
	@echo "  make migrate-all         Alias for make migrate"
	@echo "  make migrate-core           Run Core Alembic migrations"
	@echo "  make revision-core msg=create_domain"
	@echo "  make migrate-auth           Run Auth Alembic migrations"
	@echo "  make seed-auth              Create the local signature administrator"
	@echo "  make seed-local-users       Create 14 local test accounts across all implemented plans"
	@echo "  make invite-lifetime name='...' email=... document_type=BR_CPF document_country=BR locale=pt-BR actor=EMAIL reason='...'"
	@echo "  make create-lifetime-tenant owner_email=... member_email=... legal_name='...' actor=EMAIL reason='...'"
	@echo "  make grant-lifetime tenant_id=UUID actor=EMAIL reason='...'"
	@echo "  make revoke-lifetime tenant_id=UUID actor=EMAIL reason='...'"
	@echo "  make reset-mfa email=EMAIL actor=EMAIL reason='...'"
	@echo "  make revision-auth msg=create_users"



test:
	PYTHONPATH=$(TEST_PYTHONPATH) $(TEST_ENV) poetry run pytest

lint:
	PYTHONPATH=$(TEST_PYTHONPATH) poetry run ruff check .

docs:
	poetry run python -m toolbox.docs.local_accounts
	poetry run mkdocs serve -f mkdocs.local.yml --dev-addr 127.0.0.1:8000

docs-build:
	poetry run python -m toolbox.docs.local_accounts
	poetry run mkdocs build --strict



doctor:
	@command -v poetry >/dev/null 2>&1 || (echo "[error] Poetry is not installed"; exit 1)
	@command -v docker >/dev/null 2>&1 || (echo "[error] Docker is not installed"; exit 1)
	@test -f "$(LOCAL_ENV_FILE)" || (echo "[error] $(LOCAL_ENV_FILE) is missing; copy .env.example to $(LOCAL_ENV_FILE)"; exit 1)
	@poetry check >/dev/null
	@docker compose version >/dev/null
	@docker info >/dev/null 2>&1 || (echo "[error] Docker daemon is unavailable; start Docker Engine or another compatible daemon"; exit 1)
	@$(LOCAL_COMPOSE) config --quiet

	@echo "[ok] Poetry, Docker Compose, environment and project metadata are ready"

local-config:
	$(LOCAL_COMPOSE) config --quiet

local-start: local-config
	$(LOCAL_COMPOSE) up -d --wait

local-up: local-config
	$(LOCAL_COMPOSE) up -d --build --wait

local-up-stripe: local-config
	$(LOCAL_COMPOSE) up -d --build --wait

local-down:
	$(LOCAL_COMPOSE) --profile "*" down --remove-orphans

local-reset:
	@test "$(environment)" != "production" || (echo "[error] Local reset cannot run in production"; exit 2)
	$(LOCAL_COMPOSE) --profile "*" down --volumes --remove-orphans
	$(MAKE) bootstrap

local-logs:
	$(LOCAL_COMPOSE) logs -f --tail=100

local-rebuild:
	$(LOCAL_COMPOSE) up -d --build --force-recreate --wait

stripe-up:
	$(LOCAL_COMPOSE) up -d stripe-cli

stripe-logs:
	$(LOCAL_COMPOSE) logs -f --tail=100 stripe-cli

migrate-core:
	$(LOCAL_MAINTENANCE) run --rm --build alembic python toolbox/database/migrate.py core

revision-core:
	@test -n "$(msg)" || (echo "Usage: make revision-core msg=create_domain"; exit 2)
	$(LOCAL_COMPOSE) exec -T core-api alembic -c apps/core_api/alembic.ini revision --autogenerate -m "$(msg)"

migrate-auth:
	$(LOCAL_MAINTENANCE) run --rm --build alembic python toolbox/database/migrate.py auth

migrate-eventing:
	$(LOCAL_MAINTENANCE) run --rm --build alembic python toolbox/database/migrate.py eventing

migrate-notification:
	$(LOCAL_MAINTENANCE) run --rm --build alembic python toolbox/database/migrate.py notification

revision-auth:
	@test -n "$(msg)" || (echo "Usage: make revision-auth msg=create_users"; exit 2)
	$(LOCAL_COMPOSE) exec -T auth-api alembic -c apps/auth_api/alembic.ini revision --autogenerate -m "$(msg)"

migrate:
	$(LOCAL_MAINTENANCE) run --rm --build alembic

migrate-all: migrate

seed-auth: migrate-auth
	$(LOCAL_COMPOSE) exec -T auth-api python toolbox/seeds/auth_admin.py

seed-local-users:
	@test "$(environment)" != "production" || (echo "[error] Test seed is local only"; exit 2)
	$(LOCAL_SEED) run --rm --build seed


invite-lifetime: migrate
	@test -n "$(name)" -a -n "$(email)" -a -n "$(document_type)" -a -n "$(document_country)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: make invite-lifetime name='Full name' email=EMAIL document_type=BR_CPF document_country=BR locale=pt-BR actor=EMAIL reason='business reason'"; exit 2)
	$(LOCAL_COMPOSE) exec auth-api python toolbox/seeds/lifetime_invitation.py --name "$(name)" --email "$(email)" --document-type "$(document_type)" --document-country "$(document_country)" --locale "$(or $(locale),en)"
	$(LOCAL_COMPOSE) exec -T core-api python toolbox/seeds/lifetime_account.py grant --owner-email "$(email)" --actor "$(actor)" --reason "$(reason)"

create-lifetime-tenant: migrate
	@test -n "$(owner_email)" -a -n "$(member_email)" -a -n "$(legal_name)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: make create-lifetime-tenant owner_email=EMAIL member_email=EMAIL legal_name='Legal name' actor=EMAIL reason='business reason'"; exit 2)
	$(LOCAL_COMPOSE) up -d --build auth-api
	$(LOCAL_COMPOSE) run --rm --build core-api python toolbox/seeds/lifetime_account.py grant --owner-email "$(owner_email)" --actor "$(actor)" --reason "$(reason)"
	$(LOCAL_COMPOSE) run --rm --build core-api python toolbox/seeds/business_tenant.py --owner-email "$(owner_email)" --member-email "$(member_email)" --legal-name "$(legal_name)" --actor "$(actor)"

grant-lifetime: migrate-core
	@test -n "$(tenant_id)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: make grant-lifetime tenant_id=UUID actor=EMAIL reason='business reason'"; exit 2)
	$(LOCAL_COMPOSE) exec -T core-api python toolbox/seeds/lifetime_account.py grant --tenant-id "$(tenant_id)" --actor "$(actor)" --reason "$(reason)"

revoke-lifetime: migrate-core
	@test -n "$(tenant_id)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: make revoke-lifetime tenant_id=UUID actor=EMAIL reason='business reason'"; exit 2)
	$(LOCAL_COMPOSE) exec -T core-api python toolbox/seeds/lifetime_account.py revoke --tenant-id "$(tenant_id)" --actor "$(actor)" --reason "$(reason)"

reset-mfa: migrate-auth
	@test -n "$(email)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: make reset-mfa email=EMAIL actor=EMAIL reason='business reason'"; exit 2)
	$(LOCAL_COMPOSE) run --rm --build auth-api python toolbox/seeds/reset_mfa.py --email "$(email)" --actor "$(actor)" --reason "$(reason)"





compose-up: local-up

bootstrap:
	$(MAKE) migrate
	$(MAKE) seed-local-users
	$(MAKE) local-up
	@echo "[ok] Rubrica is ready at http://localhost:7171"

compose-down: local-down

production-config:
	python3 toolbox/checks/production_readiness.py $(PRODUCTION_ENV_FILE)
	$(PRODUCTION_COMPOSE) config --quiet
	@web_context="$$( $(PRODUCTION_COMPOSE) config --format json | python3 -c 'import json, sys; print(json.load(sys.stdin)["services"]["web"]["build"]["context"])' )"; \
		test -f "$$web_context/Dockerfile.prod" || (echo "[error] Frontend not found at $$web_context; set RUBRICA_WEB_CONTEXT=../../../rubrica-front in $(PRODUCTION_ENV_FILE)"; exit 1)

production-up: production-config
	$(PRODUCTION_COMPOSE) up -d --build --wait

production-down:
	$(PRODUCTION_COMPOSE) down

production-logs:
	$(PRODUCTION_COMPOSE) logs -f --tail=100

production-migrate:
	$(PRODUCTION_MAINTENANCE) run --rm --build alembic python toolbox/database/migrate.py $(or $(database),all)

production-seed:
	$(PRODUCTION_COMPOSE) exec -T auth-api python toolbox/seeds/auth_admin.py

production-invite-lifetime: production-migrate
	@test -n "$(name)" -a -n "$(email)" -a -n "$(document_type)" -a -n "$(document_country)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: sudo make production-invite-lifetime name='Full name' email=EMAIL document_type=BR_CPF document_country=BR locale=pt-BR actor=EMAIL reason='business reason'"; exit 2)
	$(PRODUCTION_COMPOSE) exec auth-api python toolbox/seeds/lifetime_invitation.py --name "$(name)" --email "$(email)" --document-type "$(document_type)" --document-country "$(document_country)" --locale "$(or $(locale),en)"
	$(PRODUCTION_COMPOSE) exec -T core-api python toolbox/seeds/lifetime_account.py grant --owner-email "$(email)" --actor "$(actor)" --reason "$(reason)"

production-create-lifetime-tenant: production-migrate
	@test -n "$(owner_email)" -a -n "$(member_email)" -a -n "$(legal_name)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: sudo make production-create-lifetime-tenant owner_email=EMAIL member_email=EMAIL legal_name='Legal name' actor=EMAIL reason='business reason'"; exit 2)
	$(PRODUCTION_COMPOSE) up -d --build auth-api
	$(PRODUCTION_COMPOSE) run --rm --build core-api python toolbox/seeds/lifetime_account.py grant --owner-email "$(owner_email)" --actor "$(actor)" --reason "$(reason)"
	$(PRODUCTION_COMPOSE) run --rm --build core-api python toolbox/seeds/business_tenant.py --owner-email "$(owner_email)" --member-email "$(member_email)" --legal-name "$(legal_name)" --actor "$(actor)"

production-grant-lifetime: production-migrate
	@test -n "$(tenant_id)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: make production-grant-lifetime tenant_id=UUID actor=EMAIL reason='business reason'"; exit 2)
	$(PRODUCTION_COMPOSE) exec -T core-api python toolbox/seeds/lifetime_account.py grant --tenant-id "$(tenant_id)" --actor "$(actor)" --reason "$(reason)"

production-revoke-lifetime: production-migrate
	@test -n "$(tenant_id)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: make production-revoke-lifetime tenant_id=UUID actor=EMAIL reason='business reason'"; exit 2)
	$(PRODUCTION_COMPOSE) exec -T core-api python toolbox/seeds/lifetime_account.py revoke --tenant-id "$(tenant_id)" --actor "$(actor)" --reason "$(reason)"

production-reset-mfa: production-migrate
	@test -n "$(email)" -a -n "$(actor)" -a -n "$(reason)" || (echo "Usage: sudo make production-reset-mfa email=EMAIL actor=EMAIL reason='business reason'"; exit 2)
	$(PRODUCTION_COMPOSE) run --rm --build auth-api python toolbox/seeds/reset_mfa.py --email "$(email)" --actor "$(actor)" --reason "$(reason)"

production-organize-r2-documents: production-migrate
	$(PRODUCTION_COMPOSE) run --rm --build core-api python toolbox/operations/reorganize_r2_documents.py $(if $(filter 1,$(apply)),--apply) $(if $(filter 1,$(delete_source)),--delete-source)

BACKUP_COMPOSE_FILE = $(if $(filter production,$(environment)),$(PRODUCTION_COMPOSE_FILE),$(LOCAL_COMPOSE_FILE))
BACKUP_ENV_FILE = $(if $(filter production,$(environment)),$(PRODUCTION_ENV_FILE),$(LOCAL_ENV_FILE))
BACKUP_PROJECT = $(if $(filter production,$(environment)),rubrica-prod,rubrica)

backup: backup-all

backup-all:
	COMPOSE_FILE=$(BACKUP_COMPOSE_FILE) ENV_FILE=$(BACKUP_ENV_FILE) COMPOSE_PROJECT_NAME=$(BACKUP_PROJECT) BACKUP_INCLUDE_DATABASES=1 BACKUP_INCLUDE_DOCUMENTS=1 BACKUP_DATABASE=all toolbox/operations/backup.sh $(BACKUP_ROOT)

backup-database:
	COMPOSE_FILE=$(BACKUP_COMPOSE_FILE) ENV_FILE=$(BACKUP_ENV_FILE) COMPOSE_PROJECT_NAME=$(BACKUP_PROJECT) BACKUP_INCLUDE_DATABASES=1 BACKUP_INCLUDE_DOCUMENTS=0 BACKUP_DATABASE=$(or $(database),all) toolbox/operations/backup.sh $(BACKUP_ROOT)

backup-files:
	COMPOSE_FILE=$(BACKUP_COMPOSE_FILE) ENV_FILE=$(BACKUP_ENV_FILE) COMPOSE_PROJECT_NAME=$(BACKUP_PROJECT) BACKUP_INCLUDE_DATABASES=0 BACKUP_INCLUDE_DOCUMENTS=1 toolbox/operations/backup.sh $(BACKUP_ROOT)

backup-production:
	@$(MAKE) --no-print-directory backup-all environment=production BACKUP_ROOT=$(BACKUP_ROOT)

backup-production-offsite:
	@$(MAKE) --no-print-directory backup-r2

backup-r2:
	toolbox/operations/r2_backup.sh create

backup-r2-init:
	toolbox/operations/r2_backup.sh init

backup-r2-check:
	toolbox/operations/r2_backup.sh check

verify-backup:
	@test -n "$(path)" || (echo "Usage: make verify-backup path=backups/TIMESTAMP"; exit 2)
	toolbox/operations/verify_backup.sh "$(path)"

smoke:
	@$(MAKE) --no-print-directory smoke-all

smoke-all:
	@$(MAKE) --no-print-directory smoke-core-generator
smoke-core-generator:
	poetry run python toolbox/smoke/core_generator.py
