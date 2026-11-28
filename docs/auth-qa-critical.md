# QA crítico de login, autenticação e sessões

A revisão usa o backend `851fb60` na linha de release e o frontend no checkout de QA, sem troca de branch. O contrato base está em [Arquitetura](ARCHITECTURE.md), [Segurança de borda](EDGE_SECURITY.md) e [Operação de produção](PRODUCTION_MVP_SETUP.md). O Auth é a autoridade sobre a identidade. O PostgreSQL guarda usuários, hashes bcrypt, papéis e links de conta. O Redis guarda sessões revogáveis, índices SHA-256 de tokens opacos e limites. O Core resolve a identidade pelo Auth e consulta a associação e o papel do workspace por operação. O frontend Angular usa rotas locais e API de mesma origem.

## Triagem inicial por cenário

P indica **Aplicável / prioritário**. S indica **Aplicável / secundário**. A indica **Adaptar**. C indica **Coberto**. N indica **Não aplicável**. B indica **Bloqueado**. As letras C, A e M na coluna de gravidade correspondem a crítica, alta e média. Custo baixo indica teste unitário ou integração existente. Custo médio indica preparação de duas identidades, manipulação controlada do relógio, duas conexões ou injeção local. Custo alto indica cadeia implantada ou navegador com provedor externo.

| ID | Triagem | Gravidade | Componente, hipótese, regra e exposição | Cobertura anterior e custo |
|---|---|---|---|---|
| LOG-01 | P | C | Login público com usuário ativo e senha inválida deve negar sem criar chaves de sessão. | Limite anterior usa banco simulado. Integração baixa. |
| LOG-02 | P | A | Login público com e-mail inexistente deve devolver a mesma resposta de credencial inválida. | Ausência coberta só por serviço. Integração baixa. |
| LOG-03 | P | A | O login para usuário inexistente pode pular bcrypt e revelar a existência de conta. | Sem amostra comparável. Integração média. |
| LOG-04 | P | C | Login usa `select(UserEntity)` com parâmetros. Entrada textual de formato inválido não deve autenticar nem mudar o banco. | Contrato de borda e SQLAlchemy. Integração baixa. |
| LOG-05 | P | A | Limites de `LoginRequest` precedem consulta pública e bcrypt. Campos inválidos não criam estado ou ecoam senha. | Schemas sem verificação dos efeitos. Integração baixa. |
| LOG-06 | S | M | A identidade normaliza maiúsculas. Conta existente deve manter o mesmo ID. | Cadastro cobre duplicidade. Integração baixa. |
| LOG-07 | S | M | A identidade remove espaços externos. Mesmo endereço deve apontar para o mesmo ID. | Cadastro cobre duplicidade. Integração baixa. |
| LOG-08 | P | A | E-mail semelhante em Unicode, mas distinto após normalização, pode apontar para usuário indevido. Testar variante sintética. | Sem teste equivalente no login. Integração baixa. |
| LOG-09 | P | C | Conta inativa deve permanecer sem acesso e sem nova sessão. | Verificação estática de `is_active`. Integração baixa. |
| LOG-10 | P | C | Exclusão lógica e física devem invalidar login e não recriar usuário nem sessão. | Login e leitura de sessão requerem revisão do filtro. Integração média. |
| LOG-11 | C | A | O limite de dez verificações em cinco minutos deve evitar bcrypt e consulta além do teto. | `test_login_attempts_are_limited_with_real_redis` observa consultas e Redis. Custo baixo. |
| LOG-12 | P | A | A mesma conta, de várias origens, deve compartilhar chave por e-mail normalizado. | Teste anterior usa uma origem. Integração baixa. |
| LOG-13 | B | A | Pulverização entre contas exige controle por IP na borda, conforme `EDGE_SECURITY.md`. | Configuração Cloudflare indisponível para validação. Custo alto. |
| LOG-14 | A | A | Auth usa IP para Turnstile e limite por e-mail. Testar invariância do limite para cabeçalhos variados. A confiança do IP exige revisão do proxy efetivo. | Turnstile testa envio do IP. Integração baixa e implantação alta. |
| LOG-15 | P | A | Falha Redis não deve liberar login ou consumir senha no banco. | Redis real disponível. Injeção média. |
| LOG-16 | P | A | Interrupção entre contador e TTL pode travar conta permanentemente. Verificar operação atômica e chave legada sem TTL. | Sem regressão em falha. Integração média. |
| LOG-17 | S | M | Após vencer a janela, deve voltar a autenticar. | Forçar vencimento em chave sintética. Custo baixo. |
| LOG-18 | P | A | Instâncias com Redis compartilhado precisam respeitar o mesmo teto em concorrência. | Teste atual usa uma instância. Integração média. |
| LOG-19 | A | C | Token opaco não transporta usuário. Alterar seus bytes deve falhar na tabela de sessão. | Rotação testa um índice antigo. Integração baixa. |
| LOG-20 | A | C | Permissão vem do Auth e do Core. Acrescentar campos de papel ao token opaco deve invalidá-lo. | MFA e papéis separados no teste atual. Integração baixa. |
| LOG-21 | A | C | Token opaco não escolhe tenant. Alterar a referência do workspace mantendo sessão válida deve ser negado pelo Core. | Teste anterior usa contexto sintético. Integração média. |
| LOG-22 | P | C | Chave de acesso expirada não deve autenticar com estado da sessão ainda existente. | Rotação testa exclusão, não TTL. Integração média. |
| LOG-23 | A | C | Tokens não são autossuficientes nem assinados. Valor desconhecido no formato válido deve falhar. | Lookup real testável. Custo baixo. |
| LOG-24 | N | C | Não há seleção de algoritmo. Token opaco é localizado por SHA-256 em Redis. | Revisão estática de `_new_token`, `_token_key` e `_state_for_token`. |
| LOG-25 | A | C | Chave de staging não deve existir no Redis isolado de produção. | Compose e duas partições Redis locais. Custo médio. |
| LOG-26 | A | C | Separação por finalidade via índices access/refresh e credenciais internas distintas. Usar refresh em endpoint protegido deve falhar. | Rotação não cruza tipos. Integração baixa. |
| LOG-27 | N | M | Token opaco não carrega `nbf` ou `iat`. Redis controla o vencimento. | Revisão estática e cobertura temporal LOG-22. |
| LOG-28 | C | C | Refresh consumido não pode criar nova sessão. Replay sequencial derruba a sessão rotacionada, conforme comportamento atual. | `test_refresh_rotation_replay_and_logout_with_real_redis` afirma invalidação. Custo baixo. |
| LOG-29 | P | A | Renovação concorrente deve produzir no máximo um sucessor e invalidar o acesso anterior. | Teste Redis existente. Incluir barreira antes da operação atômica. Custo médio. |
| LOG-30 | P | C | Logout deve invalidar access e refresh e impedir nova sessão com o refresh anterior. | O teste existente não chama logout apesar do nome. Integração baixa. |
| LOG-31 | P | C | Revogação efetiva após desativação. Access e refresh devem consultar usuário persistido. | Testes usam usuário simulado. Integração baixa. |
| LOG-32 | P | A | Redefinição válida incrementa versão e invalida todas as sessões anteriores. | `test_session_checks_password_token_version` cobre comparação. Integração baixa. |
| LOG-33 | N | M | Não existe chave de assinatura dos tokens de sessão. Chave de MFA cifra segredo TOTP e tem outro propósito. | Revisão estática da criação e busca de sessão. |
| LOG-34 | P | C | Cookie pré-login não deve fixar ID nem assumir sessão criada com credenciais válidas. | Testes de cookie simulam emissão. Integração baixa. |
| LOG-35 | P | C | Link consumido deve falhar na segunda redefinição. | Lock e `consumed_at` identificados. Integração baixa. |
| LOG-36 | P | C | Link no limite da validade deve falhar, sem consumo nem alteração de senha. | Consulta usa `expires_at > now`. Integração baixa. |
| LOG-37 | P | C | Dois resets para o mesmo token devem produzir uma única troca e incremento de versão. | `FOR UPDATE` identificado. Integração média. |
| LOG-38 | P | A | Novo link invalida anteriores. Emissões concorrentes devem respeitar esta regra implementada. | `_issue_token` atualiza links anteriores. Integração média. |
| LOG-39 | B | A | A proteção documentada depende de Turnstile e da regra Cloudflare em recuperação. Sem confirmação da quota por conta, testar apenas fluxo local e registrar lacuna. | Turnstile simulado. Custo de implantação alto. |
| LOG-40 | P | C | O reset deve usar o usuário vinculado ao token e preservar outra conta. | Schema e FK identificados. Integração baixa. |
| LOG-41 | P | C | Usuário removido com bearer ainda válido perde acesso àquele workspace. | `test_offboarding_revokes_seat_links_and_readmission_can_reset_history` cobre serviço. Integração média. |
| LOG-42 | P | C | Rebaixamento de papel vale na próxima operação com o mesmo bearer. | `test_admin_can_change_member_role_and_change_is_audited` cobre alteração. Integração média. |
| LOG-43 | P | C | Um administrador de A não administra B sem vínculo. | `test_member_cannot_manage_and_cross_tenant_access_is_denied` cobre papel em serviço. Integração média. |
| LOG-44 | A | A | Workspace é selecionado por rota/requisição, sem tenant global no token. Requisições concorrentes devem manter seus destinos. | Testar dois workspaces e efeitos no Core. Integração média. |
| LOG-45 | C | C | Origem diferente com cookie deve falhar em produção simulada. Bearer explícito continua autorizado. | `test_core_rejects_cross_origin_cookie_mutations` e refresh. Custo baixo. |
| LOG-46 | C | C | Cookies de produção precisam de Secure, HttpOnly, SameSite e escopo correto. | `test_browser_auth_responses_keep_refresh_token_in_httponly_cookie` parcial. Ampliar por inspeção HTTP. |
| LOG-47 | P | A | Login usa `returnUrl` filtrada e navegação Angular. Destinos externos não devem ser aceitos. | Sem spec específico do login. Teste frontend médio. |
| LOG-48 | P | C | Sem consulta de usuário válida no PostgreSQL, login não concede acesso nem cria sessão. | Injeção de falha na conexão real. Custo médio. |
| LOG-49 | P | A | Interrupção entre escritas de sessão pode deixar índices incompletos ou sessão órfã. | Verificar atomicidade no Redis e recuperação com nova instância. Custo médio. |
| LOG-50 | P | C | Respostas públicas de validação e logs não podem ecoar credenciais. Revisar gateway que recebe links com query. | Sem teste de validação sanitizada. Integração média, verificação implantada alta. |

## Resultados por ID

A coluna de evidência usa **I** para `tests/test_auth_qa_integration.py`, **S** para `tests/test_auth_session_security.py` e **T** para `tests/test_login_turnstile.py` e **F** para `rubrica-front/src/app/pages/login-page.component.spec.ts`. Os testes de I usam PostgreSQL 16 migrado, Redis em loopback e clientes ASGI. O transporte entre Core e Auth foi ligado aos clientes ASGI no teste. O fluxo Angular em F usa componentes e serviços simulados. Nada foi executado em servidores externos.

| ID | Pré-condição e invariantes checados | Observado, causa ou correção e evidência | Status final |
|---|---|---|---|
| LOG-01 | Usuário ativo, senha incorreta. | HTTP 401 genérico, sem sessão, hash e versão preservados. I `test_denied_login_preserves_identity_and_sessions[01]` (I:101). | APROVADO POR EVIDÊNCIA |
| LOG-02 | Identidade ausente. | HTTP 401 com o mesmo corpo de LOG-01 e sem sessão. I `test_denied_login_preserves_identity_and_sessions[02]` (I:101). Tempos em LOG-03. | APROVADO POR EVIDÊNCIA |
| LOG-03 | Cinco pares alternados, mesma senha inválida e Redis abaixo do teto. | A ausência de usuário pulava bcrypt. O caminho de ausência passou a executar a mesma operação com hash auxiliar. I `test_login_timing_exercises_bcrypt_for_known_and_unknown_identity` (I:131) afirma dez verificações e registra medianas locais. Sem inferência sobre toda a distribuição remota. | CORRIGIDO E REVALIDADO |
| LOG-04 | E-mail inexistente com aspas e pontuação literal. | HTTP 401 genérico, duas identidades e seus hashes preservados, sem sessão. Consulta SQLAlchemy parametrizada. I `test_denied_login_preserves_identity_and_sessions[04]` (I:101). | APROVADO POR EVIDÊNCIA |
| LOG-05 | E-mail ou senha com milhares de caracteres. | HTTP 422 já impedia consulta e bcrypt. A resposta devolvia o campo integral. O handler mantém localização, tipo e mensagem, e suprime valor/ctx. I `test_oversized_login_is_rejected_without_session_or_input_echo` (I:154) também confere Redis vazio. | CORRIGIDO E REVALIDADO |
| LOG-06 | E-mail sintético existente escrito em maiúsculas. | HTTP 200 e mesmo UUID no índice de sessão. I `test_normalized_login_maps_to_the_original_identity[uppercase]` (I:165). | APROVADO POR EVIDÊNCIA |
| LOG-07 | Espaços externos no mesmo e-mail. | HTTP 200 e mesmo UUID original. I `test_normalized_login_maps_to_the_original_identity[whitespace]` (I:165). | APROVADO POR EVIDÊNCIA |
| LOG-08 | Variante sintética com caractere visualmente semelhante em Unicode. | Mesmo com senha da conta original, HTTP 401, sem sessão nem mudança persistida. I `test_denied_login_preserves_identity_and_sessions[08]` (I:101). | APROVADO POR EVIDÊNCIA |
| LOG-09 | Conta desativada com senha correta. | HTTP 401 e nenhum estado de autenticação criado. I `test_denied_login_preserves_identity_and_sessions[09]` (I:101). | APROVADO POR EVIDÊNCIA |
| LOG-10 | Exclusão física e lógica com flag ativa preservada no segundo caso. | Exclusão lógica permitia login. O Auth passou a excluir registros apagados e verificar o estado da conta. Ambas as variantes negam acesso e preservam inventário e versão. I `test_denied_login_preserves_identity_and_sessions[10-*]` (I:101). | CORRIGIDO E REVALIDADO |
| LOG-11 | Onze requisições limitadas em Redis sintético. | Apenas dez chegaram ao verificador do banco. S `test_login_attempts_are_limited_with_real_redis` (S:173), em conjunto com o TTL de LOG-16. | COBERTO E REVALIDADO |
| LOG-12 | Mesmo e-mail, duas origens declaradas e capitalização variada, com contador pré-carregado. | Uma única chave atingiu 11. A tentativa acima do teto, mesmo com senha válida, foi negada. I `test_changing_origin_header_cannot_reset_account_limit` (I:174). | APROVADO POR EVIDÊNCIA |
| LOG-13 | Origem única, várias contas, implantação Cloudflare/Nginx. | O template web limita `/auth/` por IP e a regra Cloudflare é documentada. Nginx efetivo e Cloudflare não estão disponíveis nesta rodada. Falta verificar a regra ativa e um ensaio autorizado de baixo volume. | BLOQUEADO |
| LOG-14 | Headers de origem diferentes em Auth e confiança no proxy implantado. | I `test_changing_origin_header_cannot_reset_account_limit` (I:174) confirma que três headers não reiniciam o limite por e-mail. O template reescreve `X-Real-IP`, mas confia em faixas privadas amplas. Falta comprovar conexões permitidas ao proxy e o cabeçalho efetivo, sem simular tráfego no host compartilhado. | DEPENDENTE DE VALIDAÇÃO HUMANA |
| LOG-15 | Falha no Redis antes da consulta de usuário. | HTTP 500, a consulta ao PostgreSQL não foi invocada e nenhuma sessão foi gravada. Nova tentativa legítima funcionou ao remover a falha. I `test_redis_failure_does_not_fall_back_to_unlimited_login` (I:184). | APROVADO POR EVIDÊNCIA |
| LOG-16 | Chave de contador sem TTL representa interrupção antiga. | O contador excedido podia permanecer permanente. Incremento e TTL são atômicos e chaves antigas sem TTL ganham prazo. I `test_rate_limit_has_a_deadline_after_legacy_interrupted_increment` (I:199). Terceiros ainda podem refazer o bloqueio temporário conforme política atual. | CORRIGIDO E REVALIDADO |
| LOG-17 | Conta bloqueada por limite temporário. | Ao expirar a chave real no Redis, login válido volta a funcionar e remove o contador. I `test_login_recovers_after_window_expires` (I:206). | APROVADO POR EVIDÊNCIA |
| LOG-18 | Duas instâncias disputam a última tentativa num Redis compartilhado. | Uma sessão criada e uma tentativa negada após barreira de sincronização. I `test_two_login_instances_share_the_rate_limit` (I:215). | APROVADO POR EVIDÊNCIA |
| LOG-19 | Sessão válida e bytes do token alterados com o UUID de outra conta. | HTTP 401 para o valor alterado e 200 para o token original. I `test_altered_or_wrong_purpose_token_cannot_authenticate[subject]` (I:234). | APROVADO POR EVIDÊNCIA |
| LOG-20 | Token opaco alterado com texto de papel administrativo. | HTTP 401, sem contexto administrativo. Token original segue válido. I `test_altered_or_wrong_purpose_token_cannot_authenticate[permissions]` (I:234). | APROVADO POR EVIDÊNCIA |
| LOG-21 | Credencial válida de A e referência do workspace B. | HTTP 403 em ambos os sentidos, com controle positivo HTTP 200 do proprietário. I `test_valid_session_cannot_select_another_workspace` (I:592). | APROVADO POR EVIDÊNCIA |
| LOG-22 | Access index expirado, sessão e refresh ainda vivos. | HTTP 401 para o access expirado, estado principal ainda existe e refresh legítimo funciona. I `test_expired_access_index_cannot_use_live_session_state` (I:246). | APROVADO POR EVIDÊNCIA |
| LOG-23 | Valor desconhecido estruturalmente semelhante a um token de acesso. | HTTP 401 mesmo com formato válido. I `test_altered_or_wrong_purpose_token_cannot_authenticate[unknown]` (I:234). | APROVADO POR EVIDÊNCIA |
| LOG-24 | Opção de algoritmo de assinatura. | Inexistente em tokens opacos. `session_service.py` consulta chave SHA-256 do token sem ler claims. LOG-19 e LOG-23 cobrem a garantia equivalente. | NÃO APLICÁVEL |
| LOG-25 | Mesmo namespace de sessão em duas bases Redis no servidor de teste. | Access e refresh de uma base foram negados na segunda e a origem continuou autenticada. I `test_environment_storage_separates_staging_and_simulated_production` (I:256). Isolamento real depende da configuração de cada implantação. | APROVADO POR EVIDÊNCIA |
| LOG-26 | Refresh legítimo entregue como bearer em endpoint de acesso. | HTTP 401 enquanto access legítimo funciona. I `test_altered_or_wrong_purpose_token_cannot_authenticate[refresh]` (I:234). Tokens internos usam contrato separado em `contracts/auth-core/README.md`. | APROVADO POR EVIDÊNCIA |
| LOG-27 | Claims temporais do token. | Não há `nbf` ou `iat` no token opaco. A validade está no TTL Redis e foi exercitada em LOG-22. | NÃO APLICÁVEL |
| LOG-28 | Refresh legítimo utilizado, depois repetido. | Access velho falha. Replay falha e revoga o sucessor conforme o comportamento existente. S `test_refresh_rotation_replay_and_logout_with_real_redis` (S:204). | COBERTO E REVALIDADO |
| LOG-29 | Duas renovações chegaram ao script de troca antes de executar. | Um vencedor, mesmo ID de sessão, índice único, access antigo rejeitado. I `test_parallel_refresh_issues_at_most_one_new_session_pair` (I:269). A ordenação dos cookies em abas reais continua para E2E. | APROVADO POR EVIDÊNCIA |
| LOG-30 | Logout de sessão existente, com `Bearer` e `bearer`. | O formato em minúsculas passava pela autenticação e recebia 200 sem revogar. O extrator passou a tratar o esquema sem distinção de caixa. Ambas as variantes removem access, refresh e associação. I `test_logout_revokes_access_and_refresh_with_either_bearer_case` (I:290). | CORRIGIDO E REVALIDADO |
| LOG-31 | Sessão existente antes de desativar, apagar logicamente ou retirar a verificação. | Desativação já negava. Exclusão lógica e perda de verificação permitiam continuar. A elegibilidade passou a ser verificada no login, challenge MFA e uso/renovação. I `test_session_resolves_current_account_lifecycle` (I:299). | CORRIGIDO E REVALIDADO |
| LOG-32 | Duas sessões da conta e uma de controle em outra conta. | Reset válido invalida access e refresh das duas primeiras, preserva controle, aceita a senha nova e nega a antiga. I `test_password_reset_revokes_two_prior_sessions_and_leaves_other_user_active` (I:313) e S `test_session_checks_password_token_version` (S:56). | APROVADO POR EVIDÊNCIA |
| LOG-33 | Rotação do segredo de assinatura de sessão. | Não existe segredo de assinatura da sessão opaca. A chave de MFA tem outro escopo. LOG-25 e LOG-30 testam separação e revogação do mecanismo existente. | NÃO APLICÁVEL |
| LOG-34 | Cookie de outra identidade já presente ao autenticar. | Login cria ID de sessão novo associado somente ao titular das credenciais. A antiga sessão continua vinculada ao seu próprio titular. I `test_authentication_does_not_adopt_a_prelogin_cookie` (I:326). | APROVADO POR EVIDÊNCIA |
| LOG-35 | Link reset consumido e reapresentado. | Primeiro pedido muda uma vez a versão e consome o token. Segundo responde 422. I `test_consumed_recovery_link_cannot_be_used_twice` (I:336). | APROVADO POR EVIDÊNCIA |
| LOG-36 | Link de recuperação vencido em PostgreSQL. | HTTP 422, sem alteração de hash, versão ou consumo. I `test_expired_recovery_link_does_not_change_password_or_consume_link` (I:346). | APROVADO POR EVIDÊNCIA |
| LOG-37 | Duas transações tentam o mesmo link em paralelo. | Uma operação efetiva, versão incrementada uma vez e token consumido. I `test_two_password_resets_with_one_token_update_once` (I:356). | APROVADO POR EVIDÊNCIA |
| LOG-38 | Duas emissões concorrentes para a mesma conta. | Ambas deixavam links válidos quando partiam sem link anterior. Emissão e consumo agora serializam pelo usuário, na mesma ordem de locks. I `test_concurrent_recovery_issuance_leaves_only_one_unused_token` (I:376) limita a um link utilizável. Envio externo de e-mail foi simulado. | CORRIGIDO E REVALIDADO |
| LOG-39 | Origem e destinatários sintéticos, proteções implantadas. | Turnstile e caminho por IP constam na configuração e `test_turnstile_accepts_the_expected_account_action` (T:55) valida a ação simulada. Não há limite próprio por destinatário no trecho de recuperação. Falta comprovar controle externo e decidir se por destinatário é requisito. | BLOQUEADO |
| LOG-40 | Token do usuário A acompanhado de identidade de B no corpo. | Apenas A muda de versão. Hash e versão de B preservados. I `test_recovery_request_cannot_override_token_owner` (I:411). | APROVADO POR EVIDÊNCIA |
| LOG-41 | Sessão ainda válida depois de registrar desligamento no workspace. | Leitura antes 200, depois 403 no tenant. O token segue válido para acessar a lista de workspaces. I `test_same_session_loses_workspace_access_after_offboarding` (I:570). | APROVADO POR EVIDÊNCIA |
| LOG-42 | Sessão de administrador, associação rebaixada para membro no banco. | Rota administrativa passa a retornar 403 sem exigir novo login. Leitura geral segue disponível. I `test_same_session_loses_admin_permission_after_role_change` (I:581). | APROVADO POR EVIDÊNCIA |
| LOG-43 | Dois administradores de workspaces sem associação cruzada. | Próprio endpoint 200 e endpoint alheio 403 dos dois lados. I `test_valid_session_cannot_select_another_workspace` (I:592). O mesmo teste sustenta LOG-21 por equivalência da arquitetura. | APROVADO POR EVIDÊNCIA |
| LOG-44 | Uma identidade administra dois workspaces, com plano compatível para múltiplos assentos e duas operações simultâneas. | Alterações com o mesmo bearer preservam o destino de cada URL. Cada locale ficou apenas no workspace esperado. I `test_parallel_workspace_writes_keep_destinations_separate` (I:601). Integração da garantia do backend. O seletor visual em abas reais ainda exige E2E. | APROVADO POR EVIDÊNCIA |
| LOG-45 | Cookie válido e dois cabeçalhos Origin. | Origem externa recebe 403 e deixa a sessão intacta. Mesma origem revoga. S `test_core_rejects_cross_origin_cookie_mutations` (S:154) revalida o Core e o controle positivo com bearer. I `test_cross_origin_cookie_request_cannot_revoke_a_valid_session` (I:437). | COBERTO E REVALIDADO |
| LOG-46 | Login em modo produção simulado. | Cookies host-only, Path=/, Secure, HttpOnly, SameSite=Lax. O refresh não é parte do JSON. I `test_production_cookie_scope_and_flags` (I:421) e S `test_browser_auth_responses_keep_refresh_token_in_httponly_cookie` (S:23). O exemplo de staging usa modo staging e o código só aciona Secure em produção. Validar navegador e política de staging antes de usar credenciais de teste sensíveis. | COBERTO E REVALIDADO |
| LOG-47 | Retornos externos absolutos, relativos ao protocolo, esquema não HTTP, barras invertidas e caminho legítimo. | Teste Angular direcionou os quatro casos externos ao dashboard e preservou o link legítimo. F `login return destination` (F:9). Sem navegador real. | APROVADO POR EVIDÊNCIA |
| LOG-48 | Falha injetada no estabelecimento da conexão ao PostgreSQL. | HTTP 500, sem índice de access ou sessão. Login legítimo recupera ao remover a falha. I `test_postgres_connection_failure_does_not_issue_session` (I:448). | APROVADO POR EVIDÊNCIA |
| LOG-49 | Interrupção simulada entre escritas ou antes de EXEC. | Escritas separadas deixavam sessão órfã. Uma transação Redis garante que, antes de EXEC, nenhum estado parcial fique visível. A instância recriada autentica normalmente. I `test_interrupted_session_write_leaves_no_partial_indexes` (I:464). Não foi simulado failover ou perda de persistência Redis. | CORRIGIDO E REVALIDADO |
| LOG-50 | Erros em login, reset, MFA e refresh, além dos logs no caminho dos links. | A API ecoava segredos em 422. O ajuste local passou em I `test_auth_validation_does_not_echo_secrets_or_log_request_bodies` (I:499). Em staging, os dois proxies registraram os marcadores fictícios da query e do Referer. A confirmação abrange os logs de origem de staging. | VULNERABILIDADE ENCONTRADA |

## Casos adicionais

- **LOG-51 · Alta · Corrigido e revalidado.** bcrypt 4.3 truncava silenciosamente uma nova senha acima de 72 bytes UTF-8. Regressão `test_new_password_beyond_bcrypt_byte_limit_is_rejected_before_consuming_token` (I:511) confirma HTTP 422 sem consumo do token nem incremento da versão, depois sucesso para senha válida. O limite de bytes é aplicado aos fluxos de entrada que criam ou redefinem senha. Senhas já armazenadas continuam usando a verificação legada. Avaliar qualquer migração ou invalidação de senha existente como decisão separada.
- **LOG-52 · Alta · Dependente de validação humana.** Um refresh que chegue depois da rotação é tratado como replay e revoga a sessão. A regra foi preservada. Duas abas reais com o mesmo cookie podem sofrer logout quando uma requisição atrasar e o browser aplicar a limpeza de cookies. O ensaio mínimo usa abas locais, resposta atrasada e verificações de cookies e de continuação da sessão. Se reproduzir, decidir se a solução fica na coordenação de abas ou no contrato de replay.

## Ameaças residuais e aprovação humana

1. **Crítica, LOG-50.** `account_service.py:177` e `:220` geram links de reset e ativação com token na query. A coleta em staging confirmou que o gateway e o web registram a query e o Referer. O formato combined padrão do Nginx inclui ambos. O ensaio usou apenas marcadores fictícios. A exposição em produção, os destinos de coleta e os logs históricos continuam sem verificação. [Formato de log do Nginx](https://nginx.org/en/docs/http/ngx_http_log_module.html)
2. **Alta, LOG-13/14/39.** Confirmar topologia do túnel, origens confiáveis, reescrita de cabeçalhos e resposta 429 com origem controlada. Confirmar controle de recuperação por destinatário e tratamento de falha do provedor de e-mail. A ficha local não prova regras efetivas do Cloudflare ou do Nginx implantado.
3. **Alta, LOG-25/29/44/46/52.** Conferir separação de Redis dos projetos e cookies reais no navegador. Exercitar duas abas para renovar e trocar de workspace. A prova backend registra o destino por requisição e preserva a política de replay.
4. **Alta, LOG-03/51.** Medida local pequena não elimina diferenças de latência entre redes e hashes legados. Revisar necessidade de política de senhas antigas e verificar que a interface comunica o teto em bytes antes da homologação.

### O que precisa do responsável pelo Rúbrica

| Quando | ID | Autorização ou decisão necessária | Trabalho que o QA pode adiantar |
|---|---|---|---|
| Antes da homologação | LOG-50 | Atualizar os dois proxies de staging e enviar as contagens da coleta pós-correção. O ensaio inicial confirmou o problema. | A sanitização está nos templates de origem. O deploy de produção e qualquer ação sobre logs históricos ficam para uma decisão separada. |
| Na mesma janela de staging | LOG-13/14/39 | Conferência autorizada em 28/11/2026. Falta evidência da regra ativa da zona, com origem de contagem, rotas, janela, limite e ação. | Usar a evidência do painel e um ensaio de baixo volume com contas sintéticas depois de obter acesso autenticado. |
| Se a validação reproduzir um problema | LOG-39/52 | Decidir um limite por destinatário ou uma mudança na política de replay somente se os controles atuais se mostrarem insuficientes e a correção exigir mudança de regra. | Testar a concorrência em navegador local assim que houver um executor disponível. |
| Se houver proposta de migração | LOG-51 | Aprovar a política para senhas antigas caso a migração exija redefinição ou invalidação de credenciais. | Preservar a compatibilidade atual e validar o limite de novas senhas. |

Ao encontrar um item que depende do responsável, comunicar no chat e registrar no roteiro o ID, o risco, a autorização ou decisão exata e o próximo passo mínimo. A aprovação final da release continua humana.

### Ensaio remoto de staging em 28/11/2026

Às 15:42:51 UTC, três GETs HTTPS sem sessão consultaram `/reset-password`, `/verify-email` e `/auth/turnstile/config`, com um marcador fictício na query. As três respostas foram HTTP 302 para o Cloudflare Access, com os identificadores de requisição `a61a7c23988df191-GRU`, `a61a7c245e7c1ba8-GRU` e `a61a7c253a3eb23d-GRU`. O cliente preservou a validação TLS e parou no redirecionamento. Isso confirma a barreira pública de acesso. Ainda falta evidência de que as rotas chegam aos proxies, de como a query é registrada e das regras de limite. O alias `oracle` não está configurado neste container, e o painel Cloudflare não está conectado à sessão de QA.

#### Coleta de contagens no servidor de staging

No shell do servidor, o bloco abaixo faz dois GETs dentro do gateway do projeto `rubrica-staging` e imprime somente status e contagens. `query` e `referer` são marcadores fictícios. `trace` é um ID de requisição fictício usado como controle positivo. Com o formato corrigido, espere dois HTTP 200 e `query=0 referer=0 trace=2` em cada proxy. Um status diferente, falha ao consultar logs ou controle positivo incompleto invalida a comparação.

```bash
(
  set -euo pipefail
  qa_marker="rubrica-qa-log50-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  qa_since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  for qa_route in reset-password verify-email; do
    printf '/%s ' "$qa_route"
    docker exec rubrica-staging-gateway-1 wget -S -O /dev/null \
      --header='Host: staging.rubricasignature.com' \
      --header="Referer: https://staging.rubricasignature.com/qa?r=${qa_marker}-referer" \
      --header="X-Request-ID: ${qa_marker}-trace" \
      "http://127.0.0.1:8080/${qa_route}?token=${qa_marker}-query" 2>&1 |
      awk '/HTTP\// { print $1, $2 }'
  done
  for qa_container in rubrica-staging-gateway-1 rubrica-staging-web-1; do
    docker logs --since "$qa_since" "$qa_container" 2>&1 |
      awk -v name="$qa_container" -v fake="$qa_marker" '
        index($0, fake "-query") { query++ }
        index($0, fake "-referer") { referer++ }
        index($0, "request_id=" fake "-trace") { trace++ }
        END { printf "%s query=%d referer=%d trace=%d\n", name, query, referer, trace }
      '
  done
)
```

O teste interno confirma apenas os logs de origem. Para a borda, registrar a regra ativa no painel Cloudflare e confirmar em requisições autorizadas que o controle específico por IP e por rota é aplicado. Um 302 antes do login Cloudflare Access não demonstra limite por IP ou proteção contra disparos excessivos de e-mail.

### Resultado do coletor no servidor de staging

O operador confirmou que `make staging-smoke` passou e retornou estas contagens, sem compartilhar linhas dos logs.

```text
/reset-password HTTP/1.1 200
/verify-email HTTP/1.1 200
rubrica-staging-gateway-1 query=2 referer=2
rubrica-staging-web-1 query=2 referer=2
```

Cada proxy registrou os dois marcadores de URL e os dois de Referer. **LOG-50 continua bloqueando a homologação.** O template `infra/gateway/nginx.staging.conf` é montado pelo Compose de staging. O web usa `rubrica-front/nginx.conf` pelo `Dockerfile.prod` e o mesmo template atende a configuração do web de produção no repositório.

Os templates `infra/gateway/nginx.staging.conf`, `infra/gateway/nginx.conf` e `rubrica-front/nginx.conf` passam a usar um formato de access log com método, rota sanitizada, status e ID da requisição. A query e o Referer saem do formato, e o caminho de assinatura fica mascarado. A correção ainda precisa da revalidação em staging com `query=0 referer=0 trace=2` nos dois proxies. Ela cobre os access logs futuros. Logs de erro, agregadores, arquivos históricos e a regra de limite no Cloudflare exigem verificação própria.

O Nginx 1.30.4 descartável passou no `nginx -t` e no teste HTTP local encadeado do gateway ao web. Com a configuração anterior, as três variantes registraram os marcadores de query, Referer e assinatura. Com a correção, cada gateway retornou quatro HTTP 200 e registrou quatro IDs de requisição, e o web registrou os oito. Nenhum marcador protegido entrou nos access logs. Foram exercitadas recuperação, ativação, uma rota de assinatura e a configuração Turnstile. Os templates foram executados em loopback, com upstream e página SPA fictícios. [Nginx 1.30.4](https://nginx.org/download/)

No servidor de staging, validar os contêineres temporários com `nginx -t`, recriar o web com a imagem atualizada e recriar explicitamente o gateway para aplicar o arquivo montado do checkout novo. Depois testar `make staging-smoke` e executar o coletor. O check do gateway que já está rodando pode ler a configuração do mount anterior.

## Execução e resultados das suítes

- Backend `851fb60`, no checkout de QA, e frontend `5f93e50` no respectivo checkout. Ambos estavam limpos no início. A linha de base foi **548 aprovados no backend** e **86 aprovados no frontend**, com duas advertências preexistentes de bibliotecas no backend.
- O runner local descartável usou PostgreSQL 16, migrações dos cinco bancos e Redis em loopback, com duas identidades e dois workspaces sintéticos nos cenários de isolamento. O equivalente no ambiente de desenvolvimento de projeto é `make test-integration`, com os serviços de teste já preparados. Nesta sessão, o comando isolado foi `env -i PATH="$PATH" HOME=/home/ubuntu LANG=C.UTF-8 bash /tmp/rubrica-stripe-validation.sh --tb=short -o junit_family=xunit1`. O nome do runner temporário é histórico.
- Primeira rodada de regressão com `tests/test_auth_qa_integration.py --tb=short`. **34 aprovados e 16 falhas** antes dos ajustes. Uma das falhas era preparação inválida do caso de múltiplos workspaces, inicialmente sem campos obrigatórios e posteriormente sem assentos suficientes. As outras 15 reproduziram defeitos em oito grupos. O oráculo continuou sendo as duas escritas válidas em destinos independentes.
- LOG-03 teve medianas de **193,7 ms** para identidade existente e **2,7 ms** para inexistente antes do ajuste. Após a correção, as medianas foram **193,2 ms** e **193,3 ms**, respectivamente. São cinco pares de requisições em loopback por execução. A regressão afirma a execução de bcrypt para cada tentativa, sem depender de limiar de latência flutuante.
- Backend final com **599 aprovados**, zero falhas e zero pulados. São 51 instâncias novas de integração, incluindo parametrizações. Ruff e `git diff --check` passaram. `make test-integration` passou a incluir o módulo novo no mesmo alvo que a CI usa. O alvo Docker em si não foi executado nesta sessão.
- Frontend final com `npm run lint` e `npm test -- --watch=false`. **91 aprovados**, cinco variantes novas de retorno de login. Nenhum deploy ou teste em navegador externo.
- Não havia Chrome, Chromium ou WebKit do Playwright disponíveis no ambiente. A validação local do frontend foi feita no executor Angular/Vitest.

## Totais e arquivos

- **Triagem dos 50 originais.** 30 prioritários, 3 secundários, 8 adaptados, 4 cobertos, 3 não aplicáveis, 0 adiados e 2 bloqueados.
- **Status dos 50 originais.** 31 aprovados por evidência, 8 corrigidos e revalidados, 4 cobertos e revalidados, 3 não aplicáveis, 2 bloqueados, 1 dependente de validação humana e 1 vulnerabilidade encontrada de configuração. LOG-51 e LOG-52 são adicionais.
- **Implementação.** `apps/auth_api/src/auth_api/bootstrap/app.py`, `infrastructure/security.py`, `modules/accounts/account_schema.py`, `modules/accounts/account_service.py`, `modules/sessions/session_service.py`, `modules/users/passwords.py` e `modules/users/user_schema.py`, todos a partir de `apps/auth_api/src/auth_api`.
- **Regressões.** `tests/test_auth_qa_integration.py`, `tests/test_auth_session_security.py`, `makefile` e `rubrica-front/src/app/pages/login-page.component.spec.ts`.
- **Relatório.** `docs/auth-qa-critical.md` e referência no plano crítico. As duas árvores permanecem locais, sem commit, push ou deploy.

O Redis executa os comandos de sessão juntos após EXEC. O teste injeta a falha antes de EXEC e verifica o estado real, sem afirmar recuperação para falhas de armazenamento ou de persistência posteriores. [Transações Redis](https://redis.io/docs/latest/develop/using-commands/transactions/)
