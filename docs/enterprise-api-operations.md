# Operação da API empresarial — Parte 14

## Implantação e isolamento

Esta entrega implementa o contrato; não é autorização de publicação nem migração automática de produção. Atualize backend e frontend da mesma branch. Execute as migrações explícitas antes de iniciar serviços: Core até `0041_enterprise_execution`, Auth até `0014_machine_retirements` e Observability até `0003_enterprise_usage`. Não use configuração produtiva, credenciais, buckets ou dados reais nos ensaios de desenvolvimento.

Os arquivos Compose de staging e produção incluem `enterprise-worker`, `enterprise-sandbox-worker`, `enterprise-maintenance` e `clamav`. Os workers pertencem ao Core, acessam somente seu banco e usam os mesmos overlays de R2/timestamp. Não possuem listener nem porta publicada. Aplicação HTTP usa `ENTERPRISE_DEDICATED_WORKERS=true`; no desenvolvimento bare metal e Compose local, coordenadores embutidos executam os mesmos filhos isolados. ClamAV é necessário para liberar documentos; não há aprovação automática quando está indisponível. No dev, inicie a dependência opcional `clamav` e configure `ENTERPRISE_CLAMAV_HOST=127.0.0.1`.

Fila persistente cifrada, até 50 trabalhos pendentes/em execução por empresa/modo. Limite distribuído padrão: quatro atos live globais, dois por tenant e um sandbox global. Sandbox não toma vagas live. Cada trabalho executa em outro processo com limites padrão de 60 segundos de parede/CPU e 1 GiB de endereço virtual; o container tem teto de 1280 MiB, CPU, PIDs, filesystem somente leitura e tmpfs limitado. Timeout mata o grupo de processos; owner/lease impedem conclusão por processo antigo. Dimensione esses limites com PDFs representativos antes de anunciar capacidade de produção. Escalar réplicas não aumenta as cotas globais no banco.

Uploads aceitam no máximo 50.000.000 bytes e entram em quarentena. Parsing profundo, ClamAV e assinatura executam fora do processo HTTP. POST de scan/consentimento retorna **202** e o ID do trabalho. Máquina consulta `/api/v1[/sandbox]/compartments/{id}/jobs/{job_id}`; signatário consulta `/api/v1[/sandbox]/signing-session/jobs/{job_id}` com sua sessão restrita. Repetir scan falho exige documents:create. Retry de consentimento exige a sessão original, válida. Callback SerproID consumido não é reutilizado: se falhar antes da assinatura, reinicie a autorização pessoal. Nunca reutilize código OAuth após consumo.

Limites HTTP: IP no Nginx, tenant e token no Core, orçamento administrativo persistente por ator/tenant. Sessão humana segue a política MFA existente do Auth; staging continua dispensando autenticador conforme configuração do ambiente. Administrador pode desativar integração: chamadas seguintes e trabalhos ainda na fila são recusados. Ato externo já iniciado pode produzir resultado e precisa de reconciliação, não de uma nova emissão.

## Recuperar resultado externo sem duplicar emissão

Antes da chamada paga, o Core grava uma intenção com owner e hash do comando, PDF de entrada, chave de saída fixa e contexto cifrado. Depois da resposta verificada, persiste bytes e checkpoint antes do commit do ato. Queda entre persistência e commit permite reconstruir assinatura, evidência, ledger e evento uma única vez. Timeout sem resposta é `uncertain`: não autoriza nova chamada paga. A manutenção recupera resultado já persistido. Consulta administrativa por integração: `GET .../operations`; `POST .../operations/{id}/reconcile` enfileira leitura do resultado existente, sem chamar o provedor.

Se o provedor emitiu e os bytes nunca chegaram ao Rubrica, a reconciliação depende da recuperação desse **mesmo** resultado junto ao provedor. Não existe garantia técnica de recuperar bytes que o provedor não disponibiliza. Não apague o bloqueio nem faça uma segunda emissão para "resolver". A primitiva `provider_operations.recover(..., artifact=...)` exige correspondência do PDF original e validação criptográfica/cadeia/revogação; sua execução é operacional, não um endpoint público de upload irrestrito.

## Dados temporários, sandbox e encerramento

Manutenção limpa documentos sandbox com 30 dias, inclusive solicitações simuladas abertas. Live aceitos/ativos não são apagados por idade. Quarentena/rejeitados live não utilizados podem ser removidos após 30 dias. Exclusão é estrita e retomável; referências e consumo não desaparecem se DELETE/ausência não foram confirmados. Sessões/autorizações expiradas e payloads transitórios são limpos em lotes. PDFs em spool usam arquivos temporários sem nome persistente; tmpfs do container limita espaço residual e é removido com o container.

Contrato suspende no corte e preserva retirada administrativa até a data exata de recuperação (30 dias), sem ampliar o prazo por migração. Depois, `ENTERPRISE_RETENTION_PURGE_ENABLED=true` permite expurgo corrente. A flag permanece desligada até o ensaio operacional. Destinos externos do cliente nunca são apagados. Fechamento registra quatro provas separadas: objetos/órfãos Rubrica ausentes; metadados/segredos pessoais removidos; Auth aposentou credenciais; backups declarados foram compactados/verificados. Falha em uma etapa permanece pendente, visível no painel. Não alegar conclusão completa somente porque o bucket está vazio.

Após todas as provas e um contrato pago ativo, administrador confirma **novo contrato vazio** com o recibo de fechamento. Integrações/dados/token anteriores não são restaurados. Retry do recibo anterior é idempotente e não revoga tokens criados para o contrato novo.

## Barreira verificável de backups

`ENTERPRISE_BACKUP_POLICY=external` é o padrão. `none` só conclui sem backup em development. Registre em `ENTERPRISE_BACKUP_REPOSITORIES` os SHA-256 das strings RESTIC_REPOSITORY de **todos** os repositórios gerenciados deste ambiente. Sem inventário/prova, o fechamento fica pendente. Cada ambiente deve ter repositório/prefixo e arquivos de configuração próprios; nunca inclua snapshots de outro projeto no inventário.

O operador executa `toolbox/operations/enterprise_retention_docker.sh` com:

- RUBRICA_BACKUP_CONFIG: arquivo absoluto da configuração de backup deste ambiente;
- RUBRICA_PROJECT_DIR: checkout backend absoluto;
- RUBRICA_BACKUP_SECRETS_DIR: diretório absoluto dos secrets desse ambiente;
- BACKUP_ROOT: diretório absoluto e exclusivo dos arquivos de backup;
- RUBRICA_BACKUP_NETWORK: rede Docker com acesso interno ao Core e saída ao R2.

O arquivo de configuração precisa declarar RUBRICA_BACKUP_ENVIRONMENT, COMPOSE_PROJECT_NAME, COMPOSE_FILE, ENV_FILE, ENTERPRISE_CORE_INTERNAL_URL (http://core-api:8000), CORE_INTERNAL_SERVICE_KEY_FILE e as credenciais/paths Restic existentes. O wrapper usa Python, Restic e Compose **em container**. O socket Docker concede privilégio operacional; esse job é exclusivo do operador, nunca do cliente/API. Os mounts do checkout/config/secrets são somente leitura e apenas BACKUP_ROOT é gravável.

Sem argumentos, faz **dry-run**. Aplicação exige `--apply --confirm REPLACE_PRE_ERASURE_BACKUP_HISTORY`. Isso cria/verifica dump atual sem os dados expurgados, envia snapshot novo, verifica Restic, remove **todos os snapshots compartilhados anteriores à barreira**, compacta/verifica novamente e remove arquivos locais gerenciados antigos. Afeta o histórico de rollback de todas as empresas presentes nesses dumps compartilhados. Não executar com outros jobs de backup concorrentes; agende em janela exclusiva. Upload recente de dump antigo continua antigo: é comparada também a data da pasta original. Conteúdo sem manifesto/inventário é recusado.

O ACK interno exige identidade retention_worker e chave interna, ambiente/repositório registrado, timestamps posteriores ao expurgo e provas positivas de compactação/arquivos locais/objetos. Registro não cobre cópias fora desse inventário. Arquivos já baixados manualmente, snapshots do host ou retenção imutável externa exigem inventário/operador próprio e impedem afirmar eliminação global. Em restore, nunca use snapshot anterior a uma barreira já concluída; confira inventário de closures antes de liberar rede/aplicação.

## Chaves, incidentes e liberação

Tokens e segredos HMAC podem ser substituídos no painel; token antigo perde validade, segredo aparece uma vez. Rotação de credencial do provedor incrementa versão e exige reabrir autorização de fluxos que congelaram a anterior; nunca faz fallback para a empresa Rubrica.

Não substitua a chave raiz de armazenamento diretamente: ela protege PDFs, cofres de providers/destinos/webhooks e checkpoints. Sua rotação exige janela sem novos atos, inventário verificado, cópia de rollback cifrada, recriptografia explícita de cada envelope/objeto com contexto original e validação integral antes de retirar a chave anterior. Não registrar chaves em logs nem Git. Incidente: desative integração/revogue token, interrompa novas emissões, preserve apenas identificadores de operações e reconcilie resultados incertos sem reemissão.

Portal público `/docs` tem OpenAPI filtrado, PDF fictício e coleção sem secrets. Não fornece contas de seed. Os testes locais cobrem HTTP Auth/Core com bancos separados, concorrência PostgreSQL em Docker, quedas/owners/quotas, isolamento, expurgo e provas de backup. Provedores pagos e scanner são doubles nesses testes. Antes da liberação externa: validar ClamAV real, S3/R2, e-mail/webhook e SerproID/timestamp no ambiente autorizado, executar carga representativa e concluir revisão de segurança independente. Não converter esses gates externos em "aprovado" a partir de testes unitários.
