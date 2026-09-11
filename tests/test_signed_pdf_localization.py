from io import BytesIO

from pypdf import PdfReader, PdfWriter

from core_api.modules.signature_request.signed_pdf import generate_signed_pdf


def test_japanese_stamp_and_locale_are_embedded_in_signed_pdf() -> None:
    source = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(source)
    stamp = {"signer_name": "山田 太郎", "signed_at": "2026-09-10T12:00:00+09:00", "evidence_sha256": "a" * 64, "stamp": {"page": 1, "x": 0.5, "y": 0.8, "locale": "ja-JP", "timezone": "Asia/Tokyo"}}
    rendered = generate_signed_pdf(source.getvalue(), stamps=[stamp], metadata={"RubricaLocale": "ja-JP"})
    reader = PdfReader(BytesIO(rendered))
    assert rendered.startswith(b"%PDF")
    assert reader.metadata["/RubricaLocale"] == "ja-JP"
    assert "山田" in (reader.pages[0].extract_text() or "")
