from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SupportedLocale = Literal["pt-BR", "en", "es", "ja-JP"]
SUPPORTED_LOCALES: tuple[SupportedLocale, ...] = ("pt-BR", "en", "es", "ja-JP")
DEFAULT_LOCALE: SupportedLocale = "en"


def normalize_locale(value: object) -> SupportedLocale:
    candidate = str(value or "").strip().replace("_", "-").lower()
    if candidate == "pt" or candidate.startswith("pt-"):
        return "pt-BR"
    if candidate == "ja" or candidate.startswith("ja-"):
        return "ja-JP"
    if candidate == "es" or candidate.startswith("es-"):
        return "es"
    if candidate == "en" or candidate.startswith("en-"):
        return "en"
    return DEFAULT_LOCALE


def normalize_country_code(value: object) -> str | None:
    candidate = str(value or "").strip().upper()
    if not candidate:
        return None
    if len(candidate) != 2 or not candidate.isascii() or not candidate.isalpha():
        raise ValueError("country_code must use ISO 3166-1 alpha-2 format")
    return candidate


def normalize_currency(value: object) -> str:
    candidate = str(value or "").strip().upper()
    if len(candidate) != 3 or not candidate.isascii() or not candidate.isalpha():
        raise ValueError("currency must use ISO 4217 format")
    return candidate


def normalize_timezone(value: object) -> str:
    candidate = str(value or "").strip()
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return candidate
