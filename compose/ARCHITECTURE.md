# Arquitetura do Docker Compose do Rubrica

Este arquivo é a referência de arquitetura para humanos e agentes de código (incluindo Codex) ao alterar `compose/`.

## Regra principal

Não classifique arquivos pela empresa externa envolvida. Classifique pela responsabilidade no Docker Compose:

- `services/` = containers/processos executáveis da topologia;
- `features/` = capacidades e integrações que configuram ou estendem serviços existentes;
- `resources/` = recursos compartilhados do ambiente que não pertencem a uma feature específica;
- `local.yml` e `production.yml` = pontos de entrada curtos, sem concentrar configuração de aplicação.

## Estrutura esperada

```text
compose/
├── local.yml
├── production.yml
├── ARCHITECTURE.md
├── services/
│   ├── postgres.yml
│   ├── redis.yml
│   ├── auth-api.yml
│   ├── core-api.yml
│   ├── eventing-api.yml
│   ├── notification-api.yml
│   ├── web.yml
│   ├── gateway.yml
│   ├── stripe-cli.yml
│   ├── cloudflared.yml
│   └── k6.yml
├── features/
│   ├── stripe-production.yml
│   ├── r2-documents.yml
│   └── serpro-timestamp.yml
└── resources/
    ├── local.yml
    └── production.yml
```

## `services/`: o que roda

Um arquivo em `services/` representa um container ou processo Docker identificável.

Exemplos:

- PostgreSQL e Redis são serviços de infraestrutura;
- Auth/Core/Eventing/Notification são serviços da aplicação;
- Web e Gateway são serviços da aplicação/edge;
- `cloudflared` é um serviço de runtime de produção;
- `k6` é um serviço/ferramenta executável sob profile;
- `stripe-cli` é um container auxiliar **somente local**.

### Stripe CLI não é a integração Stripe

O serviço `stripe-cli`, definido em `services/stripe-cli.yml`, existe exclusivamente para desenvolvimento local. Ele executa `stripe listen`, recebe eventos do Stripe e encaminha o webhook para:

```text
http://core-api:8000/billing/webhooks/stripe
```

Ele também sincroniza o signing secret efêmero através de `stripe_webhook_runtime`.

**Nunca adicionar `stripe-cli` ao `production.yml`.** Em produção o Stripe entrega webhooks diretamente ao endpoint público do Rubrica através do gateway/tunnel.

## `features/`: o que está habilitado/configurado

Uma feature representa uma capacidade da aplicação que não precisa corresponder a um container próprio.

### Stripe

As variantes `local` e `production` de `services/core-api.yml` contêm a configuração de billing Stripe aplicada ao Core:

- `BILLING_PROVIDER`;
- referências para `stripe_secret_key` e `stripe_webhook_secret`;
- preços Stripe;
- `BILLING_GRACE_PERIOD_DAYS`;
- no local, o caminho do signing secret gerado pelo Stripe CLI.

`services/stripe-cli.yml` reúne o container local e os recursos que ele compartilha com o Core:

- `stripe_secret_key`;
- `stripe_webhook_secret`;
- `stripe_webhook_runtime`.

`features/stripe-production.yml` declara somente `stripe_secret_key` e `stripe_webhook_secret` para o Core de produção.

O arquivo de recursos é separado porque o Docker Compose **não importa automaticamente secrets, volumes ou networks referenciados por um serviço recebido via `extends`**. Os pontos de entrada incluem explicitamente o arquivo de recursos Stripe do próprio ambiente.

Stripe é diferente de R2/SERPRO em uma coisa importante: **Stripe é o billing padrão e faz parte da composição normal**. Portanto `local.yml` e `production.yml` já o conectam automaticamente ao `core-api`; não é necessário adicionar um segundo `-f` para Stripe.

### Cloudflare R2

`features/r2-documents.yml` é um override opcional. Ele altera o storage operacional do Core para R2 e declara os secrets específicos do R2.

Ele deve continuar utilizável sobre local ou produção com um segundo `-f`.

### SERPRO Timestamp

`features/serpro-timestamp.yml` é um override opcional. Ele habilita o provider de timestamp SERPRO e declara o secret correspondente.

Não transformar SERPRO Timestamp em dependência obrigatória da composição normal.

## `resources/`: recursos compartilhados do ambiente

`resources/local.yml` e `resources/production.yml` contêm recursos que pertencem ao ambiente como um todo e não a uma feature específica.

Exemplos:

- secrets compartilhados por serviços;
- volumes persistentes gerais;
- redes `rubrica_internal` e `rubrica_external`.

Não devolver secrets do Stripe para esses arquivos. No local eles acompanham `services/stripe-cli.yml`; em produção pertencem a `features/stripe-production.yml`.

## Pontos de entrada

### Local

`local.yml` deve continuar pequeno e subir o ambiente local normal com:

- PostgreSQL;
- Redis;
- APIs;
- Web;
- Gateway;
- Stripe CLI;
- Stripe configurado no Core;
- k6 apenas quando seu profile for solicitado.

Comando canônico:

```bash
docker compose --env-file .env -f compose/local.yml up -d --build
```

### Produção

`production.yml` deve continuar pequeno e subir:

- PostgreSQL;
- Redis;
- APIs;
- Web;
- Gateway;
- Cloudflare Tunnel;
- Stripe configurado no Core.

**Produção não sobe Stripe CLI.**

Comando canônico:

```bash
sudo docker compose --env-file .env.production -f compose/production.yml up -d --build
```

## Invariantes que não devem ser quebradas

1. Em produção, somente `gateway` pode possuir `ports:`.
2. A porta publicada de produção continua `127.0.0.1:${GATEWAY_HOST_PORT:-7171}:8080`.
3. `cloudflared` deve alcançar `http://gateway:8080` e depender do healthcheck do gateway.
4. `stripe-cli` é exclusivamente local.
5. Stripe é billing padrão de produção; sua configuração do Core pertence a `services/core-api.yml` e seus recursos locais acompanham `services/stripe-cli.yml` e os de produção pertencem a `features/stripe-production.yml`.
6. R2 e SERPRO Timestamp continuam opcionais.
7. Manter variáveis e preços do Stripe nas variantes correspondentes de `services/core-api.yml`.
8. Não mover secrets específicos do Stripe para `resources/local.yml` ou `resources/production.yml`.
9. Nunca versionar valores reais de secrets; usar arquivos em `${SECRETS_DIR:-/etc/rubrica/secrets}`.
10. Preservar os nomes dos serviços porque são usados por DNS interno, Nginx, scripts e dependências.
11. Preservar caminhos de Dockerfile, comandos Gunicorn, healthchecks, volumes persistentes e redes existentes.
12. `local.yml` e `production.yml` não devem voltar a virar arquivos monolíticos.

## Como decidir onde colocar algo novo

Use esta sequência:

```text
É um container/processo que roda?
├─ Sim -> services/
│  └─ É apenas ferramenta de desenvolvimento? -> conecte somente no local.
└─ Não
   └─ Configura/estende uma capacidade externa da aplicação? -> features/
      └─ Secrets/volumes exclusivos dela também ficam associados à feature.
```

Se o recurso for compartilhado por várias partes do ambiente e não pertencer a uma feature específica, use `resources/`.

## Antes de alterar `compose/`

Ao fazer qualquer refatoração:

1. leia este arquivo;
2. preserve as invariantes acima;
3. valide todos os YAMLs;
4. rode `docker compose ... config` para local e produção quando Docker Compose estiver disponível;
5. confirme novamente que produção só publica a porta do gateway;
6. teste overlays opcionais de R2 e SERPRO;
7. não altere código Python/Angular para resolver um problema puramente de Compose.
