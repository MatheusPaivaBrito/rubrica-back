# Docker Compose do Rubrica

A pasta é dividida por responsabilidade para manter `local.yml` e `production.yml` pequenos. A estrutura usa `include` + `extends` e requer Docker Compose 2.20+.

Para regras de manutenção e para agentes de código, leia **`ARCHITECTURE.md` antes de alterar esta pasta**.

## Estrutura

- `local.yml`: ponto de entrada do ambiente local.
- `production.yml`: ponto de entrada da produção.
- `services/`: containers/processos da topologia.
- `features/stripe-local.yml`: Stripe CLI, secrets e volume de webhook do ambiente local.
- `features/stripe-production.yml`: secrets Stripe usados em produção.
- `features/r2-documents.yml`: override opcional para documentos no Cloudflare R2.
- `features/serpro-timestamp.yml`: override opcional para SERPRO Timestamp.
- `resources/`: secrets, volumes e networks compartilhados que não pertencem a uma feature específica.

## Stripe

Stripe é o billing padrão e já faz parte da composição normal.

No local, `features/stripe-local.yml` sobe o container auxiliar que executa `stripe listen` e sincroniza o signing secret efêmero com o Core através de `stripe_webhook_runtime`.

Em produção **não existe `stripe-cli`**. `features/stripe-production.yml` declara somente `stripe_secret_key` e `stripe_webhook_secret`; os webhooks chegam pelo endpoint público normal.

## Local

```bash
docker compose --env-file .env -f compose/local.yml up -d --build
```

O ambiente local sobe PostgreSQL, Redis, APIs, Web, gateway e `stripe-cli` sem profile adicional.

O k6 permanece opcional:

```bash
docker compose --env-file .env -f compose/local.yml --profile benchmark run --rm k6
```

## Produção

```bash
sudo docker compose --env-file .env.production -f compose/production.yml up -d --build
```

Somente `gateway` publica porta no host:

```text
127.0.0.1:7171 -> gateway:8080
```

PostgreSQL, Redis, APIs e Web ficam acessíveis apenas pelas redes Docker.

### Cloudflare Tunnel

O `cloudflared` usa `cloudflare_tunnel_token`, depende do healthcheck do `gateway` e compartilha a rede interna com ele.

O tunnel é remotamente gerenciado; a rota de origem configurada na Cloudflare deve apontar para:

```text
http://gateway:8080
```

## Cloudflare R2 para documentos

R2 continua opcional e pode ser habilitado sobre local ou produção.

Local:

```bash
docker compose --env-file .env \
  -f compose/local.yml \
  -f compose/features/r2-documents.yml \
  up -d --build
```

Produção:

```bash
sudo docker compose --env-file .env.production \
  -f compose/production.yml \
  -f compose/features/r2-documents.yml \
  up -d --build
```

Secrets preservados:

- `r2_documents_endpoint`
- `r2_documents_access_key_id`
- `r2_documents_secret_access_key`
- `r2_documents_bucket`

O storage local de documentos continua montado para facilitar migração e rollback. O bucket de documentos permanece separado do bucket de backups.

## SERPRO Timestamp

O SERPRO Timestamp continua opcional:

```bash
sudo docker compose --env-file .env.production \
  -f compose/production.yml \
  -f compose/features/serpro-timestamp.yml \
  up -d --build
```

Para homologação local, o mesmo override pode ser usado com `compose/local.yml`.

## R2 + SERPRO juntos

```bash
sudo docker compose --env-file .env.production \
  -f compose/production.yml \
  -f compose/features/r2-documents.yml \
  -f compose/features/serpro-timestamp.yml \
  up -d --build
```
