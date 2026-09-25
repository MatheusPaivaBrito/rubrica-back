# Validação da refatoração Compose

## Resultado desta revisão

- Todos os YAMLs da pasta `compose/` foram carregados com sucesso por parser YAML.
- O modelo efetivo dos serviços de `local.yml` foi comparado com a entrega anterior e permaneceu equivalente.
- O modelo efetivo dos serviços de `production.yml` foi comparado com a entrega anterior e permaneceu equivalente.
- O conjunto efetivo de secrets, volumes e networks de local e produção permaneceu equivalente à entrega anterior.
- A configuração Stripe do Core foi movida para `features/stripe.yml`.
- `stripe_secret_key`, `stripe_webhook_secret` e o runtime volume local foram removidos de `resources/` genérico e passaram para arquivos de recursos da feature Stripe.
- `stripe_webhook_runtime` existe somente no modelo local; produção não recebe volume Stripe não utilizado.
- `stripe-cli` continua presente no local e ausente em produção.
- Na produção resolvida estaticamente, somente `gateway` possui `ports`, com `127.0.0.1:${GATEWAY_HOST_PORT:-7171}:8080`.
- R2 e SERPRO Timestamp continuam overrides opcionais que alteram `core-api`.
- Todas as referências de secrets, volumes nomeados e networks usadas pelos serviços possuem declaração no modelo do respectivo ambiente.
- Uma varredura por padrões comuns de credenciais reais (`sk_live_`, `whsec_`, AWS access key e tokens JWT-like) não encontrou ocorrências.

## Arquitetura Stripe validada

### Local

- `core-api` herda a configuração de `features/stripe.yml` na variante `local`;
- `stripe-cli` continua em `services/stripe-cli.yml`;
- `stripe-cli` usa `stripe_secret_key` e `stripe_webhook_runtime`;
- o Core lê o signing secret efêmero em `/run/rubrica/stripe/stripe_webhook_secret`;
- os recursos específicos ficam em `features/stripe-local-resources.yml`.

### Produção

- `core-api` herda a configuração de `features/stripe.yml` na variante `production`;
- `BILLING_PROVIDER` continua `stripe`;
- os mesmos nomes de variáveis/preços Stripe foram preservados;
- `stripe_secret_key` e `stripe_webhook_secret` continuam secrets baseados em arquivos;
- os recursos específicos ficam em `features/stripe-production-resources.yml`;
- `stripe-cli` não faz parte da topologia de produção.

## Arquivos desta revisão

### Criados

- `compose/ARCHITECTURE.md`
- `compose/README.md`
- `compose/VALIDATION.md`
- arquivos por serviço em `compose/services/`
- recursos compartilhados em `compose/resources/`
- `compose/features/stripe.yml`
- `compose/features/stripe-local-resources.yml`
- `compose/features/stripe-production-resources.yml`
- `compose/features/r2-documents.yml`
- `compose/features/serpro-timestamp.yml`

### Alterados

- `compose/local.yml`
- `compose/production.yml`
- `compose/services/core-api.yml`
- `compose/resources/local.yml`
- `compose/resources/production.yml`
- `compose/README.md`
- `compose/VALIDATION.md`

### Removidos

- `compose/r2-documents.yml`, substituído por `compose/features/r2-documents.yml`;
- `compose/production.timestamp.yml`, substituído por `compose/features/serpro-timestamp.yml`.

## Docker Compose `config`

Os comandos oficiais foram executados com Docker Compose v5.5.1:

```bash
docker compose --env-file .env -f compose/local.yml config
docker compose --env-file .env.production -f compose/production.yml config
```

Também foram validados os overlays R2 e SERPRO, em local e produção. Todos os
modelos passaram por `docker compose config`. O ambiente local com R2 foi
construído e iniciado; gateway, PostgreSQL e Redis ficaram saudáveis, o Stripe
CLI sincronizou o webhook e o Core iniciou com `R2DocumentStorage`.

A suíte Python terminou com 252 testes aprovados e 4 ignorados. Ruff, Poetry,
os quatro bancos e as rotas HTTP do gateway também foram verificados.
