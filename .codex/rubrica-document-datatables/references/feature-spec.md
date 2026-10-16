# Feature full stack: documentos e fluxo de assinaturas

## Estado

- Especificação em construção.
- Partes registradas: 1, 2, 3, 4 e 5.
- Implementação ainda não autorizada por esta anotação.
- Feature full stack, com trabalho coordenado entre `rubrica-back` e `rubrica-front`.
- Skill mantida no repositório backend como fonte central da especificação.

## Objetivo geral

Modernizar o fluxo de documentos e assinaturas do Rúbrica em uma branch exclusiva, mantendo o comportamento já disponível e criando uma base adequada para as próximas partes da feature.

## Acompanhamento da implementação

Última atualização do quadro: **2026-10-16**.

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
| 1F | Testes unitários, integração e E2E das duas tabelas | ambos | 1C–1E | `IMPLEMENTADO` | 61 testes frontend e 285 testes backend aprovados; build de produção aprovado | E2E visual específico das duas tabelas ainda pode ser ampliado. |

### Parte 2 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 2A | Fechar regras de posição, signatário, ausência e edição após abertura | produto/ambos | decisões pendentes da Parte 2 | `NÃO INICIADO` | Requisitos preliminares abaixo | Resolver decisões funcionais abertas. |
| 2B | Entitlement de posicionamento pago e autorização server-side | backend | 2A | `NÃO INICIADO` | Regra ainda não existe | Modelar capacidade e downgrade. |
| 2C | Persistência, migration e API das posições normalizadas | backend | 2A, 2B | `NÃO INICIADO` | Nenhuma migration criada | Definir schema, validações e imutabilidade. |
| 2D | Editor visual de posições no PDF | frontend | 2A, 2C | `NÃO INICIADO` | Visualizador atual não prepara posições do emissor | Criar interação e prévia responsiva. |
| 2E | Congelamento na abertura e aplicação no PDF | backend | 2C, 2D | `NÃO INICIADO` | Fluxo atual permanece | Integrar snapshot e composição incremental. |
| 2F | Evidência canônica com lista de posições | backend | 2E | `NÃO INICIADO` | Evidência atual não contém o novo modelo | Registrar posições sem duplicação. |
| 2G | Testes de coordenadas, planos, múltiplos signatários e preservação | ambos | 2B–2F | `NÃO INICIADO` | Nenhum teste novo | Executar matriz definida na Parte 2. |

### Parte 3 — pacotes de trabalho

| ID | Entrega | Repositório | Dependências | Status | Evidência | Pendente/próximo passo |
|---|---|---|---|---|---|---|
| 3A | Entitlement CNPJ + Profissional/Equipe | backend | regra comercial confirmada | `NÃO INICIADO` | Política existente ainda não cobre a feature | Reusar `business_features_enabled`. |
| 3B | Modelo de templates, logos, snapshots e ativos normalizados | backend | 3A | `NÃO INICIADO` | Nenhum modelo/migration | Definir formatos, hashes, limites e retenção. |
| 3C | Configuração administrativa e seleção por solicitação | frontend/backend | 3A, 3B | `NÃO INICIADO` | Nenhuma interface/API | Criar presets seguros e prévia. |
| 3D | Captura opcional de assinatura desenhada por mouse/toque | frontend/backend | decisões pendentes da Parte 3 | `NÃO INICIADO` | Recurso ausente | Definir habilitada versus obrigatória e formato normalizado. |
| 3E | Renderização distinta de CNPJ e representante | backend | 3B–3D, Parte 2 | `NÃO INICIADO` | Carimbo atual permanece | Preservar alegações e identificadores obrigatórios. |
| 3F | Segurança de imagens, evidências e testes completos | ambos | 3B–3E | `NÃO INICIADO` | Nenhum teste novo | Cobrir arquivos hostis, planos, dispositivos e imutabilidade. |

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

### Decisões ainda pendentes

- Se cada posição será obrigatoriamente atribuída a um signatário ou se também haverá posições genéricas.
- Se o signatário poderá ajustar uma posição predefinida ou apenas confirmá-la; pelo objetivo informado, o padrão recomendado é posição fixa.
- Comportamento da conta paga quando nenhuma posição for configurada: usar o posicionamento padrão atual ou exigir pelo menos uma posição.
- Se “um por página” será configurado manualmente ou por uma ação automática de replicação.
- Regras de tamanho mínimo/máximo e prevenção de sobreposição.
- Regra explícita para editar uma solicitação já aberta: proibir definitivamente ou exigir cancelamento e criação de nova versão/solicitação.
- Como distribuir posições quando existem vários signatários e várias páginas.
- Se o acesso vitalício cortesia receberá o entitlement de posicionamento personalizado.

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

### Decisões ainda pendentes

- Se o emissor apenas habilita a assinatura desenhada ou pode torná-la obrigatória para concluir.
- Se o signatário pode escolher entre desenhar, digitar o nome ou usar somente o carimbo padrão quando mais de uma opção estiver habilitada.
- Quais campos técnicos serão sempre obrigatórios no carimbo.
- Quais formatos de logo serão aceitos como entrada e qual será o formato normalizado de armazenamento.
- Quantos templates e logos cada tenant poderá manter.
- Se administradores criam templates livres ou personalizam modelos seguros predefinidos; a segunda opção é recomendada inicialmente.
- Se o carimbo institucional será lançado somente quando existir um fluxo real de credencial organizacional, mantendo até lá apenas o template de representante com identidade visual empresarial.
- Tratamento do acesso vitalício cortesia a essa capacidade empresarial.

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

## Próximas partes

Acrescente aqui a Parte 6 e as seguintes conforme o usuário as definir. Separe requisitos confirmados de sugestões e atualize os critérios de aceitação sem apagar decisões anteriores.
