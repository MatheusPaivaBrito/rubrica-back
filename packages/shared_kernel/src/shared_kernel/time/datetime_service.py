from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class DateTimeService:
    DEFAULT_TIMEZONE = "UTC"

    # ------------------------------------
    # NOW
    # ------------------------------------
    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(UTC)

    @classmethod
    def now(cls, timezone: str | None = None) -> datetime:
        return datetime.now(cls.get_timezone(timezone))

    # ------------------------------------
    # TIMEZONE
    # ------------------------------------
    @classmethod
    def get_timezone(cls, timezone: str | None = None) -> ZoneInfo:
        try:
            return ZoneInfo(timezone or cls.DEFAULT_TIMEZONE)
        except ZoneInfoNotFoundError:
            return ZoneInfo(cls.DEFAULT_TIMEZONE)

    @classmethod
    def to_timezone(cls, value: datetime, timezone: str | None = None) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(cls.get_timezone(timezone))

    @classmethod
    def to_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    # ------------------------------------
    # SERIALIZATION
    # ------------------------------------
    @classmethod
    def to_iso(cls, value: datetime | None, timezone: str | None = None) -> str | None:
        if value is None:
            return None
        return cls.to_timezone(value=value, timezone=timezone).isoformat()

    @staticmethod
    def from_iso(value: str) -> datetime:
        return datetime.fromisoformat(value)

    # ------------------------------------
    # FORMATTING
    # ------------------------------------
    @classmethod
    def format(
        cls,
        value: datetime | None,
        timezone: str | None = None,
        fmt: str = "%Y-%m-%d %H:%M:%S",
    ) -> str | None:
        if value is None:
            return None
        return cls.to_timezone(value=value, timezone=timezone).strftime(fmt)

    # ------------------------------------
    # COMPARISON
    # ------------------------------------
    @classmethod
    def is_expired(cls, value: datetime) -> bool:
        return cls.to_utc(value) < cls.utc_now()

    @classmethod
    def is_future(cls, value: datetime) -> bool:
        return cls.to_utc(value) > cls.utc_now()

    @classmethod
    def is_past(cls, value: datetime) -> bool:
        return cls.to_utc(value) < cls.utc_now()

    # ------------------------------------
    # DELTA
    # ------------------------------------
    @staticmethod
    def add_seconds(value: datetime, seconds: int) -> datetime:
        return value + timedelta(seconds=seconds)

    @staticmethod
    def add_minutes(value: datetime, minutes: int) -> datetime:
        return value + timedelta(minutes=minutes)

    @staticmethod
    def add_hours(value: datetime, hours: int) -> datetime:
        return value + timedelta(hours=hours)

    @staticmethod
    def add_days(value: datetime, days: int) -> datetime:
        return value + timedelta(days=days)

    @staticmethod
    def subtract_seconds(value: datetime, seconds: int) -> datetime:
        return value - timedelta(seconds=seconds)

    @staticmethod
    def subtract_minutes(value: datetime, minutes: int) -> datetime:
        return value - timedelta(minutes=minutes)

    @staticmethod
    def subtract_hours(value: datetime, hours: int) -> datetime:
        return value - timedelta(hours=hours)

    @staticmethod
    def subtract_days(value: datetime, days: int) -> datetime:
        return value - timedelta(days=days)

    # ------------------------------------
    # RANGE
    # ------------------------------------
    @staticmethod
    def start_of_day(value: datetime) -> datetime:
        return value.replace(hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def end_of_day(value: datetime) -> datetime:
        return value.replace(hour=23, minute=59, second=59, microsecond=999999)

    @staticmethod
    def start_of_hour(value: datetime) -> datetime:
        return value.replace(minute=0, second=0, microsecond=0)

    @staticmethod
    def end_of_hour(value: datetime) -> datetime:
        return value.replace(minute=59, second=59, microsecond=999999)

    # ------------------------------------
    # HUMANIZE
    # ------------------------------------
    @classmethod
    def minutes_ago(cls, value: datetime) -> int:
        delta = cls.utc_now() - cls.to_utc(value)
        return int(delta.total_seconds() / 60)

    @classmethod
    def hours_ago(cls, value: datetime) -> int:
        delta = cls.utc_now() - cls.to_utc(value)
        return int(delta.total_seconds() / 3600)

    @classmethod
    def days_ago(cls, value: datetime) -> int:
        delta = cls.utc_now() - cls.to_utc(value)
        return delta.days
