---
name: rubrica-document-datatables
description: Planejar e implementar a evolução full stack do fluxo de documentos e assinaturas do Rúbrica, incluindo DataTables, carimbos, verificação opcional de identidade e notas de release. Use ao continuar esta feature, revisar seu escopo ou executar uma de suas partes.
---

# Evolução full stack de documentos e assinaturas

Evolua o fluxo de documentos e assinaturas do Rúbrica sem perder comportamentos existentes. A feature abrange frontend e backend, embora esta skill seja mantida no repositório `rubrica-back` como referência central.

A primeira parte alcança as duas listas principais do dashboard:

- documentos enviados;
- solicitações abertas para assinatura.

Antes de planejar ou alterar código, leia [references/feature-spec.md](references/feature-spec.md). Esse arquivo é a fonte de verdade incremental da feature e deve receber as próximas partes fornecidas pelo usuário.

## Controle de execução

- Antes de iniciar trabalho, localize o pacote correspondente no quadro `Acompanhamento da implementação` da especificação e confirme dependências e pendências.
- Divida toda nova parte em pacotes pequenos, demonstráveis e reversíveis antes de implementar. Não use “Parte concluída” como substituto do status de cada pacote.
- Ao começar um pacote, marque `EM ANDAMENTO`, registre a data e descreva o próximo resultado observável.
- Marque `IMPLEMENTADO` somente quando o código necessário estiver presente. Marque `VERIFICADO` somente depois de executar os testes e critérios de aceitação relevantes.
- Registre evidências objetivas: caminhos de arquivos, migrations, endpoints, testes executados e commit quando existir. Não use descrições vagas como “feito”.
- Se algo ficar incompleto, mantenha o status real e preencha `Pendente/próximo passo`. Não promova pacote parcial para implementado.
- Use `BLOQUEADO` apenas com motivo verificável e ação necessária; use `ADIADO` para decisão consciente de escopo.
- Atualize o quadro no mesmo conjunto de mudanças do código correspondente. Ao finalizar uma sessão, registre também itens iniciados mas não concluídos.

## Forma de trabalho

- Trate esta mudança como uma feature ampla e isolada em branch própria.
- Use a branch `feature/document-signing-workflow`, criada a partir da `main` atualizada, salvo se o usuário escolher outro nome.
- Não exclua branches. A intenção informada pelo usuário é manter apenas `main` e a branch da feature, mas qualquer exclusão exige solicitação explícita e confirmação dos alvos.
- Antes de editar, inspecione os endpoints, consultas e contratos no backend, além do consumo das duas listas no frontend.
- Preserve alterações existentes do usuário e não misture correções não relacionadas.
- Não implemente partes futuras apenas porque a estrutura parece sugeri-las; registre-as quando forem informadas.

## Decisões da tabela

- Use uma biblioteca pronta de DataTable compatível com a versão atual do Angular; não recrie paginação, ordenação e filtros como um componente artesanal.
- Antes de adicionar dependência, verifique compatibilidade, manutenção, licença, tamanho/importação e acessibilidade. Prefira uma opção Angular-native que permita conservar a identidade visual existente.
- Reaproveite um único componente/configuração comum quando isso não apagar diferenças funcionais entre as duas tabelas.
- Preserve todos os filtros, ações, estados vazios, permissões, responsividade e traduções existentes.
- A ordenação inicial deve ser determinística: o item recém-criado aparece primeiro. Ordene por `created_at` decrescente, com `id` decrescente como desempate; não use ordenação lexicográfica de identificadores como substituto da data.
- O backend deve garantir ordenação, paginação e filtragem sobre o conjunto completo. Não masque um contrato incorreto ordenando apenas o subconjunto carregado no navegador.
- Após upload ou criação de solicitação, atualize a fonte da tabela de maneira previsível e mantenha o item novo no topo segundo a ordenação ativa.

## Validação

- Cubra a ordenação inicial, inclusive datas iguais e respostas da API fora de ordem.
- Cubra a preservação dos filtros existentes e os novos filtros definidos na especificação.
- Cubra atualização após upload/criação, paginação, estado vazio, falha de carregamento e ações permitidas por perfil.
- Verifique desktop e viewport móvel, navegação por teclado, nomes acessíveis e traduções suportadas.
- Execute os comandos já existentes nos projetos para lint, testes, build e E2E relevantes; não invente um fluxo paralelo quando os repositórios já oferecem comandos adequados.
- Ao concluir cada parte, informe o que foi implementado, o que foi somente inferido e quais requisitos continuam pendentes na especificação.

## Posicionamento dos carimbos visuais

- Considere o posicionamento personalizado uma capacidade de conta paga. Para conta gratuita, o frontend não renderiza botão, controle desabilitado, cadeado, modal nem mensagem de upgrade dentro do fluxo de documentos. O backend continua sendo a autoridade e deve negar seu uso por chamada direta.
- A vantagem pode ser comunicada na landing page e na apresentação pública dos planos, fora do fluxo operacional da conta gratuita.
- Baseie a autorização no estado de assinatura/plano já consolidado pelo módulo de billing, não apenas em um campo enviado pelo cliente. Contas gratuitas continuam usando o posicionamento padrão do fluxo atual.
- Trate o posicionamento definido por quem abre a solicitação como dado do fluxo, persistido e validado no backend, não apenas como estado transitório do visualizador de PDF.
- Vincule cada posição à versão congelada do documento, à página e, quando aplicável, ao signatário destinatário.
- Represente coordenadas de modo independente de zoom, DPI e viewport; converta para o sistema de coordenadas do PDF apenas na composição final.
- Permita várias posições no mesmo documento, inclusive uma posição em cada página, sem presumir que existe apenas um carimbo global.
- Depois que a solicitação for aberta, não aceite alterações silenciosas nas posições. Qualquer edição posterior precisa obedecer à regra de imutabilidade definida na especificação e deixar evidência auditável.
- Não confunda o carimbo visual de assinatura/rubrica com o Carimbo do Tempo SERPRO/RFC 3161. O primeiro é aparência e posicionamento no PDF; o segundo é evidência criptográfica e não depende de coordenadas visuais.
- Preserve assinaturas anteriores ao compor novos carimbos e impeça sobreposição acidental entre signatários quando houver múltiplas assinaturas.
- Múltiplos carimbos visuais de uma mesma assinatura não geram cópias independentes do registro completo de evidências. Mantenha uma evidência canônica por evento de assinatura e registre nela a lista de posições aplicadas; cada ocorrência visual referencia a mesma assinatura/evidência.

## Personalização empresarial do carimbo

- Restrinja a personalização visual a tenant empresarial com CNPJ configurado e plano Profissional ou Equipe ativo. Reuse a regra central de recursos empresariais do billing; não confie em flags do cliente.
- Não renderize o editor de carimbo em contas inelegíveis. A capacidade pode ser divulgada somente na landing page e na comparação de planos.
- Separe templates de carimbo institucional/CNPJ e de representante. Um carimbo de representante deve identificar a pessoa natural e a empresa representada; não o apresente como assinatura direta do CNPJ.
- Só use um carimbo institucional como assinatura da pessoa jurídica quando o evento realmente tiver credencial organizacional apropriada. Logo e CNPJ impressos isoladamente não provam assinatura criptográfica da empresa.
- Permita que o emissor escolha, por solicitação, quais elementos opcionais estarão disponíveis ou serão exigidos: identidade visual, logo e assinatura manuscrita desenhada.
- Trate a assinatura desenhada com mouse ou toque como elemento visual e manifestação auxiliar, nunca como autenticação forte, certificado digital ou substituto das evidências canônicas.
- Congele na abertura da solicitação um snapshot da configuração, do logo e do template. Alterações posteriores na identidade visual do tenant não mudam solicitações abertas nem documentos históricos.
- Valide e normalize imagens no backend, limite tipo, dimensões e tamanho e remova conteúdo ativo. Não incorpore SVG ou metadados não confiáveis diretamente no PDF.
- Minimize dados do traçado manuscrito. Preserve o artefato visual e seu hash; não retenha pressão, velocidade ou telemetria biométrica sem finalidade, base legal e política específicas.

## Verificação opcional de identidade

- Trate documento, biometria facial e prova de vida como requisito opcional escolhido pelo emissor para cada solicitação empresarial elegível; não altere o fluxo padrão de todas as assinaturas.
- Prefira o Datavalid V5 para brasileiros quando a contratação e o credenciamento forem viáveis. Use validação cadastral, biometria facial, vivacidade e QR Code da CNH conforme a política escolhida.
- Diferencie explicitamente comparação com biometria oficial da Senatran de comparação com foto de referência fornecida pelo cliente. O segundo modo é fallback e oferece garantia inferior.
- Não presuma cobertura biométrica oficial para toda pessoa com CPF. O caminho mais forte depende de uma referência facial disponível na base governamental, normalmente associada à CNH/Senatran.
- Vincule toda sessão ao signatário, solicitação, versão/hash do documento e nonce de uso único. Resultados do provedor devem chegar ao backend e não podem ser aceitos por declaração do cliente.
- Registre na evidência o modo realmente executado, provedor, versão, transação, resultados, faixas/pontuações, política, tentativas e hashes; nunca descreva um fallback como validação em base oficial.
- Minimize retenção de selfie, vídeo, documento e template biométrico. Não incorpore biometria no PDF nem exponha pontuações sensíveis em carimbos visuais.

## Notas de release no aviso de atualização

- Evolua o `PwaUpdateService` existente; não crie um segundo mecanismo concorrente de atualização.
- Entregue metadados de release como JSON versionado junto da versão PWA pronta, preferencialmente em `appData` do manifesto do Angular Service Worker ou por artefato de build correlacionado de forma inequívoca ao hash da versão.
- O JSON deve incluir versão do schema, identificador único da release, data/hora e destaques curtos traduzidos. Valide o contrato antes de renderizar e use o texto genérico atual como fallback.
- Renderize os destaques como texto, nunca como HTML arbitrário. Limite quantidade e comprimento para manter o SweetAlert rápido de ler e adequado ao celular.
- Use `event.latestVersion`, não a versão atualmente carregada, para evitar mostrar notas de uma release diferente daquela que será ativada.
- “Mais tarde” adia apenas naquela sessão. Não marque a release como instalada/lida antes de `activateUpdate()` concluir; uma nova sessão pode oferecer novamente a atualização ainda pendente.
