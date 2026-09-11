# Rubrica MVP - configuração e validação de produção

Este documento é o roteiro operacional para colocar o Rubrica no ar. Não grave
tokens neste arquivo, no .env ou no Git. Os valores secretos ficam somente em
secrets/production no servidor, com permissão 0600.

## 1. Contas e links necessários

### Domínio e Cloudflare

- Registrar domínio:
  https://developers.cloudflare.com/registrar/get-started/register-domain/
- Painel Cloudflare:
  https://dash.cloudflare.com/
- Criar registros DNS:
  https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/
- Criar API Token:
  https://developers.cloudflare.com/fundamentals/api/get-started/create-token/
- Certbot DNS Cloudflare:
  https://certbot-dns-cloudflare.readthedocs.io/en/stable/
- SSL Full (strict):
  https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/

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
3. Em DNS, crie um registro A:
   - Nome: app
   - Conteúdo: IPv4 público do servidor
   - Proxy: ativado
4. Em SSL/TLS, selecione Full (strict).
5. Libere TCP 80 e 443 no firewall do servidor.
6. Não exponha PostgreSQL, Redis ou portas 8100-8104 publicamente.

No arquivo .env.production, RUBRICA_DOMAIN deve conter somente o hostname, sem
https e sem barra:

    RUBRICA_DOMAIN=app.seudominio.com
    LETSENCRYPT_EMAIL=infra@seudominio.com
    RUBRICA_WEB_CONTEXT=../rubrica-front

## 3. Criar o token Cloudflare para o certificado

No painel Cloudflare:

1. Acesse My Profile > API Tokens > Create Token.
2. Use o modelo Edit Zone DNS.
3. Permissão: Zone > DNS > Edit.
4. Recurso: inclua somente a zona do domínio do Rubrica.
5. Copie o token uma única vez.
6. No servidor:

    cd ~/rubrica/rubrica-back
    cp secrets/production/cloudflare.ini.example secrets/production/cloudflare.ini
    nano secrets/production/cloudflare.ini
    chmod 600 secrets/production/cloudflare.ini

Conteúdo:

    dns_cloudflare_api_token = COLE_O_TOKEN_AQUI

Não use a Global API Key da Cloudflare.

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

    nano secrets/production/resend_api_key
    chmod 600 secrets/production/resend_api_key

8. Configure no .env.production:

    NOTIFICATION_DEFAULT_FROM_EMAIL=no-reply@mail.seudominio.com
    RESEND_FROM_EMAIL=Rubrica <no-reply@mail.seudominio.com>

O domínio depois do @ precisa ser exatamente o domínio verificado no Resend.

## 5. Configurar a Stripe em modo de teste

O Rubrica possui um único plano mensal pago com assinaturas ilimitadas, cinco
assinaturas gratuitas antes da cobrança e tolerância padrão de 10 dias após
falha de pagamento. O vencimento é controlado pelo período informado pelo Stripe.

1. Ative o modo de teste ou crie uma Sandbox.
2. Crie um produto chamado Rubrica - Assinaturas ilimitadas.
3. Crie três preços recorrentes mensais para esse produto:
   - BRL;
   - USD;
   - JPY.
4. Copie os três IDs iniciados por price_.
5. Preencha no .env.production:

    STRIPE_PRICE_BRL=price_COLE_O_ID_BRL
    STRIPE_PRICE_USD=price_COLE_O_ID_USD
    STRIPE_PRICE_JPY=price_COLE_O_ID_JPY

6. Em Developers > API Keys, copie a secret key de teste iniciada por sk_test_.
7. Salve-a somente neste arquivo:

    nano secrets/production/stripe_secret_key
    chmod 600 secrets/production/stripe_secret_key

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
11. Copie o signing secret iniciado por whsec_ para:

    nano secrets/production/stripe_webhook_secret
    chmod 600 secrets/production/stripe_webhook_secret

Chaves, produtos, preços e webhooks do modo teste não existem no modo live. A
troca para produção exige recriar esses objetos no modo live e substituir todos
os respectivos arquivos e IDs.

## 6. Gerar os segredos internos

Execute no servidor. Cada valor deve ser independente:

    cd ~/rubrica/rubrica-back
    umask 077
    openssl rand -base64 48 > secrets/production/postgres_password
    openssl rand -base64 48 > secrets/production/auth_mfa_encryption_key
    openssl rand -base64 48 > secrets/production/auth_identity_encryption_key
    openssl rand -base64 48 > secrets/production/auth_identity_hmac_key
    openssl rand -base64 48 > secrets/production/notification_internal_service_key
    openssl rand -base64 48 > secrets/production/core_internal_service_key
    openssl rand -base64 48 > secrets/production/evidence_secret

Crie a senha inicial do administrador no gerenciador de senhas e grave-a em:

    nano secrets/production/auth_seed_admin_password

Confira os onze arquivos exigidos:

    find secrets/production -maxdepth 1 -type f ! -name '*.example' ! -name README.md -printf '%f\n' | sort
    chmod 600 secrets/production/*

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
- cloudflare.ini

## 7. Preparar o ambiente

    cd ~/rubrica/rubrica-back
    cp .env.production.example .env.production
    nano .env.production

Preencha:

- RUBRICA_DOMAIN;
- LETSENCRYPT_EMAIL;
- e-mail administrativo;
- remetente Resend;
- IDs dos três preços Stripe;
- quantidades de workers, se necessário.

Não coloque senhas ou tokens no .env.production.

Valide antes de iniciar:

    make production-config

O comando deve terminar sem erro e sem imprimir valores secretos.

## 8. Primeiro deploy

    docker compose --env-file .env.production -f docker-compose.prod.yml run --rm certbot-init
    make production-up
    make production-migrate
    make production-seed
    docker compose --env-file .env.production -f docker-compose.prod.yml ps

Todos os serviços devem estar Up. Depois verifique:

    curl -I https://app.seudominio.com/
    docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 auth-api notification-api core-api web

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
7. No Rubrica, confirme status ativo e assinaturas ilimitadas.
8. Cancele a assinatura no Stripe.
9. Confirme que customer.subscription.updated ou deleted atualizou o Rubrica.

## 10. Backup e restauração

Depois do primeiro deploy válido:

    make backup-production

Guarde a pasta criada em armazenamento criptografado fora do servidor. Em
seguida prove a restauração sem tocar na produção:

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
6. Substitua os três STRIPE_PRICE no .env.production.
7. Reinicie Core:

    docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate core-api

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
