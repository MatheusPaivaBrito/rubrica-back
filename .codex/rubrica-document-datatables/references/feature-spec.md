# Feature full stack: documentos e fluxo de assinaturas

## Estado

- Especificação em construção.
- Partes registradas: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 e 12.
- Partes 1, 2, 3, 5, 6, 7, 9, 11 e 12 autorizadas e implementadas na branch da feature; Partes 4 e 8 adiadas. A Parte 10 foi autorizada em 2026-10-25 e está em andamento, priorizando confidencialidade criptográfica dos documentos e uma migração ensaiada integralmente em staging. A validação integral da Parte 12 ainda depende do runtime Docker de staging e do servidor de produção.
- Feature full stack, com trabalho coordenado entre `rubrica-back` e `rubrica-front`.
- Skill mantida no repositório backend como fonte central da especificação.

## Objetivo geral

Modernizar o fluxo de documentos e assinaturas do Rúbrica em uma branch exclusiva, mantendo o comportamento já disponível e criando uma base adequada para as próximas partes da feature.

## Acompanhamento da implementação

Última atualização do quadro: **2026-10-25**.

### Legenda obrigatória

| Status | Significado |
|---|---|
| `NÃO INICIADO` | Existe apenas especificação; nenhum código da etapa foi implementado. |
| `EM ANDAMENTO` | Há trabalho iniciado, mas o resultado ainda não satisfaz todos os critérios do pacote. |
| `BLOQUEADO` | Não pode avançar sem decisão, credencial, contrato ou dependência identificada. |
| `IMPLEMENTADO` | O código do pacote está presente, porém a verificação completa ainda não terminou. |
| `VERIFICADO` | Implementação e testes/aceites objetivos do pacote foram concluídos. |
| `ADIADO` | Pacote retirado conscientemente do ciclo atual, com justificativa registrada. |

Regras:

- O status se refere à implementação desta feature; investigação preliminar não transforma um pacote em `IMPLEMENTADO`.
- Uma Parte somente está concluída quando todos os seus pacotes obrigatórios estão `VERIFICADO` ou formalmente `ADIADO`.
- Cada atualização deve preencher evidência concreta e o que continua pendente.
- Se backend e frontend avançarem separadamente, mantenha pacotes separados; não marque a integração como concluída antecipadamente.
- Alterações de escopo devem atualizar primeiro a decomposição e somente depois o código.

### Parte 1 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 1A | Fechar filtros, colunas, paginação e critérios de UX | ambos | decisão de produto | `VERIFICADO` | Busca, data e status preservados; ordenação por coluna e páginas de 5 itens definidas | Novos filtros de negócio podem entrar depois sem bloquear este corte. |
| 1B | Selecionar e validar biblioteca DataTable para Angular 22 | frontend | 1A | `VERIFICADO` | TanStack Angular Table 9.3.1, MIT, build Angular 22 aprovado | Biblioteca headless preserva o design responsivo atual. |
| 1C | Contratos backend de filtro, paginação e ordenação determinística | backend | 1A | `VERIFICADO` | Listagens completas usam `created_at DESC, id DESC`; paginação/filtros operam sobre o conjunto autorizado completo no cliente | Migrar para paginação server-side apenas quando o volume justificar. |
| 1D | DataTable de solicitações de assinatura | frontend | 1B, 1C | `VERIFICADO` | Busca, data, status, ações, ordenação e paginação integrados | Build e regressão frontend aprovados. |
| 1E | DataTable de documentos enviados | frontend | 1B, 1C | `VERIFICADO` | Busca, data, ações, ordenação e paginação integrados | Upload novo retorna ao topo pela ordem padrão. |
| 1F | Testes unitários, integração e E2E das duas tabelas | ambos | 1C–1E | `VERIFICADO` | 61 testes frontend, lint e build de produção aprovados; Playwright comprovou ordenação, paginação, busca, teclado, contenção responsiva e snapshots das duas tabelas em iPhone 8/13, Pixel 2/7 e desktop | Os 25 cenários legados de `pdf-mobile.spec.ts` estão desatualizados com fluxos atuais de planos, login e cadastro; sua manutenção é separada e não reduz a cobertura específica das DataTables. |

### Parte 2 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 2A | Fechar regras de posição, signatário, ausência e edição após abertura | produto/ambos | decisões pendentes da Parte 2 | `VERIFICADO` | Em 2026-10-22 foram adotados os padrões recomendados: posição atribuída a signatário, fixa, fallback atual quando ausente, replicação por página, bloqueio após abertura, cortesia sem entitlement e rejeição de sobreposição | Nenhum. |
| 2B | Entitlement de posicionamento pago e autorização server-side | backend | 2A | `VERIFICADO` | `custom_stamp_placement` é derivado de assinatura paga ativa, sem cortesia; backend revalida ao salvar e abrir | Nenhum. |
| 2C | Persistência, migration e API das posições normalizadas | backend | 2A, 2B | `VERIFICADO` | Migration `0026`; JSON versionado por request, signatário e página; GET/PUT restritos ao rascunho autorizado | Nenhum. |
| 2D | Editor visual de posições no PDF | frontend | 2A, 2C | `VERIFICADO` | Modal no rascunho permite selecionar signatário, posicionar no PDF e replicar em todas as páginas; controle não existe na UI gratuita | Nenhum. |
| 2E | Congelamento na abertura e aplicação no PDF | backend | 2C, 2D | `VERIFICADO` | Configuração só é gravável em `draft`; abertura congela o snapshot e o gerador aplica todas as posições atribuídas | Nenhum. |
| 2F | Evidência canônica com lista de posições | backend | 2E | `VERIFICADO` | Uma evidência por assinatura contém `stamp_positions`; várias representações visuais não duplicam a manifestação de vontade | Nenhum. |
| 2G | Testes de coordenadas, planos, múltiplos signatários e preservação | ambos | 2B–2F | `IMPLEMENTADO` | 75 testes backend focados, 61 frontend e lint aprovados; E2E Playwright cobre desktop/toque, páginas de tamanhos/rotação diferentes, replicação e vínculo ao signatário | Executar o E2E após disponibilizar navegador compatível: Playwright não fornece Chromium para Ubuntu 26.04 neste ambiente. |

### Parte 3 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 3A | Entitlement CNPJ + Profissional/Equipe | backend | regra comercial confirmada | `VERIFICADO` | `custom_stamp_branding` exige tenant empresarial, `BR_CNPJ` e plano Profissional/Equipe ativo | Nenhum. |
| 3B | Modelo de templates, logos, snapshots e ativos normalizados | backend | 3A | `VERIFICADO` | Templates `standard`, `business` e `representative`; cor e PNG decodificado, validado, limitado e regravado; snapshot no request | Nenhum. |
| 3C | Configuração administrativa e seleção por solicitação | frontend/backend | 3A, 3B | `VERIFICADO` | Editor permite salvar o branding como padrão empresarial; solicitações novas carregam o padrão e congelam seu snapshot; API e UI permanecem condicionadas ao entitlement | Nenhum. |
| 3D | Captura opcional de assinatura desenhada por mouse/toque | frontend/backend | decisões pendentes da Parte 3 | `VERIFICADO` | Emissor pode exigir por solicitação; signatário desenha em canvas por mouse/toque, pode limpar, e backend exige quando configurado | Nenhum. |
| 3E | Renderização distinta de CNPJ e representante | backend | 3B–3D, Parte 2 | `VERIFICADO` | Snapshot seleciona template e preserva a representação empresarial já vinculada à evidência; logo e assinatura desenhada são elementos visuais | Nenhum. |
| 3F | Segurança de imagens, evidências e testes completos | ambos | 3B–3E | `IMPLEMENTADO` | PNG real é verificado e normalizado, com limites de bytes/dimensões; conteúdo falso é rejeitado; suites backend/frontend e lint aprovadas; E2E de toque/desktop registrado | Executar o E2E após disponibilizar navegador compatível; inspeção visual real do PDF permanece no aceite manual. |

### Parte 4 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 4A | Viabilidade comercial, regulatória e DPIA | externo/produto | cotação Serpro e GCC | `NÃO INICIADO` | Pesquisa preliminar, sem contrato | Obter preços, credenciamento e base legal. |
| 4B | Abstração de provedor e política por solicitação | backend | 4A e decisões comerciais | `NÃO INICIADO` | Nenhuma interface criada | Definir modos oficial/fallback e estados. |
| 4C | Integração Datavalid V5 e GCC | backend | 4A, 4B, credenciais sandbox | `NÃO INICIADO` | Sem credenciais ou chamadas | Implementar sessões, tokens, idempotência e erros. |
| 4D | Captura controlada de documento e prova de vida | frontend | 4B, 4C | `NÃO INICIADO` | Fluxo ausente | Projetar câmera, acessibilidade e consentimento. |
| 4E | Decisão, retries, fallback e revisão | backend/frontend | 4B–4D | `NÃO INICIADO` | Política ausente | Implementar máquina de estados sem aprovação silenciosa. |
| 4F | Evidência, criptografia, retenção e descarte | backend/infra | 4C–4E | `NÃO INICIADO` | Política específica ausente | Definir campos públicos/privados e prazos. |
| 4G | Testes sandbox, fraude/replay, falhas e auditoria | ambos | 4C–4F | `NÃO INICIADO` | Nenhum teste novo | Executar matriz da Parte 4 sem chamadas pagas não autorizadas. |

### Parte 5 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 5A | Fechar schema JSON, release ID e regras editoriais | frontend/produto | decisões pendentes da Parte 5 | `VERIFICADO` | Schema v1 com `release_id`, `released_at` e destaques por locale em `appData` | Incrementar `release_id` e textos a cada release. |
| 5B | Arquivo editorial, validação e incorporação no `appData` | frontend/CI | 5A | `VERIFICADO` | `ngsw-config.json` gera o mesmo `appData` no `ngsw.json` de produção | Build Angular validou a configuração. |
| 5C | Parse seguro de `latestVersion.appData` e fallbacks | frontend | 5A, 5B | `VERIFICADO` | Parser limita schema, tipos, quantidade e tamanho; fallback en/pt-BR e modal genérico | Conteúdo editorial é exibido pela propriedade `text`, sem HTML. |
| 5D | SweetAlert com destaques e controle por sessão | frontend | 5C | `VERIFICADO` | Modal evita concorrência e grava dispensa por `release_id` na sessão | Ativação e recarga continuam no fluxo confirmado. |
| 5E | Testes e procedimento editorial de release | frontend/CI | 5B–5D | `VERIFICADO` | Testes cobrem quatro locales, fallback, conteúdo hostil, JSON inválido, sessão e concorrência | 61 testes frontend aprovados. |

### Parte 6 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 6A | Inventariar chamadas externas executadas dentro de transações e locks | backend | nenhuma | `VERIFICADO` | Inventário confirmou storage em upload/versionamento; identidade, storage, geração de PDF, SerproID e timestamp no fluxo de assinatura; convite já era enviado após commit | Checkout/portal Stripe e provisionamento inicial de conta continuam registrados como fronteiras externas próprias; não pertencem à operação criptográfica desta parte. |
| 6B | Definir protocolo de operação de assinatura em fases e idempotência | backend | 6A | `VERIFICADO` | `signature_operations` persiste uma operação única por request/signer com estados `processing`, `failed`, `artifact_ready` e `completed`, lease, contador de tentativas e hashes | Nenhum no escopo da assinatura; evolução futura pode criar reconciliador periódico para leases expirados. |
| 6C | Retirar leitura/gravação de storage e chamadas Serpro da transação longa | backend | 6B | `VERIFICADO` | Upload e versionamento usam validação/confirmação curta; assinatura faz identidade, storage, PDF, certificado e timestamp fora da transação e revalida sob lock na confirmação | Nenhum. |
| 6D | Tratar falhas, retries, operações abandonadas e artefatos órfãos | backend/infra | 6B, 6C | `VERIFICADO` | Falha antes do artefato marca a operação como `failed`; retry reutiliza a operação; `artifact_ready` é retomável; artefato não confirmado é descartado quando ainda não foi registrado | Reconciliador automático de operações permanentemente abandonadas é melhoria operacional futura, não requisito para retry seguro sob demanda. |
| 6E | Testes concorrentes e de falha nas fronteiras transacionais | backend | 6C, 6D, Parte 7 | `VERIFICADO` | PostgreSQL real comprovou liberação do lock antes do callback externo com `FOR UPDATE NOWAIT`, falha/retry, cobrança somente na confirmação, idempotência e duas assinaturas sequenciais | Chamadas Serpro reais continuam deliberadamente fora do CI para não gerar custo. |

### Parte 7 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 7A | Subir PostgreSQL e Redis isolados no CI | backend/CI | nenhuma | `VERIFICADO` | `ensure-integration-services` sobe ambos via Compose, espera healthchecks e o preflight recusa hosts que não sejam loopback | Nenhum. |
| 7B | Aplicar migrations antes dos testes de integração | backend/CI | 7A | `VERIFICADO` | Workflow executa `make migrate-all` antes de `make test-integration`; migration `0025` foi aplicada em PostgreSQL real | Nenhum. |
| 7C | Tornar testes PostgreSQL obrigatórios no CI | backend/CI | 7A, 7B | `VERIFICADO` | Gate define `RUBRICA_DATABASE_TESTS=1`, executa o arquivo explicitamente e isola dados com `TRUNCATE ... CASCADE` sem contornar os gatilhos append-only | Nenhum. |
| 7D | Tornar testes Redis e concorrência de sessão obrigatórios no CI | backend/CI | 7A | `VERIFICADO` | Gate fornece `RUBRICA_TEST_REDIS_URL` e seleciona explicitamente limitação de login, rotação, replay, logout e concorrência contra Redis real | Nenhum. |
| 7E | Separar e reportar unitários e integração sem duplicar desnecessariamente o pipeline | backend/CI | 7C, 7D | `VERIFICADO` | `make test-unit` exclui somente integrações reais; `make test-integration` seleciona os quatro gates e usa `-rA`, portanto um skip inesperado aparece e falha no preflight por configuração ausente | Nenhum. |

### Parte 8 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 8A | Reavaliar necessidade comercial e operacional de eventing distribuído | produto/arquitetura | receita, escala ou requisito operacional concreto | `ADIADO` | Eventing possui estrutura parcial, mas o produto ainda não justifica Kafka e sua operação | Retomar apenas quando os gatilhos da Parte 8 forem atendidos. |
| 8B | Integrar produtores ao outbox transacional | backend | 8A aprovada | `ADIADO` | Core, Auth e Notification ainda não publicam no eventing de forma operacional | Não expandir agora; manter o fluxo síncrono atual sob testes e observabilidade. |
| 8C | Implementar relay/dispatcher e processamento idempotente | backend/worker | 8B | `ADIADO` | Worker atual é placeholder e não há relay operacional | Definir somente quando existir consumidor real e requisito de entrega assíncrona. |
| 8D | Avaliar Kafka versus alternativa mais simples | arquitetura/infra | 8A | `ADIADO` | Kafka está apenas na direção arquitetural, sem necessidade comprovada | Preferir a menor solução que satisfaça volume, ordenação, retenção e replay exigidos. |
| 8E | Testar entrega, duplicidade, reprocessamento, DLQ e recuperação | backend/infra | 8B–8D | `ADIADO` | Nenhuma topologia operacional foi escolhida | Tornar obrigatório somente se a Parte 8 for formalmente reativada. |

### Parte 9 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 9A | Absorver o contrato da Platform Infra e inventariar a base do Nexo | backend/arquitetura | handoffs Platform Infra e Nexo | `VERIFICADO` | Handoff absorvido; esta especificação e `docs/OBSERVABILITY.md` registram as fronteiras definitivas | Nenhum. O handoff transitório permanece fora do Git. |
| 9B | Adaptar nomes, configurações e contratos do Nexo para o domínio Rúbrica | backend | 9A | `VERIFICADO` | `apps/observability_api`, namespace `rubrica_*` e busca textual sem identificadores estrangeiros no código operacional | Nenhum. |
| 9C | Integrar banco, migrations, Compose, Makefile e checks de runtime | backend/infra | 9B | `VERIFICADO` | Banco `rubrica_observability`, migrations `0001`/`0002`, Compose, readiness, backup e `make migrate-observability`; migration real executada até o head | Nenhum. |
| 9D | Integrar rede privada da plataforma, secret Viewer e degradação segura | backend/infra | 9B, conta de serviço no Grafana | `VERIFICADO` | Cinco aliases privados; secrets de produção; Grafana local parado produziu `health=ok` e status `unavailable`, depois recuperou para `available` | No deploy, o operador ainda deve criar e rotacionar a conta Viewer conforme o runbook; nenhuma credencial é criada pelo código. |
| 9E | Instrumentar métricas HTTP e de produto nas APIs do Rúbrica | backend | 9B, 9C | `VERIFICADO` | `shared_kernel.observability`; collectors Auth/Core/Eventing/Observability; cinco `/metrics` comprovados com Gunicorn multiprocess | Notification expõe métricas HTTP; não recebeu collector de produto porque não há conexão durável própria reutilizável no bootstrap atual. |
| 9F | Implementar autorização e consultas controladas de observabilidade | backend | 9B–9D | `VERIFICADO` | Status interno protegido por `X-Rubrica-Service-Key`, comparação constante e respostas sanitizadas; testes de chave ausente/inválida | Consultas de logs/métricas/traces para usuários permanecem deliberadamente fora deste primeiro corte e exigirão política própria antes de existir. |
| 9G | Configurar coleta, logs, traces, dashboards e alertas na Platform Infra | platform_infra/backend | 9D, 9E, contratos fechados | `VERIFICADO` | Job `rubrica-apis`, dashboard `Rubrica / APIs`, alertas, Tempo na rede privada; cinco targets `up=1`, logs no Loki e traces dos cinco serviços no Tempo | Nenhum no código; provisionar o token Viewer é tarefa de deploy. |
| 9H | Validar migrations, resiliência, segurança e integração ponta a ponta | backend/infra/CI | 9C–9G | `VERIFICADO` | 14 testes focados e suíte completa com 299 aprovados/4 ignorados; Ruff/Poetry/Compose/promtool válidos; migration e smoke Docker executados com plataforma disponível e Grafana indisponível | A validação usou ambiente local e credenciais de desenvolvimento; repetir o smoke após o deploy de produção sem expor secrets. |

### Parte 10 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 10A | Inventariar arquivos, buckets, prefixes, referências e limites de acesso | backend/infra | nenhuma | `EM ANDAMENTO` | Storage, R2, banco e scripts operacionais já foram localizados; a matriz completa por artefato ainda não foi fechada | Concluir originais, versões, assinados, evidências, ativos visuais, temporários, órfãos e backups. |
| 10B | Criar clone fiel e isolado de produção em staging para o ensaio | backend/infra | 10A, bucket exclusivo | `VERIFICADO` | Em 2026-10-25, `rubrica_core` foi clonado e 54/54 objetos foram copiados sem mutar produção; um objeto ausente no R2 foi recuperado em modo somente leitura do volume legado pelo SHA-256 | Preservar o procedimento para o runbook e o futuro teste de restauração. |
| 10C | Criar reconciliação sanitizada e baseline antes da migração | backend/infra | 10B | `VERIFICADO` | O clone confirmou 54 referências, 16.884.302 bytes, zero ausentes e zero inválidos; os 54 objetos foram autenticados contra os SHA-256 do banco e classificados como plaintext legado antes da migração | Repetir a reconciliação depois da cifra e no rollout produtivo. |
| 10D | Implementar envelope encryption por tenant, documento e objeto | backend/segurança | 10A–10C | `IMPLEMENTADO` | Formato v2 deriva contextos tenant/documento, gera DEK aleatória por objeto, embrulha a DEK e cifra chunks AES-256-GCM com AAD e terminador autenticado | Validar no R2 real e inspecionar que o download direto é opaco. |
| 10E | Definir custódia, rotação e separação das chaves | backend/infra/segurança | 10D | `EM ANDAMENTO` | Root secret é separado do R2/banco; senha do usuário foi rejeitada; hierarquia e versão foram implementadas | Comprovar backup/restore da root, documentar rotação e avaliar migração futura para OCI Vault/KMS. |
| 10F | Migrar o clone em staging com dual-read e new-write cifrado | backend/infra | 10C–10E | `IMPLEMENTADO` | New-write usa v2; leitor aceita v2, v1 e plaintext controlado; clone e baseline reais foram aprovados com 54 objetos | Concluir a cifra dos 54 objetos, reconciliação pós-migração e desligamento do fallback no clone. |
| 10G | Otimizar e medir o caminho R2 → Core → visualizador | ambos/infra | 10D–10F | `IMPLEMENTADO` | Core transmite chunks verificados via `StreamingResponse`, desliga buffering Nginx, reutiliza cliente R2, expõe histogramas por estágio e o dashboard reutiliza o último preview na sessão; smoke isolado de 1/10/25/50 MiB manteve pico Python em 16,5 MiB ao cifrar e 9,38 MiB ao decifrar | Repetir benchmark com amostras, concorrência e medição real do navegador/R2 no servidor. |
| 10H | Validar confidencialidade, integridade, isolamento e falhas | backend/segurança | 10D–10G | `IMPLEMENTADO` | Testes cobrem round-trip em chunks, adulteração, truncamento, chave errada e troca de tenant/documento; 321 unitários backend passaram | Completar prova no bucket real, falha durante upload/migração e integração PostgreSQL. |
| 10I | Validar backup, restauração, retenção e descarte criptográfico | backend/infra/produto | 10E–10H | `NÃO INICIADO` | Restic e buckets separados existem, mas a restauração conjunta ainda não foi comprovada | Testar restauração de banco+objetos+chaves, RPO/RTO, legal hold, rotação e perda controlada de chave. |
| 10J | Planejar e executar rollout de produção com plaintext desativado | backend/infra | 10A–10I verificados | `NÃO INICIADO` | Produção permanece intacta e fora do ensaio; concluir staging não encerra esta Parte | Aprovar janela, cópia independente de rollback, backup, dry-run, lotes, observação, reconciliação final e remoção definitiva do fallback plaintext. |

### Parte 11 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 11A | Fechar modelo de documento, versão e rodadas encadeadas | produto/ambos | decisões desta Parte 11 | `VERIFICADO` | Contrato exige motivo, nova validade e seleção dos pendentes; novos signatários entram no rascunho da rodada criada | Nenhum. |
| 11B | Persistir encadeamento e criar nova rodada sem mutar a expirada | backend | 11A | `VERIFICADO` | Migration `0027`, autorrelacionamento único, número da rodada, endpoint idempotente e evento `signature_request.reopened`; teste PostgreSQL comprova que a rodada anterior não é alterada | Nenhum. |
| 11C | Preservar assinaturas e selecionar o artefato-base correto | backend | 11A, 11B | `VERIFICADO` | Nova rodada referencia a última versão assinada por storage key e SHA-256, verifica os bytes antes de persistir e incorpora evidências ancestrais no PDF seguinte | Nenhum. |
| 11D | Interface de reabertura e histórico agrupado | frontend | 11B, 11C | `VERIFICADO` | Dashboard oferece reabertura somente para solicitação expirada, modal de prazo/motivo/pendentes, abre o novo rascunho e agrupa o histórico de rodadas | Nenhum. |
| 11E | Links, notificações e auditoria da nova rodada | ambos | 11B–11D | `VERIFICADO` | Solicitação expirada não gera novo link; a rodada reaberta usa novo nonce e o fluxo existente envia convites idempotentes aos pendentes quando o emissor gerar o link | Nenhum. |
| 11F | Testes de integridade, permissões e múltiplas rodadas | ambos | 11B–11E | `IMPLEMENTADO` | Integração real PostgreSQL valida imutabilidade, idempotência, hash do artefato-base, preservação de duas evidências e bloqueio de link vencido; 303 testes unitários, 5 integrações e 61 testes frontend passaram | Acrescentar E2E visual da jornada completa quando houver navegador Playwright compatível; não bloqueia a implementação funcional. |

### Parte 12 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 12A | Inventariar e classificar comandos, Compose, arquivos de ambiente e profiles atuais | backend/infra | nenhuma | `VERIFICADO` | Makefile, overlays, serviços, portas, profiles, secrets e aliases foram confrontados; comandos locais ambíguos foram descontinuados com erro explícito | Nenhum. |
| 12B | Separar configuração e secrets entre dev, staging e produção | backend/infra | 12A | `VERIFICADO` | `.env.example`, `.env.staging.example` e `.env.production.example` possuem contratos distintos; staging cria secrets exclusivos sem sobrescrever e readiness validou conteúdo/permissão | Nenhum. |
| 12C | Implementar `make dev` com aplicações 100% bare metal | ambos/devex | 12A, 12B | `IMPLEMENTADO` | `toolbox/dev/run.py` inicia cinco APIs Uvicorn e Angular com hot reload, carrega o env escolhido e coordena falha/encerramento sem Docker | Executar smoke interativo completo após corrigir a propriedade do diretório local legado `.rubrica-storage`; testes usaram storage temporário seguro. |
| 12D | Implementar `make dev-docker` para dependências conteinerizadas | backend/infra/devex | 12A–12C | `IMPLEMENTADO` | Catálogo allowlist de PostgreSQL, Redis, Kafka, Loki, docs, Stripe CLI e Quick Tunnel; parser testado rejeita APIs internas e ativa profiles opcionais; portas somente em loopback | Executar smoke dos contêineres após estabilizar o Docker Desktop/WSL; nenhuma API interna está no Compose de dev. |
| 12E | Implementar staging remoto totalmente conteinerizado | ambos/infra | 12B–12D | `IMPLEMENTADO` | `compose/staging.yml`, Docker Secrets próprios, volume de documentos, gateway, Quick Tunnel padrão, providers fake/local por padrão, Stripe CLI test-mode opcional, migrations e seed de 14 fixtures | Validar no servidor a URL `trycloudflare.com`; quando Stripe estiver em teste, comprovar `sk_test_`, sincronização do `whsec_` e webhook ponta a ponta. |
| 12F | Consolidar `production-ensure`, `production-bootstrap` e deploy recorrente | backend/infra | 12A, 12B, 12E | `IMPLEMENTADO` | Ensure exige R2, valida Compose/isolation; bootstrap separa migration, subida e provider check; produção renderizada não publica portas e exclui ferramentas de dev | Revalidar no servidor com secrets e providers reais; nenhuma chamada paga foi feita localmente. |
| 12G | Reorganizar Makefile e preservar aliases seguros durante a transição | backend/infra/devex | 12C–12F | `VERIFICADO` | Interface canônica aparece em `make help`; aliases perigosos/ambíguos falham ou encaminham para operações seguras e operações de dados são explícitas | Nenhum. |
| 12H | Fechar topologia, redes e exposição de portas por nível | backend/infra/segurança | 12C–12F | `VERIFICADO` | Teste de contrato e Compose renderizado comprovam dependências dev em loopback, somente gateway de staging em loopback e zero host ports em produção | Runtime de staging continua pendente em 12E, sem alterar a validação estrutural da topologia. |
| 12I | Separar observabilidade de desenvolvimento, staging e produção | backend/infra/platform_infra | 12C–12H, Parte 9 | `IMPLEMENTADO` | Loki local é opcional por catálogo e comandos `telemetry-*`; observability_api integra staging/produção pela rede externa existente e preserva degradação segura da Parte 9 | Repetir smoke integrado de staging após correção do Docker; Platform Infra completa continua fora do Compose do produto. |
| 12J | Implementar readiness e probes operacionais dos providers | backend/infra | 12E, 12F, 12I | `IMPLEMENTADO` | Staging readiness valida ambiente/secrets; produção diferencia ensure estrutural, check operacional seguro de PostgreSQL/Redis e comando pago que recusa execução automática | Probes reais dos providers externos dependem do servidor e permanecem `não testados`; ampliar somente com operação segura específica e autorização quando houver efeito/custo. |
| 12K | Separar apenas o destino do armazenamento entre não produção e produção | backend/infra | 12B–12H, contrato da Parte 10 | `VERIFICADO` | Dev usa `.runtime/documents`, staging volume `document_storage`, produção é recusada sem `DOCUMENT_STORAGE_PROVIDER=r2`; abstração de negócio não foi duplicada | A auditoria aprofundada do ciclo de vida continua reservada à Parte 10. |
| 12L | Testar os três níveis, seleção de serviços e proteções cruzadas | backend/infra/CI | 12C–12K | `IMPLEMENTADO` | Ruff; 307 testes backend; 61 frontend; lint/build; 5 testes de seleção/isolation; contratos renderizados e staging completo comprovado com secrets, volumes, migrations, healthchecks e gateway | Smoke interativo bare metal/dev-docker ainda depende do ciclo de desenvolvimento; produção somente pode ser comprovada no servidor. |
| 12M | Atualizar os `AGENTS.md` com o fluxo operacional definitivo do Rúbrica | ambos/documentação | 12C–12L verificados | `VERIFICADO` | `AGENTS.md` backend contém contrato canônico; frontend possui instrução mínima autônoma e referência ao orquestrador; README e Make help alinhados | Nenhum. |

## Parte 1 — tabelas e ordenação

### Superfícies afetadas

1. Tabela de documentos que foram enviados ao Rúbrica.
2. Tabela de solicitações abertas para assinatura.

### Requisitos confirmados

- Adotar uma biblioteca pronta de DataTable nas duas superfícies.
- Manter todos os filtros existentes.
- Acrescentar novos filtros; os campos exatos ainda serão definidos pelo usuário.
- Corrigir o caso em que um arquivo recém-enviado aparece no fim da lista.
- Por padrão, documentos e solicitações mais recentes devem aparecer primeiro.
- Manter as ações e capacidades atuais das listas durante a troca do componente.
- Desenvolver a feature em branch própria, separada da `main`.

### Diagnóstico preliminar observado em 2026-10-15

- O frontend usa Angular 22, Bootstrap 5 e tabelas próprias; não há biblioteca de DataTable declarada no `package.json`.
- O dashboard carrega documentos por `GET /documents` e solicitações por `GET /signature-requests`.
- As solicitações são reordenadas no cliente usando comparação lexicográfica/numeric-aware do `id`. Isso não é uma garantia válida de ordem cronológica.
- O modelo de ambos os itens contém `created_at`, que deve ser a chave cronológica principal.
- A implementação precisa confirmar e garantir a ordenação nos endpoints, pois ordenação apenas no cliente é incorreta quando houver paginação ou carregamento parcial.

### Critérios de aceitação da Parte 1

- Um upload concluído aparece no topo da tabela de documentos quando a ordenação padrão estiver ativa.
- Uma solicitação recém-criada aparece no topo da tabela de assinaturas abertas quando a ordenação padrão estiver ativa.
- Recarregar a página mantém a mesma ordem.
- Itens com o mesmo `created_at` possuem desempate estável por `id` decrescente.
- Todos os filtros atuais continuam produzindo o mesmo resultado funcional.
- A biblioteca selecionada funciona com Angular 22, tem licença compatível com o projeto e não exige edição comunitária limitada para funções obrigatórias.
- As duas tabelas continuam responsivas, traduzidas e utilizáveis por teclado.
- Testes automatizados demonstram ordenação, filtragem e atualização após criação.

### Decisões ainda pendentes

- Quais novos filtros serão adicionados.
- Contrato definitivo de paginação, filtro e ordenação server-side.
- Biblioteca específica, após validação técnica no momento da implementação.
- Tamanho de página, colunas configuráveis, seleção em lote e preferências persistentes.

## Parte 2 — posicionamento prévio dos carimbos

### Objetivo

Ao abrir uma solicitação para assinatura e disponibilizar seus links, permitir que a pessoa responsável pelo envio determine previamente onde cada carimbo visual deverá aparecer no PDF. Um documento pode exigir vários carimbos, inclusive um carimbo em cada página.

Neste requisito, **carimbo** significa a representação visual da assinatura/rubrica aplicada ao PDF. Ele não é o Carimbo do Tempo SERPRO/RFC 3161, que continua sendo uma evidência criptográfica independente de posição na página.

### Requisitos confirmados

- O posicionamento personalizado de carimbos é exclusivo de conta com assinatura paga ativa.
- Conta gratuita não pode escolher posições. Ela permanece no comportamento padrão de posicionamento já oferecido pelo produto.
- Para conta gratuita, o frontend não deve apresentar botão, controle desabilitado, cadeado, modal, banner ou chamada de upgrade relacionada a essa capacidade dentro do fluxo de documentos e assinaturas.
- A vantagem do posicionamento personalizado pode aparecer na landing page e na comparação pública dos planos.
- A restrição de plano também deve ser aplicada no backend, para impedir uso por chamadas diretas à API.
- O controle das posições pertence a quem prepara e abre a solicitação de assinatura.
- A escolha acontece antes de os links de assinatura serem disponibilizados.
- A interface deve exibir o PDF e permitir indicar visualmente os locais dos carimbos.
- Deve ser possível definir posições em páginas diferentes.
- Deve ser possível configurar um carimbo por página quando o documento exigir isso.
- As posições precisam ser persistidas no backend e vinculadas à versão exata do documento aberta para assinatura.
- O signatário deve receber a instrução de assinar nos locais previamente definidos, em vez de depender somente de escolher livremente uma posição durante a assinatura.

### Regra comercial e autorização

- O frontend deve consultar uma capacidade explícita, como `custom_stamp_placement`, derivada pelo backend do plano vigente, e só renderizar a interface de posicionamento quando ela estiver habilitada.
- O backend deve validar essa capacidade ao salvar posições e novamente ao abrir a solicitação, impedindo que chamadas diretas contornem o plano.
- Todos os planos pagos ativos podem usar a capacidade, inclusive o plano Essencial, salvo futura decisão comercial diferente.
- Acesso vitalício cortesia não deve ser tratado automaticamente como plano pago. Ele só recebe essa capacidade se o produto conceder explicitamente esse entitlement.
- O downgrade ou cancelamento não apaga posições nem documentos históricos. Solicitações já abertas continuam assináveis com a configuração congelada; novos rascunhos e rascunhos ainda não abertos deixam de poder usar a capacidade.
- Uma chamada direta não autorizada deve produzir erro de domínio claro, sem depender de redirecionamento comercial e sem afetar o acesso do signatário a uma solicitação que já tenha sido aberta validamente.

### Modelo funcional esperado

Cada posição precisa conter, no mínimo:

- identificador da solicitação;
- versão congelada do documento;
- número da página;
- coordenadas e dimensões independentes do zoom da interface;
- ordem estável;
- signatário destinatário, quando a posição for individual;
- autoria e data da configuração.

O backend deve rejeitar páginas inexistentes, coordenadas fora dos limites, dimensões inválidas e posições pertencentes a outra versão do documento. A composição final deve converter as coordenadas para o sistema do PDF sem deslocamento causado por zoom, rotação, tamanho de tela ou densidade de pixels.

### Ciclo de vida

1. O responsável prepara a solicitação e adiciona os signatários.
2. Visualiza a versão que será congelada para assinatura.
3. Adiciona e ajusta uma ou mais posições de carimbo nas páginas desejadas.
4. O sistema valida a configuração e mostra uma prévia fiel.
5. Ao abrir a solicitação, documento, signatários e posições são congelados como parte da mesma operação lógica.
6. Os links são disponibilizados somente após a abertura válida.
7. Durante a assinatura, o sistema usa as posições destinadas àquele signatário e registra na evidência quais posições foram efetivamente aplicadas.

### Evidências e múltiplos carimbos

Não duplique o pacote completo de evidências para cada carimbo visual. A unidade probatória é o evento de assinatura do signatário, não cada desenho repetido no PDF.

- Produza uma evidência canônica por evento de assinatura.
- Inclua nessa evidência uma lista imutável das posições efetivamente aplicadas, contendo página, coordenadas, dimensões, ordem e identificador lógico da posição.
- Todos os carimbos visuais decorrentes do mesmo evento devem referenciar o mesmo `signature_id` e, quando exibido ou incorporado, o mesmo identificador/hash da evidência.
- É aceitável repetir nos carimbos informações visuais resumidas, como nome, data e identificador da assinatura. Isso não cria uma nova evidência.
- Não gere um JSON completo por página, não repita anexos de evidência e não solicite um novo Carimbo do Tempo SERPRO apenas porque a mesma assinatura aparece visualmente em várias páginas.
- Para múltiplos signatários, cada evento de assinatura continua tendo sua própria evidência canônica e sua própria lista de posições.
- O manifesto consolidado do documento pode relacionar todas as assinaturas e posições, mas deve referenciar as evidências canônicas sem copiá-las de maneira divergente.

### Critérios de aceitação da Parte 2

- O responsável consegue posicionar um carimbo em qualquer página válida antes de abrir a solicitação.
- Consegue cadastrar posições em múltiplas páginas, inclusive uma em cada página.
- A prévia e o PDF final apresentam o carimbo no mesmo local, dentro de tolerância técnica definida pelos testes.
- Reabrir o rascunho mantém exatamente as posições salvas.
- Não é possível abrir a solicitação com configuração incompleta ou inválida.
- Depois da abertura, posições não podem ser alteradas silenciosamente.
- Um signatário não utiliza por engano a posição destinada a outro.
- Zoom, rotação e viewport móvel não alteram a posição final no PDF.
- Assinaturas sucessivas preservam os bytes e as evidências criptográficas anteriores conforme o fluxo de assinatura incremental já adotado pelo projeto.
- O Carimbo do Tempo SERPRO continua sendo aplicado e validado independentemente dos carimbos visuais.
- Uma assinatura com vários carimbos visuais produz um único registro canônico de evidência, contendo todas as posições aplicadas.
- Conta gratuita não consegue salvar nem abrir uma solicitação com posicionamento personalizado, inclusive por chamada direta à API.
- Em conta gratuita, nenhum elemento dessa capacidade existe na interface autenticada do fluxo de documentos e assinaturas.
- A landing page pode apresentar o posicionamento personalizado como vantagem dos planos pagos.
- Conta paga ativa consegue usar a capacidade conforme os demais critérios desta parte.
- Cancelamento ou downgrade não remove evidências nem invalida solicitações que já estavam abertas.

### Casos que os testes devem cobrir

- uma posição em uma página;
- uma posição em cada página;
- várias posições na mesma página;
- documento com páginas de tamanhos diferentes;
- página rotacionada;
- posições próximas às bordas;
- tentativa de posição fora da página;
- recarregamento do rascunho;
- múltiplos signatários com posições distintas;
- aplicação sucessiva sem invalidar assinaturas anteriores;
- tentativa de alterar posições depois da abertura;
- documento ou versão diferente da usada na configuração;
- verificação de que os controles não são renderizados para conta gratuita;
- tentativa de uso por conta gratuita diretamente pela API;
- exibição dos controles para conta paga elegível;
- uso por cada plano pago ativo;
- conta cortesia sem entitlement explícito;
- cancelamento ou downgrade com rascunho e com solicitação já aberta;
- vários carimbos da mesma assinatura apontando para uma única evidência;
- múltiplos signatários, cada qual com evidência canônica independente.

### Decisões fechadas neste corte

- Toda posição pertence obrigatoriamente a um signatário; não existem posições genéricas.
- Posição predefinida é fixa para o signatário. Sem posição predefinida, permanece o posicionamento padrão já existente.
- O editor oferece replicação automática da posição do signatário em todas as páginas.
- Dimensões são limitadas pelo contrato e sobreposição entre signatários na mesma página é rejeitada.
- A configuração fica imutável após a abertura; qualquer mudança exige novo rascunho/solicitação.
- O acesso vitalício cortesia não recebe esse entitlement implicitamente.

## Parte 3 — personalização empresarial do carimbo

### Elegibilidade comercial

- Capacidade disponível somente para tenant empresarial com CNPJ configurado e plano Profissional (`rubrica_intermediate`) ou Equipe (`rubrica_team`) ativo.
- Plano gratuito e plano Essencial não recebem a capacidade.
- O frontend autenticado não renderiza editor, botão desabilitado, cadeado, banner ou modal de upgrade para contas inelegíveis.
- A landing page e a comparação pública de planos podem apresentar a personalização como vantagem dos planos empresariais.
- O backend valida tenant, CNPJ e plano ao salvar a personalização e novamente ao abrir a solicitação.
- O sistema deve reutilizar a política central de recursos empresariais do billing para evitar regras divergentes entre representação empresarial e personalização.

### Objetivo

Permitir que a empresa personalize a aparência dos carimbos usados em seus documentos, incluindo sua marca, e ofereça opcionalmente ao signatário uma área para desenhar uma assinatura com mouse ou toque. A configuração efetivamente usada é escolhida por quem emite o documento.

### Tipos distintos de carimbo

#### Carimbo institucional/CNPJ

- Representa visualmente a pessoa jurídica e pode conter logo, razão social, nome fantasia e CNPJ conforme a configuração do tenant.
- Logo e CNPJ impressos não constituem, por si sós, assinatura digital da empresa.
- O sistema só deve apresentar esse carimbo como assinatura da pessoa jurídica quando o evento tiver uma credencial organizacional apropriada, como um fluxo empresarial com certificado correspondente.
- Sem essa credencial, a marca empresarial pode aparecer como identidade visual do emissor, mas não deve criar a alegação de que o CNPJ assinou criptograficamente.

#### Carimbo de representante

- Identifica a pessoa natural que realizou a assinatura e a pessoa jurídica que ela representa.
- Deve manter visíveis ou verificáveis o nome do signatário, a empresa/CNPJ representados, o papel de representação e o identificador da assinatura/evidência.
- A personalização não pode esconder quem efetivamente manifestou vontade nem transformar uma assinatura de representante em assinatura direta da empresa.
- Deve usar o snapshot de representação empresarial já congelado no fluxo, sem consultar dados mutáveis para reconstruir o histórico.

### Componentes personalizáveis

O emissor pode selecionar, por solicitação, uma configuração permitida pelo tenant, incluindo:

- template de carimbo institucional ou de representante compatível com o tipo de participante;
- logo empresarial;
- cores dentro dos limites de contraste e legibilidade;
- campos empresariais permitidos;
- exibição da assinatura manuscrita desenhada;
- tamanho e disposição dos elementos dentro da área de carimbo.

Campos técnicos obrigatórios para rastreabilidade não podem ser removidos pelo editor. O resultado deve continuar legível em tela, impressão e validadores de PDF.

### Assinatura manuscrita com mouse ou toque

- Quando habilitada pelo emissor, a tela de assinatura permite ao signatário desenhar sua assinatura usando mouse, caneta ou toque do celular.
- O signatário deve poder limpar e refazer o desenho antes da confirmação.
- O desenho é um elemento visual opcional vinculado ao evento de assinatura; não é certificado digital, autenticação biométrica nem prova autônoma de identidade.
- O método de autenticação, consentimento, hash do documento, evidência canônica e eventual assinatura criptográfica continuam sendo as fontes técnicas de autoria e integridade.
- Armazene uma representação visual normalizada e seu hash. Por padrão, não retenha pressão, velocidade, ritmo ou outros dados comportamentais do traçado.
- O backend deve normalizar e rasterizar/serializar de forma segura o desenho antes da incorporação, com limites de tamanho, complexidade e coordenadas.

### Identidade visual e segurança de arquivos

- Aceite somente formatos de imagem explicitamente permitidos e normalize o conteúdo no backend antes de armazenar ou incorporar ao PDF.
- Defina limites de bytes, dimensões e proporção.
- Remova metadados desnecessários e rejeite conteúdo ativo, referências externas e arquivos malformados.
- Não incorpore diretamente SVG fornecido pelo usuário; quando aceito como entrada, sanitize e converta para formato seguro antes do uso.
- Preserve contraste, área de segurança e tamanho mínimo para que a marca não encubra informações técnicas obrigatórias.

### Persistência e imutabilidade

- O tenant pode manter uma configuração padrão reutilizável, mas o emissor decide se e como ela será usada em cada solicitação.
- Ao abrir a solicitação, congele um snapshot completo do template, logo normalizado, campos selecionados e regras de assinatura desenhada.
- Mudanças futuras no logo ou template do tenant não alteram solicitações abertas, PDFs concluídos nem evidências históricas.
- Registre quem selecionou a personalização, quando, qual versão foi usada e o hash dos ativos incorporados.
- A evidência canônica da assinatura referencia a versão do template, os hashes dos ativos e se houve desenho manuscrito, sem duplicar a evidência para cada ocorrência visual.

### Ciclo de vida

1. Um administrador empresarial configura e salva os padrões de identidade visual permitidos.
2. Ao preparar a solicitação, o emissor escolhe entre os templates compatíveis com cada tipo de participante.
3. O emissor decide se a assinatura manuscrita desenhada será usada naquele documento.
4. A prévia mostra o carimbo final junto das posições definidas na Parte 2.
5. Na abertura, o backend revalida elegibilidade e congela a configuração.
6. O signatário desenha a assinatura apenas quando essa opção tiver sido habilitada.
7. O sistema incorpora o carimbo conforme o snapshot e registra os hashes e referências na evidência canônica.

### Critérios de aceitação da Parte 3

- Apenas tenant com CNPJ e plano Profissional ou Equipe ativo consegue configurar ou selecionar carimbo personalizado.
- Contas inelegíveis não veem controles autenticados e não conseguem contornar a regra pela API.
- Logo válido aparece na prévia e no PDF final sem alterar proporção ou legibilidade.
- Arquivo inválido, excessivo ou com conteúdo ativo é rejeitado.
- Carimbo institucional e carimbo de representante usam templates e alegações distintas.
- O carimbo de representante identifica simultaneamente a pessoa signatária e a empresa representada.
- A personalização não remove identificadores técnicos obrigatórios.
- A assinatura desenhada funciona com mouse e toque, pode ser refeita antes da confirmação e permanece opcional conforme a decisão do emissor.
- Ausência de assinatura desenhada não altera a validade técnica dos demais métodos quando o emissor não a habilitou.
- Uma mudança posterior no logo ou template não modifica solicitações abertas nem documentos concluídos.
- Todas as ocorrências visuais da mesma assinatura continuam apontando para uma única evidência canônica.
- O PDF continua verificável independentemente do frontend do Rúbrica.

### Casos que os testes devem cobrir

- plano gratuito, Essencial, Profissional e Equipe;
- tenant pessoal ou empresarial sem CNPJ;
- tentativa direta pela API sem entitlement;
- logo PNG/JPEG válido, arquivo excessivo, formato inválido e conteúdo malformado;
- template institucional e template de representante;
- representante de empresas diferentes sem cruzamento de identidade visual;
- desenho com mouse, toque e caneta;
- limpar, refazer, confirmar desenho vazio e desenho excessivamente complexo;
- aplicação do mesmo desenho nas posições autorizadas sem duplicar evidências;
- atualização do logo após abertura e após conclusão;
- downgrade com rascunho e com solicitação já aberta;
- documento com múltiplos signatários e diferentes tipos de carimbo;
- impressão e visualização móvel do PDF final.

### Decisões fechadas neste corte

- O emissor decide por solicitação se o desenho é exigido; quando não exigido, o fluxo padrão permanece.
- O desenho é representação visual e não substitui identificação, consentimento ou assinatura criptográfica.
- Somente PNG é aceito; o backend decodifica, valida dimensões/conteúdo e regrava em PNG normalizado.
- O tenant mantém um padrão reutilizável e cada solicitação congela seu próprio snapshot.
- A personalização usa modelos seguros predefinidos, sem HTML/SVG ou template livre.
- Templates institucional e de representante são distintos; o representante preserva pessoa e empresa na evidência.
- Acesso vitalício cortesia não recebe branding empresarial implicitamente.

## Parte 4 — verificação opcional de identidade com documento e rosto

### Estado e escopo

- Capacidade opcional por solicitação, habilitada por decisão de quem emite o documento.
- Não é requisito global para assinar no Rúbrica e não substitui SerproID, certificado ICP-Brasil, consentimento ou as evidências já existentes.
- Destinada ao fluxo empresarial de maior garantia; elegibilidade comercial exata e cobrança por uso ainda precisam ser fechadas.
- Provedor preferencial: Datavalid V5 da Serpro, condicionado à contratação, credenciamento regulatório e contratação de uma GCC.

### Cobertura da CNH e limites

O caminho de maior confiança do Datavalid compara a selfie com uma referência biométrica disponível em base oficial da Senatran. Na prática, essa referência está normalmente associada à CNH. Portanto:

- possuir CPF não garante que exista uma biometria facial oficial disponível;
- quem possui CNH com biometria disponível pode usar o fluxo oficial completo;
- a decodificação e validação do QR Code exige uma CNH compatível;
- uma pessoa sem CNH pode ainda ter dados cadastrais validados, mas pode não dispor da comparação facial oficial necessária;
- quando a referência oficial estiver indisponível, o Datavalid pode usar uma foto de referência fornecida pelo cliente, se essa modalidade estiver contratada, mas o nível de garantia é inferior;
- a evidência deve distinguir `official_government_reference` de `customer_supplied_reference` e nunca apresentar os dois resultados como equivalentes.

O sistema não deve prometer que o recurso atende toda pessoa com CPF. Antes da abertura, o emissor precisa conhecer a política de fallback definida para signatários sem cobertura biométrica oficial.

### Modalidades

#### Verificação oficial preferencial

- validação cadastral/biográfica;
- prova de vida;
- comparação facial contra referência governamental disponível;
- validação do QR Code da CNH quando apresentado;
- resultado e identificador de transação recebidos diretamente pelo backend.

#### Fallback com documento ou foto de referência

- captura segura do documento e/ou foto de referência;
- prova de vida da selfie;
- comparação entre a selfie viva e a foto fornecida;
- indicação explícita de que não houve comparação facial com base governamental;
- possibilidade de revisão manual ou uso de outro método de assinatura quando o risco do documento não permitir aprovação automática.

Esse fallback confirma compatibilidade entre duas imagens e vivacidade, mas não garante sozinho que o documento apresentado seja autêntico. OCR ou extração de dados também não equivalem a documentoscopia.

### Configuração pelo emissor

Ao preparar a solicitação, o emissor pode escolher:

- não exigir verificação facial;
- exigir prova de vida e comparação oficial quando disponível;
- permitir ou negar fallback por foto/documento fornecido;
- exigir QR Code válido da CNH;
- definir o comportamento em resultado inconclusivo: nova tentativa, revisão ou recusa;
- aplicar a exigência a todos os signatários ou a participantes específicos.

A política escolhida é congelada ao abrir a solicitação e apresentada ao signatário antes da coleta.

### Fluxo técnico

1. O backend cria uma sessão curta, única e vinculada ao signatário, solicitação e versão/hash do documento.
2. O signatário recebe informação clara sobre finalidade, dados tratados, provedor e retenção.
3. A captura ocorre pela câmera no fluxo controlado do provedor; upload comum não substitui a prova de vida.
4. O backend obtém o token/autorização da GCC quando exigido e chama o Datavalid.
5. O resultado é recuperado e validado pelo backend, incluindo correlação da sessão e proteção contra replay.
6. A política congelada decide aprovação, nova tentativa, revisão ou fallback.
7. Somente uma aprovação válida libera a assinatura quando a verificação tiver sido exigida.
8. A evidência canônica registra o resultado antes da operação de assinatura.

### Evidências e retenção

Registrar, no mínimo:

- provedor e versão da API;
- identificador da transação e da sessão;
- modo de referência facial efetivamente usado;
- validações solicitadas e realizadas;
- resultado da vivacidade e da comparação facial;
- faixas/pontuações necessárias para auditoria, protegidas de exposição pública;
- política e limiares vigentes;
- número e resultado das tentativas;
- CPF pseudonimizado;
- hashes dos artefatos necessários;
- signatário, solicitação, documento e data/hora vinculados;
- informação/consentimento ou outra base legal aplicável registrada.

Por padrão, não incorporar selfie, vídeo, foto do documento ou template biométrico ao PDF. Definir retenção mínima e criptografada quando algum artefato precisar ser preservado.

### Critérios de aceitação da Parte 4

- O emissor pode ativar ou não a verificação em cada solicitação elegível.
- Solicitações sem a opção continuam usando o fluxo atual sem coleta biométrica.
- Quando exigida, nenhuma assinatura é concluída antes de resultado válido conforme a política congelada.
- Sessão de outro signatário, solicitação ou documento é rejeitada.
- Uma sessão aprovada não pode ser reutilizada.
- O resultado oficial e o fallback são rotulados e comprovados de formas distintas.
- Ausência de CNH ou biometria oficial segue a política escolhida, sem aprovação silenciosa.
- Indisponibilidade do Serpro não é convertida em aprovação; o fluxo aguarda, permite nova tentativa ou usa fallback autorizado.
- O frontend nunca toma sozinho a decisão de aprovação.
- Biometria e documentos não são expostos no carimbo visual nem no JSON público de evidências.
- O histórico permanece verificável após mudança de plano, provedor ou política.

### Casos que os testes devem cobrir

- CNH válida com QR Code, vivacidade e biometria oficial disponíveis;
- CPF válido sem referência facial governamental disponível;
- pessoa sem CNH;
- fallback autorizado e fallback proibido;
- selfie viva compatível e incompatível;
- fotografia, vídeo, replay e tentativa de troca de sessão;
- resultado inconclusivo e limite de tentativas;
- indisponibilidade, timeout e resposta malformada do provedor;
- resposta válida vinculada a outra solicitação ou pessoa;
- revogação/expiração da sessão antes da assinatura;
- múltiplos signatários com exigências diferentes;
- retenção e descarte dos artefatos biométricos;
- auditoria sem exposição de dado biométrico no PDF.

### Custos e decisões pendentes

- Obter cotação formal do Datavalid V5 para `Validação completa` e `Biométrica composta com prova de vida` nos volumes esperados.
- Obter preço e condições da GCC obrigatória.
- Definir se o custo será franquia, crédito pré-pago ou cobrança por uso.
- Definir planos empresariais elegíveis e tratamento de acesso vitalício cortesia.
- Definir política de retry e quem absorve tentativas cobradas e inconclusivas.
- Definir fornecedor/fallback para estrangeiros e documentos não cobertos.
- Definir quando a revisão humana será obrigatória.
- Realizar avaliação de impacto à proteção de dados antes da produção.

## Parte 5 — novidades da release no SweetAlert de atualização

### Objetivo

Enriquecer o SweetAlert já exibido quando o Angular Service Worker detecta uma nova versão. Além de informar que existe uma atualização, o modal deve mostrar dados estruturados da release e uma lista curta do que mudou no Rúbrica.

### Estado atual observado em 2026-10-16

- `rubrica-front/src/app/core/pwa-update.service.ts` escuta `VERSION_READY` do `SwUpdate`.
- O SweetAlert atual mostra somente título e texto genéricos traduzidos.
- Ao confirmar, chama `activateUpdate()` e recarrega a página.
- Ao escolher “Depois”, não ativa a atualização.
- O `ngsw-config.json` ainda não declara metadados de release em `appData`.

### Contrato JSON

Formato inicial recomendado:

```json
{
  "schema_version": 1,
  "release_id": "2026.10.16.1",
  "released_at": "2026-10-16T18:00:00Z",
  "content": {
    "pt-BR": {
      "title": "Uma nova versão do Rúbrica está disponível",
      "highlights": [
        "Documentos recentes agora aparecem primeiro.",
        "O fluxo de assinaturas ficou mais rápido."
      ]
    },
    "en": {
      "title": "A new Rubrica version is available",
      "highlights": [
        "Recent documents now appear first.",
        "The signing flow is faster."
      ]
    }
  }
}
```

Regras do contrato:

- `schema_version`: inteiro positivo usado para evolução compatível do formato;
- `release_id`: identificador único, imutável e diferente do hash técnico do service worker;
- `released_at`: data/hora ISO 8601 em UTC;
- `content`: mapa por locale suportado;
- `title`: título curto opcional; quando ausente, usar a tradução padrão da interface;
- `highlights`: de uma a cinco frases curtas, preferencialmente com até 120 caracteres cada;
- `pt-BR` deve ser o fallback editorial quando o locale ativo não existir, seguido pelo texto genérico atual;
- nenhum campo aceita HTML fornecido no JSON.

### Origem e correlação com a versão

- Preferir metadados `appData` da versão gerada pelo Angular Service Worker, pois o evento `VERSION_READY` já disponibiliza `latestVersion.appData`.
- Se for mantido um arquivo-fonte JSON separado para facilitar a edição editorial, o processo de build deve validá-lo e incorporá-lo ao `appData`; não buscar um `latest.json` sem versão que possa ficar desalinhado com o bundle pronto.
- O modal deve ler exclusivamente os metadados de `event.latestVersion`, garantindo que as novidades correspondam exatamente à versão que será ativada.
- Falha, ausência ou versão desconhecida do JSON não bloqueia atualização: mostrar o texto genérico existente.

### Comportamento do SweetAlert

- Manter os botões “Atualizar” e “Depois”.
- Exibir data formatada no locale do usuário e a lista de novidades em leitura rápida.
- Escapar todos os textos. Se a lista for montada com `html` do SweetAlert, criar os elementos via DOM/textContent ou usar sanitização estrita; interpolação direta é proibida.
- Em viewport móvel, evitar rolagem horizontal e manter a lista curta.
- “Atualizar” ativa a mesma versão anunciada e recarrega somente após sucesso.
- “Depois” suprime novas exibições somente durante a sessão corrente. Se a atualização continuar pendente em uma nova sessão, o aviso pode reaparecer.
- Não exibir novamente o modal concorrente para o mesmo `release_id` enquanto ele já estiver aberto.
- Se surgir uma release mais nova antes da confirmação, a próxima exibição deve usar os metadados da versão mais recente pronta.

### Processo editorial

- Cada release atualiza um único arquivo-fonte versionado, validado durante o build.
- Os textos devem explicar benefício perceptível ao usuário, não commits, nomes internos, migrations ou detalhes sensíveis.
- Use frases curtas e no máximo cinco destaques.
- Inclua os locales atualmente suportados pelo produto; ausência de tradução não deve quebrar o build quando houver fallback definido, mas deve gerar aviso verificável.
- Não inclua segredos, identificadores internos, vulnerabilidades ainda exploráveis ou informações pessoais.

### Critérios de aceitação da Parte 5

- Uma versão PWA pronta com JSON válido mostra `release_id`, data e destaques correspondentes.
- O conteúdo respeita o locale ativo e aplica fallback determinístico.
- Confirmar mantém o comportamento atual de ativar e recarregar.
- Escolher “Depois” não ativa a versão e não repete o modal na mesma sessão.
- JSON ausente, inválido ou com schema futuro mantém o aviso genérico e não impede a atualização.
- Texto malicioso é exibido como texto inerte e não executa HTML ou JavaScript.
- O modal é legível em desktop e celular.
- As notas mostradas pertencem exatamente ao hash da `latestVersion` anunciada.

### Casos que os testes devem cobrir

- `VERSION_READY` com JSON completo no locale ativo;
- fallback de locale e fallback para aviso genérico;
- data inválida, `release_id` ausente e `schema_version` desconhecido;
- zero, um, cinco e mais de cinco destaques;
- texto excessivamente longo;
- payload contendo tags, atributos de evento e caracteres especiais;
- clique em “Atualizar”, sucesso e falha de `activateUpdate()`;
- clique em “Depois” e novo evento na mesma sessão;
- duas emissões concorrentes da mesma release;
- release mais nova substituindo uma pendente;
- service worker desabilitado em desenvolvimento.

### Decisões ainda pendentes

- Formato definitivo do `release_id`: versão semântica ou identificador baseado em data.
- Se a data será exibida ou utilizada apenas para ordenação/auditoria.
- Se haverá link opcional para um changelog completo no futuro.
- Onde ficará o arquivo editorial fonte e qual etapa do build o incorporará ao `appData`.

## Parte 6 — retirar chamadas externas de transações e locks longos

### Objetivo

Reduzir contenção, esgotamento do pool e estados ambíguos no fluxo de documentos e assinaturas. Nenhuma transação de banco deve permanecer aberta enquanto aguarda rede, storage de objetos, SerproID, Carimbo do Tempo, revogação de certificados ou outro provedor externo, salvo exceção tecnicamente justificada e documentada.

### Problema confirmado

- O fluxo atual de assinatura bloqueia o pedido e executa leitura do documento, geração de PDF, assinatura por certificado, Carimbo do Tempo e gravação do artefato antes de encerrar a transação.
- Upload e criação de versão também escrevem no storage durante a transação, embora exista descarte compensatório em caso de erro.
- Uma indisponibilidade externa pode prolongar locks de linha e ocupar conexões de banco por todo o timeout do provedor.
- A correção desta parte não depende da Parte 8, de Kafka ou de um event bus.

### Direção de implementação

1. Em uma transação curta, bloquear e validar pedido, signatário, documento congelado, permissões e estado atual.
2. Registrar uma operação durável com identificador idempotente, estado inicial e hashes necessários; então confirmar a transação.
3. Executar storage, composição, SerproID e timestamp fora da transação e sem manter lock de linha.
4. Em nova transação curta, readquirir o lock, revalidar todas as precondições e confirmar exatamente uma assinatura e seu artefato.
5. Se o estado tiver mudado, não anexar silenciosamente o resultado externo; registrar resultado recuperável e realizar compensação segura quando aplicável.
6. Um retry com a mesma chave deve retomar ou retornar a mesma operação, nunca criar outra assinatura ou fazer parecer que outro usuário autorizou a operação.

O desenho definitivo pode usar uma tabela simples de operações e um reconciliador local. Não introduzir Kafka apenas para resolver a fronteira transacional desta parte.

### Critérios de aceitação da Parte 6

- Nenhuma chamada HTTP ou operação de R2 permanece dentro da transação que bloqueia o pedido de assinatura.
- Timeout do provedor não mantém lock de linha nem conexão de banco durante toda a espera.
- Duas submissões concorrentes resultam em no máximo uma assinatura confirmada.
- Retry após timeout ou resposta perdida não duplica assinatura, evidência, timestamp ou consumo faturável quando o provedor permitir idempotência.
- Queda do processo entre chamada externa e confirmação final deixa estado detectável e recuperável.
- Artefatos não confirmados são reconciliados ou removidos sem apagar objetos históricos válidos.
- O hash e a versão do documento são revalidados imediatamente antes da confirmação.
- Logs correlacionam a operação entre as fases sem registrar tokens, documentos ou segredos.

## Parte 7 — PostgreSQL e Redis reais como gates do CI

### Objetivo

Fazer o pipeline provar continuamente os comportamentos que dependem de transações, constraints, locks e comandos atômicos do Redis. Testes unitários e mocks continuam úteis, mas não substituem esses testes.

### Requisitos confirmados

- O CI deve iniciar instâncias efêmeras e isoladas de PostgreSQL e Redis.
- Todas as migrations devem ser aplicadas antes dos testes de integração.
- `RUBRICA_DATABASE_TESTS=1` e `RUBRICA_TEST_REDIS_URL` devem ser configurados pelo job apropriado.
- Um teste marcado como integração não pode virar skip silencioso por erro de configuração do CI.
- Banco e Redis de teste não podem apontar para desenvolvimento compartilhado ou produção.
- O pipeline deve usar os comandos e o Compose existentes quando adequados, evitando uma segunda infraestrutura divergente.
- Falha em migrations, healthcheck, lock, constraint ou concorrência deve reprovar o pull request.

### Cobertura mínima

- transições e estados do workflow de assinatura;
- constraints de unicidade e integridade referencial;
- triggers append-only;
- concorrência com `SELECT FOR UPDATE`;
- idempotência de assinatura e webhook;
- rotação atômica do refresh token no Redis;
- detecção de reuse/replay e revogação da sessão;
- expiração e consumo unitário dos estados temporários relevantes.

### Critérios de aceitação da Parte 7

- O workflow do GitHub Actions sobe PostgreSQL e Redis saudáveis sem depender de serviço externo pago.
- As migrations partem de banco vazio e terminam antes dos testes.
- A suíte de PostgreSQL deixa de aparecer como skipped no CI.
- Os testes reais de concorrência de Redis deixam de aparecer como skipped no CI.
- O job falha se as variáveis apontarem para host não isolado ou se os serviços não estiverem disponíveis.
- O resumo do CI diferencia unitários, integração e skips expressamente permitidos.
- O tempo adicional do job é medido; paralelização ou cache só devem ser adicionados se preservarem isolamento e determinismo.

## Parte 8 — eventing e worker distribuído (opcional e adiado)

### Decisão de escopo

Esta parte está conscientemente **ADIADA**. O Rúbrica ainda não possui receita ou carga que justifique introduzir e operar Kafka, consumers, schema registry, dead-letter queues e toda a observação associada. A existência de scaffolding de eventing não obriga sua conclusão agora.

Enquanto estiver adiada:

- não ampliar a infraestrutura Kafka;
- não migrar fluxos estáveis para eventos apenas por preferência arquitetural;
- não tornar a Parte 6 dependente de mensageria;
- manter chamadas síncronas atuais com timeout, idempotência e tratamento de erro adequados;
- corrigir apenas falhas de segurança, custo ou estabilidade do scaffolding existente quando necessário.

### Gatilhos para reavaliação

A Parte 8 somente deve voltar a `NÃO INICIADO` ou `EM ANDAMENTO` após decisão explícita e pelo menos um requisito concreto, como:

- volume medido que torne o processamento síncrono inadequado;
- necessidade real de fan-out para múltiplos consumidores independentes;
- integrações que exijam entrega durável, replay ou ordenação;
- exigência operacional de desacoplar indisponibilidade de notificações do fluxo principal;
- receita e capacidade operacional para manter broker, monitoramento, retenção, DLQ e resposta a incidentes.

Mesmo quando reavaliada, Kafka não é escolha automática. Antes da implementação, comparar uma fila gerenciada, PostgreSQL outbox com worker simples, Redis Streams e Kafka conforme volume, semântica de entrega, custo e capacidade da equipe.

### Critérios futuros de aceitação

- Existe pelo menos um produtor e um consumidor reais ligados a um caso de negócio aprovado.
- Persistência do evento ocorre atomicamente com a mudança de estado do produtor.
- Relay e consumers toleram entrega duplicada e retomam após falha.
- Retry, backoff, DLQ, replay, ordenação e retenção possuem políticas explícitas.
- Métricas, alertas, runbook e recuperação são entregues junto da feature.
- O custo e a complexidade da solução escolhida são justificados por medição, não por expectativa abstrata de escala.

## Parte 9 — observabilidade integrada à Platform Infra

### Objetivo

Integrar o Rúbrica à plataforma compartilhada de observabilidade usando uma `observability_api` pertencente ao próprio produto. A Platform Infra permanece responsável por Alloy, Loki, Prometheus, Tempo, Grafana e exporters; o Rúbrica permanece responsável por autenticação, autorização, métricas do seu domínio e memória operacional normalizada.

O código da Observability API do Nexo é apenas uma base de implementação. Nomes, bancos, métricas, permissões, fontes e regras do Nexo não fazem parte do contrato do Rúbrica e devem ser removidos ou adaptados antes de considerar qualquer pacote verificado.

### Estado inicial observado em 2026-10-22

- A base do Nexo foi copiada para `apps/observability_api`, junto de migrations, Dockerfile e dois testes iniciais.
- Compose local e produção começaram a incluir o serviço e a rede externa `platform-observability`.
- A base ainda usa `NexoDesk`, `nexodesk_observability` e prefixos Prometheus `nexodesk_*` em pontos do código e da documentação.
- O Makefile, a sequência completa de migrations, os checks de dependências, backup e CI ainda não integram completamente o novo banco/serviço.
- O endpoint de status do Grafana possui degradação inicial para `unavailable`, mas autenticação, autorização, rate limiting e consultas reais ainda não estão implementados.
- A instrumentação compartilhada das demais APIs, suporte multiprocess, OpenTelemetry, targets Prometheus, dashboards e alertas do Rúbrica continuam pendentes.

### Fronteiras obrigatórias

- A `observability_api` pertence ao Rúbrica e usa banco exclusivo para configuração e memória operacional.
- Logs brutos permanecem no Loki, métricas no Prometheus e traces no Tempo; não duplicar telemetria bruta no PostgreSQL do Rúbrica.
- A Platform Infra não acessa bancos de Auth, Core, Eventing, Notification ou Observability.
- O Rúbrica não recebe senha administrativa do Grafana. Usar conta de serviço dedicada, papel Viewer, token revogável e Docker Secret.
- Apenas serviços que precisem expor `/metrics` participam da rede de coleta. Não conectar PostgreSQL, Redis, frontend ou gateway indiscriminadamente.
- Grafana, Loki, Prometheus, Tempo e Alloy não devem ser publicados pelo gateway do Rúbrica.
- Falha ou ausência completa da Platform Infra não pode bloquear bootstrap, migrations, health, ready ou funcionalidades centrais do Rúbrica.
- Desligar o Rúbrica não pode comprometer a Platform Infra.

### Contratos iniciais

Serviço interno esperado:

```text
observability-api:8000
```

Endpoints mínimos:

| Método e rota | Responsabilidade |
|---|---|
| `GET /health` | Vida do processo, independente de banco e Grafana. |
| `GET /ready` | Prontidão do banco exclusivo da Observability API. |
| `GET /internal/observability/platform/status` | Estado controlado da conexão com Grafana; indisponibilidade não derruba a API. |
| `GET /metrics` | Métricas Prometheus internas, fora do OpenAPI público. |

Configuração base:

```text
PLATFORM_GRAFANA_URL=http://grafana:3000
PLATFORM_GRAFANA_TIMEOUT_SECONDS=3
PLATFORM_GRAFANA_SERVICE_TOKEN_FILE=/run/secrets/platform_grafana_service_token
```

O secret nunca pode aparecer em `.env`, Git, Compose como valor literal, logs, dashboards ou respostas HTTP.

### Métricas e cardinalidade

- Usar namespace estável `rubrica_`; qualquer métrica `nexodesk_*` deve ser eliminada.
- Métricas HTTP devem usar serviço, método, template de rota e classe de status.
- Nunca usar IDs de usuário, tenant, documento, assinatura, request, trace, URLs concretas ou query strings como labels.
- Cada collector de negócio consulta apenas o banco pertencente à própria API.
- Falha ao coletar indicador de negócio deve produzir uma métrica de sucesso com valor `0`, sem derrubar o scrape.
- Como as APIs usam múltiplos workers Gunicorn, implementar corretamente `PROMETHEUS_MULTIPROC_DIR`, agregação e `mark_process_dead`.
- Indicadores do produto devem ser agregados, de baixa cardinalidade e revisados para não expor dados pessoais ou documentos.

### Logs, traces e privacidade

- Logs estruturados devem incluir somente dimensões seguras, como timestamp, level, service, environment, evento, `request_id` e `trace_id`.
- Não registrar tokens, cookies, Authorization, senhas, e-mails, telefones, CPF/CNPJ, conteúdo de documentos ou payloads pessoais.
- Confirmar o endpoint OTLP efetivamente disponível na rede compartilhada antes de configurar OpenTelemetry.
- Propagar contexto entre serviços sem incluir payloads ou dados pessoais nos atributos dos spans.
- `request_id` e `trace_id` podem aparecer em logs e spans, mas não em labels Prometheus.

### Autorização e consultas

- O endpoint técnico de status permanece interno; nenhuma interface do Grafana será proxyada ao usuário.
- Antes de disponibilizar consultas de logs, métricas, traces ou incidentes, definir permissões, escopo de tenant, filtros permitidos, intervalos máximos, paginação e rate limiting.
- Consultas devem ser construídas pelo backend a partir de contratos controlados. Não aceitar PromQL, LogQL ou TraceQL arbitrários enviados pelo frontend.
- Auditar consultas, reconhecimentos e silenciamentos sem registrar tokens ou conteýo sensível.
- O primeiro corte não exige frontend nem exposição pelo gateway; isso só entra após política de acesso definida.

### Critérios de aceitação da Parte 9

- Não restam identificadores, bancos, métricas ou regras de negócio do Nexo no código do Rúbrica.
- A Observability API possui banco exclusivo, migrations no head e integração com comandos locais e de produção.
- `health` funciona sem banco e sem Platform Infra; `ready` representa somente as dependências necessárias da própria API.
- A API resolve `grafana` pela rede privada e usa somente seu token Viewer montado como secret.
- Grafana desligado retorna estado degradado controlado e não afeta outras APIs.
- Todas as APIs selecionadas expõem `/metrics` internamente com namespace `rubrica_`, suporte multiprocess e labels de baixa cardinalidade.
- Prometheus coleta os targets do Rúbrica; logs aparecem no Loki e traces chegam ao Tempo com correlação segura.
- Dashboards e alertas exibem indicadores técnicos e de produto aprovados, sem acessar bancos operacionais pela Platform Infra.
- Testes cobrem token ausente/inválido, DNS, timeout, 401/403, 429, 5xx, JSON inválido e plataforma desligada.
- Testes verificam ausência de labels de alta cardinalidade, dados pessoais e secrets em métricas, logs e respostas.
- Compose local e produção, migrations, lint, testes e smoke integrado passam com a plataforma ligada e desligada.
- Existe runbook para criar/rotacionar/revogar o token Viewer, diagnosticar targets e operar o modo degradado.

## Parte 10 — confidencialidade, criptografia e migração dos arquivos no R2

### Decisão de produto e prioridade

Esta parte deixou de ser apenas uma revisão futura. Em 2026-10-25 foi constatado
que uma pessoa com acesso administrativo ao bucket consegue baixar objetos e
abri-los como PDFs. Keys opacas, prefixes por tenant, bucket privado e a
criptografia em repouso fornecida pelo R2 não impedem que o operador do storage
veja o conteúdo.

A decisão de produto é inequívoca: documentos do cliente não devem ser legíveis
no painel do Cloudflare, por download direto do R2, em backups de objetos ou por
uma credencial que acesse somente o storage. O operador não deve inspecionar o
conteúdo durante inventário, migração, suporte, backup ou recuperação normal.
Por isso, a Parte 10 passa a ser prioridade ativa e inclui implementação,
ensaio de migração e validação de desempenho.

### Limite de segurança declarado

O Rúbrica não é um sistema de conhecimento zero. O Core precisa processar o
documento em claro por intervalos controlados para validar o PDF, gerar previews,
aplicar assinaturas visuais e PAdES, obter Carimbo do Tempo, integrar o Serpro ID
e entregar o resultado a usuários autorizados. Um invasor que controle ao mesmo
tempo o runtime do Core e a raiz das chaves ainda pode provocar uma descriptografia.

O objetivo desta parte é separação de poderes e minimização de exposição:

- acesso somente ao R2, a um backup de objetos ou à credencial S3 não revela PDFs;
- banco isolado, objeto isolado ou key opaca isolada não basta para descriptografar;
- chaves de usuário não derivam de senha, CPF, e-mail ou outro dado recuperável;
- plaintext existe apenas no processo autorizado e pelo menor tempo necessário;
- acesso excepcional à raiz criptográfica é restrito, auditável e recuperável;
- logs, erros, métricas e ferramentas operacionais nunca registram bytes, nomes
  sensíveis, chaves completas nem material criptográfico.

### Escopo dos artefatos

A proteção abrange, no mínimo:

- documento original enviado pelo usuário;
- versões congeladas apresentadas aos signatários;
- PDFs intermediários e PDFs finais assinados;
- assinaturas CMS/PAdES e tokens de Carimbo do Tempo quando persistidos fora do PDF;
- JSONs de evidência e manifestos consolidados quando armazenados como objeto;
- logos, carimbos visuais e assinaturas desenhadas quando persistidos fora do banco;
- uploads incompletos e artefatos de operações falhas;
- objetos legados em prefixes antigos e objetos migrados;
- backups e pacotes de restauração que contenham documentos ou chaves embrulhadas.

Para cada classe devem ser conhecidos, sem revelar dados reais: bucket, prefix,
tenant, proprietário lógico, tabela/coluna de referência, formato, limite de
tamanho, hash do plaintext, versão criptográfica, retenção e regra de exclusão.
A key do R2 nunca é tratada como segredo nem como prova de identidade.

### Arquitetura criptográfica alvo

A implementação deve usar envelope encryption autenticada e versionada:

1. Uma root KEK por ambiente permanece fora do R2 e fora do banco operacional,
   preferencialmente em cofre/KMS com identidade de workload e trilha de auditoria.
2. O contexto do tenant deriva ou desembrulha uma chave exclusiva do tenant.
3. O contexto do documento deriva ou desembrulha uma chave exclusiva do documento.
4. Cada objeto recebe uma DEK aleatória e nonce exclusivo; a DEK é embrulhada
   pelo contexto do documento e nunca é persistida em claro.
5. Os bytes são cifrados com AES-256-GCM em chunks autenticados. Tenant, documento,
   storage key, versão do formato e ordinal do chunk participam como AAD.
6. O cabeçalho guarda somente versões, nonces e chaves embrulhadas necessárias à
   leitura. Troca de tenant, key, cabeçalho, chunk ou ordem deve falhar fechada.
7. O SHA-256 canônico continua sendo calculado sobre o plaintext e revalidado nos
   pontos de integridade, sem ser usado como chave criptográfica.

Uma senha do usuário não pode proteger diretamente documentos: ela muda, pode ser
redefinida e não atende equipes, signatários externos, workers e processos de
assinatura sem sessão interativa. Chaves desembrulhadas podem permanecer apenas em
cache curto e limitado na memória do processo; Redis e logs não podem recebê-las.

### Ensaio fiel em staging

Antes de alterar produção, staging deve reproduzir o estado anterior à migração:

1. Parar os consumidores de staging capazes de enviar e-mail, cobrar, assinar ou
   chamar provedores usando registros copiados.
2. Clonar somente o banco `rubrica_core` necessário às referências documentais;
   Auth, Notification, Eventing e Observability não são necessários ao ensaio.
3. Copiar objetos de `rubrica-documents` para `rubrica-documents-staging` byte a
   byte, preservando keys e sem passar pela camada de storage que cifra uploads.
4. Produção é origem estritamente somente leitura. Nenhum comando pode apagar,
   mover, regravar ou alterar metadados no bucket ou banco de produção.
5. O copiador inicia em dry-run, recusa buckets iguais, não sobrescreve por padrão,
   exige `--apply` e emite somente contagens e totais sanitizados.
6. A reconciliação confirma referências, tamanho e SHA-256 sem imprimir keys
   completas, nomes, e-mails, identificadores pessoais ou conteúdo.
7. O clone é dado pessoal de produção: continua privado, protegido pelo Cloudflare
   Access, com acesso mínimo, prazo curto e descarte controlado ao final do ensaio.

A autorização de mutação desta parte vale somente para os recursos isolados e
descartáveis de staging. Ela não autoriza qualquer mutação em produção.

### Estratégia de migração

- O formato criptográfico possui identificador e versão explícitos.
- Durante uma janela controlada, a leitura aceita legado plaintext e formato novo,
  enquanto toda nova escrita usa exclusivamente o formato cifrado.
- A migração é em lotes, idempotente, retomável e com checkpoint; nunca depende
  de manter todos os objetos ou PDFs inteiros simultaneamente na memória.
- Cada objeto é lido, validado contra o hash canônico, cifrado, escrito de forma
  segura e relido/verificado antes de ser classificado como migrado.
- Falha, encerramento ou retry não pode transformar objeto válido em ilegível nem
  marcar migração incompleta como concluída.
- Ao fim, um segundo dry-run deve informar zero legados e zero divergências. Somente
  então o fallback plaintext pode ser desativado.
- O rollout de produção exige backup verificado, janela aprovada, observação,
  reconciliação final e procedimento de recuperação testado previamente.

### Desempenho e capacidade

Criptografia não pode introduzir leitura integral desnecessária nem crescimento de
memória proporcional à concorrência vezes o tamanho máximo do documento. Upload,
download e migração devem trabalhar em streaming com chunks inicialmente calibrados
em torno de 4 MiB, ajustáveis por benchmark.

O caminho de visualização deve observar estes requisitos:

1. O Core lê o objeto do R2 e o entrega ao cliente em streaming, descriptografando
   e autenticando chunks incrementalmente, sem montar uma segunda cópia integral
   do PDF na memória ou no disco. Nenhum byte ainda não autenticado pode ser
   entregue como conteúdo válido.
2. O visualizador mantém e reutiliza a mesma instância/URL segura do documento ao
   trocar de página e ao recolher ou reabrir o preview durante a mesma navegação.
   Essas interações não podem iniciar um novo download completo do R2.
3. Quando necessário, o cache contém somente bytes ainda cifrados, é privado,
   possui limite de tamanho e TTL curto e não é compartilhado entre tenants.
   PDF descriptografado não pode ser persistido em Redis, CDN, cache público ou
   disco compartilhado. Respostas autenticadas usam política de cache que impeça
   armazenamento indevido no navegador, proxy ou Cloudflare.
4. O cliente S3/R2 e seus pools HTTP são reutilizados entre requisições do mesmo
   processo. Não deve existir um novo cliente, resolução DNS ou handshake TLS por
   chunk ou por acesso quando a conexão puder ser reutilizada com segurança.
5. A instrumentação separa, sem labels de alta cardinalidade nem dados pessoais,
   o tempo gasto aguardando/transferindo do R2, descriptografando, processando no
   Core e carregando/renderizando no navegador. O tempo total sozinho não é
   suficiente para atribuir regressões.

O benchmark compara plaintext e envelope encryption com arquivos de 1, 10, 25 e
50 MiB e concorrência 1, 5, 10 e 20. Deve registrar p50/p95, throughput, CPU,
memória máxima, tempo de validação SHA-256, tempo até o primeiro byte autenticado,
tempo separado de R2/descriptografia/Core/navegador e tempo total de migração.
O teste do visualizador também conta requisições e bytes transferidos ao abrir,
trocar página, recolher e reabrir o mesmo documento. A meta inicial é regressão
inferior a 10% no tempo ponta a ponta; resultado superior pode ser aceito somente
com medição, diagnóstico e justificativa. O limite inegociável é memória limitada
por chunk, sem buffer integral por requisição.

### Integridade, isolamento e operação

- Toda leitura continua sujeita à autorização do Core por tenant, documento e papel;
  criptografia não substitui autorização.
- Objetos históricos são imutáveis. Escritas usam keys novas ou precondições que
  impeçam sobrescrita silenciosa.
- Acesso direto pelo painel R2 deve produzir apenas bytes opacos e autenticados.
- Credenciais de documentos, backups e ambientes permanecem separadas e limitadas
  ao menor conjunto de operações/buckets necessário.
- Erro de tag, hash, cabeçalho, chave, tenant ou chunk falha fechado, gera telemetria
  sanitizada e nunca devolve conteúdo parcial como documento válido.
- Backup precisa preservar conjuntamente banco, objetos cifrados e material de chave
  recuperável. Backup de objetos sem chaves e backup de chaves sem objetos não
  constituem restauração comprovada.
- Retenção, legal hold, exclusão LGPD e descarte criptográfico devem ser definidos
  por classe de artefato, sem apagar indevidamente evidência necessária ao exercício
  regular de direitos.

### Critérios de aceitação da Parte 10

- Todas as classes de arquivos e seus ciclos de vida estão inventariados.
- O clone de staging é fiel, reconciliado, temporário e incapaz de mutar produção.
- Download direto pelo Cloudflare/R2, backup ou credencial de storage não produz PDF,
  imagem, assinatura desenhada, evidência sensível ou outro conteúdo legível.
- Cada tenant/documento/objeto possui contexto criptográfico separado e autenticado;
  trocar contexto, cabeçalho ou chunks é detectado.
- Nenhuma chave documental deriva da senha ou de dados pessoais do usuário.
- Escrita nova é sempre cifrada; leitura de legado existe apenas durante a janela
  de migração e é desligada após reconciliação com zero pendências.
- A migração integral do clone pode ser interrompida, retomada e repetida sem perda,
  duplicidade, corrupção ou exposição de conteúdo.
- Hashes do plaintext antes e depois da migração coincidem para 100% das referências.
- Testes cobrem adulteração, truncamento, chave errada, replay, troca de tenant,
  acesso cruzado, objetos ausentes, órfãos e falhas no meio da gravação.
- Benchmark demonstra CPU, memória, latência e throughput dentro dos limites
  definidos, com streaming real e memória limitada por chunks.
- Trocar página, recolher e reabrir o preview na mesma navegação não baixa
  novamente o documento completo nem repete desnecessariamente a leitura do R2.
- Cache, quando habilitado, armazena somente bytes cifrados, tem TTL/tamanho
  limitados, isolamento por tenant e nenhuma persistência de plaintext.
- Métricas e testes distinguem latência do R2, descriptografia, processamento do
  Core e carregamento/renderização no navegador sem expor identificadores sensíveis.
- Restauração conjunta de banco, objetos e chaves é executada e validada em staging.
- Produção só é migrada após todos os pacotes anteriores estarem verificados e
  mediante autorização operacional explícita.

## Parte 11 — reabertura de processos de assinatura expirados

### Decisão de arquitetura

O recurso não reabre nem altera uma solicitação expirada. Ele cria uma **nova rodada de assinatura**, encadeada à anterior e pertencente à mesma versão do documento quando os bytes não forem modificados. A rodada anterior, seus eventos e suas evidências permanecem imutáveis.

```text
Documento original
└── Versão do documento
    ├── Rodada de assinatura 1 — expirada
    └── Rodada de assinatura 2 — reaberta a partir da rodada 1
```

Alertas operacionais por e-mail não formam uma parte do plano do Rúbrica. Essa capacidade pertence à Platform Infra e ao futuro aplicativo de mensageria operacional da plataforma; a `notification_api` do Rúbrica permanece responsável pelas comunicações transacionais do produto.

### Terminologia

- **Documento original:** arquivo recebido por upload e preservado pelo Rúbrica.
- **Versão do documento:** conjunto exato de bytes congelados e identificado por hash.
- **Rodada de assinatura:** processo com prazo, participantes, links, estado e histórico próprios.
- **Rodada reaberta:** nova rodada criada a partir de uma rodada expirada; não é um novo documento nem uma mutação da rodada anterior.
- **Assinatura preservada:** assinatura válida produzida em rodada anterior sobre os mesmos bytes e referenciada historicamente, sem nova data ou nova declaração de vontade.

Na interface, a ação deve se chamar **Reabrir para assinatura**. Evitar “reabrir documento” e “documento vencido” quando o que expirou foi a rodada.

### Requisitos confirmados

- Apenas uma rodada expirada pode originar a ação de reabertura.
- A rodada expirada permanece imutável e consultável no histórico.
- A reabertura cria novo identificador, novo prazo, novos links e novo histórico operacional.
- A nova rodada registra a rodada pai, o motivo, o usuário responsável e a data/hora da ação.
- O emissor escolhe quais signatários pendentes serão mantidos e pode adicionar novos signatários.
- Signatários que já assinaram não recebem novo link por padrão e suas assinaturas não são recriadas nem redatadas.
- Sem assinatura anterior, a nova rodada usa a mesma versão original do documento.
- Com assinaturas válidas anteriores, a nova rodada parte do último PDF assinado válido e preserva incrementalmente as evidências criptográficas anteriores.
- Cada nova assinatura produz sua própria evidência, autorização, consentimento e Carimbo do Tempo conforme o modo da nova rodada.
- Alterar qualquer byte do conteúdo cria uma nova versão; assinaturas anteriores não podem ser apresentadas como assinaturas da versão nova.
- O documento aparece como uma unidade na listagem, com a rodada atual e histórico das anteriores.
- Filtros distinguem processos abertos, expirados, concluídos e reabertos sem duplicar fisicamente documentos.

### Fluxo proposto

1. O emissor abre uma rodada expirada e seleciona **Reabrir para assinatura**.
2. O sistema apresenta assinaturas preserváveis, participantes pendentes e o aviso de imutabilidade da rodada anterior.
3. O emissor define novo prazo, seleciona pendentes, adiciona participantes e informa o motivo.
4. O backend valida autorização, estado expirado, versão/hash e integridade do último artefato assinado.
5. Uma nova rodada é criada em rascunho e vinculada à rodada pai.
6. O emissor revisa posições, personalização e participantes antes de abrir a nova rodada.
7. Na abertura, links novos são emitidos somente para quem ainda precisa assinar.
8. Novas assinaturas são aplicadas incrementalmente sem reescrever as preservadas.

### Modelo mínimo de dados

A implementação deve avaliar uma relação equivalente a:

- `parent_request_id`: rodada imediatamente anterior;
- `round_number`: sequência legível dentro da versão do documento;
- `reopened_reason`: justificativa sanitizada e limitada;
- `reopened_by`: identidade do ator autorizado;
- `reopened_at`: instante auditável;
- referência imutável ao artefato-base e seu hash;
- relação explícita entre assinaturas preservadas e suas rodadas de origem.

Não copie registros de assinatura para fingir que foram produzidos na rodada nova. A nova rodada referencia evidências anteriores e cria registros somente para novos eventos.

### Interface e histórico

A listagem principal deve agrupar por documento/versão e mostrar a rodada ativa mais recente, por exemplo:

```text
Contrato de prestação de serviços
Versão 1 · Rodada 2 · Reaberta
2 de 3 assinaturas
```

Os detalhes apresentam uma linha do tempo com número, estado, prazo, motivo, ator, assinaturas concluídas naquela rodada, assinaturas preservadas, participantes pendentes e participantes adicionados.

O modal contém novo prazo, motivo obrigatório, seleção de pendentes, inclusão de novos signatários, resumo das assinaturas preservadas e aviso de que a rodada expirada não será alterada.

### Regras de integridade e autorização

- Revalidar permissão por tenant e objeto no backend; ocultar o botão não é controle suficiente.
- Usar transação curta, lock e idempotência para impedir duas reaberturas concorrentes.
- Não reutilizar tokens ou links da rodada expirada.
- Não transportar consentimento, visualização, autenticação ou geolocalização de quem ainda precisará assinar.
- Verificar o hash do artefato-base antes de criar e antes de abrir a nova rodada.
- Preservar `signature_id`, evidência, CMS/PAdES e token de Carimbo do Tempo anteriores sem alterar bytes protegidos.
- Auditar tentativa, sucesso, falha e eventual cancelamento da rodada nova.
- Expiração ou reabertura não apaga evidências nem altera contadores históricos anteriores.

### Casos que os testes devem cobrir

- rodada expirada sem assinatura e parcialmente assinada;
- preservação de uma ou várias assinaturas anteriores;
- manutenção de pendentes, inclusão de novos signatários e exclusão consciente de um pendente;
- tentativa de reabrir rodada aberta, concluída ou cancelada;
- tentativa por usuário ou tenant não autorizado;
- duas reaberturas concorrentes e retry idempotente;
- links antigos revogados e links novos independentes;
- prazo válido, inválido ou no passado;
- alteração do PDF exigindo nova versão;
- falha de hash ou artefato-base;
- múltiplas reaberturas formando cadeia íntegra;
- novas assinaturas sem invalidar assinaturas e timestamps anteriores;
- agrupamento, filtros e linha do tempo no desktop e celular.

### Critérios de aceitação da Parte 11

- Nenhuma coluna ou evidência da rodada expirada é modificada pela reabertura.
- A nova rodada possui vínculo inequívoco e navegável com sua origem.
- Assinaturas anteriores permanecem verificáveis e não recebem nova data.
- Novos signatários assinam exatamente o artefato-base apresentado e validado.
- Modificação de conteúdo vira nova versão, nunca simples extensão de prazo.
- Apenas participantes da nova rodada recebem links novos.
- A listagem não duplica o documento como se cada rodada fosse outro upload.
- Histórico e auditoria permitem reconstruir quem reabriu, por quê, quando e o que foi preservado.
- Testes demonstram autorização, idempotência, concorrência, integridade e preservação das evidências.

## Parte 12 — fluxos de desenvolvimento, staging e produção

### Objetivo e princípio

Reorganizar Makefile, processos bare metal, Compose, configuração, secrets, inicialização e verificações operacionais em três níveis explícitos: desenvolvimento, staging e produção. Desenvolvimento prioriza hot reload e permite escolher onde cada dependência está; staging é o primeiro fluxo 100% Docker e reproduz a forma operacional de produção; produção mantém isolamento e providers reais.

A regra central é: **dev executa o código do produto bare metal; staging comprova a composição Docker; produção aplica a mesma disciplina com isolamento e providers reais**.

Este modelo definitivo substitui as propostas anteriores da Parte 12 que colocavam frontend e APIs internas no Compose local diário. Docker no desenvolvimento é suporte para dependências, não requisito para editar e recarregar o código do Rúbrica.

A implementação da Parte 12 foi autorizada em 2026-10-22. O quadro de acompanhamento acima é a fonte do estado efetivamente comprovado; critérios que dependem do Docker/WSL ou do servidor não devem ser promovidos para `VERIFICADO` sem o respectivo smoke.

### Ordem de conclusão desta entrega

1. Implementar e verificar integralmente a Parte 12.
2. Executar a auditoria da Parte 10 sobre arquivos, R2, integridade, retenção, backup e migração.
3. Aplicar somente as adequações realmente demonstradas pela Parte 10 e realizar o fechamento final da entrega.

A Parte 12 define a separação operacional dos providers. A Parte 10 continua sendo a autoridade para auditar o ciclo de vida e a segurança dos arquivos; não se deve duplicar ou antecipar nessa reorganização uma reimplementação das proteções já existentes.

### Matriz dos ambientes

| Aspecto | Dev bare metal | Dev + Docker | Staging | Produção |
|---|---|---|---|---|
| Comando principal | `make dev` | `make dev-docker` | `make staging-up` | `make production-up` |
| Código do Rúbrica | Frontend e APIs bare metal com hot reload | Frontend e APIs bare metal com hot reload | Frontend, gateway e APIs em contêineres | Frontend, gateway e APIs em contêineres |
| Dependências | Nada é iniciado; usa endpoints de `.env` | Infraestrutura externa em contêineres | Toda a topologia em Docker | Toda a topologia em Docker |
| Seleção | Configuração manual em `.env` | Catálogo padrão ou `services=...` | Composição fechada | Composição fechada e estrita |
| Ensure | Não executa ensure; somente preflight mínimo da configuração | Assegura somente os contêineres selecionados | Ensure completo de staging | Ensure estrito de produção |
| Configuração | `.env` | `.env` | `.env.staging` ou nome equivalente definitivo | `.env.production` |
| Secrets | Valores exclusivamente locais conforme providers fake | Secrets locais quando algum contêiner exigir | Docker Secrets de staging | Docker Secrets reais em `/etc/rubrica/secrets` |
| Providers | Fake ou endpoint escolhido pelo desenvolvedor | Fake por padrão | Fake/sandbox, nunca produção | Providers reais |
| Arquivos | Filesystem local fora do Git | Mesmo filesystem local usado pelas APIs bare metal | Volume Docker persistente | R2 privado operacional |
| Telemetria | Exporter falso/desligado ou endpoint indicado | Loki/coletores selecionáveis | Integração completa de teste | Integração contínua com Platform Infra |
| Exposição | Processos e dependências em loopback | Contêineres somente em loopback | Gateway/portas de diagnóstico controladas | Somente Cloudflare Tunnel → gateway |
| Seed | Explícito e idempotente | Explícito e idempotente | Seed próprio de staging, se aprovado; nunca dados locais implícitos | Proibido |
| MkDocs | Processo bare metal ou comando próprio | Pode ser dependência auxiliar selecionada | Ausente da composição semelhante à produção | Ausente |
| Stripe CLI | Opcional | Contêiner opcional selecionável | Ausente; usar sandbox real quando exigido | Ausente |

### Configuração e secrets

- `.env` pertence aos dois modos de desenvolvimento bare metal; staging possui arquivo próprio e `.env.production` pertence exclusivamente ao servidor.
- Todos os comandos validam a presença e o contrato do arquivo de configuração do seu nível antes de iniciar, inclusive `make dev`; essa validação mínima não é o `ensure` de infraestrutura.
- `.env` pode apontar PostgreSQL, Redis, Kafka, Loki ou qualquer dependência para localhost, contêiner, máquina remota ou serviço já instalado. `make dev` respeita esses destinos e não tenta corrigi-los.
- Nenhum arquivo de ambiente deve armazenar senha, token, chave privada ou secret real de provider.
- Staging e produção devem consumir secrets pelo mesmo contrato `/run/secrets/...`; os valores e diretórios de origem são distintos.
- Desenvolvimento pode usar valores falsos seguros exigidos pelos providers fake, sem copiar credenciais de staging ou produção.
- Em produção, a origem permanece `/etc/rubrica/secrets`, com propriedade e permissões mínimas verificadas.
- Templates podem declarar nomes e configuração não sensível, mas nunca conter valores reais.
- Staging e produção nunca geram, substituem ou corrigem secrets silenciosamente.

### Armazenamento de documentos por ambiente

A diferença entre os ambientes é exclusivamente o destino físico dos arquivos:

```text
Dev bare metal       → LocalDocumentStorage → diretório local persistente fora do Git
Dev + Docker         → LocalDocumentStorage → o mesmo diretório, pois as APIs seguem bare metal
Staging              → LocalDocumentStorage → volume Docker nomeado
Produção             → R2DocumentStorage    → bucket privado operacional
Testes automatizados → LocalDocumentStorage → diretório/volume temporário isolado
```

As definições de segurança permanecem as mesmas nos dois providers. Não existe uma versão enfraquecida das regras para desenvolvimento. Devem continuar compartilhados:

- contratos de armazenamento e identidade dos artefatos;
- cálculo e verificação de hashes;
- criptografia e proteção de dados já adotadas pelo Rúbrica;
- autorização por tenant, usuário e objeto;
- validação de PDF, MIME, tamanho e conteúdo;
- vínculo entre documento, versão, assinatura, evidência e manifesto;
- nomes de objetos gerados pela aplicação, sem confiar no nome fornecido pelo usuário;
- prevenção de sobrescrita indevida e detecção de adulteração;
- trilhas de auditoria, tratamento de falhas e preservação dos bytes assinados;
- políticas funcionais de retenção e exclusão, ressalvadas as diferenças operacionais que a Parte 10 vier a comprovar.

O código de negócio deve consumir uma única abstração de storage. Não espalhar condicionais de ambiente pelos fluxos de documento e assinatura; a seleção do provider acontece na composição/configuração.

No desenvolvimento diário:

- `DOCUMENT_STORAGE_PROVIDER=local` é obrigatório por padrão;
- documentos ficam em diretório local persistente, ignorado pelo Git e acessível aos processos bare metal sem `sudo`;
- `dev-docker-down` não remove esse diretório;
- somente um reset local explicitamente destrutivo pode removê-lo;
- testes usam armazenamento temporário próprio e não compartilham o volume de desenvolvimento;
- o ambiente funciona offline e não depende de credenciais R2.

No staging, o mesmo provider local usa volume Docker nomeado, preservado por `staging-down`; isso testa persistência e permissões em contêiner sem introduzir R2 no ambiente de validação.

Em produção:

- `DOCUMENT_STORAGE_PROVIDER=r2` é obrigatório;
- `production-ensure` recusa provider local e produção sem configuração R2 completa;
- documentos e backups usam buckets e credenciais separados conforme a política validada;
- nenhum filesystem efêmero de contêiner pode ser tratado como armazenamento persistente;
- mudanças de prefix, bucket, migração, reconciliação e restauração permanecem sujeitas à auditoria da Parte 10.

Teste do provider R2 fora de produção, se necessário, usa comando explícito, credenciais limitadas e bucket exclusivo de teste. Nunca usa o bucket operacional de produção, não faz parte de `dev`, `dev-docker` ou `staging-up` e não sincroniza automaticamente arquivos locais com R2.

### Semântica dos comandos

- `dev` valida apenas `.env`, executáveis e contratos mínimos, então inicia frontend e APIs bare metal. Não sobe nem assegura dependências.
- `dev-docker` executa ensure das dependências solicitadas, sobe esses contêineres e depois inicia frontend e APIs bare metal.
- `staging` é a primeira composição 100% Docker e valida a forma de empacotamento e operação próxima de produção.
- `ensure` verifica e prepara pré-condições do nível correspondente. Não deve ser confundido com o preflight mínimo de `dev`.
- `bootstrap` inicializa um ambiente completo e pode alterar estado de forma prevista e documentada.
- `provider-check` comprova configuração e comunicação com dependências externas sem ser confundido com healthcheck de processo.
- `up` apenas sobe serviços já preparados; não deve esconder migrations, seed, geração de secrets ou provisionamento externo.
- Operações de dev, staging e produção precisam ter nomes explícitos; comandos genéricos não podem selecionar outro nível por acidente.

### `make dev` — aplicações bare metal

É o caminho mais direto e deliberadamente não possui ensure de infraestrutura:

1. Exigir e validar `.env` sem modificá-lo.
2. Verificar somente executáveis necessários aos processos bare metal, dependências do projeto e conflitos nas portas das aplicações.
3. Iniciar frontend e todas as APIs internas do Rúbrica fora do Docker, preferencialmente com hot reload e encerramento coordenado.
4. Conectar exatamente aos endpoints informados em `.env`, independentemente de estarem bare metal, em contêineres ou remotos.
5. Falhar com diagnóstico claro se uma dependência apontada estiver indisponível, sem instalá-la, iniciá-la ou trocar seu endereço.

Não exige Docker, não cria rede, não sobe PostgreSQL/Redis/Kafka/Loki, não executa migration ou seed e não gera configuração. É responsabilidade do desenvolvedor fornecer as dependências apontadas.

### `make dev-docker` — dependências em Docker

É o fluxo principal de desenvolvimento. Somente infraestrutura e ferramentas externas às APIs internas entram em contêineres; frontend e APIs continuam bare metal para preservar hot reload rápido.

Uso padrão:

```bash
make dev-docker
```

Sobe o conjunto padrão de dependências definido após o inventário — esperado inicialmente PostgreSQL, Redis e demais componentes realmente necessários — executa ensure/readiness desses contêineres e inicia as aplicações bare metal.

Seleção manual:

```bash
make dev-docker services=postgres,redis
make dev-docker services=postgres,loki,kafka
```

`make dev-docker=loki,postgres` não será adotado porque GNU Make interpreta essa forma como atribuição de variável. O parâmetro `services=` aceita nomes canônicos separados por vírgula, rejeita nomes desconhecidos e assegura somente os serviços escolhidos.

O ensure desse fluxo deve:

1. Validar `.env` e garantir que os endpoints selecionados correspondem às portas publicadas pelos contêineres.
2. Verificar Docker/Compose, redes, volumes, portas e arquivos necessários apenas aos serviços selecionados.
3. Subir os contêineres solicitados, aguardar health/readiness e apresentar falha por serviço.
4. Aplicar migrations ou seed somente por comandos/flags explícitos definidos no bootstrap de desenvolvimento; o comando diário não altera dados implicitamente.
5. Iniciar frontend e APIs bare metal depois que as dependências estiverem prontas.

Contêiner de frontend ou API interna não pertence a `dev-docker`. MkDocs, Stripe CLI, Quick Tunnel, Loki/coletores e Kafka podem compor o catálogo selecionável conforme sua necessidade real e seus profiles, mas não precisam integrar o conjunto padrão.

### Bootstrap de desenvolvimento

Um comando explícito, como `make dev-bootstrap`, prepara a estação pela primeira vez: valida/cria o `.env` a partir do template sem sobrescrever configuração existente, prepara recursos locais seguros, sobe o conjunto padrão de dependências, aplica migrations, executa seed idempotente e inicia as aplicações bare metal. Depois disso, o uso diário volta a `make dev` ou `make dev-docker`.

`dev-migrate` e `dev-seed` permanecem operações explícitas e reutilizáveis. Seed não roda automaticamente em cada inicialização diária.

### Ferramentas opcionais de desenvolvimento

- MkDocs é suporte regular ao desenvolvimento; pode rodar bare metal por comando próprio ou ser selecionado como dependência auxiliar no `dev-docker`.
- Stripe CLI permanece opcional e só sobe por `stripe-up` ou seleção explícita em `dev-docker`.
- Quick Tunnel permanece opcional e só expõe o ambiente após comando explícito como `quick-tunnel-up` ou seleção equivalente.
- Quick Tunnel e Stripe CLI não devem ser acoplados obrigatoriamente; cada integração pode ser ligada de forma independente.
- A Platform Infra de desenvolvimento permanece opcional; seus componentes podem ser selecionados quando o objetivo for desenvolver ou validar métricas, logs, traces, dashboards e alertas.
- Comandos `down`, `logs` e `status` específicos devem existir para as ferramentas opcionais quando isso reduzir ambiguidade operacional.

### Staging — primeiro fluxo 100% Docker

Staging existe para validar aquilo que dev bare metal não comprova: imagens, Dockerfiles, entrypoints, dependências entre serviços, Docker Secrets, redes, volumes, gateway, healthchecks e ordem de inicialização.

O fluxo deve:

1. Usar configuração própria, nunca `.env` de desenvolvimento nem `.env.production`.
2. Executar `staging-ensure` para validar Docker/Compose, secrets de staging, redes, volumes, portas e providers fake/sandbox.
3. Executar frontend, gateway, APIs internas, PostgreSQL, Redis e demais dependências necessárias em contêineres.
4. Usar Docker Secrets com os mesmos nomes e destinos internos de produção, mas valores exclusivos de staging.
5. Usar imagens e comandos equivalentes aos de produção sempre que possível, permitindo apenas diferenças justificadas de endpoint, escala, TLS externo e providers.
6. Persistir documentos em volume Docker nomeado e nunca acessar o R2 operacional.
7. Expor somente portas necessárias em loopback ou em rede controlada; não se apresentar como ambiente público de produção.
8. Não incluir MkDocs, Stripe CLI, Quick Tunnel ou seed local na composição padrão próxima de produção.
9. Permitir migrations e um eventual seed próprio de staging apenas por comandos explícitos.
10. Executar smoke ponta a ponta antes de qualquer deploy de produção.

Comandos esperados incluem `staging-ensure`, `staging-bootstrap`, `staging-up`, `staging-down`, `staging-migrate`, `staging-status`, `staging-logs` e `staging-smoke`.

### `production-ensure`

O comando de produção deve ser estrito, somente preparatório e falhar de maneira objetiva:

1. Exigir `.env.production` e recusar dependência de `.env`.
2. Exigir todos os secrets aplicáveis em `/etc/rubrica/secrets`.
3. Verificar existência, conteúdo não vazio, propriedade e permissões dos secrets sem exibi-los.
4. Validar redes, volumes, diretórios persistentes e configuração Compose final.
5. Validar configuração do Cloudflare Tunnel permanente.
6. Confirmar que PostgreSQL, Redis, APIs, observabilidade e MkDocs não publicam portas no host.
7. Confirmar que cloudflared alcança somente o gateway pela topologia aprovada.
8. Confirmar ausência de seed, MkDocs, Stripe CLI e Quick Tunnel na configuração de produção.
9. Validar que providers selecionados possuem a configuração estrutural correspondente.
10. Validar a rede privada, o token Viewer e os endpoints de ingestão/consulta necessários à integração com a Platform Infra.

Não gera secrets, não executa migrations, não sobe a aplicação e não realiza chamada paga.

### `production-bootstrap`

Destina-se à primeira instalação ou recuperação controlada, não a todo deploy:

1. Executar `production-ensure`.
2. Subir PostgreSQL e Redis e confirmar seus estados internos de readiness.
3. Confirmar volumes e bancos necessários.
4. Aplicar migrations por etapa explícita e com falha interrompendo o fluxo.
5. Subir APIs internas e validar readiness.
6. Subir frontend e gateway.
7. Subir o Cloudflare Tunnel permanente.
8. Executar healthchecks internos e validações seguras de providers.
9. Produzir relatório final de prontidão sem revelar secrets ou dados pessoais.

O bootstrap de produção nunca executa seed local, cria usuários de teste, gera secrets, inicia Stripe CLI/MkDocs, publica portas internas, apaga volumes ou reseta bancos. Deploys recorrentes usam `production-migrate` e `production-up`, não o bootstrap completo por padrão.

### Observabilidade por ambiente

A `observability_api` pertence ao Rúbrica e continua fazendo parte de dev, staging e produção. Loki, Prometheus, Tempo, Grafana e Alloy pertencem à `platform_infra` e não devem ser incorporados ao Compose principal do produto.

No desenvolvimento:

- a aplicação deve funcionar normalmente sem a Platform Infra;
- instrumentação de métricas, logs e traces permanece ativa ou degradável, sem bloquear health, readiness, migrations, seed ou fluxos do produto;
- Loki, coletores e outros componentes são ligados sob demanda, inclusive por `make dev-docker services=...`, quando o trabalho envolve telemetria, correlação, dashboards ou alertas;
- comandos dedicados, como `telemetry-up`, `telemetry-down`, `telemetry-status` e `telemetry-smoke`, devem facilitar esse teste sem torná-lo requisito de todo `dev` ou `dev-docker`;
- falha de exportação local deve ser visível em logs técnicos controlados, sem produzir loop de falhas nem despejar dados pessoais;
- testes unitários e de contrato podem usar exporters em memória ou endpoints falsos; o smoke integrado usa a Platform Infra real local.

No staging, a telemetria deve ser validada em topologia conteinerizada próxima de produção. O smoke confirma separadamente scrape de métricas, ingestão de logs e traces, mas indisponibilidade da Platform Infra continua sem bloquear o produto.

Em produção:

- o Rúbrica se conecta continuamente à Platform Infra pela rede privada já contratada na Parte 9;
- Prometheus coleta métricas das APIs, Alloy/Loki recebe logs e OpenTelemetry envia traces ao endpoint confirmado do Tempo/collector;
- a `observability_api` usa conta Viewer exclusiva e Docker Secret próprio para consultas permitidas;
- indisponibilidade da Platform Infra degrada monitoramento, nunca a assinatura, autenticação, documentos, migrations ou health essencial;
- `production-ensure` valida configuração, secrets, DNS, rede e endpoints sem exigir que uma falha transitória derrube o produto;
- `production-provider-check` executa um evento/trace sintético identificado e confirma ingestão quando isso for seguro;
- dashboards, alertas e retenção permanecem responsabilidade da Platform Infra, enquanto o Rúbrica mantém os contratos e a instrumentação.

O status precisa diferenciar `telemetria configurada`, `exportação alcançável`, `ingestão confirmada` e `plataforma degradada`. Um endpoint configurado ou uma métrica exposta não comprova que logs e traces chegaram aos respectivos backends.

### Validação de providers

Cada provider deve distinguir três estados:

1. **Configurado:** arquivos, endpoints e parâmetros obrigatórios existem e possuem formato básico válido.
2. **Alcançável:** DNS, conexão e TLS funcionam.
3. **Operacional:** autenticação e uma operação segura e representativa foram comprovadas.

`production-ensure` executa apenas validações estruturais e passivas. `production-provider-check` executa probes reais, somente leitura ou sintéticos reversíveis, com timeout e saída sanitizada.

| Provider | Probe operacional esperado |
|---|---|
| PostgreSQL | Conexão e consulta somente leitura em cada banco requerido |
| Redis | `PING` e operação temporária isolada quando necessário |
| R2 de documentos | Autenticação e acesso ao bucket; objeto temporário somente se explicitamente seguro |
| R2 de backup | Acesso ao repositório/bucket sem confundir com teste completo de restore |
| Stripe | Consulta somente leitura de conta, produtos ou configuração aplicável |
| Resend | Validação de autenticação por endpoint seguro, sem envio quando possível |
| SerproID | Obtenção/validação controlada de token sem produzir assinatura |
| Carimbo do Tempo Serpro | Autenticação e disponibilidade sem emitir token cobrado por padrão |
| Cloudflare Tunnel | Estado conectado e acesso ao gateway esperado |
| Observabilidade | Evento sintético identificado e confirmação de ingestão quando seguro |

Chamadas pagas, envio de e-mail, assinatura, emissão de carimbo ou qualquer operação com efeito externo ficam fora do check padrão. Se necessárias, usam comando separado como `production-provider-check-paid`, com autorização explícita, identificação do custo/efeito e proteção contra execução acidental.

O relatório deve indicar individualmente `configurado`, `alcançável`, `operacional`, `degradado`, `não testado` ou `falhou`; presença de variável não pode ser apresentada como integração operacional.

### Redes e portas

No dev bare metal, as portas das aplicações e os endpoints das dependências vêm de `.env`. No dev-docker, cada dependência selecionada publica somente em `127.0.0.1`, para consumo pelos processos bare metal. A referência inicial, a confirmar no inventário, é:

```text
7171 gateway          7180 frontend
7101 auth-api         7102 core-api
7103 eventing-api     7104 notification-api
7105 observability    7190 MkDocs
7432 PostgreSQL       7379 Redis
Kafka/Loki/OTLP       portas definidas pelo catálogo após inventário
```

Quick Tunnel é a única exposição externa opcional do desenvolvimento e precisa de ação explícita. Staging expõe apenas o gateway e portas técnicas deliberadamente necessárias em loopback; serviços internos comunicam-se por redes Docker.

Em produção, a topologia de entrada é:

```text
Internet → Cloudflare → Cloudflare Tunnel → gateway → frontend/APIs internas
```

- Nenhuma porta de PostgreSQL, Redis, API interna, observabilidade ou MkDocs é publicada no host.
- Cloudflared acessa apenas o gateway na rede necessária.
- Gateway acessa somente frontend e APIs requeridas.
- APIs acessam apenas suas dependências autorizadas.
- Banco e Redis não compartilham redes desnecessárias com frontend ou cloudflared.
- O Compose renderizado, e não apenas o arquivo-fonte, é a evidência final de isolamento.

### Interface-alvo do Makefile

```text
Desenvolvimento bare metal:
  dev
  dev-bootstrap      dev-migrate         dev-seed

Desenvolvimento com dependências Docker:
  dev-docker
  dev-docker services=postgres,redis
  dev-docker services=postgres,loki,kafka
  dev-docker-down    dev-docker-status   dev-docker-logs

Ferramentas opcionais:
  docs-up            docs-logs
  stripe-up          stripe-down          stripe-logs
  quick-tunnel-up    quick-tunnel-down    quick-tunnel-logs
  telemetry-up       telemetry-down       telemetry-status
  telemetry-smoke

Staging 100% Docker:
  staging-ensure     staging-bootstrap
  staging-up         staging-down
  staging-migrate    staging-status
  staging-logs       staging-smoke

Testes:
  test-unit          test-integration     test-all

Produção:
  production-ensure          production-bootstrap
  production-config          production-migrate
  production-up              production-down
  production-status          production-logs
  production-provider-check  production-provider-check-paid
```

Aliases históricos devem ser inventariados antes de remoção. Durante eventual transição, aliases seguros podem apontar para o novo comando explícito, mas nenhum alias ambíguo pode escolher produção por variável incidental.

### Instruções operacionais para agentes

Depois que os pacotes técnicos da Parte 12 estiverem implementados e verificados, criar ou atualizar `AGENTS.md` versionado nos repositórios do Rúbrica. As instruções devem refletir os comandos que realmente existirem; o plano não pode ser copiado antecipadamente como se já estivesse operacional.

O contrato para agentes deve registrar, no mínimo:

- localização e responsabilidade de `rubrica-back` e `rubrica-front`;
- `.env` exclusivamente local e `.env.production` exclusivamente no servidor;
- proibição de colocar secrets em arquivos de ambiente ou no Git;
- comandos canônicos `dev`, `dev-docker services=...`, `dev-bootstrap`, migrations, seed e ferramentas opcionais;
- staging como primeiro fluxo 100% Docker e os comandos `staging-*` correspondentes;
- comandos canônicos e mais restritivos para `production-ensure`, migrations, deploy, bootstrap e provider checks;
- diferença entre `ensure`, `bootstrap`, `up`, health/readiness e `provider-check`;
- regra de nunca executar seed, MkDocs, Stripe CLI ou Quick Tunnel em produção;
- topologia bare metal, dependências Docker em loopback, staging conteinerizado e isolamento de produção pelo Cloudflare Tunnel → gateway;
- comportamento da observabilidade: Platform Infra opcional para testes locais de telemetria e integrada em produção, sempre com degradação segura;
- obrigação de consultar Makefile, Compose renderizado e documentação vigente antes de sugerir comandos;
- proibição de chamadas pagas, envio real, assinatura, timestamp ou mutação externa sem autorização explícita;
- comandos de validação e critérios mínimos antes de commit, push ou orientação de deploy;
- cuidado com arquivos e volumes pertencentes a root e preferência por Docker sem `sudo` no desenvolvimento quando o usuário possuir acesso ao daemon.

Como backend e frontend são repositórios Git separados, a implementação deve decidir uma fonte canônica e evitar duas cópias extensas divergentes. A preferência é manter o contrato operacional detalhado no backend e um `AGENTS.md` curto no frontend com suas regras próprias e referência clara ao contrato do ambiente, desde que essa referência funcione nos contextos reais de checkout e CI. Se os repositórios também forem usados isoladamente, cada um precisa conter instruções mínimas suficientes para não depender de um diretório irmão ausente.

Os `AGENTS.md` não devem conter credenciais, endereços privados sensíveis, dados pessoais, senhas de seed reais fora do contrato público de desenvolvimento nem procedimentos destrutivos como padrão. Qualquer alteração futura em Makefile, nomes de comandos, arquivos de ambiente, secrets, profiles ou topologia deve atualizar as instruções no mesmo conjunto de mudanças.

### Testes e critérios de aceitação da Parte 12

- `make dev` exige e valida `.env`, inicia frontend e APIs internas bare metal com hot reload e não exige Docker nem executa ensure de dependências.
- `make dev` respeita os endpoints configurados e falha claramente quando indisponíveis, sem instalar, iniciar ou redirecionar dependências.
- `make dev-docker` sobe somente dependências externas às APIs internas, aguarda readiness e mantém frontend/APIs bare metal.
- `make dev-docker services=postgres,loki` seleciona exatamente os serviços solicitados; nomes desconhecidos ou combinações inválidas falham antes de alterar estado.
- O conjunto padrão de `dev-docker` é documentado e não inclui frontend ou APIs internas do Rúbrica.
- Nenhum comando diário de dev executa migrations ou seed implicitamente; `dev-bootstrap`, `dev-migrate` e `dev-seed` possuem responsabilidades explícitas e são idempotentes onde aplicável.
- Stripe CLI, Quick Tunnel, Kafka e componentes de telemetria somente sobem quando estiverem no conjunto padrão aprovado ou forem selecionados explicitamente.
- Dev funciona com a Platform Infra desligada; `telemetry-up` e `telemetry-smoke` validam métricas, logs e traces sob demanda.
- Dependências Docker de desenvolvimento publicam portas somente em loopback e os processos bare metal usam os mesmos endpoints declarados em `.env`.
- Nenhum comando de dev lê configuração, secrets, buckets ou providers reais de staging/produção por acidente.
- Staging é 100% Docker, usa Docker Secrets próprios, imagens/entrypoints próximos de produção e passa por `staging-ensure` e `staging-smoke`.
- Staging não usa `.env`, `.env.production`, secrets reais, R2 operacional, seed local, MkDocs, Stripe CLI ou Quick Tunnel em sua composição padrão.
- Dev persiste documentos em filesystem local fora do Git; staging usa volume Docker nomeado; produção recusa provider local e exige R2.
- Trocar o provider não altera contratos de criptografia, hash, autorização, validação, evidência ou preservação; testes de contrato executam a mesma matriz de segurança nos providers aplicáveis.
- `dev-docker-down` e `staging-down` preservam seus arquivos; remoção exige comando destrutivo explícito e não existe sincronização automática para R2.
- Testes R2 fora da produção usam bucket e credenciais exclusivos, nunca o bucket operacional.
- `production-ensure` falha antes do deploy quando configuração, secret, permissão, volume, rede ou isolamento estiver incorreto.
- Nenhum comando de produção lê `.env`/configuração de staging, cria secret, executa seed ou inclui serviço de desenvolvimento.
- A configuração Compose de produção não publica portas internas e aceita tráfego de entrada somente por Cloudflare Tunnel → gateway.
- Produção valida a integração privada com a Platform Infra e confirma separadamente coleta de métricas, ingestão de logs e ingestão de traces.
- Indisponibilidade da Platform Infra aparece como degradação observável, mas não bloqueia readiness essencial nem fluxos do produto.
- `production-bootstrap` é seguro para primeira instalação, interrompe em falha e não apaga ou reinicializa dados existentes.
- Cada provider reporta separadamente configuração, alcance e operação comprovada.
- Checks padrão não realizam chamadas pagas nem efeitos externos; checks pagos exigem comando e autorização separados.
- Makefile, Compose e documentação usam a mesma terminologia e não oferecem comandos duplicados com semântica divergente.
- Os `AGENTS.md` descrevem os comandos realmente implementados, distinguem dev bare metal, dev-docker, staging e produção e impedem o uso do ambiente errado.
- Um teste/revisão documental detecta comandos inexistentes ou referências divergentes entre Makefile, Compose, documentação e `AGENTS.md`.
- Testes automatizados validam seleção de dependências, staging/produção renderizados, ausência de serviços proibidos, publicação de portas e proteção contra cruzamento de níveis.
- Smokes controlados comprovam dev, dev-docker completo/parcial, staging e produção antes de marcar os pacotes como `VERIFICADO`.

## Próximas partes

Acrescente aqui a Parte 12 e as seguintes conforme o usuário as definir. Separe requisitos confirmados de sugestões e atualize os critérios de aceitação sem apagar decisões anteriores.
