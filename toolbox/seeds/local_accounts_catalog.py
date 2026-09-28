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
