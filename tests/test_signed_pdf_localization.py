from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pypdf import PdfReader, PdfWriter

from core_api.modules.signature_request.database_workflow_service import DatabaseSignatureWorkflowService
from core_api.modules.signature_request.workflow_schema import StampPosition
from core_api.modules.signature_request.signed_pdf import _alpha3_country_code, _draw_country_flag, _stamp_locale_for_country, generate_signed_pdf


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


def test_company_representative_stamp_shows_legal_name_and_cnpj() -> None:
    source = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(source)
    stamp = {
        "signer_name": "Representante Local",
        "signed_at": "2026-09-25T01:30:00-03:00",
        "evidence_sha256": "b" * 64,
        "participant_role": "company_representative",
        "representation_snapshot": {
            "legal_name": "Empresa Local de Testes Ltda.",
            "registration_type": "BR_CNPJ",
            "registration_masked": "••.•••.•••/••••-61",
        },
        "stamp": {
            "page": 1,
            "x": 0.5,
            "y": 0.8,
            "locale": "pt-BR",
            "timezone": "America/Sao_Paulo",
            "country_code": "BR",
            "show_flag": True,
        },
    }

    rendered = generate_signed_pdf(source.getvalue(), stamps=[stamp], metadata={})
    text = PdfReader(BytesIO(rendered)).pages[0].extract_text() or ""

    assert "Representante Local" in text
    assert "Empresa Local de Testes Ltda." in text
    assert "CNPJ:" in text
    assert "61" in text


def test_full_stamp_uses_issuer_company_when_signer_is_not_a_representative() -> None:
    source = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(source)
    rendered = generate_signed_pdf(source.getvalue(), stamps=[{
        "signer_name": "Pessoa Signatária",
        "signed_at": "2026-10-23T21:00:00-03:00",
        "evidence_sha256": "c" * 64,
        "issuer_snapshot": {
            "legal_name": "Empresa Emissora Ltda.",
            "registration_type": "BR_CNPJ",
            "registration_masked": "••.•••.•••/••••-61",
        },
        "stamp": {"page": 1, "x": 0.5, "y": 0.5, "locale": "pt-BR", "display_variant": "full"},
    }], metadata={})

    text = PdfReader(BytesIO(rendered)).pages[0].extract_text() or ""
    assert "Empresa Emissora Ltda." in text
    assert "CNPJ:" in text


def test_drawn_signature_does_not_render_stamp_text() -> None:
    source = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(source)
    rendered = generate_signed_pdf(source.getvalue(), stamps=[{
        "signer_name": "Nome não deve aparecer",
        "signed_at": "2026-10-23T21:00:00-03:00",
        "evidence_sha256": "d" * 64,
        "drawn_signature_png_data_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
        "stamp": {"page": 1, "x": 0.5, "y": 0.5, "display_variant": "drawn"},
    }], metadata={})

    assert "Nome não deve aparecer" not in (PdfReader(BytesIO(rendered)).pages[0].extract_text() or "")


def test_stamp_locale_follows_supported_country() -> None:
    assert _stamp_locale_for_country("BR", "en") == "pt-BR"
    assert _stamp_locale_for_country("ES", "en") == "es"
    assert _stamp_locale_for_country("JP", "en") == "ja-JP"


def test_signature_evidence_uses_tenant_country_when_identity_is_optional() -> None:
    request = SimpleNamespace(id=uuid4(), document_id=uuid4(), document_version=1, document_sha256="b" * 64)
    signer = SimpleNamespace(id=uuid4(), name="山田 太郎", email="aiko@example.jp")
    configured_signer_id = uuid4()

    evidence = DatabaseSignatureWorkflowService._signature_evidence(
        request,
        signer,
        "aiko@example.jp",
        SimpleNamespace(isoformat=lambda: "2026-09-19T12:00:00+09:00"),
        StampPosition(page=1, x=0.5, y=0.5, locale="ja-JP", timezone="Asia/Tokyo", signer_id=configured_signer_id),
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
    assert evidence["stamp"]["signer_id"] == str(configured_signer_id)


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
