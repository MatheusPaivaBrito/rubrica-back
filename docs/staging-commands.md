# Comandos de staging

Execute na raiz do backend. Use `make staging-help` para consultar esta referência no terminal.

## Configuração e aplicação

- `make staging-secrets-init` — cria os Docker Secrets isolados de staging.
- `make staging-ensure` — valida a configuração, os secrets e o isolamento do Compose.
- `make staging-bootstrap` — aplica migrações, roda o seed, sobe a aplicação e executa o smoke.
- `make staging-up` — sobe ou atualiza a aplicação e o túnel sem rodar migrações ou seed.
- `make staging-down` — encerra a aplicação e preserva os volumes.

## Estado e diagnóstico

- `make staging-status` — lista todos os containers de staging.
- `make staging-logs` — acompanha os logs de staging.
- `make staging-smoke` — verifica o gateway, o MkDocs, o túnel e os serviços.
- `make staging-public-url` — mostra a URL pública configurada.
- `make staging-docs-url` — mostra a URL do MkDocs.

## Banco e contas de teste

- `make staging-migrate` — aplica as migrações nos bancos de staging.
- `make staging-seed` — aplica as migrações e cria ou atualiza as contas de teste.
- `make staging-check-users` — lista todas as contas do Auth, incluindo inativas, e o total em uma consulta somente leitura.
- `make staging-reset-db` — para a aplicação e apaga somente o volume PostgreSQL de staging.
- `make staging-reset-db-seed` — valida staging, apaga o PostgreSQL e executa o bootstrap completo.

Os resets apagam as contas e dados existentes no PostgreSQL de staging. Redis, R2 e os demais volumes são preservados.

## Ensaio de migração de documentos

- `make staging-clone-core-from-production confirm=CLONE_PRODUCTION_CORE_TO_STAGING` — substitui o Core de staging por uma cópia de produção e deixa a aplicação parada.
- `make staging-clone-r2-documents` — simula a cópia dos objetos referenciados para o R2 de staging. Acrescente `apply=1` para copiar.
- `make staging-encrypt-r2-documents` — audita presença, integridade e cifra dos objetos de staging. Acrescente `apply=1` para cifrar os objetos legados.

Mantenha a aplicação e o túnel parados enquanto o banco de staging contiver a cópia de produção.

## Observabilidade de staging local

Estes comandos operam apenas sobre a instância local de Observability na porta 8104 e seu PostgreSQL.

- `make observability-staging-up` — sobe a API e seu PostgreSQL preservando volumes.
- `make observability-staging-install-secret source=/caminho/protegido` — instala o token existente a partir de um arquivo protegido.
- `make observability-staging-connect` — habilita a publicação na Platform Infra.
- `make observability-staging-disconnect` — desabilita a publicação e mantém a API ativa.
- `make observability-staging-status` — mostra o estado dos serviços.
- `make observability-staging-logs` — acompanha os logs.
- `make observability-staging-ensure` — valida ingestão e consulta em modo somente leitura.
- `make observability-staging-test` — testa a integração e confirma a rejeição de credenciais e escopos inválidos.
- `make observability-staging-evidence` — grava evidência sanitizada em `.runtime`.
