"""Generate a local-only login reference; never publish this directory."""
import html
import os
from pathlib import Path
from shutil import copyfile

from toolbox.seeds.local_accounts_catalog import ACCOUNTS, LIFETIME, PROFESSIONAL, STAGING_ACCOUNTS, TEAM
from toolbox.seeds.scenario_pdf import scenario_pdf


DOCUMENT_ROUTES = {
    "staging-commands.md": "staging-commands.md",
    "ARCHITECTURE.md": "architecture.md",
    "PRODUCTION_MVP_SETUP.md": "production.md",
    "SERPRO_TIMESTAMP_SETUP.md": "serpro-timestamp.md",
    "SERPROID_SETUP.md": "serpro-id.md",
    "CLOUDFLARE_R2.md": "cloudflare-r2.md",
    "EDGE_SECURITY.md": "edge-security.md",
    "OBSERVABILITY.md": "observability.md",
    "OFFSITE_BACKUP_B2.md": "offsite-backup.md",
    "CONTACT_AND_SEARCH_SETUP.md": "contact-and-search.md",
    "ECNPJ_PDF_SIGNING.md": "ecnpj-signing.md",
    "MVP_TENANT_BILLING_EMAIL_FLOW.md": "billing-and-email.md",
    "stripe-local.md": "stripe-local.md",
}


def _copy_documentation(target: Path) -> None:
    source = Path("docs")
    replacements = {
        f"({original})": f"({route})" for original, route in DOCUMENT_ROUTES.items()
    }
    for original, route in DOCUMENT_ROUTES.items():
        content = (source / original).read_text(encoding="utf-8")
        for old_link, new_link in replacements.items():
            content = content.replace(old_link, new_link)
        (target / route).write_text(content, encoding="utf-8")


def main() -> None:
    environment = os.getenv("ENVIRONMENT", "development").lower()
    if environment not in {"local", "development", "staging"}:
        raise RuntimeError("Account documentation is exclusive to development and staging")
    environment_label = "STAGING" if environment == "staging" else "AMBIENTE LOCAL"
    account_title = "Contas de staging" if environment == "staging" else "Contas de desenvolvimento"
    raw_password = os.getenv("LOCAL_TEST_ACCOUNT_PASSWORD", "RubricaLocal123!")
    password = html.escape(raw_password)
    count = len(ACCOUNTS) + (len(STAGING_ACCOUNTS) if environment == "staging" else 0)
    lines = [
        '<section class="accounts-hero">',
        f'<span class="eyebrow">{environment_label}</span>',
        f"# {account_title}",
        "<p>Copie uma conta completa e cole no primeiro campo do login do Rubrica.</p>",
        f'<div class="summary"><strong>{count} contas</strong><code>{password}</code></div>',
        "</section>",
        '<p class="local-note">Contas confirmadas pelo seed, sem Microsoft Authenticator. '
        "No login, cole no campo de e-mail: o Rubrica separa e-mail e senha automaticamente.</p>",
        '## Preparar contas de teste',
        '<section class="plan-card seed-commands">',
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
    lines += ["", "## Contas por plano"]
    for title, accounts in (("Gratuito — 1 conta", ACCOUNTS[:1]),
                            ("Essencial — 1 conta", ACCOUNTS[1:2]),
                            ("Profissional — 3 contas", PROFESSIONAL),
                            ("Equipe — 6 contas", TEAM),
                            ("Vitalício — 3 contas", LIFETIME)):
        lines += ["", f"### {title}", '<section class="plan-card">', '<div class="account-list">']
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
    if environment == "staging":
        lines += ["", "## Cenários de staging"]
        groups = (
            ("Recuperação do espaço pessoal", STAGING_ACCOUNTS[:5]),
            ("Troca de workspace e franquia", STAGING_ACCOUNTS[5:8]),
            ("Permissões e readmissão", STAGING_ACCOUNTS[8:14]),
            ("Sede, filiais e sucessão", STAGING_ACCOUNTS[14:19]),
            ("Identidades e assinatura", STAGING_ACCOUNTS[19:20]),
            ("Exportação e encerramento", (*STAGING_ACCOUNTS[20:22], STAGING_ACCOUNTS[25])),
            ("Checkout, upgrade e virada de ciclo", STAGING_ACCOUNTS[22:25]),
        )
        for title, accounts in groups:
            lines += ["", f"### {title}", '<section class="plan-card"><div class="account-list">']
            for email, scenario in accounts:
                lines.append(
                    '<article class="account-row">'
                    f'<div class="account-identity"><strong>{html.escape(scenario)}</strong><span>{html.escape(email)}</span></div>'
                    '<div class="account-actions">'
                    f'<button type="button" class="copy-credentials" data-email="{html.escape(email, quote=True)}" '
                    f'data-password="{html.escape(raw_password, quote=True)}">Copiar conta</button>'
                    "</div></article>"
                )
            lines += ["</div></section>"]
        lines += [
            "", "## PDFs para upload",
            "- [Documento pessoal fictício](assets/teste-pessoal.pdf)",
            "- [Documento empresarial fictício, com duas páginas](assets/teste-empresa.pdf)",
            "",
            "As contas do seed têm e-mail confirmado. Para testar o recebimento real de mensagens, "
            "cadastre ou convide um endereço de teste com caixa postal acessível.",
        ]
    target = Path(".artifacts/local-docs")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    assets = target / "assets"
    assets.mkdir(exist_ok=True, mode=0o700)
    if environment == "staging":
        (assets / "teste-pessoal.pdf").write_bytes(scenario_pdf("PDF pessoal de teste"))
        (assets / "teste-empresa.pdf").write_bytes(scenario_pdf("PDF empresarial de teste", copies=2))
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
    _copy_documentation(target)
    home = target / "index.md"
    home.write_text(
        "# Portal de desenvolvimento Rubrica\n\n"
        "Documentação técnica e referências locais em um único lugar.\n\n"
        "- [Contas de desenvolvimento](test-accounts.md)\n"
        "- [Comandos de staging](staging-commands.md)\n"
        "- [Arquitetura](architecture.md)\n"
        "- [Preparação de produção](production.md)\n"
        "- [Carimbo do tempo SERPRO](serpro-timestamp.md)\n"
        "- [Serpro ID](serpro-id.md)\n"
        "- [Cloudflare R2](cloudflare-r2.md)\n",
        encoding="utf-8",
    )
    home.chmod(0o600)
    # Remove the generated legacy page so stale credentials are not served.
    (target / "accounts.md").unlink(missing_ok=True)
    page = target / "test-accounts.md"
    page.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    page.chmod(0o600)


if __name__ == "__main__":
    main()
