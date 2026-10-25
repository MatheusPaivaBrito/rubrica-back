# Cloudflare R2 no Rubrica

Use três buckets privados e tokens de conta limitados ao respectivo bucket:

- `rubrica-backups`: dumps criptografados dos quatro bancos da aplicação;
- `rubrica-documents`: PDFs operacionais acessados diretamente pelo Core via API S3.
- `rubrica-documents-staging`: PDFs descartáveis do staging, isolados da produção.

Não habilite acesso público, domínio público ou CORS nesses buckets.

## Documentos

Crie estes arquivos com modo `0600` em `/etc/rubrica/secrets`:

```text
r2_documents_endpoint
r2_documents_access_key_id
r2_documents_secret_access_key
r2_documents_bucket
document_storage_encryption_key
```

O arquivo `document_storage_encryption_key` deve ser exclusivo deste armazenamento
e ter pelo menos 32 caracteres aleatórios. Sem ele, objetos cifrados não podem ser
recuperados. O arquivo `r2_documents_bucket` contém `rubrica-documents` em produção
e `rubrica-documents-staging` no staging.

Para subir o ambiente com o R2:

```bash
docker compose --env-file .env.production \
  -f compose/production.yml -f compose/features/r2-documents.yml \
  up -d --build core-api gateway
```

Os alvos `make production-config`, `make production-migrate` e
`make production-up` incluem esse overlay. Assim, a produção não volta
acidentalmente ao volume local.

O banco continua guardando somente a chave opaca e o SHA-256 canônico do objeto.
Antes do upload, o Core usa envelope encryption v2. A raiz do ambiente deriva os
contextos independentes do tenant e do documento; cada objeto recebe uma DEK
aleatória, embrulhada pelo contexto do documento. O conteúdo é cifrado com
AES-256-GCM em chunks autenticados, atualmente de 4 MiB, e inclui storage key,
contexto e ordinal como AAD. Troca de tenant, reordenação, adulteração ou
truncamento falham de forma fechada.

O R2 recebe somente `application/octet-stream`. Baixar um objeto diretamente
pelo painel Cloudflare, por backup ou com uma credencial exclusiva do storage não
produz PDF legível. O Core reutiliza o cliente/pool HTTP do R2 e entrega respostas
autorizadas em streaming, autenticando e descriptografando chunks sem criar uma
segunda cópia integral na memória. A senha do usuário nunca é material de chave.

Durante uma migração controlada, `DOCUMENT_STORAGE_ALLOW_LEGACY_PLAINTEXT=true`
permite ler os objetos históricos. Primeiro faça o dry-run e depois aplique:

```bash
make production-encrypt-r2-documents
make production-encrypt-r2-documents apply=1
```

O leitor reconhece o formato v1 inicialmente implantado e plaintext somente
durante a janela de migração. O migrador sempre grava o formato v2. Depois que o
segundo dry-run informar zero objetos legados, defina
`DOCUMENT_STORAGE_ALLOW_LEGACY_PLAINTEXT=false` e recrie o Core. Nunca remova ou
substitua a chave sem uma rotação/migração verificada.

## Ensaio da migração em staging

O ensaio usa somente o banco Core e o bucket descartável de staging. Produção é
origem somente leitura. Primeiro substitua o banco Core de staging por um dump
verificado de produção; o comando exige confirmação literal e deixa o Core parado:

```bash
make staging-clone-core-from-production \
  confirm=CLONE_PRODUCTION_CORE_TO_STAGING
```

O copiador R2 consulta somente as keys referenciadas pelo banco clonado, recusa
buckets iguais ou destino sem `staging`, não sobrescreve e nunca imprime keys. Faça
o inventário e depois a cópia:

```bash
make staging-clone-r2-documents
make staging-clone-r2-documents apply=1
```

Valide os SHA-256 do plaintext e migre o clone. Esses comandos operam apenas no
bucket configurado nos secrets de staging:

```bash
make staging-encrypt-r2-documents
make staging-encrypt-r2-documents apply=1
make staging-encrypt-r2-documents
```

O último comando precisa informar zero objetos legados e zero divergências. Só
então suba o Core de staging com o fallback plaintext desligado. Durante o clone,
serviços capazes de enviar e-mail, cobrar ou chamar provedores permanecem parados.

Para isolar CPU/memória da latência de rede:

```bash
make document-crypto-benchmark
```

O aceite final também mede o R2 e o navegador reais; o benchmark isolado não
substitui o ensaio ponta a ponta.
Antes de habilitar isso no servidor, os objetos do volume atual devem ser
copiados preservando as chaves e conferidos pelo SHA-256 registrado no banco.
Com o ambiente em janela de manutenção, faça primeiro a conferência e depois a
cópia. O comando não remove o volume local:

```bash
docker compose --env-file .env.production \
  -f compose/production.yml -f compose/features/r2-documents.yml \
  run --rm core-api python toolbox/operations/migrate_documents_to_r2.py

docker compose --env-file .env.production \
  -f compose/production.yml -f compose/features/r2-documents.yml \
  run --rm core-api python toolbox/operations/migrate_documents_to_r2.py --apply
```

A migração e o backup abrangem tanto as versões originais dos documentos quanto
os PDFs finais gerados pelas assinaturas. Cada objeto é conferido pelo SHA-256
registrado no banco.

## Backups manuais

Os comandos aceitam o ambiente local por padrão. Use `environment=production`
no servidor:

```bash
make backup-all environment=production
make backup-database environment=production database=all
make backup-database environment=production database=auth
make backup-files environment=production
```

Os aliases de banco são `core`, `auth`, `eventing` e `notification`.
`backup-files` lê os objetos pelo provedor configurado, inclusive R2, valida os
hashes e gera um arquivo independente para restauração.

## Backup diário dos bancos

O backup inclui `rubrica_core`, `rubrica_auth`, `rubrica_eventing` e
`rubrica_notification`. Os documentos não são duplicados no backup diário
quando já estão no bucket operacional.

Além dos quatro arquivos R2 já criados para backup, gere uma senha Restic e
guarde uma cópia fora do servidor. Sem ela o backup não pode ser restaurado:

```bash
openssl rand -base64 48 | sudo tee /etc/rubrica/secrets/r2_backup_restic_password >/dev/null
sudo chmod 600 /etc/rubrica/secrets/r2_backup_restic_password
```

Crie `/etc/rubrica/backup-r2.env` com modo `0600`:

```sh
RUBRICA_PROJECT_DIR=/home/ubuntu/projects/rubrica/rubrica-back
COMPOSE_FILE=compose/production.yml
ENV_FILE=.env.production
COMPOSE_PROJECT_NAME=rubrica-prod
BACKUP_ROOT=/var/backups/rubrica
R2_ENDPOINT_FILE=/etc/rubrica/secrets/r2_endpoint
R2_BACKUP_BUCKET_FILE=/etc/rubrica/secrets/r2_backup_bucket
AWS_ACCESS_KEY_ID_FILE=/etc/rubrica/secrets/r2_access_key_id
AWS_SECRET_ACCESS_KEY_FILE=/etc/rubrica/secrets/r2_secret_access_key
RESTIC_PASSWORD_FILE=/etc/rubrica/secrets/r2_backup_restic_password
RESTIC_KEEP_WITHIN=7d
DELETE_LOCAL_AFTER_UPLOAD=1
```

Instale o Restic, inicialize o repositório e teste um backup manual:

```bash
sudo apt-get update && sudo apt-get install -y restic
sudo install -m 0755 toolbox/operations/r2_backup.sh /usr/local/bin/rubrica-r2-backup
sudo make backup-r2-init
sudo make backup-r2
sudo make backup-r2-check
```

Depois instale e habilite o timer diário:

```bash
sudo install -m 0644 infra/systemd/rubrica-r2-backup.service /etc/systemd/system/
sudo install -m 0644 infra/systemd/rubrica-r2-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rubrica-r2-backup.timer
systemctl list-timers rubrica-r2-backup.timer
```

O timer roda todos os dias às 04:00 UTC e recupera execuções perdidas após
reinício. Cada execução mantém os snapshots dos últimos 7 dias e executa
`prune` para liberar no R2 os blocos que deixaram de ser utilizados. Depois que
o envio e a retenção remota terminam com sucesso, o diretório temporário local
é removido.

Não configure uma regra de expiração de 7 dias diretamente nos objetos do
bucket `rubrica-backups`: o Restic deduplica blocos entre snapshots, então a
remoção isolada pelo R2 pode corromper backups ainda válidos. A retenção deve
ser aplicada somente por `restic forget --keep-within 7d --prune`.
