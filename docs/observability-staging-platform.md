# Observability staging local — contrato Platform v2

Somente PostgreSQL e observability_api, projeto Compose `rubrica-observability-staging-local`, API `127.0.0.1:8104`. Os volumes existentes são preservados. Não inicia Auth, Core, seeds, collector, Tunnel ou outros produtos.

## Configuração e chave

O produto usa somente `PLATFORM_URL=https://grafana.7f3a9c2e8b.stream` e `PLATFORM_TOKEN_FILE=/run/secrets/platform_token`. Uma chave Bearer autentica status, heartbeat, metrics e query. Não usa credenciais administrativas/Viewer do Grafana, Cloudflare Access ou Tunnel.

A API foi conferida com `id`: UID/GID 0. O secret precisa ser legível por esse UID, arquivo 0600 e diretório 0700. Não cole valores no chat ou no comando. No servidor da Platform, somente o operador pode recuperar a chave existente com `sudo make project-token PROJECT=rubrica PROJECT_ENV=staging`. Este fluxo não acessa aquele servidor nem gera outra chave.

Com a chave existente em um arquivo local protegido, instale:

```bash
cd /home/matheus/projects/rubrica/rubrica-back
make observability-staging-install-secret source=/caminho/local/chave-existente
```

O instalador copia atomicamente apenas para `.runtime/observability-staging/secrets/platform_token`, com 0600. Esse diretório é ignorado pelo Git. O overlay monta o arquivo como Docker Secret `platform_token`. Se já houver somente o arquivo histórico `platform_ingest_token`, o helper reutiliza esse arquivo como origem do mesmo Docker Secret, sem exigir reinstalação.

## Subir e testar

```bash
# Inicialização/rebuild: somente o PostgreSQL próprio e a API, sem seeds.
make observability-staging-up
# Recria somente a API, com o secret e publisher habilitado.
make observability-staging-connect
make observability-staging-status
# Aguarde um ciclo de 30 s e o scrape remoto antes das provas.
make observability-staging-ensure
make observability-staging-test
make observability-staging-evidence
```

`up` aplica explicitamente apenas migrations da Observability e mantém os volumes. `connect` não faz build: execute `up` primeiro depois de alterar o código. Nenhum pacote é instalado no host. `disconnect` recria só a API sem o publisher.

O ensure é não mutante: GET `/ingest/v1/status` e POST `/ingest/v1/query`, com corpo `{"metric":"rubrica_business_metrics_collection_success","service":"observability_api"}`. Nunca envia heartbeat ou métricas. Distingue configured, reachable, authenticated, authorized e operational. Exige contrato 2, identidade correta, presença/snapshot/coleta recentes e consulta Prometheus com valor 1 e timestamp recente. Usa o relógio informado pelo receptor. Resposta vazia, escopo errado, sinal antigo ou HTTP 200 de `/api/health` não comprovam integração.

`test` acrescenta verificações reais não mutantes: ausência/chave inválida recebem 401, adulteração de escopo/serviço e PromQL são rejeitados. Não provoca falha no servidor remoto. Timeout, recuperação, filas e perda de conectividade são exercitados nos testes unitários com transporte simulado. Evidências contêm somente estados, códigos e contagens, sem headers ou secrets.

Se houver redirect/login do Cloudflare Access, o ensure falha e indica ao operador a **etapa 2 de `platform_infra/docs/PLATFORM_UPDATE.md`**. Não adicione credenciais alternativas. Após a correção pelo operador, use `connect` para retirar a pausa de autenticação e repita as provas.

## Publicação e isolamento

Heartbeat e snapshot completo de famílias `rubrica_` a cada 30 s. Counter/histogram bucket/sum/count são preservados; `_created`, python/process e famílias com labels incompatíveis são descartadas integralmente. Labels seguem a allowlist do PROJECTS.md; sem nomes, IDs ou conteúdo de clientes.

TLS validado, sem redirects, uma requisição em voo, uma atualização pendente por tipo (a nova substitui a anterior), timeout total 10 s, backoff com jitter 1–30 s, validade 90 s e limite 30 requisições/minuto. 429 respeita Retry-After; 401/403 e bloqueio Access pausam ambas as filas; 413/415/422 pausam o payload incompatível. Reiniciar descarta pendências. Falha da plataforma não altera health/readiness nem negócio.

Desenvolvimento desabilitado por padrão. Staging e produção validam identidades distintas e devem receber suas próprias chaves; este Compose é exclusivamente staging. A entrada não recebe logs/traces nem OTLP.

## Validação local em 2026-11-05

Envio real e consulta reais aprovados: contrato 2, 36 amostras no snapshot, métrica de sucesso com valor 1 e timestamp recente. As cinco provas negativas do comando `test` passaram. Health `ok`, readiness `ready`; PostgreSQL e volumes originais preservados. Suíte: 572 testes passaram, 14 ignorados por dependerem de infraestrutura adicional; Ruff aprovado. Não houve acesso administrativo ao servidor remoto nem alteração de Cloudflare.
