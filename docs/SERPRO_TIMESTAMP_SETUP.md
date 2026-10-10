# Carimbo do tempo SERPRO

A Rubrica exige carimbo do tempo em toda nova solicitação e permite escolher:

- evidências com carimbo RFC 3161 da ACT SERPRO;
- evidências com certificado digital Serpro ID e carimbo RFC 3161 da ACT SERPRO.

Na modalidade de carimbo do tempo, o signatário não precisa instalar o Serpro ID nem possuir certificado digital. A modalidade fica congelada depois que a solicitação é aberta.

## Credenciais

Contrate a API Timestamp no SERPRO e obtenha a `Consumer Key` e a `Consumer Secret`. Essas credenciais são diferentes do `SERPROID_CLIENT_ID` e do `SERPROID_CLIENT_SECRET`.

No `.env.production`, configure:

```dotenv
SERPRO_TIMESTAMP_PROVIDER=serpro
SERPRO_TIMESTAMP_CONSUMER_KEY=sua-consumer-key
SERPRO_TIMESTAMP_ACCEPTED_POLICY_OIDS=oid-da-politica-aprovada
```

Crie o secret no servidor:

```bash
sudo install -d -m 700 /etc/rubrica/secrets
sudo sh -c 'umask 077; cat > /etc/rubrica/secrets/serpro_timestamp_consumer_secret'
```

Cole a Consumer Secret, pressione `Enter` e depois `Ctrl+D`.

Instale também o bundle PEM de âncoras de confiança aprovado para a cadeia da
ACT SERPRO. Não copie o certificado retornado pelo próprio token como raiz:

```bash
sudo install -m 600 cadeia-icp-brasil-aprovada.pem \
  /etc/rubrica/secrets/serpro_timestamp_trust_roots.pem
```

Confirme o OID configurado contra a Política de Carimbo do Tempo vigente da
ACT SERPRO. A aplicação falha fechada se a cadeia, revogação, política, nonce,
`messageImprint` ou cobertura integral do PDF não puderem ser comprovados.

## Comportamento

- Com `SERPRO_TIMESTAMP_PROVIDER=fake`, novas solicitações não podem ser abertas; o modo existe somente para desenvolvimento e compatibilidade com registros legados.
- Com o provider `serpro`, credenciais, bundle confiável e política aceita, o operador pode abrir solicitações com evidências e carimbo do tempo.
- A modalidade Serpro ID também exige a API Timestamp configurada e recebe o carimbo depois da assinatura PAdES/CMS.
- Se o SERPRO estiver indisponível, a assinatura não é concluída nem cobrada.
- O relatório de evidências mostra a hora certificada, autoridade, política, número de série e hashes do token.
- O `timestamp_response_base64` permite validação técnica independente do registro RFC 3161.

Após configurar, aplique as migrações e reinicie o Core:

```bash
sudo make production-migrate
sudo make production-up
curl -sS https://rubricasignature.com/signing/timestamp/config
```

O alvo `production-up` inclui os complementos de R2 e carimbo do tempo. Se os
comandos Compose forem executados manualmente, ambos os arquivos complementares
também precisam ser informados; sem `compose/features/serpro-timestamp.yml`, a
produção não monta os secrets do carimbo e o endpoint informa `enabled: false`.

O último comando deve retornar `{"enabled":true}`.
