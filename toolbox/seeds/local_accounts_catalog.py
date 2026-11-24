"""Development-only account catalog shared by the seed and local docs."""

# Administrators count toward the plan member limit.
PROFESSIONAL = (
    ("local.empresa.admin@example.local", "Administrador Profissional Local"),
    ("local.empresa.membro@example.local", "Membro Profissional Local 1"),
    ("local.profissional.membro2@example.local", "Membro Profissional Local 2"),
)
TEAM = (
    ("local.equipe.admin@example.local", "Administrador Equipe Local"),
    *((f"local.equipe.membro{i}@example.local", f"Membro Equipe Local {i}") for i in range(1, 6)),
)
LIFETIME = (
    ("local.vitalicio.admin@example.local", "Administrador Vitalício Local"),
    ("local.vitalicio.membro1@example.local", "Membro Vitalício Local 1"),
    ("local.vitalicio.membro2@example.local", "Membro Vitalício Local 2"),
)
ACCOUNTS = (
    ("local.pessoal@example.local", "Conta Gratuita Local"),
    ("local.essencial@example.local", "Conta Essencial Local"),
    *PROFESSIONAL,
    *TEAM,
    *LIFETIME,
)

# Journal entries preserve their order so synthetic identity numbers stay stable.
STAGING_SCENARIOS = (
    ("sem-workspace", "Conta antiga sem workspace"),
    ("ex-membro-sem-pessoal", "Desligado do último workspace, sem espaço pessoal"),
    ("suspenso-sem-pessoal", "Vínculo suspenso, sem espaço pessoal"),
    ("sem-assento-sem-pessoal", "Sem assento e sem espaço pessoal"),
    ("ex-membro-com-pessoal", "Desligado do empresarial, com PDF pessoal"),
    ("outra-empresa", "Desligado da empresa A, ativo na empresa B e no pessoal"),
    ("tres-workspaces", "Espaço pessoal e duas empresas ativas"),
    ("franquia-esgotada", "Franquia pessoal esgotada, empresa ativa"),
    ("arquivos-proprios", "Permissão de acervo: somente próprios"),
    ("arquivos-desde-entrada", "Permissão de acervo: desde a entrada"),
    ("arquivos-todos", "Permissão de acervo: todos"),
    ("assina-pela-empresa", "Assinatura restrita à empresa, com espaço pessoal"),
    ("readmitir-restaurar", "Desligado com histórico, para restaurar vínculo"),
    ("readmitir-novo", "Desligado com histórico, para readmitir sem histórico"),
    ("admin-sede", "Administrador da sede sem vínculo direto nas filiais"),
    ("gestor-filial", "Gestor com acesso somente à filial A"),
    ("auditor-filial", "Auditor com acesso somente à filial A"),
    ("membro-filial", "Membro com acesso somente à filial A"),
    ("admin-sucessor", "Membro ativo para promoção e sucessão na sede"),
    ("identidades", "Conta com CPF preferido e passaporte de outro país"),
    ("exportacao-aberta", "Administrador de workspace encerrado, exportação disponível"),
    ("exportacao-vencida", "Administrador de workspace encerrado, exportação vencida"),
    ("checkout", "Workspace pessoal descartável para pagamento de teste"),
    ("upgrade-empresa", "Workspace pessoal com PDF para upgrade empresarial"),
    ("virada-ciclo", "Membro com assento ativo para testar retirada na virada"),
    ("encerramento", "Administrador de workspace descartável para encerramento"),
)


def staging_email(key: str) -> str:
    return f"staging.cenario.{key}@example.local"


STAGING_ACCOUNTS = tuple((staging_email(key), name) for key, name in STAGING_SCENARIOS)
