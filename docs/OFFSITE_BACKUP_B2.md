# Backup externo do Rubrica: Backblaze B2

Backblaze B2 é o destino separado da máquina de produção. Os primeiros 10 GB
armazenados são gratuitos; acima disso há cobrança. O `restic` criptografa os
arquivos antes do envio. O bucket deve ser **privado** e exclusivo para backups;
não use o bucket de documentos públicos nem uma conta Cloudflare R2 da mesma
operação. Confira o uso e configure alerta/limite de gasto no painel B2.

## Preparar uma vez

1. Crie um bucket privado no B2 e uma Application Key limitada a esse bucket,
   com leitura e escrita. Anote o endpoint S3 da região do bucket.
2. Instale `restic` no servidor (`sudo apt install restic`). Crie os arquivos
   `/etc/rubrica/secrets/b2_key_id`, `b2_application_key` e `restic_password`,
   com proprietário `root` e modo `0600`. Gere uma senha longa e aleatória para
   o restic e mantenha uma cópia dela **fora do servidor**, em cofre seguro;
   sem ela o backup não pode ser restaurado.
3. Crie `/etc/rubrica/backup-offsite.env`, modo `0600`, com os caminhos abaixo.
   Troque `REGION` e `BUCKET` pelos valores do B2. Esse arquivo não contém as
   próprias chaves:

   ```sh
   RESTIC_REPOSITORY=s3:s3.REGION.backblazeb2.com/BUCKET/rubrica-production
   RESTIC_PASSWORD_FILE=/etc/rubrica/secrets/restic_password
   AWS_ACCESS_KEY_ID_FILE=/etc/rubrica/secrets/b2_key_id
   AWS_SECRET_ACCESS_KEY_FILE=/etc/rubrica/secrets/b2_application_key
   ```

4. No checkout do backend, abra uma sessão root para que `make` e Docker tenham
   acesso aos arquivos protegidos:

   ```sh
   sudo -i
   cd /home/ubuntu/projects/rubrica/rubrica-back
   set -a
   . /etc/rubrica/backup-offsite.env
   set +a
   toolbox/operations/offsite_backup.sh init
   make backup-production-offsite
   toolbox/operations/offsite_backup.sh check
   ```

O `make backup-production-offsite` cria um backup local completo, confere os
SHA256 e envia uma cópia criptografada. Erro de upload retorna código diferente
de zero e deixa o backup local para inspeção. Não apague o backup local antes
de comprovar uma restauração remota.

## Operação

Execute o comando diariamente em um timer/cron root, com as quatro variáveis
carregadas de `/etc/rubrica/backup-offsite.env`; monitore o código de saída.
Exemplo para `sudo crontab -e` no servidor com o layout deste projeto:

```cron
15 3 * * * cd /home/ubuntu/projects/rubrica/rubrica-back && set -a && . /etc/rubrica/backup-offsite.env && set +a && /usr/bin/make backup-production-offsite >> /var/log/rubrica-backup.log 2>&1
```

Verifique o log no dia seguinte e configure alerta para falhas do cron;
o simples agendamento não confirma que a cópia foi enviada.
Todo mês, em uma máquina isolada, recupere o snapshot mais recente com
`toolbox/operations/offsite_backup.sh restore /tmp/rubrica-restore`
(o diretório de destino não pode existir) e execute
`make verify-backup path=...` na pasta restaurada que contém `SHA256SUMS`.

O backup atual arquiva os documentos em um único `tar.gz` a cada execução;
isso reduz a deduplicação entre dias. A faixa gratuita de 10 GB pode acabar
rapidamente. Acompanhe o crescimento e defina retenção antes de automatizar
remoção de snapshots. O B2 pode manter versões ocultas após exclusões; aplique
uma regra de ciclo de vida compatível com a retenção escolhida. Não configure
Object Lock enquanto ainda não houver política de retenção e restauração
testada.
