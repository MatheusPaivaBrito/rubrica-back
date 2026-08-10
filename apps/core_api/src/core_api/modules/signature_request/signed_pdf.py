from __future__ import annotations

import json
from hashlib import sha256
from io import BytesIO
from typing import Any

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen.canvas import Canvas


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def evidence_sha256(payload: dict[str, Any]) -> str:
    return sha256(canonical_json(payload)).hexdigest()


def generate_signed_pdf(
    original: bytes,
    *,
    stamps: list[dict[str, Any]],
    metadata: dict[str, str],
) -> bytes:
    reader = PdfReader(BytesIO(original))
    writer = PdfWriter()
    for page_number, page in enumerate(reader.pages, start=1):
        writer.add_page(page)
        output_page = writer.pages[-1]
        page_stamps = [item for item in stamps if int(item["stamp"]["page"]) == page_number]
        for item in page_stamps:
            width = float(output_page.mediabox.width)
            height = float(output_page.mediabox.height)
            overlay = _stamp_overlay(width, height, item)
            output_page.merge_page(PdfReader(overlay).pages[0])
    inherited = {str(key): str(value) for key, value in (reader.metadata or {}).items() if value is not None}
    inherited.update({f"/{key.lstrip('/')}": value for key, value in metadata.items()})
    writer.add_metadata(inherited)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _stamp_overlay(width: float, height: float, item: dict[str, Any]) -> BytesIO:
    stamp = item["stamp"]
    box_width = min(205.0, width * 0.42)
    box_height = 48.0
    center_x = float(stamp["x"]) * width
    center_y = (1 - float(stamp["y"])) * height
    left = min(max(4.0, center_x - box_width / 2), width - box_width - 4.0)
    bottom = min(max(4.0, center_y - box_height / 2), height - box_height - 4.0)
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(width, height), pageCompression=1)
    canvas.setFillColor(white)
    canvas.setStrokeColor(HexColor("#187A66"))
    canvas.setLineWidth(1.5)
    canvas.roundRect(left, bottom, box_width, box_height, 4, fill=1, stroke=1)
    canvas.setFillColor(HexColor("#0D5B4B"))
    canvas.setFont("Helvetica-Bold", 6)
    canvas.drawString(left + 7, bottom + 34, "ASSINADO ELETRONICAMENTE POR")
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(left + 7, bottom + 21, str(item["signer_name"])[:38])
    canvas.setFont("Helvetica", 6.5)
    canvas.drawString(left + 7, bottom + 9, f'{item["signed_at"]}  evidencia {item["evidence_sha256"][:12]}')
    canvas.save()
    stream.seek(0)
    return stream
