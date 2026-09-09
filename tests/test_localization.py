import pytest
from pydantic import ValidationError

from auth_api.modules.sessions.session_schema import UiContextResponse
from auth_api.modules.users.user_schema import UserCreate, UserPreferencesUpdate
from core_api.modules.tenant.tenant_schema import TenantCreate, TenantPreferencesUpdate
from shared_kernel.localization import (
    normalize_country_code,
    normalize_currency,
    normalize_locale,
    normalize_timezone,
)


def test_locale_variants_are_normalized_with_a_safe_fallback() -> None:
    assert normalize_locale("pt_BR") == "pt-BR"
    assert normalize_locale("ja") == "ja-JP"
    assert normalize_locale("en-US") == "en"
    assert normalize_locale("unsupported") == "en"


def test_user_locale_is_normalized_in_creation_and_preferences() -> None:
    user = UserCreate(
        name="Rubrica Demo",
        email="demo@example.com",
        cpf="529.982.247-25",
        password="a-secure-password",
        preferred_locale="ja",
    )
    preferences = UserPreferencesUpdate(preferred_locale="pt_PT")

    assert user.preferred_locale == "ja-JP"
    assert preferences.preferred_locale == "pt-BR"


def test_ui_context_v2_exposes_the_user_locale() -> None:
    context = UiContextResponse(
        subject="demo@example.com",
        preferred_locale="ja-JP",
        permission_keys=[],
        capability_hash="fingerprint",
    )

    assert context.version == 2
    assert context.preferred_locale == "ja-JP"


def test_tenant_international_preferences_are_normalized() -> None:
    tenant = TenantCreate(
        name="Tokyo",
        slug="tokyo",
        default_locale="ja",
        country_code="jp",
        timezone="Asia/Tokyo",
        currency="jpy",
    )

    assert tenant.default_locale == "ja-JP"
    assert tenant.country_code == "JP"
    assert tenant.timezone == "Asia/Tokyo"
    assert tenant.currency == "JPY"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("country_code", "JPN"),
        ("timezone", "Mars/Olympus"),
        ("currency", "YE"),
    ],
)
def test_invalid_tenant_preferences_are_rejected(field: str, value: str) -> None:
    payload = {
        "default_locale": "en",
        "country_code": "US",
        "timezone": "UTC",
        "currency": "USD",
        field: value,
    }

    with pytest.raises(ValidationError):
        TenantPreferencesUpdate(**payload)


def test_low_level_international_validators() -> None:
    assert normalize_country_code("") is None
    assert normalize_country_code("br") == "BR"
    assert normalize_currency("brl") == "BRL"
    assert normalize_timezone("America/Sao_Paulo") == "America/Sao_Paulo"
