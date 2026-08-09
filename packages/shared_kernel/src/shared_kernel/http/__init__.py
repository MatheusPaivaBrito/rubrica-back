from __future__ import annotations

from dataclasses import dataclass, field
import logging
import sys
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse
import orjson


@dataclass(frozen=True)
class CorsConfig:
    enabled: bool = True
    allow_origins: tuple[str, ...] = ()
    allow_credentials: bool = True


@dataclass(frozen=True)
class HomeAction:
    label: str
    url: str
    primary: bool = False
    available: bool = True


@dataclass(frozen=True)
class HomeCard:
    title: str
    description: str
    status: str
    available: bool = True


@dataclass(frozen=True)
class HomeSection:
    title: str
    description: str
    cards: tuple[HomeCard, ...]
    columns: int = 3


@dataclass(frozen=True)
class HomePage:
    service_name: str
    eyebrow: str
    description: str
    actions: tuple[HomeAction, ...]
    sections: tuple[HomeSection, ...] = field(default_factory=tuple)


def parse_cors_origins(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(dict.fromkeys(item.strip().rstrip("/") for item in value.split(",") if item.strip()))


def apply_cors(app: FastAPI, config: CorsConfig) -> None:
    if not config.enabled:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allow_origins) or ["*"],
        allow_credentials=config.allow_credentials,
        allow_methods=["DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT"],
        allow_headers=["Accept", "Authorization", "Content-Type", "Origin", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )


def apply_request_correlation(app: FastAPI, *, service_name: str) -> None:
    @app.middleware("http")
    async def request_correlation(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id
        request.state.service_name = service_name
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response


def apply_request_logging(app: FastAPI, *, service_name: str, environment: str = "development") -> None:
    logger = logging.getLogger(f"{service_name}.http")
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.propagate = False

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        started_at = perf_counter()
        response = await call_next(request)
        duration_ms = round((perf_counter() - started_at) * 1000, 3)
        response.headers["x-process-time-ms"] = f"{duration_ms:.2f}"
        response.headers["x-service-name"] = service_name
        response.headers["x-environment"] = environment
        logger.info(
            orjson.dumps(
                {
                    "message": "http_request",
                    "service": service_name,
                    "environment": environment,
                    "request_id": getattr(request.state, "request_id", None),
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                }
            ).decode("utf-8")
        )
        return response


def create_docs_router(title: str) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/docs")
    async def swagger_docs() -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{title} - Swagger")

    @router.get("/redoc")
    async def redoc_docs() -> HTMLResponse:
        return get_redoc_html(openapi_url="/openapi.json", title=f"{title} - ReDoc")

    return router


def render_service_home(*, request: Request, page: HomePage) -> HTMLResponse:
    actions = "".join(
        f'<a class="action {"primary" if action.primary else ""} {"disabled" if not action.available else ""}" href="{action.url}">{action.label}</a>'
        for action in page.actions
    )
    sections = "".join(
        f'<section><div class="section-title"><h2>{section.title}</h2><p>{section.description}</p></div><div class="grid columns-{section.columns}">'  # noqa: E501
        + "".join(
            f'<article><span class="status {"online" if card.available else ""}">{card.status}</span><h3>{card.title}</h3><p>{card.description}</p></article>'  # noqa: E501
            for card in section.cards
        )
        + "</div></section>"
        for section in page.sections
    )
    html = (
        "<!doctype html>"
        '<html lang="en"><head>'
        '<meta charset="utf-8" />'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />'
        f"<title>{page.service_name}</title>"
        "<style>"
        ":root{color-scheme:dark;--bg:#080c14;--panel:#101827;--soft:#162033;--border:#2a3850;--text:#e7edf6;--muted:#9aa8bd;--accent:#58c4dc;--ok:#7ee787;--warn:#f2cc60}"  # noqa: E501
        "*{box-sizing:border-box}body{min-height:100vh;margin:0;background:linear-gradient(135deg,#080c14,#101827 50%,#0d1524);color:var(--text);font-family:Inter,system-ui,sans-serif}"  # noqa: E501
        "main{width:min(1120px,calc(100% - 32px));min-height:100vh;margin:0 auto;display:grid;align-content:center;gap:28px;padding:48px 0}"  # noqa: E501
        ".eyebrow{width:fit-content;padding:8px 10px;border:1px solid var(--border);border-radius:8px;color:#8be9fd;font-weight:800;font-size:.82rem}"  # noqa: E501
        "h1{margin:0;font-size:clamp(2.4rem,6vw,4.8rem);line-height:.98}h2,h3,p{margin:0}p{color:var(--muted);line-height:1.65}.actions{display:flex;flex-wrap:wrap;gap:12px}"  # noqa: E501
        ".action{border:1px solid var(--border);border-radius:8px;color:var(--text);padding:10px 14px;text-decoration:none;font-weight:800}.action.primary{background:#123142;border-color:#22d3ee}"  # noqa: E501
        "section{display:grid;gap:14px}.section-title{display:flex;justify-content:space-between;gap:18px;align-items:end}.section-title p{max-width:620px}"  # noqa: E501
        ".grid{display:grid;gap:14px}.columns-2{grid-template-columns:repeat(2,minmax(0,1fr))}.columns-3{grid-template-columns:repeat(3,minmax(0,1fr))}"  # noqa: E501
        "article{min-height:150px;border:1px solid var(--border);border-radius:8px;background:rgba(16,24,39,.84);padding:18px;display:grid;align-content:start;gap:12px}"  # noqa: E501
        ".status{width:fit-content;padding:6px 8px;border-radius:8px;background:rgba(255,255,255,.05);color:var(--warn);font-size:.78rem;font-weight:800}.status.online{color:var(--ok)}"  # noqa: E501
        "@media(max-width:760px){.columns-2,.columns-3{grid-template-columns:1fr}.section-title{display:grid}}"  # noqa: E501
        "</style></head><body><main>"
        f'<div class="eyebrow">{page.eyebrow}</div>'
        f"<h1>{page.service_name}</h1>"
        f"<p>{page.description}</p>"
        f'<div class="actions">{actions}</div>'
        f"{sections}"
        "</main></body></html>"
    )
    return HTMLResponse(html)
