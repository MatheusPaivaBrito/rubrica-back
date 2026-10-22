# Observabilidade do Rúbrica

O Rúbrica publica telemetria para a Platform Infra compartilhada sem conceder
acesso aos seus bancos operacionais. Logs brutos permanecem no Loki, métricas
no Prometheus e traces no Tempo. O banco `rubrica_observability` guarda somente
configuração e memória operacional normalizada.

## Contratos internos

- `GET /metrics` em Auth, Core, Eventing, Notification e Observability;
- `GET /health` da Observability API independe de banco e Grafana;
- `GET /ready` verifica somente o banco da Observability API;
- `GET /internal/observability/platform/status` exige
  `X-Rubrica-Service-Key` e nunca expõe o token do Grafana.

As métricas usam o prefixo `rubrica_`. Labels aceitos são dimensões fechadas,
como serviço, método, template de rota, classe HTTP e estados de domínio. IDs,
e-mails, CPF/CNPJ, request IDs e trace IDs não podem ser labels.

## Secrets de produção

Crie arquivos com permissão `0600` em `${SECRETS_DIR:-/etc/rubrica/secrets}`:

```text
platform_grafana_service_token
observability_internal_service_key
```

`platform_grafana_service_token` pertence a uma conta de serviço exclusiva
`rubrica-observability-api`, papel Viewer, revogável e com expiração. Para
rotacionar, crie novo token no Grafana, substitua atomicamente o arquivo e
recrie somente `observability-api`; revogue o token anterior após validar o
status. Nunca use `admin/admin` entre serviços.

Gere `observability_internal_service_key` com pelo menos 32 bytes aleatórios.
Ele autentica chamadas internas ao endpoint de status e deve ser rotacionado
como os demais service keys.

## Rede e modo degradado

`make local-config` e `make production-config` garantem que a rede externa
`platform-observability` exista. A rede pode permanecer sem containers da
plataforma; isso não impede o Rúbrica de iniciar.

Os aliases coletados pelo Prometheus são:

- `rubrica-auth-api:8000`;
- `rubrica-core-api:8000`;
- `rubrica-eventing-api:8000`;
- `rubrica-notification-api:8000`;
- `rubrica-observability-api:8000`.

Com Grafana indisponível, o endpoint de status retorna `unavailable` com uma
razão segura. Health, ready, migrations e funções centrais continuam operando.
O exportador OTLP usa `http://tempo:4318/v1/traces`; falhas de exportação não
interrompem requisições.

## Diagnóstico

1. Execute `make migrate-observability` e confirme `GET /ready`.
2. Confira `up{job="rubrica-apis"}` no Prometheus.
3. Confira o dashboard `Rubrica / APIs` no Grafana.
4. Pesquise `{compose_project=~"rubrica|rubrica-prod"}` no Loki.
5. Gere uma requisição com `X-Request-ID` conhecido e correlacione log e trace.
6. Se um target estiver `DOWN`, valide a rede e o alias; não conecte bancos ou
   o gateway à rede de observabilidade.

O Rúbrica deve ser testado com a Platform Infra ligada e desligada. Não use
`docker compose down -v` na plataforma, pois seus volumes guardam o histórico
de telemetria.
