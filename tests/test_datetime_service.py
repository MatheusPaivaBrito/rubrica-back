from datetime import UTC, datetime

from shared_kernel.time.datetime_service import DateTimeService


def test_datetime_service_normalizes_naive_values_to_utc() -> None:
    value = datetime(2026, 9, 8, 12, 30)

    normalized = DateTimeService.to_utc(value)

    assert normalized.tzinfo is UTC
    assert normalized.isoformat() == "2026-09-08T12:30:00+00:00"


def test_datetime_service_converts_timezone_and_falls_back_to_utc() -> None:
    value = datetime(2026, 9, 8, 12, 30, tzinfo=UTC)

    tokyo = DateTimeService.to_timezone(value, "Asia/Tokyo")
    fallback = DateTimeService.to_timezone(value, "Invalid/Timezone")

    assert tokyo.isoformat() == "2026-09-08T21:30:00+09:00"
    assert fallback.isoformat() == "2026-09-08T12:30:00+00:00"


def test_datetime_service_serialization_and_arithmetic_remain_aware() -> None:
    value = DateTimeService.from_iso("2026-09-08T12:30:00+00:00")

    assert DateTimeService.to_iso(DateTimeService.add_days(value, 2)) == "2026-09-10T12:30:00+00:00"
    assert DateTimeService.start_of_day(value).tzinfo is UTC
    assert DateTimeService.end_of_hour(value).microsecond == 999999
