"""Generate a local-only login reference; never publish this directory."""
import html
import os
from pathlib import Path
from shutil import copyfile

from toolbox.seeds.local_accounts_catalog import ACCOUNTS, LIFETIME, PROFESSIONAL, TEAM


def main() -> None:
    environment = os.getenv("ENVIRONMENT", "development").lower()
    if environment not in {"local", "development", "staging"}:
        raise RuntimeError("Account documentation is exclusive to development and staging")
    environment_label = "STAGING" if environment == "staging" else "AMBIENTE LOCAL"
    account_title = "Contas de staging" if environment == "staging" else "Contas de desenvolvimento"
    raw_password = os.getenv("LOCAL_TEST_ACCOUNT_PASSWORD", "RubricaLocal123!")
    password = html.escape(raw_password)
    lines = [
        '<section class="accounts-hero">',
        f'<span class="eyebrow">{environment_label}</span>',
        f"# {account_title}",
        "<p>Copie uma conta completa e cole no primeiro campo do login do Rubrica.</p>",
        f'<div class="summary"><strong>5 tenants</strong><span>14 contas</span><code>{password}</code></div>',
        "</section>",
        '<p class="local-note">Contas confirmadas pelo seed, sem Microsoft Authenticator. '
        "No login, cole no campo de e-mail: o Rubrica separa e-mail e senha automaticamente.</p>",
        '<section class="plan-card seed-commands"><h2>Preparar contas de teste</h2>',
        '<p>Na primeira preparação do desenvolvimento, crie a configuração, aplique migrations, '
        'execute o seed e inicie o Rubrica:</p>',
        '<div class="seed-command"><code>make dev-bootstrap</code><button type="button" '
        'data-copy-command="make dev-bootstrap">Copiar comando</button></div>',
        '<p>Para reaplicar apenas as mesmas fixtures no banco de desenvolvimento:</p>',
        '<div class="seed-command"><code>make dev-seed</code><button type="button" '
        'data-copy-command="make dev-seed">Copiar comando</button></div>',
        '<p>O bootstrap de staging aplica migrations, executa o mesmo catálogo no banco isolado e '
        'sobe a stack completa. O seed nunca é habilitado em produção.</p>',
        '<div class="seed-command"><code>make staging-bootstrap</code><button type="button" '
        'data-copy-command="make staging-bootstrap">Copiar comando</button></div>',
        '<div class="seed-command"><code>make staging-seed</code><button type="button" '
        'data-copy-command="make staging-seed">Copiar comando</button></div>',
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
