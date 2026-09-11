# Fluxo de conta, tenant, franquia e cobrança do MVP

## Regra comercial

- Todo cadastro público cria uma conta proprietária e um tenant próprio.
- O proprietário recebe o papel global `signature_admin` e vira membro `admin` do tenant.
- Usuários convidados ou criados pelo administrador continuam sendo signatários por padrão; eles não recebem outro tenant automaticamente.
- Documentos, solicitações, membros e billing pertencem ao tenant.
- Cada tenant recebe cinco assinaturas concluídas gratuitamente. A franquia não é multiplicada pela quantidade de usuários.
- A sexta assinatura exige uma assinatura Stripe ativa.
- O Checkout concluído deixa a conta como `pending`; somente webhook `customer.subscription.*` com status `active` ou `trialing` libera uso ilimitado.
- O período contratado é mensal, mas o vencimento oficial sempre vem do `current_period_end` do Stripe; o Rubrica não soma 30 dias manualmente.
- Pagamentos e falhas são registrados no ledger `billing_payments`, com valores em unidade monetária mínima, moeda, período e data de pagamento.
- Uma falha inicia tolerância padrão de 10 dias. Durante a tolerância o tenant continua usando o serviço; depois dela, novas assinaturas são bloqueadas enquanto o pagamento não for regularizado.
- Um pagamento confirmado restaura o estado `active` e encerra a tolerância.
- Quando o Stripe informar `unpaid` ou `canceled`, o acesso ilimitado é bloqueado imediatamente; não é aberta uma segunda tolerância local.

## Provisionamento

O Auth cria o usuário e chama `POST /internal/tenants/provision` no Core usando uma chave de serviço exclusiva. O endpoint é idempotente pelo e-mail normalizado do proprietário, cria o tenant, a associação administrativa e a `billing_account` com limite cinco.

A moeda inicial deriva apenas do país informado (`BRL` para BR, `JPY` para JP e `USD` como fallback), nunca do idioma escolhido. Ela continua editável nas preferências do tenant.

Em produção, `core_internal_service_key` deve ser um segredo aleatório independente e estar disponível para Auth e Core.

## E-mails transacionais

- Auth solicita confirmação de e-mail e recuperação de senha ao Notification/Resend.
- Falhas HTTP do Notification agora são propagadas como indisponibilidade (`503`) e registradas sem expor token ou resposta sensível.
- Core envia mensagens de cobrança aos administradores do tenant para Checkout recebido, assinatura ativa/cancelada e pagamento confirmado/falho.
- Mensagens possuem conteúdo inicial em `pt-BR`, `en` e `ja-JP`, escolhido pelo locale do tenant.
- A chave de idempotência usa o ID do evento Stripe e um hash do destinatário.
- O webhook só termina como processado depois que o Notification aceita os e-mails. Falhas deixam o evento como `failed`, permitindo nova tentativa do mesmo evento.

## Eventos Stripe obrigatórios

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_succeeded`
- `invoice.payment_failed`

## Consulta administrativa

- `GET /billing/tenants/{tenant_id}/account` informa status, vencimento do período, fim da tolerância e consumo da franquia.
- `GET /billing/tenants/{tenant_id}/payments` lista o histórico financeiro do tenant para administradores e auditores.
- Valores são inteiros na menor unidade da moeda: centavos para BRL/USD e unidade inteira para JPY.

## Validação restante para produção

1. Configurar domínio e remetente verificados no Resend.
2. Criar os três preços Stripe e cadastrar os IDs BRL, USD e JPY.
3. Configurar o webhook Stripe com todos os eventos acima.
   No Stripe, configurar Revenue Recovery para tentar cobranças por 10 dias e cancelar a assinatura quando todas as tentativas falharem.
4. Executar cadastro real, confirmação de e-mail e recuperação de senha.
5. Confirmar que o cadastro criou exatamente um tenant e uma billing account com `0/5` usos.
6. Concluir cinco assinaturas e confirmar bloqueio da sexta.
7. Fazer Checkout em modo de teste, receber o webhook ativo e confirmar uso ilimitado.
8. Simular pagamento falho/cancelamento e confirmar estado da conta e e-mails aos administradores.

O MVP somente deve ser declarado validado em produção após esse smoke test com credenciais reais; testes automatizados não comprovam entrega externa do Resend nem recebimento público do Stripe.
