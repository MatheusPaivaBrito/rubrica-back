"""Fail-closed ClamAV adapter; only the configured internal scanner is contacted."""

import socket
import struct

from fastapi import HTTPException
from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.enterprise.document_access import lookup_document, verified_content
from core_api.modules.enterprise.entities import EnterpriseRequest
from core_api.modules.tenant.tenant_service import tenant_service
from core_api.modules.enterprise.storage_settings import for_mode


def scan_stream(stream):
    if not settings.ENTERPRISE_CLAMAV_HOST:
        raise HTTPException(503, "Document scanner is not configured")
    try:
        with socket.create_connection((settings.ENTERPRISE_CLAMAV_HOST,
                                       settings.ENTERPRISE_CLAMAV_PORT), timeout=30) as connection:
            connection.sendall(b"zINSTREAM\x00")
            while chunk := stream.read(256 * 1024):
                connection.sendall(struct.pack(">I", len(chunk)) + chunk)
            connection.sendall(struct.pack(">I", 0))
            response = bytearray()
            while len(response) <= 4096:
                chunk = connection.recv(1024)
                if not chunk:
                    break
                response.extend(chunk)
                if b"\x00" in chunk:
                    break
    except OSError as exc:
        raise HTTPException(503, "Document scanner unavailable") from exc
    result = bytes(response).rstrip(b"\x00\r\n")
    if result == b"stream: OK":
        return "ready"
    if result.startswith(b"stream: ") and result.endswith(b" FOUND"):
        return "rejected"
    raise HTTPException(503, "Document scanner returned an invalid result")


def scan_document(context, document_id):
    with SessionLocal.begin() as db:
        item = lookup_document(db, context, document_id, lock=True)
        if item.status in {"ready", "rejected"}:
            return {"id": item.id, "status": item.status}
        if item.status != "quarantined":
            raise HTTPException(409, "Document cannot be scanned")
        with verified_content(configured_document_storage(for_mode(settings, context.sandbox, item.storage_namespace)), item.storage_key,
                              item.sha256, item.size_bytes) as stream:
            item.status = scan_stream(stream)
        tenant_service._audit(db, context.tenant_id, f"integration:{context.integration_id}",
            "enterprise.document.scanned", {"document_id": str(item.id),
                "token_public_id": context.token_public_id, "status": item.status})
        if item.status == "rejected":
            # Existing drafts remain unopenable because availability is rechecked.
            for request in db.scalars(select(EnterpriseRequest).where(
                EnterpriseRequest.document_id == item.id, EnterpriseRequest.status == "draft")):
                request.status = "cancelled"
        return {"id": item.id, "status": item.status}
