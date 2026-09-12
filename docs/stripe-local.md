# Stripe local com Docker Compose

O ambiente local usa a imagem oficial `stripe/stripe-cli` para encaminhar os
eventos do Stripe ao Core sem instalar o CLI no Ubuntu.

Os valores reais ficam fora do repositorio:

```text
/etc/rubrica/secrets/
├── resend_api_key
├── stripe_secret_key
└── stripe_webhook_secret
```

Crie a estrutura e a chave da API antes da primeira subida:

```bash
sudo install -d -m 700 /etc/rubrica/secrets
sudoedit /etc/rubrica/secrets/stripe_secret_key
sudo chmod 600 /etc/rubrica/secrets/stripe_secret_key
```

Suba o listener e consulte o segredo de assinatura emitido por ele:

```bash
docker compose up -d stripe-cli
docker compose logs -f stripe-cli
```

Copie somente o valor `whsec_...` exibido em `Ready! Your webhook signing
secret is ...`, grave-o e reinicie o Core:

```bash
sudoedit /etc/rubrica/secrets/stripe_webhook_secret
sudo chmod 600 /etc/rubrica/secrets/stripe_webhook_secret
docker compose restart core-api
```

Depois disso, `docker compose up -d --build` inicia o listener junto aos demais
servicos. O segredo do listener de teste permanece associado a conta e chave
utilizadas. Se trocar a conta ou a chave de teste, confira novamente os logs e
atualize `stripe_webhook_secret`.

Esse listener e exclusivo para desenvolvimento. Em producao, cadastre o
endpoint HTTPS no Stripe e use o segredo `whsec_...` daquele endpoint.
