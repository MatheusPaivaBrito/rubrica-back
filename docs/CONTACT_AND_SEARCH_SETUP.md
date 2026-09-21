# Contato e indexação do site

## Receber e-mails sem caixa corporativa

1. No Cloudflare, abra **Email > Email Routing** para `rubricasignature.com` e ative o serviço. Confira os registros MX e SPF sugeridos antes de aceitar; se já houver SPF para o Resend, mantenha **um único** registro SPF que autorize ambos os serviços.
2. Adicione e verifique um endereço Gmail dedicado ao Rubrica como **Destination address**. O proprietário do Gmail precisa confirmar o link recebido.
3. Crie regras para `contact@rubricasignature.com` e `privacidade@rubricasignature.com`, ambas apontando ao Gmail verificado. Teste enviando de outro endereço externo para cada alias.
4. O formulário manda a mensagem para `CONTACT_INBOX_EMAIL` (padrão `contact@rubricasignature.com`) usando o serviço Resend já configurado. Confira no Gmail se a mensagem de teste chegou. O e-mail informado pelo visitante aparece no corpo para permitir a resposta manual.

O Email Routing recebe e encaminha mensagens. O envio de respostas como `@rubricasignature.com` requer uma configuração de saída separada; responder pelo Gmail pessoal pode revelar o endereço Gmail ao destinatário.

## Ativar o formulário

1. Crie um widget Cloudflare Turnstile para `rubricasignature.com`. O mesmo widget protege o formulário de contato e o login; no login, o servidor também confere a ação `login` e o hostname.
2. Coloque a **site key** em `CONTACT_TURNSTILE_SITE_KEY` no arquivo de ambiente de produção.
3. Grave a **secret key** somente em `${SECRETS_DIR}/contact_turnstile_secret_key` no servidor, com as mesmas permissões dos demais arquivos de segredo.
4. Antes de subir o novo Compose, confirme que o arquivo existe. O Compose de produção monta esse arquivo como secret no Core API.
5. Faça um envio pela página `/contato` e confira a chegada no Gmail. Teste também login válido e inválido; o token do Turnstile deve ser renovado a cada tentativa. O formulário permanece indisponível até as chaves serem configuradas. Em produção, o login também falha fechado se faltarem as chaves.

Em desenvolvimento, `compose/local.yml` aceita `CONTACT_TURNSTILE_SITE_KEY` e `CONTACT_TURNSTILE_SECRET_KEY` do ambiente. As chaves de teste oficiais do Turnstile servem apenas para desenvolvimento.

## Google Search Console

O container web serve HTML gerado na build para `/`, `/contato`, `/privacidade`, `/termos` e `/exclusao-de-dados`. As rotas de conta e assinatura continuam como aplicação cliente.

1. Cadastre a propriedade **Domínio** `rubricasignature.com` no Search Console e publique o registro TXT de verificação no DNS do Cloudflare.
2. Após o deploy, confira `https://rubricasignature.com/robots.txt` e `https://rubricasignature.com/sitemap.xml`.
3. Envie `sitemap.xml` em **Sitemaps** e use **Inspeção de URL** para testar `/` e `/contato`.

O sitemap inclui apenas as cinco páginas públicas. O `robots.txt` orienta o rastreamento, mas não substitui autenticação nem garante a exclusão de uma URL do índice.
