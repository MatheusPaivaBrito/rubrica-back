ENV_FILE ?= .env
-include $(ENV_FILE)
export

CORE_API_PORT ?= 8100
CORE_WEB_CONCURRENCY ?= 2
AUTH_API_PORT ?= 8101
EVENTING_API_PORT ?= 8102
NOTIFICATION_API_PORT ?= 8103
OBSERVABILITY_API_PORT ?= 8104
AUTH_WEB_CONCURRENCY ?= 2
GATEWAY_HOST_PORT ?= 8180
GATEWAY_PORT ?= $(GATEWAY_HOST_PORT)
POSTGRES_HOST_PORT ?= 5435
REDIS_HOST_PORT ?= 6381
KAFKA_HOST_PORT ?= 9092
LOKI_HOST_PORT ?= 3100
GRAFANA_HOST_PORT ?= 3000
ALLOY_HOST_PORT ?= 12345



KIND ?= kind
KUBECTL ?= kubectl
K8S_KIND_CLUSTER ?= rubrica
K8S_NAMESPACE ?= rubrica

SHARED_PYTHONPATH = packages/shared_kernel/src
CORE_PYTHONPATH = apps/core_api/src:$(SHARED_PYTHONPATH)
AUTH_PYTHONPATH = apps/auth_api/src:$(SHARED_PYTHONPATH)
EVENTING_PYTHONPATH = apps/eventing_api/src:$(SHARED_PYTHONPATH)
NOTIFICATION_PYTHONPATH = apps/notification_api/src:$(SHARED_PYTHONPATH)
OBSERVABILITY_PYTHONPATH = apps/observability_api/src:$(SHARED_PYTHONPATH)
TEST_PYTHONPATH = .:apps/auth_api/src:apps/core_api/src:apps/eventing_api/src:apps/notification_api/src:apps/observability_api/src:apps/worker/src:packages/shared_kernel/src
COMPOSE_PROD_FILE ?= docker-compose.prod.yml
PROD_ENV_FILE ?= .env.production
BACKUP_ROOT ?= backups

MIGRATION_ENV = env -u DEBUG -u DATABASE_URL -u CORE_DATABASE_URL -u AUTH_DATABASE_URL -u EVENTING_DATABASE_URL -u NOTIFICATION_DATABASE_URL -u OBSERVABILITY_DATABASE_URL -u POSTGRES_HOST -u POSTGRES_PORT -u POSTGRES_HOST_PORT -u POSTGRES_DB -u CORE_POSTGRES_DB -u AUTH_POSTGRES_DB -u EVENTING_POSTGRES_DB -u NOTIFICATION_POSTGRES_DB -u OBSERVABILITY_POSTGRES_DB

.PHONY: help dev-all prod-all dev-core prod-core ensure-core dev-auth prod-auth ensure-auth doctor test lint docs-build compose-up compose-down bootstrap smoke smoke-all smoke-core-generator migrate migrate-core revision-core migrate-auth revision-auth migrate-eventing migrate-notification migrate-observability migrate-all seed-auth production-config production-up production-migrate production-seed backup backup-production verify-backup

help:
	@echo "Rubrica"
	@echo "============================================================"
	@echo "Development"
	@echo "  make dev-all             Run generated APIs together"
	@echo "  dev-core                 Run core_api"
	@echo "  dev-auth                 Run auth_api"
	@echo "  make prod-all            Run generated APIs with per-service Gunicorn workers"
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
	@echo "  make compose-up          Start Docker Compose"
	@echo "  make compose-down        Stop Docker Compose"
	@echo "  make bootstrap           Build containers, migrate databases and create the local admin"
	@echo "  make production-config  Validate the production Compose and secrets"
	@echo "  make production-up      Build and start the production stack"
	@echo "  make production-migrate Apply every production migration"
	@echo "  make backup-production  Back up all databases and signed documents"
	@echo "  make verify-backup path=backups/TIMESTAMP"


	@echo ""
	@echo "Project host endpoints"
	@echo "  Postgres   localhost:$(POSTGRES_HOST_PORT)"
	@echo "  Redis      localhost:$(REDIS_HOST_PORT)"
	@echo ""
	@echo "Database"
	@echo "  Postgres host endpoint: localhost:$(POSTGRES_HOST_PORT)"
	@echo "  make ensure-postgres     Start this project's isolated Postgres"
	@echo "  make migrate             Run Core and Auth database migrations"
	@echo "  make migrate-all         Alias for make migrate"
	@echo "  make migrate-core           Run Core Alembic migrations"
	@echo "  make revision-core msg=create_domain"
	@echo "  make migrate-auth           Run Auth Alembic migrations"
	@echo "  make seed-auth              Create the local signature administrator"
	@echo "  make revision-auth msg=create_users"



dev-all:
	@$(MAKE) --no-print-directory -j 2 dev-core dev-auth

prod-all:
	@$(MAKE) --no-print-directory -j 2 prod-core prod-auth

dev-core: ensure-core
	PYTHONPATH=$(CORE_PYTHONPATH) poetry run uvicorn core_api.main:app --host localhost --port $(CORE_API_PORT) --reload

prod-core: ensure-core
	PYTHONPATH=$(CORE_PYTHONPATH) poetry run gunicorn core_api.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$(CORE_API_PORT) --workers $(CORE_WEB_CONCURRENCY)

ensure-core:
	PYTHONPATH=$(CORE_PYTHONPATH) poetry run python toolbox/checks/ensure_runtime_dependencies.py core

dev-auth: ensure-auth
	PYTHONPATH=$(AUTH_PYTHONPATH) poetry run uvicorn auth_api.main:app --host localhost --port $(AUTH_API_PORT) --reload

prod-auth: ensure-auth
	PYTHONPATH=$(AUTH_PYTHONPATH) poetry run gunicorn auth_api.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$(AUTH_API_PORT) --workers $(AUTH_WEB_CONCURRENCY)

ensure-auth:
	PYTHONPATH=$(AUTH_PYTHONPATH) poetry run python toolbox/checks/ensure_runtime_dependencies.py auth

test:
	PYTHONPATH=$(TEST_PYTHONPATH) poetry run pytest

lint:
	PYTHONPATH=$(TEST_PYTHONPATH) poetry run ruff check .

docs-build:
	poetry run mkdocs build --strict



doctor:
	@command -v poetry >/dev/null 2>&1 || (echo "[error] Poetry is not installed"; exit 1)
	@command -v docker >/dev/null 2>&1 || (echo "[error] Docker is not installed"; exit 1)
	@test -f "$(ENV_FILE)" || (echo "[error] $(ENV_FILE) is missing; copy .env.local.example to $(ENV_FILE)"; exit 1)
	@poetry check >/dev/null
	@docker compose version >/dev/null
	@docker info >/dev/null 2>&1 || (echo "[error] Docker daemon is unavailable; start Docker Engine or another compatible daemon"; exit 1)
	@docker compose config >/dev/null

	@echo "[ok] Poetry, Docker Compose, environment and project metadata are ready"

ensure-postgres:
	docker compose up -d --wait --wait-timeout 90 postgres
	@echo "[ok] Project Postgres: localhost:$(POSTGRES_HOST_PORT)"

migrate-core: ensure-postgres
	PYTHONPATH=$(CORE_PYTHONPATH) $(MIGRATION_ENV) poetry run alembic -c apps/core_api/alembic.ini upgrade head

revision-core:
	@test -n "$(msg)" || (echo "Usage: make revision-core msg=create_domain"; exit 2)
	PYTHONPATH=$(CORE_PYTHONPATH) $(MIGRATION_ENV) poetry run alembic -c apps/core_api/alembic.ini revision --autogenerate -m "$(msg)"

migrate-auth: ensure-postgres
	PYTHONPATH=$(AUTH_PYTHONPATH) $(MIGRATION_ENV) poetry run alembic -c apps/auth_api/alembic.ini upgrade head

migrate-eventing: ensure-postgres
	PYTHONPATH=$(EVENTING_PYTHONPATH) $(MIGRATION_ENV) poetry run alembic -c apps/eventing_api/alembic.ini upgrade head

migrate-notification: ensure-postgres
	PYTHONPATH=$(NOTIFICATION_PYTHONPATH) $(MIGRATION_ENV) poetry run alembic -c apps/notification_api/alembic.ini upgrade head

migrate-observability: ensure-postgres
	PYTHONPATH=$(OBSERVABILITY_PYTHONPATH) $(MIGRATION_ENV) poetry run alembic -c apps/observability_api/alembic.ini upgrade head

revision-auth:
	@test -n "$(msg)" || (echo "Usage: make revision-auth msg=create_users"; exit 2)
	PYTHONPATH=$(AUTH_PYTHONPATH) $(MIGRATION_ENV) poetry run alembic -c apps/auth_api/alembic.ini revision --autogenerate -m "$(msg)"

migrate: migrate-core migrate-auth migrate-eventing migrate-notification migrate-observability
	@echo "[ok] Selected database migrations are current"

migrate-all: migrate

seed-auth: migrate-auth
	PYTHONPATH=$(AUTH_PYTHONPATH) poetry run python toolbox/seeds/auth_admin.py





compose-up:
	docker compose up -d --build

bootstrap: compose-up migrate seed-auth
	@echo "[ok] Rubrica is ready at http://localhost:8080"

compose-down:
	docker compose --profile "*" down --remove-orphans

production-config:
	docker compose --env-file $(PROD_ENV_FILE) -f $(COMPOSE_PROD_FILE) config --quiet

production-up: production-config
	docker compose --env-file $(PROD_ENV_FILE) -f $(COMPOSE_PROD_FILE) up -d --build --wait

production-migrate:
	docker compose --env-file $(PROD_ENV_FILE) -f $(COMPOSE_PROD_FILE) exec -T auth-api alembic -c apps/auth_api/alembic.ini upgrade head
	docker compose --env-file $(PROD_ENV_FILE) -f $(COMPOSE_PROD_FILE) exec -T core-api alembic -c apps/core_api/alembic.ini upgrade head
	docker compose --env-file $(PROD_ENV_FILE) -f $(COMPOSE_PROD_FILE) exec -T eventing-api alembic -c apps/eventing_api/alembic.ini upgrade head
	docker compose --env-file $(PROD_ENV_FILE) -f $(COMPOSE_PROD_FILE) exec -T notification-api alembic -c apps/notification_api/alembic.ini upgrade head
	docker compose --env-file $(PROD_ENV_FILE) -f $(COMPOSE_PROD_FILE) exec -T observability-api alembic -c apps/observability_api/alembic.ini upgrade head

production-seed:
	docker compose --env-file $(PROD_ENV_FILE) -f $(COMPOSE_PROD_FILE) exec -T auth-api python toolbox/seeds/auth_admin.py

backup:
	COMPOSE_FILE=docker-compose.yml ENV_FILE=$(ENV_FILE) toolbox/operations/backup.sh $(BACKUP_ROOT)

backup-production:
	COMPOSE_FILE=$(COMPOSE_PROD_FILE) ENV_FILE=$(PROD_ENV_FILE) toolbox/operations/backup.sh $(BACKUP_ROOT)

verify-backup:
	@test -n "$(path)" || (echo "Usage: make verify-backup path=backups/TIMESTAMP"; exit 2)
	toolbox/operations/verify_backup.sh "$(path)"

smoke:
	@$(MAKE) --no-print-directory smoke-all

smoke-all:
	@$(MAKE) --no-print-directory smoke-core-generator
smoke-core-generator:
	poetry run python toolbox/smoke/core_generator.py
