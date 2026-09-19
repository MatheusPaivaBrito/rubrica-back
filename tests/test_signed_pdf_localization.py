from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pypdf import PdfReader, PdfWriter

from core_api.modules.signature_request.database_workflow_service import DatabaseSignatureWorkflowService
from core_api.modules.signature_request.workflow_schema import StampPosition
from core_api.modules.signature_request.signed_pdf import _alpha3_country_code, _draw_country_flag, generate_signed_pdf


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


def test_signature_evidence_uses_tenant_country_when_identity_is_optional() -> None:
    request = SimpleNamespace(id=uuid4(), document_id=uuid4(), document_version=1, document_sha256="b" * 64)
    signer = SimpleNamespace(id=uuid4(), name="山田 太郎", email="aiko@example.jp")

    evidence = DatabaseSignatureWorkflowService._signature_evidence(
        request,
        signer,
        "aiko@example.jp",
        SimpleNamespace(isoformat=lambda: "2026-09-19T12:00:00+09:00"),
        StampPosition(page=1, x=0.5, y=0.5, locale="ja-JP", timezone="Asia/Tokyo"),
        "rubrica-evidence-v1",
        None,
        None,
        "127.0.0.1",
        "Mobile Safari",
        None,
        "JP",
    )

    assert evidence["stamp"]["country_code"] == "JP"
    assert evidence["stamp"]["show_flag"] is True
    assert evidence["stamp"]["template"] == "JP"


def test_japanese_flag_is_drawn_from_server_country(monkeypatch: pytest.MonkeyPatch) -> None:
    drawn: list[str] = []
    monkeypatch.setattr(
        "core_api.modules.signature_request.signed_pdf._draw_country_flag",
        lambda _canvas, _left, _bottom, country: drawn.append(country),
    )
    source = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(source)
    stamp = {
        "signer_name": "山田 太郎",
        "signed_at": "2026-09-19T12:00:00+09:00",
        "evidence_sha256": "a" * 64,
        "stamp": {
            "page": 1,
            "x": 0.5,
            "y": 0.8,
            "locale": "ja-JP",
            "timezone": "Asia/Tokyo",
            "country_code": "JP",
            "show_flag": True,
        },
    }

    generate_signed_pdf(source.getvalue(), stamps=[stamp], metadata={})

    assert drawn == ["JP"]


@pytest.mark.parametrize("country", ["US", "BR", "ES", "JP", "PT"])
def test_supported_market_flags_are_graphical(country: str) -> None:
    canvas = MagicMock()

    _draw_country_flag(canvas, 0, 0, country)

    canvas.drawCentredString.assert_not_called()


@pytest.mark.parametrize(
    ("country", "alpha3"),
    [("US", "USA"), ("BR", "BRA"), ("ES", "ESP"), ("JP", "JPN"), ("PT", "PRT")],
)
def test_supported_market_country_codes_use_iso_alpha3(country: str, alpha3: str) -> None:
    assert _alpha3_country_code(country) == alpha3
