"""Public integration contract: no administrative/internal schema or live secrets."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)
SECURITY_HEADERS = {"Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'",
                    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


def public_schema(app):
    routes = [route for route in app.routes if getattr(route, "path", "").startswith("/api/v1/")]
    result = get_openapi(title="Rubrica — API Empresarial", version="1.0.0", routes=routes,
        description="Tokens somente no servidor. Sandbox usa dados fictícios e não chama provedores pagos. Limite de PDF: 50.000.000 bytes.")
    result.setdefault("components", {}).setdefault("securitySchemes", {}).update({
        "EnterpriseToken": {"type": "http", "scheme": "bearer", "description": "Token de máquina criado em Configurações → Integrações e API."},
        "SignerSession": {"type": "http", "scheme": "bearer", "description": "Sessão temporária de um único signatário; exige consentimento pessoal."},
    })
    for path, operations in result["paths"].items():
        for operation in operations.values():
            if isinstance(operation, dict):
                operation["security"] = [{"SignerSession" if "/signing-session" in path else "EnterpriseToken": []}]
    return result


@router.get("/docs", response_class=HTMLResponse)
@router.get("/docs/", response_class=HTMLResponse)
async def portal():
    return HTMLResponse(Path(__file__).with_name("developer_portal.html").read_text(), headers=SECURITY_HEADERS)


@router.get("/docs/style.css")
async def stylesheet():
    return Response("body{margin:0;background:#f8f8fa;color:#24232b;font:16px/1.6 system-ui,sans-serif}main{max-width:1000px;margin:auto;padding:2rem 1rem}header{border-bottom:3px solid #a82035;padding-bottom:1rem}h1,h2{color:#a82035}nav{display:flex;flex-wrap:wrap;gap:1rem;margin:1rem 0}a{color:#982036}section{background:white;border:1px solid #dedee5;border-radius:12px;padding:1.25rem;margin:1.25rem 0}pre{overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f2f5;padding:1rem;border-radius:8px}table{border-collapse:collapse;width:100%}td,th{text-align:left;border-bottom:1px solid #dedee5;padding:.6rem}code{overflow-wrap:anywhere}.notice{border-left:4px solid #a82035;padding-left:1rem}li{margin:.45rem 0}@media(max-width:600px){main{padding:1rem .75rem}section{padding:.9rem}table{font-size:.85rem}}",
        media_type="text/css", headers=SECURITY_HEADERS)


@router.get("/docs/openapi.json")
async def schema(request: Request):
    return public_schema(request.app)


@lru_cache(maxsize=1)
def sample_pdf():
    from reportlab.pdfgen.canvas import Canvas
    stream = BytesIO()
    canvas = Canvas(stream)
    canvas.drawString(50, 780, "Rubrica - documento ficticio de sandbox")
    canvas.drawString(50, 750, "Este arquivo nao contem dados de clientes.")
    canvas.showPage()
    canvas.save()
    return stream.getvalue()


@router.get("/docs/sample.pdf")
async def download_sample():
    return Response(sample_pdf(), media_type="application/pdf", headers={**SECURITY_HEADERS,
        "Content-Disposition": 'attachment; filename="rubrica-sandbox.pdf"'})


@router.get("/docs/postman.json")
async def collection():
    return {"info": {"name": "Rubrica API sandbox", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "variable": [{"key": key, "value": value} for key, value in (("baseUrl", "https://SEU_HOST"), ("compartmentId", "UUID"),
                     ("documentId", "UUID"), ("requestId", "UUID"), ("machineToken", ""), ("signerSession", ""))],
        "item": [{"name": name, "request": {"method": method, "url": "{{baseUrl}}/api/v1/sandbox/compartments/{{compartmentId}}/" + path,
            "header": [{"key": "Authorization", "value": "Bearer {{machineToken}}"}]}}
            for name, method, path in (("Listar documentos", "GET", "documents"), ("Consultar documento", "GET", "documents/{{documentId}}"),
                ("Baixar PDF", "GET", "documents/{{documentId}}/download"), ("Consultar solicitação", "GET", "signature-requests/{{requestId}}"),
                ("Baixar resultado", "GET", "signature-requests/{{requestId}}/artifact"), ("Consumo", "GET", "usage"))]}
