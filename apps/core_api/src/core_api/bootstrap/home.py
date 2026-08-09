from html import escape
from pathlib import Path
import subprocess
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from core_api.bootstrap.domain_generator import DomainGeneratorError, generate_core_domain
from core_api.infrastructure.auth_context import require_permission
from toolbox.checks.migration_status import (
    MigrationStatus,
    inspect_project_migrations,
    migrate_service,
)


router = APIRouter(
    include_in_schema=False,
    dependencies=[Depends(require_permission("*"))],
)
PROJECT_ROOT = Path(__file__).resolve().parents[5]
MODULES_ROOT = PROJECT_ROOT / "apps/core_api/src/core_api/modules"


async def _read_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    parsed = parse_qs(body, keep_blank_values=True)
    return {
        key: ",".join(value for value in values if value) if key == "many_to_many" else values[-1]
        for key, values in parsed.items()
    }


def _redirect(*, notice: str | None = None, error: str | None = None) -> RedirectResponse:
    query = urlencode({key: value for key, value in {"notice": notice, "error": error}.items() if value})
    return RedirectResponse(url=f"/?{query}" if query else "/", status_code=303)


def _domains() -> tuple[str, ...]:
    if not MODULES_ROOT.exists():
        return ()
    return tuple(sorted(path.name for path in MODULES_ROOT.iterdir() if path.is_dir() and not path.name.startswith("__")))


def _domain_options(domains: tuple[str, ...], *, include_empty: bool = False) -> str:
    options = ['<option value="">None</option>'] if include_empty else []
    options.extend(f'<option value="{escape(domain)}">{escape(domain)}</option>' for domain in domains)
    return "".join(options)


def _migration_payload(status: MigrationStatus) -> dict[str, object]:
    return {
        "service": status.service,
        "label": status.label,
        "state": status.state,
        "current": list(status.current),
        "heads": list(status.heads),
        "detail": status.detail,
    }


@router.get("/")
def home(request: Request) -> HTMLResponse:
    notice = request.query_params.get("notice")
    error = request.query_params.get("error")
    current_domains = _domains()
    domains = "".join(f"<span>{escape(domain)}</span>" for domain in current_domains) or "<span>No domains yet</span>"
    belongs_to_options = _domain_options(current_domains, include_empty=True)
    many_to_many_options = _domain_options(current_domains)
    notice_html = f'<p class="notice success">{escape(notice)}</p>' if notice else ""
    error_html = f'<p class="notice error">{escape(error)}</p>' if error else ""
    return HTMLResponse(
        f'''
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Core Domain Generator</title>
            <style>
              :root {{ color-scheme: dark; --bg:#080c14; --panel:#101827; --border:#2a3850; --text:#e7edf6; --muted:#9aa8bd; --accent:#58c4dc; --danger:#ff7b72; --success:#7ee787; }}
              * {{ box-sizing:border-box; }}
              body {{ margin:0; min-height:100vh; background:linear-gradient(135deg,#080c14,#101827); color:var(--text); font-family:Inter,system-ui,sans-serif; }}
              main {{ width:min(960px,calc(100% - 32px)); margin:0 auto; padding:44px 0; display:grid; gap:22px; }}
              h1 {{ margin:0; font-size:clamp(2.2rem,6vw,4.5rem); letter-spacing:0; }}
              p {{ margin:0; color:var(--muted); line-height:1.6; }}
              .panel {{ border:1px solid var(--border); border-radius:8px; background:rgba(16,24,39,.9); padding:18px; display:grid; gap:16px; }}
              form {{ display:grid; gap:12px; }}
              label {{ display:grid; gap:6px; color:var(--muted); font-weight:700; }}
              .choice {{ grid-template-columns:auto 1fr; align-items:start; }}
              .choice input {{ min-height:auto; margin-top:4px; }}
              .choice small {{ display:block; color:var(--muted); font-weight:500; margin-top:3px; }}
              input,select {{ min-height:42px; border:1px solid var(--border); border-radius:8px; background:#0c1320; color:var(--text); padding:0 12px; font:inherit; }}
              select[multiple] {{ min-height:116px; padding:8px 12px; }}
              button,a {{ min-height:42px; border:1px solid rgba(88,196,220,.62); border-radius:8px; background:#123142; color:#ecfeff; font-weight:800; padding:0 16px; display:inline-flex; align-items:center; justify-content:center; text-decoration:none; cursor:pointer; }}
              .domains {{ display:flex; flex-wrap:wrap; gap:8px; }}
              .domains span {{ padding:6px 8px; border-radius:8px; background:rgba(255,255,255,.05); color:#8be9fd; font-weight:800; font-size:.8rem; }}
              .migration-panel {{ display:grid; gap:10px; border:1px solid var(--border); border-radius:8px; background:#0c1320; padding:14px; }}
              .migration-panel.pending {{ border-color:#f2cc60; background:rgba(187,128,9,.1); }}
              .migration-heading,.migration-row {{ display:flex; align-items:center; justify-content:space-between; gap:12px; }}
              .migration-summary,.migration-detail {{ color:var(--muted); font-size:.78rem; }}
              .migration-list,.migration-copy {{ display:grid; gap:7px; }}
              .migration-row {{ padding-top:8px; border-top:1px solid rgba(88,196,220,.14); }}
              .migration-state {{ font-size:.74rem; font-weight:900; text-transform:uppercase; }}
              .migration-state.up_to_date {{ color:var(--success); }}
              .migration-state.pending {{ color:#f2cc60; }}
              .migration-state.unavailable,.migration-state.error {{ color:var(--danger); }}
              .migration-action {{ min-height:34px; }}
              .notice {{ padding:10px 12px; border-radius:8px; font-weight:800; }}
              .success {{ color:var(--success); border:1px solid rgba(126,231,135,.42); }}
              .error {{ color:var(--danger); border:1px solid rgba(255,123,114,.42); }}
            </style>
          </head>
          <body>
            <main>
              <header>
                <h1>Core Domain Generator</h1>
                <p>Add CRUD domains to this generated Core API. Keep the lightweight default or opt into SQLAlchemy relationships and an Alembic migration.</p>
              </header>
              {notice_html}
              {error_html}
              <section class="panel">
                <h2>Domains</h2>
                <div class="domains">{domains}</div>
                <a href="/docs">Open Swagger</a>
              </section>
              <section class="migration-panel" aria-live="polite">
                <div class="migration-heading">
                  <strong>Database migrations</strong>
                  <span class="migration-summary">Checking...</span>
                </div>
                <div class="migration-list"></div>
              </section>
              <section class="panel">
                <h2>Add Core CRUD Domain</h2>
                <form method="post" action="/generator/domains">
                  <label>Domain name <input name="domain" placeholder="books" required pattern="[a-zA-Z][a-zA-Z0-9_-]*"></label>
                  <label>Belongs to <select name="belongs_to">{belongs_to_options}</select></label>
                  <label>Many-to-many with <select name="many_to_many" multiple size="4">{many_to_many_options}</select></label>
                  <label>Relationship notes <input name="relationship_notes" placeholder="books can be moved between shelves"></label>
                  <label class="choice">
                    <input type="checkbox" name="relational" value="1">
                    <span>
                      Relational persistence
                      <small>Create real foreign keys, association tables and an Alembic migration. Related domains must already have migrations.</small>
                    </span>
                  </label>
                  <label class="choice">
                    <input type="checkbox" name="apply_migration" value="1">
                    <span>
                      Apply migration now
                      <small>Run make migrate-core after generating a relational domain.</small>
                    </span>
                  </label>
                  <button type="submit">Generate Domain</button>
                </form>
              </section>
            </main>
            <script>
              function migrationRow(status) {{
                const row = document.createElement('div');
                row.className = 'migration-row';
                const copy = document.createElement('div');
                copy.className = 'migration-copy';
                const title = document.createElement('strong');
                title.textContent = status.label;
                const state = document.createElement('span');
                state.className = 'migration-state ' + status.state;
                state.textContent = status.state.replaceAll('_', ' ');
                copy.append(title, state);
                if (status.detail) {{
                  const detail = document.createElement('span');
                  detail.className = 'migration-detail';
                  detail.textContent = status.detail;
                  copy.append(detail);
                }}
                const form = document.createElement('form');
                form.method = 'post';
                form.action = '/generator/migrations/' + status.service;
                const button = document.createElement('button');
                button.type = 'submit';
                button.className = 'migration-action';
                button.textContent = status.state === 'pending' ? 'Migrate' : 'Run migration';
                form.append(button);
                row.append(copy, form);
                return row;
              }}

              async function loadMigrations() {{
                const panel = document.querySelector('.migration-panel');
                const summary = panel.querySelector('.migration-summary');
                const list = panel.querySelector('.migration-list');
                try {{
                  const response = await fetch('/generator/migrations');
                  if (!response.ok) throw new Error('HTTP ' + response.status);
                  const statuses = await response.json();
                  list.replaceChildren(...statuses.map(migrationRow));
                  const pending = statuses.filter((status) => status.state === 'pending').length;
                  panel.classList.toggle('pending', pending > 0);
                  summary.textContent = pending
                    ? pending + ' pending migration' + (pending === 1 ? '' : 's')
                    : (statuses.length ? 'No pending migrations' : 'No database APIs');
                }} catch (error) {{
                  summary.textContent = 'Status unavailable: ' + error.message;
                }}
              }}
              loadMigrations();
            </script>
          </body>
        </html>
        '''
    )


@router.get("/generator/migrations")
def migration_statuses() -> JSONResponse:
    statuses = inspect_project_migrations(PROJECT_ROOT)
    return JSONResponse([_migration_payload(status) for status in statuses])


@router.post("/generator/migrations/{service}")
def apply_migration(service: str) -> RedirectResponse:
    try:
        result = migrate_service(PROJECT_ROOT, service)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return _redirect(error=str(exc))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[-1] if detail else f"Migration failed for {service}"
        return _redirect(error=message)
    return _redirect(notice=f"{service} migrations applied successfully.")


@router.post("/generator/domains")
async def add_domain(request: Request) -> RedirectResponse:
    form = await _read_form(request)
    domain = form.get("domain", "").strip()
    persistence = (
        "relational"
        if form.get("relational", "").strip() == "1"
        else "memory"
    )
    try:
        generate_core_domain(
            project_root=PROJECT_ROOT,
            name=domain,
            belongs_to=form.get("belongs_to", "").strip() or None,
            many_to_many=form.get("many_to_many", "").strip() or None,
            relationship_notes=form.get("relationship_notes", "").strip() or None,
            persistence=persistence,
        )
    except DomainGeneratorError as exc:
        return _redirect(error=str(exc))

    if persistence == "relational" and form.get("apply_migration", "").strip() == "1":
        result = subprocess.run(
            ("make", "migrate-core"),
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            message = detail[-1] if detail else "make migrate-core failed"
            return _redirect(error=f"Domain {domain} was generated, but {message}")

    return _redirect(notice=f"Domain {domain} generated. Restart the API to load the new router.")
