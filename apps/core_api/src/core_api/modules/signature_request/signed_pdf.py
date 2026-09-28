from __future__ import annotations

import json
from hashlib import sha256
from io import BytesIO
from typing import Any

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont


pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))


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
    representation = item.get("representation_snapshot")
    company_representation = (
        item.get("participant_role") == "company_representative"
        and isinstance(representation, dict)
    )
    box_width = min(255.0, width * 0.48)
    box_height = 96.0 if company_representation else 72.0
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
    identity_country = str(item.get("identity_document_country") or "").upper()
    country_code = identity_country or str(stamp.get("country_code") or "").upper()
    flag_width = 25.0 if country_code and stamp.get("show_flag", True) else 0.0
    if flag_width:
        _draw_country_flag(
            canvas,
            left + box_width - flag_width - 6,
            bottom + 49,
            country_code,
        )
    locale = str(stamp.get("locale", "en"))
    japanese = locale == "ja-JP"
    label = {
        "pt-BR": "ASSINADO ELETRONICAMENTE POR",
        "es": "FIRMADO ELECTRÓNICAMENTE POR",
        "en": "ELECTRONICALLY SIGNED BY",
        "ja-JP": "電子署名者",
    }.get(locale, "ELECTRONICALLY SIGNED BY")
    bold_font = "HeiseiMin-W3" if japanese else "Helvetica-Bold"
    regular_font = "HeiseiMin-W3" if japanese else "Helvetica"
    text_width = box_width - flag_width - 16
    canvas.setFont(bold_font, 7 if japanese else 6)
    content_offset = 24.0 if company_representation else 0.0
    canvas.drawString(left + 7, bottom + 58 + content_offset, _fit_text(label, bold_font, 7 if japanese else 6, text_width))
    canvas.setFont(bold_font, 9)
    canvas.drawString(left + 7, bottom + 43 + content_offset, _fit_text(str(item["signer_name"]), bold_font, 9, text_width))
    identity_type = str(item.get("identity_document_type") or "").replace("BR_", "").replace("PT_", "")
    identity_masked = str(item.get("identity_document_masked") or "")
    identity_prefix = _alpha3_country_code(identity_country)
    identity_value = f"{identity_type}: {identity_masked}" if identity_type and identity_masked else ""
    identity_text = " · ".join(value for value in (identity_prefix, identity_value) if value)
    canvas.setFont(regular_font, 7)
    if identity_text:
        canvas.drawString(left + 7, bottom + 30 + content_offset, _fit_text(identity_text, regular_font, 7, box_width - 14))
    if company_representation:
        legal_name = str(
            representation.get("legal_name")
            or representation.get("display_name")
            or ""
        )
        registration_type = str(representation.get("registration_type") or "").replace("BR_", "")
        registration_masked = str(representation.get("registration_masked") or "")
        canvas.setFont(bold_font, 7)
        canvas.drawString(left + 7, bottom + 41, _fit_text(legal_name, bold_font, 7, box_width - 14))
        canvas.setFont(regular_font, 7)
        registration_text = f"{registration_type}: {registration_masked}" if registration_type and registration_masked else registration_masked
        if registration_text:
            canvas.drawString(left + 7, bottom + 30, _fit_text(registration_text, regular_font, 7, box_width - 14))
    evidence_label = {"pt-BR": "evidência", "en": "evidence", "es": "evidencia", "ja-JP": "証拠"}.get(locale, "evidence")
    timezone = str(stamp.get("timezone", "UTC"))[:32]
    canvas.setFont(regular_font, 6.5)
    canvas.drawString(left + 7, bottom + 18, _fit_text(f'{item["signed_at"]} · {timezone}', regular_font, 6.5, box_width - 14))
    canvas.drawString(left + 7, bottom + 7, _fit_text(f'{evidence_label}: {item["evidence_sha256"][:16]}', regular_font, 6.5, box_width - 14))
    canvas.save()
    stream.seek(0)
    return stream


def _fit_text(value: str, font_name: str, font_size: float, max_width: float) -> str:
    if pdfmetrics.stringWidth(value, font_name, font_size) <= max_width:
        return value
    suffix = "…"
    fitted = value
    while fitted and pdfmetrics.stringWidth(fitted + suffix, font_name, font_size) > max_width:
        fitted = fitted[:-1]
    return fitted.rstrip() + suffix


def _alpha3_country_code(country_code: str) -> str:
    return {
        "BR": "BRA",
        "JP": "JPN",
        "PT": "PRT",
        "ES": "ESP",
        "US": "USA",
    }.get(country_code.upper(), country_code.upper())


def _draw_country_flag(canvas: Canvas, left: float, bottom: float, country_code: str) -> None:
    canvas.saveState()
    if country_code == "BR":
        canvas.setFillColor(HexColor("#009C3B"))
        canvas.rect(left, bottom, 24, 14, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#FFDF00"))
        path = canvas.beginPath()
        path.moveTo(left + 12, bottom + 12)
        path.lineTo(left + 21, bottom + 7)
        path.lineTo(left + 12, bottom + 2)
        path.lineTo(left + 3, bottom + 7)
        path.close()
        canvas.drawPath(path, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#002776"))
        canvas.circle(left + 12, bottom + 7, 3.2, fill=1, stroke=0)
    elif country_code == "JP":
        canvas.setFillColor(white)
        canvas.setStrokeColor(HexColor("#D9DEE7"))
        canvas.rect(left, bottom, 24, 14, fill=1, stroke=1)
        canvas.setFillColor(HexColor("#BC002D"))
        canvas.circle(left + 12, bottom + 7, 4.2, fill=1, stroke=0)
    elif country_code == "US":
        canvas.setFillColor(white)
        canvas.setStrokeColor(HexColor("#D9DEE7"))
        canvas.rect(left, bottom, 24, 14, fill=1, stroke=1)
        canvas.setFillColor(HexColor("#B22234"))
        for stripe in range(0, 7, 2):
            canvas.rect(left, bottom + stripe * 2, 24, 2, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#3C3B6E"))
        canvas.rect(left, bottom + 8, 10, 6, fill=1, stroke=0)
        canvas.setFillColor(white)
        for row in range(2):
            for column in range(3):
                canvas.circle(left + 2 + column * 3, bottom + 9.5 + row * 2.5, 0.35, fill=1, stroke=0)
    elif country_code == "ES":
        canvas.setFillColor(HexColor("#AA151B"))
        canvas.rect(left, bottom, 24, 14, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#F1BF00"))
        canvas.rect(left, bottom + 3.5, 24, 7, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#AA151B"))
        canvas.rect(left + 7, bottom + 5, 1.5, 3.5, fill=1, stroke=0)
    elif country_code == "PT":
        canvas.setFillColor(HexColor("#046A38"))
        canvas.rect(left, bottom, 9.5, 14, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#DA291C"))
        canvas.rect(left + 9.5, bottom, 14.5, 14, fill=1, stroke=0)
        canvas.setStrokeColor(HexColor("#FFCC00"))
        canvas.setLineWidth(1.2)
        canvas.circle(left + 9.5, bottom + 7, 3, fill=0, stroke=1)
        canvas.setFillColor(white)
        canvas.rect(left + 8.2, bottom + 5.2, 2.6, 3.6, fill=1, stroke=0)
        canvas.setStrokeColor(HexColor("#DA291C"))
        canvas.rect(left + 8.2, bottom + 5.2, 2.6, 3.6, fill=0, stroke=1)
    else:
        canvas.setFillColor(HexColor("#EFF3F8"))
        canvas.setStrokeColor(HexColor("#8A96A8"))
        canvas.rect(left, bottom, 24, 14, fill=1, stroke=1)
        canvas.setFillColor(HexColor("#26364D"))
        canvas.setFont("Helvetica-Bold", 6)
        canvas.drawCentredString(left + 12, bottom + 4, country_code[:2])
    canvas.restoreState()
