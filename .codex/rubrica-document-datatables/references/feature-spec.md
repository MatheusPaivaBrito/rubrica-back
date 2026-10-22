# Feature full stack: documentos e fluxo de assinaturas

## Estado

- Especificação em construção.
- Partes registradas: 1, 2, 3, 4, 5, 6, 7, 8, 9 e 10.
- Partes 1, 2, 3, 5, 6, 7 e 9 autorizadas e implementadas na branch da feature; Partes 4 e 8 adiadas e Parte 10 reservada para revisão posterior.
- Feature full stack, com trabalho coordenado entre `rubrica-back` e `rubrica-front`.
- Skill mantida no repositório backend como fonte central da especificação.

## Objetivo geral

Modernizar o fluxo de documentos e assinaturas do Rúbrica em uma branch exclusiva, mantendo o comportamento já disponível e criando uma base adequada para as próximas partes da feature.

## Acompanhamento da implementação

Última atualização do quadro: **2026-10-22**.

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
| 10A | Inventariar todos os arquivos, buckets, prefixes e metadados persistidos | backend/infra | nenhuma | `NÃO INICIADO` | Escopo registrado nesta Parte 10; nenhuma revisão executada | Mapear originais, versões, PDFs assinados, evidências, manifestos, ativos visuais, temporários e backups. |
| 10B | Reconstruir o ciclo de vida completo entre banco, storage local e R2 | backend | 10A | `NÃO INICIADO` | Fluxos ainda não foram rastreados ponta a ponta | Documentar criação, leitura, versionamento, assinatura, substituição, migração, exclusão e recuperação. |
| 10C | Revisar integridade, imutabilidade e vínculo criptográfico dos objetos | backend/segurança | 10A, 10B | `NÃO INICIADO` | Nenhuma conclusão registrada | Verificar hashes, checksums, version IDs, manifesto, evidências, prevenção de sobrescrita e detecção de adulteração. |
| 10D | Revisar isolamento, autorização e exposição de arquivos | backend/segurança | 10A, 10B | `NÃO INICIADO` | Nenhuma conclusão registrada | Auditar tenant, autorização por objeto, URLs assinadas, duração, replay, enumeração, MIME e download seguro. |
| 10E | Revisar retenção, exclusão, LGPD e preservação probatória | produto/backend/infra | 10A–10D, decisão jurídica/produto | `NÃO INICIADO` | Políticas consolidadas ainda não foram confrontadas com o código | Definir matriz por tipo de artefato, finalidade, prazo, legal hold, descarte e conflito entre apagamento e prova. |
| 10F | Revisar backup, restauração, replicação e recuperação de desastre | infra/backend | 10A, 10B | `NÃO INICIADO` | Existem mecanismos de backup R2, mas o ciclo de restauração de documentos não foi comprovado nesta parte | Verificar cobertura, criptografia, credenciais separadas, RPO/RTO, teste de restore e perda parcial de banco ou objetos. |
| 10G | Localizar objetos órfãos, referências quebradas e layouts legados | backend/infra | 10A–10C | `NÃO INICIADO` | Histórico já incluiu mudança de prefixo e migração de objetos | Definir auditoria somente leitura e reconciliação segura antes de qualquer correção ou remoção. |
| 10H | Produzir relatório, matriz de riscos e plano mínimo de adequação | arquitetura/segurança | 10A–10G | `NÃO INICIADO` | Esta anotação define apenas o trabalho futuro | Separar fatos comprovados, hipóteses, riscos e mudanças recomendadas; nenhuma implementação automática. |

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

## Parte 10 — revisão do armazenamento de arquivos e R2

### Decisão de prioridade

Executar esta parte por último no ciclo atual. A revisão é um reforço de integridade, preservação e operação diante de uma provável migração futura do R2; neste momento não existe evidência de incidente crítico que justifique colocá-la à frente das Partes 6 e 7. A postergação não autoriza presumir que os controles já foram validados nem executar a migração sem a auditoria prevista aqui.

### Objetivo

Realizar uma revisão técnica e operacional de como o Rúbrica recebe, identifica, transforma, armazena, recupera, preserva e exclui arquivos, com atenção especial ao Cloudflare R2. Esta parte começa exclusivamente como auditoria e documentação: não autoriza alterar código, banco, buckets, objetos, configurações, lifecycle rules ou dados existentes.

### Escopo da revisão

A revisão deve localizar e diferenciar, no mínimo:

- documento original enviado pelo usuário;
- versões congeladas apresentadas aos signatários;
- PDFs intermediários e PDFs finais assinados;
- assinaturas CMS/PAdES e tokens de Carimbo do Tempo;
- JSONs de evidência e manifestos consolidados;
- logos, carimbos visuais e assinaturas desenhadas, quando existirem;
- arquivos temporários, staging, uploads incompletos e artefatos de operações falhas;
- objetos legados em prefixes antigos e objetos migrados;
- backups de banco, arquivos e repositórios Restic relacionados ao R2.

Para cada classe de arquivo, registrar bucket, prefix/key, proprietário lógico, tenant, tabela e coluna de referência, formato, tamanho máximo, hash/checksum, criptografia, versionamento, retenção, forma de acesso e regra de exclusão. Não confundir a key do R2 com identidade confiável do documento: o vínculo deve ser demonstrado por identificadores e hashes persistidos de modo consistente.

### Perguntas obrigatórias

1. Quais buckets e credenciais são usados para documentos operacionais e backups, e eles estão realmente separados?
2. Como a key é construída e como tenant, documento, versão, solicitação e assinatura são relacionados sem permitir colisão ou acesso cruzado?
3. O banco aponta para objetos imutáveis ou uma mesma key pode ser sobrescrita silenciosamente?
4. Os bytes originais e cada versão assinada permanecem preservados exatamente como produzidos?
5. Quais hashes são calculados, em qual momento e contra quais bytes? Eles são revalidados no download e antes/depois da assinatura?
6. Evidência e manifesto possuem vínculo verificável por terceiros com o PDF correspondente?
7. Versionamento, Object Lock, retenção ou outro controle impedem alterações administrativas não autorizadas? Se não impedem, alterações são ao menos detectáveis?
8. URLs pré-assinadas possuem escopo mínimo, expiração adequada, método restrito e proteção contra reutilização indevida?
9. Uploads validam tamanho, MIME real, estrutura PDF, conteúdo ativo e nome fornecido pelo usuário sem confiar apenas em extensão ou header?
10. Falhas entre banco e R2 deixam objetos órfãos, registros sem objeto ou versões parcialmente confirmadas?
11. Exclusão de conta/documento respeita LGPD sem destruir indevidamente evidências necessárias para exercício regular de direitos ou obrigações legais?
12. Backups cobrem banco e objetos de forma consistente, e existe restauração testada que preserve a correspondência entre registros e arquivos?
13. Mudanças de bucket ou prefix mantêm compatibilidade com documentos históricos e possuem reconciliação verificável?
14. É possível exportar documento, evidências e manifesto e validá-los sem depender exclusivamente do banco ou de uma URL ativa do Rúbrica?
15. Logs e métricas permitem detectar falhas, objetos ausentes, divergência de hash, crescimento anormal, custo e operações administrativas sem registrar conteúdo sensível?

### Segurança e conformidade

- Confirmar isolamento por tenant e autorização por objeto em upload, visualização, download, assinatura e exclusão.
- Revisar permissões das credenciais R2 pelo princípio do menor privilégio; documentos e backups não devem compartilhar acesso amplo sem justificativa.
- Confirmar TLS em trânsito e a proteção em repouso oferecida/configurada, distinguindo criptografia do provedor de criptografia controlada pela aplicação.
- Segredos permanecem em Docker Secrets ou mecanismo equivalente e nunca aparecem em Git, `.env` versionado, logs ou respostas.
- Acesso administrativo, migração e recuperação devem deixar trilha auditável e não permitir substituir silenciosamente um documento histórico.
- Definir retenção por finalidade e tipo de artefato, incluindo descarte seguro, legal hold e resposta a solicitações de titulares.
- Não classificar automaticamente Object Lock, versionamento ou backup como requisito obrigatório: primeiro registrar o risco, a necessidade probatória e o custo, então recomendar a medida proporcional.

### Método da revisão

- Inspecionar código real, migrations, modelos, serviços de storage, Compose, Makefile, scripts operacionais, testes e documentação.
- Reconstruir os fluxos de ponta a ponta e produzir uma tabela por artefato com evidências de arquivo e linha.
- Comparar referências do banco com convenções de keys e prefixes, sem listar nomes reais que contenham dados pessoais.
- Qualquer inventário no R2 deve começar em modo somente leitura e agregado. Não baixar documentos pessoais nem realizar chamadas potencialmente cobradas sem autorização específica.
- Não apagar, mover, copiar, regravar ou corrigir objetos durante a auditoria.
- Classificar achados em comprovado, risco potencial, hipótese e não verificável.
- Separar correções necessárias de melhorias opcionais; evitar recomendar nova infraestrutura quando controles existentes forem suficientes.

### Entrega esperada

O relatório da Parte 10 deve conter:

- diagrama do ciclo de vida dos arquivos;
- inventário de buckets, prefixes e classes de objetos sem revelar dados pessoais ou secrets;
- matriz entre registros de banco, objects keys, hashes, versões e evidências;
- avaliação de isolamento, autorização, integridade, imutabilidade, retenção e recuperação;
- lista de objetos órfãos ou referências quebradas apenas em forma agregada e sanitizada;
- riscos classificados por criticidade e impacto real;
- plano de adequação mínimo, ordenado por dependência, com critérios objetivos de aceite;
- indicação explícita do que já funciona, do que foi apenas inferido e do que não pôde ser verificado.

### Critérios de aceitação da Parte 10

- Todas as classes conhecidas de arquivos estão inventariadas e associadas aos módulos que as criam e consomem.
- O fluxo entre upload, banco, R2, assinatura, evidências, download, backup e exclusão está documentado ponta a ponta.
- A revisão demonstra se sobrescrita ou adulteração é impedida, detectada ou atualmente não controlada.
- O isolamento entre tenants e a autorização por objeto são avaliados em todos os endpoints relevantes.
- A correspondência entre PDF, versão, assinatura, timestamp, evidência e manifesto é explicada com hashes e referências concretas.
- Prefixes antigos, migrações e fallback de leitura são avaliados sem alterar documentos históricos.
- Retenção, descarte, legal hold e direitos dos titulares possuem lacunas e decisões pendentes claramente identificadas.
- Backup e restauração são diferenciados de alta disponibilidade e têm cobertura, RPO/RTO e teste de recuperação avaliados.
- Nenhuma chamada paga, leitura de documento pessoal ou mutação em R2 ocorre sem autorização adicional.
- O resultado final é uma auditoria acionável; nenhuma mudança de implementação é incluída nesta parte sem nova autorização.

## Próximas partes

Acrescente aqui a Parte 11 e as seguintes conforme o usuário as definir. Separe requisitos confirmados de sugestões e atualize os critérios de aceitação sem apagar decisões anteriores.
