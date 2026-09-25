# Cloudflare R2 no Rubrica

Use dois buckets privados e dois tokens de conta limitados ao respectivo bucket:

- `rubrica-backups`: dumps criptografados dos quatro bancos da aplicação;
- `rubrica-documents`: PDFs operacionais acessados diretamente pelo Core via API S3.

Não habilite acesso público, domínio público ou CORS nesses buckets.

## Documentos

Crie estes arquivos com modo `0600` em `/etc/rubrica/secrets`:

```text
r2_documents_endpoint
r2_documents_access_key_id
r2_documents_secret_access_key
r2_documents_bucket
```

O último arquivo contém `rubrica-documents`. Para subir o ambiente com o R2:

```bash
docker compose --env-file .env.production \
  -f compose/production.yml -f compose/features/r2-documents.yml \
  up -d --build core-api gateway
```

O banco continua guardando somente a chave opaca do objeto. Upload, leitura e
exclusão passam pelo Core; o navegador não recebe credenciais nem URL pública.
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
COMPOSE_PROJECT_NAME=rubrica
BACKUP_ROOT=/var/backups/rubrica
R2_ENDPOINT_FILE=/etc/rubrica/secrets/r2_endpoint
R2_BACKUP_BUCKET_FILE=/etc/rubrica/secrets/r2_backup_bucket
AWS_ACCESS_KEY_ID_FILE=/etc/rubrica/secrets/r2_access_key_id
AWS_SECRET_ACCESS_KEY_FILE=/etc/rubrica/secrets/r2_secret_access_key
RESTIC_PASSWORD_FILE=/etc/rubrica/secrets/r2_backup_restic_password
RESTIC_KEEP_DAILY=7
RESTIC_KEEP_WEEKLY=4
RESTIC_KEEP_MONTHLY=6
DELETE_LOCAL_AFTER_UPLOAD=1
```

Instale o Restic, inicialize o repositório e teste um backup manual:

```bash
sudo apt-get update && sudo apt-get install -y restic
sudo install -m 0755 toolbox/operations/r2_backup.sh /usr/local/bin/rubrica-r2-backup
sudo /usr/local/bin/rubrica-r2-backup init
sudo /usr/local/bin/rubrica-r2-backup create
sudo /usr/local/bin/rubrica-r2-backup check
```

Depois instale e habilite o timer diário:

```bash
sudo install -m 0644 infra/systemd/rubrica-r2-backup.service /etc/systemd/system/
sudo install -m 0644 infra/systemd/rubrica-r2-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rubrica-r2-backup.timer
systemctl list-timers rubrica-r2-backup.timer
```

O timer roda às 03:15 de São Paulo, recupera execuções perdidas após reinício e
aplica retenção de 7 diários, 4 semanais e 6 mensais. Depois que o envio e a
retenção remota terminam com sucesso, o diretório temporário local é removido.
