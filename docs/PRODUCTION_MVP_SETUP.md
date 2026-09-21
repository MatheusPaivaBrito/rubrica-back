# Rubrica MVP - configuração e validação de produção

Este documento é o roteiro operacional para colocar o Rubrica no ar. Não grave
tokens neste arquivo, no .env ou no Git. Os valores secretos ficam somente em
`/etc/rubrica/secrets` no servidor, com permissão 0600.

O layout esperado dos checkouts no servidor é:

    ~/projects/rubrica/
    ├── rubrica-back/
    └── rubrica-front/

`rubrica-web` continua sendo o nome interno do projeto Angular e da pasta de
build em `dist`. Ele não é o nome do checkout do frontend no servidor.

## 1. Contas e links necessários

### Domínio e Cloudflare

- Registrar domínio:
  https://developers.cloudflare.com/registrar/get-started/register-domain/
- Painel Cloudflare:
  https://dash.cloudflare.com/
- Criar registros DNS:
  https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/
- Criar Cloudflare Tunnel:
  https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-remote-tunnel/

### Resend

- Criar conta:
  https://resend.com/signup
- Domínios:
  https://resend.com/domains
- API Keys:
  https://resend.com/api-keys
- Documentação de verificação:
  https://resend.com/docs/dashboard/domains/introduction
- Documentação de API Keys:
  https://resend.com/docs/api-reference/api-keys/create-api-key

### Stripe

- Criar conta:
  https://dashboard.stripe.com/register
- API Keys:
  https://dashboard.stripe.com/test/apikeys
- Produtos:
  https://dashboard.stripe.com/test/products
- Webhooks:
  https://dashboard.stripe.com/test/webhooks
- Produtos e preços:
  https://docs.stripe.com/products-prices/how-products-and-prices-work
- Webhooks:
  https://docs.stripe.com/webhooks
- Cartões de teste:
  https://docs.stripe.com/testing

Comece no ambiente de teste da Stripe. Somente depois de todo o checklist passar,
repita produtos, preços e webhook no modo live.

## 2. Comprar e apontar o domínio

1. Compre o domínio e adicione-o à Cloudflare.
2. Defina o hostname público. Exemplo: app.seudominio.com.
3. Crie um Cloudflare Tunnel dedicado ao Rubrica.
4. No hostname público do túnel, use o serviço HTTP `http://web:80`.
5. Não publique portas do Compose nem libere 80/443 para o Rubrica no firewall.
6. Não exponha PostgreSQL, Redis ou portas internas das APIs publicamente.

No arquivo .env.production, RUBRICA_DOMAIN deve conter somente o hostname, sem
https e sem barra:

    RUBRICA_DOMAIN=app.seudominio.com
    RUBRICA_WEB_CONTEXT=../../rubrica-front

## 3. Criar o Cloudflare Tunnel

No painel Cloudflare Zero Trust:

1. Acesse Networks > Tunnels e crie um túnel Cloudflared dedicado ao Rubrica.
2. Adicione o hostname `rubricasignature.com`.
3. Configure o serviço de origem como HTTP e URL `web:80`.
4. Copie o token do comando Docker apresentado pela Cloudflare.
5. No servidor:

    sudo install -d -m 700 -o root -g root /etc/rubrica/secrets
    sudoedit /etc/rubrica/secrets/cloudflare_tunnel_token
    sudo chown root:root /etc/rubrica/secrets/cloudflare_tunnel_token
    sudo chmod 600 /etc/rubrica/secrets/cloudflare_tunnel_token

O arquivo contém somente o token do túnel, sem o comando `docker run`.

## 4. Configurar o Resend

Recomendação: use um subdomínio exclusivo, como mail.seudominio.com, para isolar
a reputação dos e-mails transacionais.

1. Em Resend > Domains, adicione mail.seudominio.com.
2. Copie exatamente os registros SPF, DKIM e MX apresentados.
3. Crie esses registros no DNS da Cloudflare.
4. Para registros de e-mail, mantenha o proxy desativado quando a Cloudflare
   oferecer essa opção.
5. Aguarde o domínio aparecer como Verified.
6. Crie uma API key chamada Rubrica Production, limitada a envio quando essa
   opção estiver disponível.
7. Salve a chave no servidor:

    sudoedit /etc/rubrica/secrets/resend_api_key
    sudo chmod 600 /etc/rubrica/secrets/resend_api_key

8. Configure no .env.production:

    NOTIFICATION_DEFAULT_FROM_EMAIL=no-reply@mail.seudominio.com
    RESEND_FROM_EMAIL=Rubrica <no-reply@mail.seudominio.com>

O domínio depois do @ precisa ser exatamente o domínio verificado no Resend.

## 5. Configurar a Stripe em modo de teste

O Rubrica possui os planos mensais Base e Intermediário, cinco assinaturas
gratuitas antes da cobrança e tolerância padrão de 10 dias após falha de
pagamento. O vencimento é controlado pelo período informado pelo Stripe.

1. Ative o modo de teste ou crie uma Sandbox.
2. Crie os produtos `Rubrica Base` e `Rubrica Intermediate`.
3. Em cada produto, crie preços recorrentes mensais separados em BRL, USD, EUR e JPY. JPY não usa casas decimais.
4. Copie cada ID iniciado por `price_`.
5. Preencha no `.env.production`. Uma moeda sem ID retorna indisponibilidade no checkout em vez de cobrar em outra moeda:

    STRIPE_PRICE_BRL=price_BASE_BRL
    STRIPE_PRICE_USD=price_BASE_USD
    STRIPE_PRICE_EUR=price_BASE_EUR
    STRIPE_PRICE_JPY=price_BASE_JPY
    STRIPE_PRICE_INTERMEDIATE_BRL=price_INTERMEDIATE_BRL
    STRIPE_PRICE_INTERMEDIATE_USD=price_INTERMEDIATE_USD
    STRIPE_PRICE_INTERMEDIATE_EUR=price_INTERMEDIATE_EUR
    STRIPE_PRICE_INTERMEDIATE_JPY=price_INTERMEDIATE_JPY

6. Em Developers > API Keys, copie a secret key de teste iniciada por sk_test_.
7. Salve-a somente neste arquivo:

    sudoedit /etc/rubrica/secrets/stripe_secret_key
    sudo chmod 600 /etc/rubrica/secrets/stripe_secret_key

8. Crie um webhook público:

    https://app.seudominio.com/billing/webhooks/stripe

9. Inscreva o endpoint nestes eventos:
   - checkout.session.completed
   - customer.subscription.created
   - customer.subscription.updated
   - customer.subscription.deleted
   - invoice.payment_succeeded
   - invoice.payment_failed
10. Em Billing > Revenue recovery > Retries, configure tentativas por 10 dias e
    escolha cancelar a assinatura se a recuperação falhar.
11. Em Settings > Billing > Customer portal, habilite a atualização de
    assinaturas, permita a troca de preço e adicione os preços Base e
    Intermediário das quatro moedas. Mantenha o ciclo de cobrança inalterado;
    o Rubrica preserva o uso do período durante upgrade e downgrade.
12. Copie o signing secret iniciado por whsec_ para:

    sudoedit /etc/rubrica/secrets/stripe_webhook_secret
    sudo chmod 600 /etc/rubrica/secrets/stripe_webhook_secret

Chaves, produtos, preços e webhooks do modo teste não existem no modo live. A
troca para produção exige recriar esses objetos no modo live e substituir todos
os respectivos arquivos e IDs.

## 6. Gerar os segredos internos

Execute no servidor. Cada valor deve ser independente:

    sudo install -d -m 700 -o root -g root /etc/rubrica/secrets
    umask 077
    openssl rand -base64 48 | sudo tee /etc/rubrica/secrets/postgres_password >/dev/null
    openssl rand -base64 48 | sudo tee /etc/rubrica/secrets/auth_mfa_encryption_key >/dev/null
    openssl rand -base64 48 | sudo tee /etc/rubrica/secrets/auth_identity_encryption_key >/dev/null
    openssl rand -base64 48 | sudo tee /etc/rubrica/secrets/auth_identity_hmac_key >/dev/null
    openssl rand -base64 48 | sudo tee /etc/rubrica/secrets/notification_internal_service_key >/dev/null
    openssl rand -base64 48 | sudo tee /etc/rubrica/secrets/core_internal_service_key >/dev/null
    openssl rand -base64 48 | sudo tee /etc/rubrica/secrets/evidence_secret >/dev/null

Crie a senha inicial do administrador no gerenciador de senhas e grave-a em:

    sudoedit /etc/rubrica/secrets/auth_seed_admin_password

Confira os arquivos exigidos:

    sudo find /etc/rubrica/secrets -maxdepth 1 -type f -printf '%f\n' | sort
    sudo chmod 600 /etc/rubrica/secrets/*

Arquivos esperados:

- postgres_password
- auth_seed_admin_password
- auth_mfa_encryption_key
- auth_identity_encryption_key
- auth_identity_hmac_key
- notification_internal_service_key
- core_internal_service_key
- resend_api_key
- evidence_secret
- stripe_secret_key
- stripe_webhook_secret
- contact_turnstile_secret_key
- serproid_client_secret
- cloudflare_tunnel_token

O arquivo `serproid_client_secret` precisa conter o segredo real para o Core
API iniciar. Consulte [SERPROID_SETUP.md](SERPROID_SETUP.md) para configurar e
testar a assinatura com certificado.

## 7. Preparar o ambiente

    cd ~/rubrica/rubrica-back
    cp .env.production.example .env.production
    nano .env.production

Preencha:

- RUBRICA_DOMAIN;
- e-mail administrativo;
- remetente Resend;
- ID do preço Stripe BRL e, quando disponíveis, os preços USD e JPY;
- quantidades de workers, se necessário.

Não coloque senhas ou tokens no .env.production.

Valide antes de iniciar:

    make production-config

O comando deve terminar sem erro e sem imprimir valores secretos.

## 8. Primeiro deploy

    make production-up
    make production-migrate
    make production-seed
    docker compose --env-file .env.production -f compose/production.yml ps

Todos os serviços devem estar Up. Depois verifique:

    curl -I https://app.seudominio.com/
    docker compose --env-file .env.production -f compose/production.yml logs --tail=100 auth-api notification-api core-api web

Não publique enquanto houver traceback, erro de conexão, falha de migration,
erro Resend ou erro de assinatura Stripe.

## 9. Validação ponta a ponta

### Conta e e-mail

1. Abra a tela de criação de conta.
2. Crie uma conta com um e-mail real de teste.
3. Confirme que o e-mail chegou pelo Resend.
4. Abra o link e confirme o e-mail.
5. Entre na conta.
6. Solicite recuperação de senha.
7. Confirme a chegada do segundo e-mail.
8. Troque a senha e entre novamente.
9. Ative MFA, saia e entre usando o código.

### Assinatura

1. Faça upload de um PDF.
2. Crie uma solicitação.
3. Adicione pelo menos dois signatários.
4. Compartilhe o link.
5. Assine com o primeiro usuário.
6. Confirme que o segundo vê a versão com o primeiro carimbo.
7. Assine com o segundo.
8. Baixe o PDF consolidado.
9. Consulte as evidências no dashboard.
10. Confirme que usuário não signatário recebe somente visualização autorizada
    ou a mensagem de acesso correspondente.

### Limite gratuito e Stripe

1. Use uma conta de teste até completar cinco assinaturas contabilizadas.
2. Confirme que a sexta assinatura exige plano pago.
3. Abra /plan e inicie o Checkout.
4. Use o cartão de teste 4242 4242 4242 4242, data futura e qualquer CVC.
5. Confirme o retorno para /plan?checkout=success.
6. No painel Stripe, confirme entrega HTTP 2xx dos eventos.
7. No Rubrica, confirme o status ativo e a franquia de 25 ou 30 arquivos.
8. Use o botão de upgrade ou troca de plano e confirme que o portal apresenta
   Base e Intermediário na moeda da conta.
9. Cancele a assinatura no Stripe.
10. Confirme que customer.subscription.updated ou deleted atualizou o Rubrica.

### Conta vitalícia por convite da equipe

A conta vitalícia deve ser criada somente por alguém com acesso administrativo
ao servidor. O comando pede o documento de forma interativa, sem exibi-lo nem
gravá-lo no histórico do terminal. O Rubrica envia o e-mail de ativação e o
próprio titular define a senha:

    sudo make production-invite-lifetime \
      name='Nome completo' \
      email=pessoa@example.com \
      document_type=BR_CPF \
      document_country=BR \
      locale=pt-BR \
      actor=staff@rubricasignature.com \
      reason='Parceria estratégica'

Depois de informar o número do documento no prompt protegido, o comando:

1. cria a conta desativada com senha aleatória irrecuperável;
2. criptografa o documento e armazena somente a exibição mascarada;
3. cria o tenant da pessoa;
4. envia o link de ativação para ela escolher a própria senha;
5. concede acesso vitalício e registra responsável, motivo e horário na
   auditoria de billing.

Para uma conta que já existe, localize o UUID do tenant e conceda somente o
benefício:

    sudo make production-grant-lifetime \
      tenant_id=UUID \
      actor=staff@rubricasignature.com \
      reason='Parceria estratégica'

Uma concessão pode ser revogada, sem remover a conta nem seu histórico:

    sudo make production-revoke-lifetime \
      tenant_id=UUID \
      actor=staff@rubricasignature.com \
      reason='Encerramento da concessão'

## 10. Backup e restauração

Depois do primeiro deploy válido:

    make backup-production

Para enviar a cópia criptografada para o Backblaze B2, siga
[`OFFSITE_BACKUP_B2.md`](OFFSITE_BACKUP_B2.md) e use
`make backup-production-offsite`. Em seguida prove a restauração sem tocar na
produção:

    make verify-backup path=backups/YYYYmmddTHHMMSSZ

O resultado esperado informa:

- checksums válidos;
- seis bancos restaurados;
- arquivo dos documentos legível.

## 11. Troca da Stripe para live

Somente depois de todo o teste passar:

1. Conclua a ativação comercial da conta Stripe.
2. Mude o painel para live.
3. Recrie produto e preços live.
4. Crie o webhook live com a mesma URL e eventos.
5. Substitua stripe_secret_key e stripe_webhook_secret.
6. Substitua os STRIPE_PRICE disponíveis no .env.production.
7. Reinicie Core:

    docker compose --env-file .env.production -f compose/production.yml up -d --force-recreate core-api

8. Faça uma compra real de pequeno valor e confirme pagamento, webhook,
   ativação e acesso ilimitado.
9. Não use cartões reais enquanto o servidor ainda estiver com sk_test_.

## 12. Critério de liberação do MVP

O MVP pode ser vendido quando todos os itens abaixo estiverem confirmados:

- domínio e HTTPS válidos;
- Resend entregando confirmação e recuperação;
- cadastro, login, recuperação e MFA funcionais;
- assinatura e PDF consolidado funcionais;
- cinco assinaturas gratuitas contabilizadas;
- Stripe live recebendo pagamento e webhooks;
- assinatura paga liberando uso ilimitado;
- backup externo criado;
- restauração de backup comprovada;
- logs sem erros críticos;
- nenhum segredo rastreado pelo Git.

Se qualquer item falhar, corrija-o antes de adicionar funcionalidades novas.
