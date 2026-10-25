LOCAL_ENV_FILE ?= .env
DEV_ENV_FILE ?= $(LOCAL_ENV_FILE)
STAGING_ENV_FILE ?= .env.staging
PRODUCTION_ENV_FILE ?= .env.production
DOCS_ENV_FILE ?= $(if $(wildcard $(DEV_ENV_FILE)),$(DEV_ENV_FILE),.env.example)
-include $(LOCAL_ENV_FILE)
export

GATEWAY_HOST_PORT ?= 7171
LOCAL_TEST_ACCOUNT_PASSWORD ?= RubricaLocal123!



KIND ?= kind
KUBECTL ?= kubectl
K8S_KIND_CLUSTER ?= rubrica
K8S_NAMESPACE ?= rubrica

TEST_PYTHONPATH = .:apps/auth_api/src:apps/core_api/src:apps/eventing_api/src:apps/notification_api/src:apps/observability_api/src:apps/worker/src:packages/shared_kernel/src
TEST_ENV = env -u DEBUG
comma := ,
LOCAL_COMPOSE_FILE ?= compose/dev-dependencies.yml
DEV_COMPOSE_FILE ?= compose/dev-dependencies.yml
STAGING_COMPOSE_FILE ?= compose/staging.yml
PRODUCTION_COMPOSE_FILE ?= compose/production.yml
PRODUCTION_R2_COMPOSE_FILE ?= compose/features/r2-documents.yml
PRODUCTION_TIMESTAMP_COMPOSE_FILE ?= compose/features/serpro-timestamp.yml
LOCAL_COMPOSE = docker compose --env-file $(LOCAL_ENV_FILE) -f $(LOCAL_COMPOSE_FILE)
DEV_COMPOSE = docker compose --env-file $(DEV_ENV_FILE) -f $(DEV_COMPOSE_FILE)
DOCS_COMPOSE = docker compose --env-file $(DOCS_ENV_FILE) -f $(DEV_COMPOSE_FILE)
# Prevent values exported from the development .env above from overriding the
# explicit staging/production env files (shell variables outrank --env-file).
ISOLATED_COMPOSE = env -i PATH="$(PATH)" HOME="$(HOME)" docker compose
STAGING_COMPOSE = $(ISOLATED_COMPOSE) --env-file $(STAGING_ENV_FILE) -f $(STAGING_COMPOSE_FILE) -f compose/features/r2-documents.yml -f compose/features/serpro-timestamp.yml
PRODUCTION_COMPOSE = $(ISOLATED_COMPOSE) --env-file $(PRODUCTION_ENV_FILE) -f $(PRODUCTION_COMPOSE_FILE) -f $(PRODUCTION_R2_COMPOSE_FILE) -f $(PRODUCTION_TIMESTAMP_COMPOSE_FILE)
LOCAL_MAINTENANCE = $(LOCAL_COMPOSE) -f compose/services/alembic.yml
LOCAL_SEED = $(LOCAL_COMPOSE) -f compose/services/seed.yml
DEV_MAINTENANCE = $(DEV_COMPOSE) -f compose/services/alembic.yml
DEV_SEED = $(DEV_COMPOSE) -f compose/services/seed.yml
PRODUCTION_MAINTENANCE = $(PRODUCTION_COMPOSE) -f compose/services/alembic.yml -f compose/services/alembic-production.yml
STAGING_MAINTENANCE = $(STAGING_COMPOSE) -f compose/services/alembic.yml -f compose/services/alembic-production.yml
STAGING_SEED = $(STAGING_COMPOSE) -f compose/services/alembic.yml -f compose/services/seed-staging.yml
STAGING_TOOLS_IMAGE ?= rubrica-staging-tools:local
STAGING_TOOLS = docker run --rm -i --volume "$(CURDIR):/app" --workdir /app $(STAGING_TOOLS_IMAGE)
PRODUCTION_SECRETS_DIR ?= /etc/rubrica/secrets
STAGING_SECRETS_DIR ?= $(CURDIR)/.secrets/staging
BACKUP_ROOT ?= backups
ECNPJ_DOCUMENT_DIR ?= /srv/rubrica-ecnpj
ECNPJ_PFX_FILE ?= /etc/rubrica/secrets/empresa-ecnpj-a1.pfx
ECNPJ_ICP_TRUST_ROOTS_FILE ?= /etc/rubrica/secrets/icp-brasil-trust-roots.pem
ECNPJ_SIGNATURE_POLICY_FILE ?= /etc/rubrica/policies/PA_PAdES_AD_RB_v1_3.der
ECNPJ_SIGNATURE_POLICY_URL ?= http://politicas.icpbrasil.gov.br/PA_PAdES_AD_RB_v1_3.der

.PHONY: help help-production dev dev-bootstrap dev-docker dev-docker-down dev-docker-status dev-docker-logs dev-migrate dev-seed staging-secrets-init staging-ensure staging-bootstrap staging-up staging-down staging-status staging-logs staging-public-url staging-docs-url staging-migrate staging-seed staging-smoke production-ensure production-bootstrap production-status production-provider-check production-provider-check-paid doctor test test-unit test-integration lint docs docs-up docs-logs docs-build telemetry-up telemetry-down telemetry-status telemetry-smoke quick-tunnel-up quick-tunnel-down quick-tunnel-logs ensure-observability-network ensure-local-databases ensure-integration-services ensure-production-databases local-config local-start local-up local-up-stripe local-down local-reset local-logs local-rebuild compose-up compose-down bootstrap stripe-up stripe-down stripe-logs migrate migrate-core revision-core migrate-auth revision-auth migrate-eventing migrate-notification migrate-observability migrate-all seed-auth seed-local-users invite-lifetime create-lifetime-tenant grant-lifetime revoke-lifetime reset-mfa production-config production-up production-down production-logs production-migrate production-seed production-invite-lifetime production-create-lifetime-tenant production-grant-lifetime production-revoke-lifetime production-reset-mfa production-organize-r2-documents production-sign-ecnpj backup backup-all backup-database backup-files backup-production backup-production-offsite backup-r2 backup-r2-init backup-r2-check verify-backup smoke smoke-all smoke-core-generator
.PHONY: staging-clone-core-from-production staging-clone-r2-documents staging-encrypt-r2-documents document-crypto-benchmark

help:
	@echo "Rúbrica — comandos por ambiente"
	@echo "============================================================"
	@echo "Desenvolvimento — aplicações bare metal com hot reload"
	@echo "  make dev                       Inicia frontend e APIs; não inicia infraestrutura"
	@echo "  make dev-docker                Inicia PostgreSQL/Redis e depois as aplicações"
	@echo "  make dev-docker services=postgres,loki"
	@echo "  make dev-bootstrap             Primeira preparação: .env, banco, migrations e seed"
	@echo "  make dev-migrate               Aplica migrations no banco de desenvolvimento"
	@echo "  make dev-seed                  Cria/atualiza as contas locais de teste"
	@echo ""
	@echo "Ferramentas opcionais de desenvolvimento"
	@echo "  make docs                      Abre MkDocs em http://127.0.0.1:7190 (.env é opcional)"
	@echo "  make docs-logs                 Acompanha os logs do MkDocs"
	@echo "  make stripe-up                 Inicia Stripe CLI"
	@echo "  make quick-tunnel-up           Inicia Cloudflare Quick Tunnel"
	@echo "  make telemetry-up              Inicia Loki local"
	@echo ""
	@echo "Staging — aplicação completa em Docker"
	@echo "  make staging-secrets-init      Cria somente os secrets isolados de staging"
	@echo "  make staging-bootstrap         Executa migrations, seed, stack completa e smoke"
	@echo "  make staging-up                Sobe stack e túnel Cloudflare nomeado sem migration/seed"
	@echo "  make staging-migrate           Aplica migrations nos cinco bancos de staging"
	@echo "  make staging-seed              Cria/atualiza as mesmas contas de teste no staging"
	@echo "  make staging-status            Exibe todos os contêineres"
	@echo "  make staging-smoke             Valida stack e gateway"
	@echo "  make staging-logs              Acompanha os logs"
	@echo "  make staging-public-url        Mostra a URL pública estável do staging"
	@echo "  make staging-docs-url          Mostra a URL pública das contas de teste"
	@echo "  make staging-down              Encerra preservando volumes"
	@echo "  make staging-clone-core-from-production confirm=CLONE_PRODUCTION_CORE_TO_STAGING"
	@echo "  make staging-clone-r2-documents [apply=1]  Clona objetos referenciados"
	@echo "  make staging-encrypt-r2-documents [apply=1] Audita/migra criptografia"
	@echo ""
	@echo "Qualidade"
	@echo "  make doctor                    Verifica ferramentas e configuração de dev"
	@echo "  make lint                      Executa Ruff"
	@echo "  make test-unit                 Executa testes unitários"
	@echo "  make test-integration          Executa testes reais com PostgreSQL/Redis"
	@echo "  make document-crypto-benchmark Mede criptografia em chunks sem a rede R2"
	@echo ""
	@echo "Produção — resumo; use 'make help-production' para operações avançadas"
	@echo "  make production-ensure        Valida ambiente sem alterar produção"
	@echo "  make production-migrate       Aplica migrations explicitamente"
	@echo "  make production-up            Constrói e sobe a stack"
	@echo "  make production-status        Exibe o estado dos serviços"
	@echo "  make production-provider-check Verifica providers seguros"

help-production:
	@echo "Rúbrica — operações avançadas de produção"
	@echo "============================================================"
	@echo "  make production-bootstrap"
	@echo "  make production-logs"
	@echo "  make production-sign-ecnpj input=documento.pdf output=documento_assinado.pdf"
	@echo "  sudo make production-invite-lifetime name='...' email=... document_type=BR_CPF document_country=BR locale=pt-BR actor=EMAIL reason='...'"
	@echo "  sudo make production-create-lifetime-tenant owner_email=... member_email=... legal_name='...' actor=EMAIL reason='...'"
	@echo "  sudo make production-grant-lifetime tenant_id=UUID actor=EMAIL reason='...'"
	@echo "  sudo make production-revoke-lifetime tenant_id=UUID actor=EMAIL reason='...'"
	@echo "  sudo make production-reset-mfa email=EMAIL actor=EMAIL reason='...'"
	@echo "  sudo make production-organize-r2-documents [apply=1] [delete_source=1]"
	@echo "  make backup-all [environment=production]"
	@echo "  make backup-database database=all|core|auth|eventing|notification|observability [environment=production]"
	@echo "  make backup-files [environment=production]"
	@echo "  make backup-production  Alias for backup-all environment=production"
	@echo "  sudo make backup-r2       Back up production databases and upload encrypted copy to R2"
	@echo "  sudo make backup-r2-init  Initialize the encrypted R2 backup repository once"
	@echo "  sudo make backup-r2-check Check the encrypted R2 backup repository"
	@echo "  make backup-production-offsite  Alias for backup-r2"
	@echo "  make verify-backup path=backups/TIMESTAMP"

dev:
	@test -f "$(DEV_ENV_FILE)" || (echo "[error] $(DEV_ENV_FILE) is missing; copy .env.example to $(DEV_ENV_FILE)"; exit 2)
	DEV_ENV_FILE=$(DEV_ENV_FILE) poetry run python toolbox/dev/run.py

dev-docker:
	@test -f "$(DEV_ENV_FILE)" || (echo "[error] $(DEV_ENV_FILE) is missing; run 'make dev-bootstrap'"; exit 2)
	DEV_ENV_FILE=$(DEV_ENV_FILE) poetry run python toolbox/dev/dependencies.py "$(services)"
	$(MAKE) --no-print-directory dev DEV_ENV_FILE=$(DEV_ENV_FILE)

dev-docker-down:
	$(DEV_COMPOSE) --profile "*" down --remove-orphans

dev-docker-status:
	$(DEV_COMPOSE) --profile "*" ps -a

dev-docker-logs:
	$(DEV_COMPOSE) --profile "*" logs -f --tail=100 $(if $(services),$(subst $(comma), ,$(services)),)

dev-migrate:
	DEV_ENV_FILE=$(DEV_ENV_FILE) poetry run python toolbox/dev/dependencies.py postgres
	$(DEV_MAINTENANCE) run --rm --build alembic

dev-seed:
	DEV_ENV_FILE=$(DEV_ENV_FILE) poetry run python toolbox/dev/dependencies.py postgres,redis
	$(DEV_SEED) run --rm --build seed

dev-bootstrap:
	@test -f "$(DEV_ENV_FILE)" || cp .env.example "$(DEV_ENV_FILE)"
	$(MAKE) --no-print-directory dev-migrate DEV_ENV_FILE=$(DEV_ENV_FILE) LOCAL_ENV_FILE=$(DEV_ENV_FILE)
	$(MAKE) --no-print-directory dev-seed DEV_ENV_FILE=$(DEV_ENV_FILE) LOCAL_ENV_FILE=$(DEV_ENV_FILE)
	$(MAKE) --no-print-directory dev-docker DEV_ENV_FILE=$(DEV_ENV_FILE) services="$(services)"

.PHONY: staging-tools-build
staging-tools-build:
	docker build --tag $(STAGING_TOOLS_IMAGE) --file apps/core_api/dockerfile .

staging-secrets-init: staging-tools-build
	@test -f "$(STAGING_ENV_FILE)" || cp .env.staging.example "$(STAGING_ENV_FILE)"
	docker run --rm -i --volume "$(CURDIR):/app" --workdir /app --env STAGING_ENV_FILE=$(STAGING_ENV_FILE) $(STAGING_TOOLS_IMAGE) python -m toolbox.dev.init_staging_secrets

staging-ensure: ensure-observability-network staging-tools-build
	$(STAGING_TOOLS) python -m toolbox.checks.staging_readiness "$(STAGING_ENV_FILE)"
	$(STAGING_COMPOSE) config --quiet
	@$(STAGING_COMPOSE) config --format json | $(STAGING_TOOLS) python toolbox/checks/compose_contract.py staging

staging-up: staging-ensure
	$(STAGING_COMPOSE) up -d --build --wait
	@$(MAKE) --no-print-directory staging-public-url STAGING_ENV_FILE=$(STAGING_ENV_FILE)

staging-down:
	$(STAGING_COMPOSE) down --remove-orphans

staging-status:
	$(STAGING_COMPOSE) ps -a

staging-logs:
	$(STAGING_COMPOSE) logs -f --tail=100

staging-public-url:
	@base="$$(sed -n 's/^PUBLIC_WEB_URL=//p' "$(STAGING_ENV_FILE)" | tail -n 1)"; \
		test -n "$$base" || (echo "[error] PUBLIC_WEB_URL não está configurada em $(STAGING_ENV_FILE)"; exit 2); \
		echo "[ok] Rubrica staging: $$base"; \
		echo "[ok] Contas de teste: $$base/test-accounts/"

staging-docs-url:
	@base="$$(sed -n 's/^PUBLIC_WEB_URL=//p' "$(STAGING_ENV_FILE)" | tail -n 1)"; \
		test -n "$$base" || (echo "[error] PUBLIC_WEB_URL não está configurada em $(STAGING_ENV_FILE)"; exit 2); \
		echo "$$base/test-accounts/"

staging-migrate: staging-ensure
	$(STAGING_COMPOSE) up -d --wait postgres
	$(STAGING_COMPOSE) exec -T postgres bash /docker-entrypoint-initdb.d/init-multiple-databases.sh
	$(STAGING_MAINTENANCE) run --rm --build alembic python toolbox/database/migrate.py all

staging-seed: staging-migrate
	$(STAGING_SEED) run --rm --build seed

staging-smoke: staging-ensure
	$(STAGING_COMPOSE) ps --status running
	@test -n "$$($(STAGING_COMPOSE) ps --services --status running cloudflared)" || (echo "[error] staging named Cloudflare Tunnel is not running"; exit 2)
	@curl -fsS "http://127.0.0.1:$${STAGING_GATEWAY_HOST_PORT:-7271}/" >/dev/null
	@curl -fsS "http://127.0.0.1:$${STAGING_GATEWAY_HOST_PORT:-7271}/test-accounts/" >/dev/null
	@echo "[ok] staging gateway, test accounts, named Cloudflare Tunnel and required containers are operational"

.PHONY: staging-encrypt-r2-documents
staging-encrypt-r2-documents: staging-ensure
	$(STAGING_MAINTENANCE) run --rm --build alembic python -m toolbox.operations.encrypt_r2_documents $(if $(apply),--apply,)

staging-clone-core-from-production:
	@test "$(confirm)" = "CLONE_PRODUCTION_CORE_TO_STAGING" || (echo "[error] esta operação substitui somente o banco Core de staging; use confirm=CLONE_PRODUCTION_CORE_TO_STAGING"; exit 2)
	@set -eu; \
		dump_file="$$(mktemp /tmp/rubrica-core-clone.XXXXXX.dump)"; \
		production_core_db="$$(sed -n 's/^CORE_POSTGRES_DB=//p' "$(PRODUCTION_ENV_FILE)" | tail -n 1)"; \
		staging_core_db="$$(sed -n 's/^CORE_POSTGRES_DB=//p' "$(STAGING_ENV_FILE)" | tail -n 1)"; \
		production_core_db="$${production_core_db:-rubrica_core}"; \
		staging_core_db="$${staging_core_db:-rubrica_core}"; \
		trap 'rm -f "$$dump_file"' EXIT; \
		$(STAGING_COMPOSE) stop core-api auth-api eventing-api notification-api observability-api gateway web docs cloudflared >/dev/null; \
		$(PRODUCTION_COMPOSE) exec -T postgres sh -c 'pg_dump -U "$$POSTGRES_USER" -Fc "$$1"' _ "$$production_core_db" >"$$dump_file"; \
		test -s "$$dump_file"; \
		$(STAGING_COMPOSE) exec -T postgres sh -c 'psql -U "$$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -v core_db="$$1" -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:'"'"'core_db'"'"' AND pid <> pg_backend_pid()" >/dev/null' _ "$$staging_core_db"; \
		$(STAGING_COMPOSE) exec -T postgres sh -c 'dropdb -U "$$POSTGRES_USER" --if-exists "$$1" && createdb -U "$$POSTGRES_USER" "$$1"' _ "$$staging_core_db"; \
		$(STAGING_COMPOSE) exec -T postgres sh -c 'pg_restore -U "$$POSTGRES_USER" -d "$$1" --no-owner --no-privileges --exit-on-error' _ "$$staging_core_db" <"$$dump_file"; \
		echo "[ok] rubrica_core restaurado no PostgreSQL isolado de staging; aplicação e integrações permanecem paradas"

staging-clone-r2-documents: staging-ensure
	@test -d "$(PRODUCTION_SECRETS_DIR)" || (echo "[error] diretório de secrets de produção ausente"; exit 2)
	@test -d "$(STAGING_SECRETS_DIR)" || (echo "[error] diretório de secrets de staging ausente"; exit 2)
	$(STAGING_MAINTENANCE) run --rm --build \
		-v "$(PRODUCTION_SECRETS_DIR):/run/production-r2:ro" \
		-v "$(STAGING_SECRETS_DIR):/run/staging-r2:ro" \
		alembic python -m toolbox.operations.clone_r2_documents_to_staging \
		--source-endpoint-file /run/production-r2/r2_documents_endpoint \
		--source-access-key-id-file /run/production-r2/r2_documents_access_key_id \
		--source-secret-access-key-file /run/production-r2/r2_documents_secret_access_key \
		--source-bucket-file /run/production-r2/r2_documents_bucket \
		--destination-endpoint-file /run/staging-r2/r2_documents_endpoint \
		--destination-access-key-id-file /run/staging-r2/r2_documents_access_key_id \
		--destination-secret-access-key-file /run/staging-r2/r2_documents_secret_access_key \
		--destination-bucket-file /run/staging-r2/r2_documents_bucket \
		--source-prefix "$$(sed -n 's/^R2_DOCUMENTS_PREFIX=//p' "$(PRODUCTION_ENV_FILE)" | tail -n 1)" \
		--destination-prefix "$$(sed -n 's/^R2_DOCUMENTS_PREFIX=//p' "$(STAGING_ENV_FILE)" | tail -n 1)" \
		$(if $(apply),--apply,)

staging-bootstrap: staging-seed
	$(MAKE) --no-print-directory staging-up STAGING_ENV_FILE=$(STAGING_ENV_FILE)
	$(MAKE) --no-print-directory staging-smoke STAGING_ENV_FILE=$(STAGING_ENV_FILE)

test:
	PYTHONPATH=$(TEST_PYTHONPATH) $(TEST_ENV) poetry run pytest

test-unit:
	PYTHONPATH=$(TEST_PYTHONPATH) $(TEST_ENV) poetry run pytest --ignore=tests/test_database_workflow.py -k "not real_redis"

test-integration: ensure-integration-services
	PYTHONPATH=$(TEST_PYTHONPATH) $(TEST_ENV) poetry run python toolbox/checks/integration_test_services.py
	PYTHONPATH=$(TEST_PYTHONPATH) $(TEST_ENV) poetry run pytest \
		tests/test_database_workflow.py \
		tests/test_auth_session_security.py::test_login_attempts_are_limited_with_real_redis \
		tests/test_auth_session_security.py::test_refresh_rotation_replay_and_logout_with_real_redis \
		-rA

lint:
	PYTHONPATH=$(TEST_PYTHONPATH) poetry run ruff check .

document-crypto-benchmark:
	PYTHONPATH=$(TEST_PYTHONPATH) poetry run python -m toolbox.benchmark.document_crypto_benchmark $(if $(sizes),--sizes-mib $(sizes),) $(if $(repetitions),--repetitions $(repetitions),)

docs:
	@test -f "$(DOCS_ENV_FILE)" || (echo "[error] arquivo de ambiente do MkDocs não encontrado: $(DOCS_ENV_FILE)"; exit 2)
	@$(DOCS_COMPOSE) config --quiet || (echo "[error] $(DOCS_ENV_FILE) ou o Compose do MkDocs é inválido"; exit 2)
	$(DOCS_COMPOSE) up -d --build --wait docs
	@echo "[ok] Development docs available at http://127.0.0.1:$${DOCS_HOST_PORT:-7190}"

docs-up: docs

docs-logs:
	$(DOCS_COMPOSE) logs -f --tail=100 docs

telemetry-up:
	DEV_ENV_FILE=$(DEV_ENV_FILE) poetry run python toolbox/dev/dependencies.py loki

telemetry-down:
	$(DEV_COMPOSE) stop loki

telemetry-status:
	$(DEV_COMPOSE) ps -a loki

telemetry-smoke:
	@curl -fsS "http://127.0.0.1:$${LOKI_HOST_PORT:-3100}/ready" >/dev/null
	@echo "[ok] local Loki is ready; full Platform Infra ingestion remains an integrated platform smoke"

quick-tunnel-up:
	$(DEV_COMPOSE) --profile quick-tunnel up -d quick-tunnel

quick-tunnel-down:
	$(DEV_COMPOSE) --profile quick-tunnel stop quick-tunnel

quick-tunnel-logs:
	$(DEV_COMPOSE) --profile quick-tunnel logs -f --tail=100 quick-tunnel

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

ensure-observability-network:
	@docker network inspect platform-observability >/dev/null 2>&1 || docker network create platform-observability >/dev/null

ensure-local-databases: local-config
	$(LOCAL_COMPOSE) up -d --wait postgres
	$(LOCAL_COMPOSE) exec -T postgres bash /docker-entrypoint-initdb.d/init-multiple-databases.sh

ensure-integration-services: ensure-local-databases
	$(LOCAL_COMPOSE) up -d --wait redis

local-config:
	$(LOCAL_COMPOSE) config --quiet

local-start:
	@echo "[deprecated] use 'make dev-docker'"; exit 2

local-up:
	@echo "[deprecated] use 'make dev-docker' or 'make staging-up'"; exit 2

local-up-stripe:
	$(MAKE) --no-print-directory stripe-up

local-down:
	$(MAKE) --no-print-directory dev-docker-down

local-reset:
	@echo "[error] destructive local reset was removed; use explicit Docker volume commands after inspecting targets"; exit 2

local-logs:
	$(MAKE) --no-print-directory dev-docker-logs

local-rebuild:
	@echo "[deprecated] application code runs bare metal; use 'make staging-up' to rebuild containers"; exit 2

stripe-up:
	$(DEV_COMPOSE) --profile stripe up -d stripe-cli

stripe-down:
	$(DEV_COMPOSE) --profile stripe stop stripe-cli

stripe-logs:
	$(DEV_COMPOSE) --profile stripe logs -f --tail=100 stripe-cli

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

migrate-observability: ensure-local-databases
	$(LOCAL_MAINTENANCE) run --rm --build alembic python toolbox/database/migrate.py observability

revision-auth:
	@test -n "$(msg)" || (echo "Usage: make revision-auth msg=create_users"; exit 2)
	$(LOCAL_COMPOSE) exec -T auth-api alembic -c apps/auth_api/alembic.ini revision --autogenerate -m "$(msg)"

migrate: ensure-local-databases
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
	@echo "[deprecated] use 'make dev-bootstrap'"; exit 2

compose-down: local-down

production-ensure: ensure-observability-network
	python3 toolbox/checks/production_readiness.py $(PRODUCTION_ENV_FILE)
	$(PRODUCTION_COMPOSE) config --quiet
	@web_context="$$( $(PRODUCTION_COMPOSE) config --format json | python3 -c 'import json, sys; print(json.load(sys.stdin)["services"]["web"]["build"]["context"])' )"; \
		test -f "$$web_context/Dockerfile.prod" || (echo "[error] Frontend not found at $$web_context; set RUBRICA_WEB_CONTEXT=../../../rubrica-front in $(PRODUCTION_ENV_FILE)"; exit 1)
	@$(PRODUCTION_COMPOSE) config --format json | python3 toolbox/checks/compose_contract.py production

production-config: production-ensure

production-status:
	$(PRODUCTION_COMPOSE) ps -a

production-provider-check: production-ensure
	$(PRODUCTION_COMPOSE) exec -T postgres pg_isready -U "$${POSTGRES_USER:-rubrica}" -d "$${POSTGRES_DB:-rubrica}"
	$(PRODUCTION_COMPOSE) exec -T redis redis-cli ping
	@echo "[ok] PostgreSQL and Redis operational; external providers are configured but paid/mutating operations were not executed"

production-provider-check-paid:
	@echo "[error] paid or externally mutating provider probes require a provider-specific, explicitly authorized command"; exit 2

.PHONY: production-encrypt-r2-documents
production-encrypt-r2-documents: production-ensure
	$(PRODUCTION_COMPOSE) exec -T core-api python -m toolbox.operations.encrypt_r2_documents $(if $(apply),--apply,)

ensure-production-databases: production-config
	$(PRODUCTION_COMPOSE) up -d --wait postgres
	$(PRODUCTION_COMPOSE) exec -T postgres bash /docker-entrypoint-initdb.d/init-multiple-databases.sh

production-up: production-ensure
	$(PRODUCTION_COMPOSE) up -d --build --wait

production-bootstrap: production-migrate
	$(MAKE) --no-print-directory production-up PRODUCTION_ENV_FILE=$(PRODUCTION_ENV_FILE)
	$(MAKE) --no-print-directory production-provider-check PRODUCTION_ENV_FILE=$(PRODUCTION_ENV_FILE)

production-down:
	$(PRODUCTION_COMPOSE) down

production-logs:
	$(PRODUCTION_COMPOSE) logs -f --tail=100

production-migrate: ensure-production-databases
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

production-sign-ecnpj: production-config
	@test -n "$(input)" -a -n "$(output)" || (echo "Usage: make production-sign-ecnpj input=documento.pdf output=documento_assinado.pdf"; exit 2)
	@case "$(input)$(output)" in */*) echo "[error] input and output must be file names inside $(ECNPJ_DOCUMENT_DIR)"; exit 2;; esac
	@test -f "$(ECNPJ_DOCUMENT_DIR)/$(input)" || (echo "[error] Input PDF not found: $(ECNPJ_DOCUMENT_DIR)/$(input)"; exit 2)
	@test -f "$(ECNPJ_PFX_FILE)" || (echo "[error] PKCS#12 not found: $(ECNPJ_PFX_FILE)"; exit 2)
	@test -f "$(ECNPJ_ICP_TRUST_ROOTS_FILE)" || (echo "[error] ICP-Brasil trust roots not found: $(ECNPJ_ICP_TRUST_ROOTS_FILE)"; exit 2)
	@test -f "$(ECNPJ_SIGNATURE_POLICY_FILE)" || (echo "[error] Signature policy not found: $(ECNPJ_SIGNATURE_POLICY_FILE)"; exit 2)
	$(PRODUCTION_COMPOSE) run --rm --no-deps \
		-v "$(ECNPJ_DOCUMENT_DIR):/operator/documents" \
		-v "$(ECNPJ_PFX_FILE):/operator/secrets/ecnpj.pfx:ro" \
		-v "$(ECNPJ_ICP_TRUST_ROOTS_FILE):/operator/secrets/icp-brasil-roots.pem:ro" \
		-v "$(ECNPJ_SIGNATURE_POLICY_FILE):/operator/policies/signature-policy.der:ro" \
		core-api python toolbox/sign_pdf_ecnpj.py \
			"/operator/documents/$(input)" "/operator/documents/$(output)" \
			--pfx /operator/secrets/ecnpj.pfx \
			--signer-trust-roots /operator/secrets/icp-brasil-roots.pem \
			--policy-file /operator/policies/signature-policy.der \
			--policy-url "$(ECNPJ_SIGNATURE_POLICY_URL)"

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
