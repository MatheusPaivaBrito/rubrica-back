# Assinatura com certificado Serpro ID

A URI de retorno cadastrada no Serpro ID é:

`https://rubricasignature.com/api/auth/serproid/callback`

O Nginx encaminha o callback ao Core API. A opção de assinatura com certificado
aparece ao signatário quando a integração está configurada, a identidade do
Rubrica contém CPF ou CNPJ e ele é o último signatário pendente. A assinatura
comum por evidências continua disponível.

## Credenciais

Em `.env.production`, defina `SERPROID_CLIENT_ID`. Salve o `client_secret` em
`SECRETS_DIR/serproid_client_secret` (por padrão,
`/etc/rubrica/secrets/serproid_client_secret`) com permissão `0600`. O Compose
monta esse arquivo somente no Core API. Não coloque o segredo no `.env` ou no
Git. O arquivo de segredo não pode ficar vazio.
Use `SERPROID_ENVIRONMENT=production` com as credenciais e a URI registradas
em produção. O ambiente local usa `homologation` por padrão.

```sh
sudo install -m 600 -o root -g root /dev/null /etc/rubrica/secrets/serproid_client_secret
sudoedit /etc/rubrica/secrets/serproid_client_secret
```

No servidor, depois de configurar o ID e o segredo, reconstrua Core e Web:

```sh
docker compose --env-file .env.production -f compose/production.yml up -d --build core-api web
```

Em desenvolvimento local, `.env.example` possui `SERPROID_CLIENT_ID` e
`SERPROID_CLIENT_SECRET` vazios. Use credenciais de homologação com a URL de
retorno autorizada nesse ambiente; não reutilize a aplicação de produção.

## Fluxo e limites

O Rubrica gera `state` de uso único e PKCE S256, vincula autorização a
solicitação, signatário e hash do PDF congelado, troca o código por token,
compara CPF/CNPJ do certificado com o cadastro e obtém o certificado. Em seguida,
envia ao Serpro o hash do ByteRange do PDF, incorpora a resposta CMS como
assinatura PAdES, verifica integridade e assinatura criptográfica e só então
conclui a solicitação. Falhas deixam a solicitação pendente.

A opção com certificado é permitida somente para o **último signatário**. O
fluxo atual recompõe o PDF para acrescentar carimbos; fazer isso depois de uma
assinatura PAdES anterior invalidaria seus bytes assinados. Para permitir
múltiplos signatários com certificado no mesmo PDF, o fluxo precisará usar
revisões incrementais em todas as etapas. Pelo mesmo motivo, o Rubrica recusa
esse caminho para PDFs enviados com assinaturas digitais anteriores.

A verificação local cobre integridade criptográfica e correspondência do
certificado retornado pelo Serpro. A validação independente da cadeia ICP-Brasil
e da revogação deve ser feita em um validador confiável, como o VALIDAR do ITI.
Até essa validação externa, não exiba uma afirmação automática de confiança da
cadeia para o usuário.

Referências: [autorização](https://serproid.serpro.gov.br/documentacao/autorizacao/1-codigo-autorizacao/),
[token](https://serproid.serpro.gov.br/manual-integracao/autorizacao/2-token-acesso/),
[assinatura digital](https://serproid.serpro.gov.br/documentacao/utilizacao-certificado/assinatura-digital/)
e [VALIDAR](https://validar.iti.gov.br/).
