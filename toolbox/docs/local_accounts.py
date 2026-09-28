"""Generate a local-only login reference; never publish this directory."""
import html
import os
from pathlib import Path
from shutil import copyfile

from toolbox.seeds.local_accounts_catalog import ACCOUNTS, LIFETIME, PROFESSIONAL, TEAM


def main() -> None:
    if os.getenv("ENVIRONMENT", "development").lower() not in {"local", "development"}:
        raise RuntimeError("Account documentation is exclusive to local development")
    raw_password = os.getenv("LOCAL_TEST_ACCOUNT_PASSWORD", "RubricaLocal123!")
    password = html.escape(raw_password)
    lines = [
        '<section class="accounts-hero">',
        '<span class="eyebrow">AMBIENTE LOCAL</span>',
        "# Contas de desenvolvimento",
        "<p>Copie uma conta completa e cole no primeiro campo do login do Rubrica.</p>",
        f'<div class="summary"><strong>5 tenants</strong><span>14 contas</span><code>{password}</code></div>',
        "</section>",
        '<p class="local-note">Contas confirmadas pelo seed, sem Microsoft Authenticator. '
        "No login, cole no campo de e-mail: o Rubrica separa e-mail e senha automaticamente.</p>",
        '<section class="plan-card seed-commands"><h2>Recriar o ambiente local</h2>',
        '<p>Para apagar os bancos locais, reaplicar todas as migrações, executar o seed e subir o Rubrica novamente:</p>',
        '<div class="seed-command"><code>make local-reset</code><button type="button" '
        'data-copy-command="make local-reset">Copiar comando</button></div>',
        '<p><strong>Esse comando apaga todos os dados dos volumes locais.</strong> Ele é bloqueado quando '
        '<code>environment=production</code>.</p>',
        '<p>Para apenas reaplicar o seed sem apagar os cenários existentes:</p>',
        '<div class="seed-command"><code>make seed-local-users</code><button type="button" '
        'data-copy-command="make seed-local-users">Copiar comando</button></div>',
        '</section>',
    ]
    for title, accounts in (("Gratuito — 1 conta", ACCOUNTS[:1]),
                            ("Essencial — 1 conta", ACCOUNTS[1:2]),
                            ("Profissional — 3 contas", PROFESSIONAL),
                            ("Equipe — 6 contas", TEAM),
                            ("Vitalício — 3 contas", LIFETIME)):
        lines += ["", f'<section class="plan-card"><h2>{title}</h2>', '<div class="account-list">']
        for index, (email, _) in enumerate(accounts):
            escaped_email = html.escape(email, quote=True)
            role = "Administrador" if index == 0 else "Membro"
            lines.append(
                '<article class="account-row">'
                f'<div class="account-identity"><strong>{escaped_email}</strong><span>{role}</span></div>'
                '<div class="account-actions">'
                f'<button type="button" class="copy-credentials" data-email="{escaped_email}" '
                f'data-password="{html.escape(raw_password, quote=True)}">Copiar conta</button>'
                "</div></article>"
            )
        lines += ["</div></section>"]
    target = Path(".artifacts/local-docs")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    assets = target / "assets"
    assets.mkdir(exist_ok=True, mode=0o700)
    source_assets = Path("toolbox/docs/assets")
    copyfile(source_assets / "local_accounts.css", assets / "local_accounts.css")
    copyfile(source_assets / "local_accounts.js", assets / "local_accounts.js")
    copyfile(
        Path("../rubrica-web/public/icons/rubrica-brand/source/rubrica-lockup-primary.png"),
        assets / "rubrica-logo.png",
    )
    copyfile(
        Path("../rubrica-web/public/icons/rubrica-brand/mark/48x48/rubrica-mark-primary-48x48.png"),
        assets / "rubrica-favicon.png",
    )
    page = target / "index.md"
    page.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    page.chmod(0o600)


if __name__ == "__main__":
    main()
