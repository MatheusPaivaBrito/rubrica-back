# Carimbo do tempo SERPRO

O fluxo principal da Rubrica pode aplicar automaticamente um carimbo RFC 3161 da ACT SERPRO ao PDF assinado. O signatário não precisa instalar o Serpro ID nem possuir certificado digital. O Serpro ID continua disponível como modalidade opcional de assinatura com certificado.

## Credenciais

Contrate a API Timestamp no SERPRO e obtenha a `Consumer Key` e a `Consumer Secret`. Essas credenciais são diferentes do `SERPROID_CLIENT_ID` e do `SERPROID_CLIENT_SECRET`.

No `.env.production`, configure:

```dotenv
SERPRO_TIMESTAMP_CONSUMER_KEY=sua-consumer-key
```

Crie o secret no servidor:

```bash
sudo install -d -m 700 /etc/rubrica/secrets
sudo sh -c 'umask 077; cat > /etc/rubrica/secrets/serpro_timestamp_consumer_secret'
```

Cole a Consumer Secret, pressione `Enter` e depois `Ctrl+D`.

## Comportamento

- Sem as duas credenciais, o fluxo continua funcionando sem carimbo externo.
- Com as duas credenciais, toda assinatura recebe um `DocTimeStamp` RFC 3161 no PDF.
- Se o SERPRO estiver indisponível, a assinatura não é concluída nem cobrada.
- O relatório de evidências mostra a hora certificada, autoridade, política, número de série e hashes do token.
- O `timestamp_response_base64` permite validação técnica independente do registro RFC 3161.

Após configurar, aplique as migrações e reinicie o Core:

```bash
sudo make production-migrate
sudo docker compose --env-file .env.production -f compose/production.yml up -d --build core-api web
curl -sS https://rubricasignature.com/signing/timestamp/config
```

O último comando deve retornar `{"enabled":true}`.
