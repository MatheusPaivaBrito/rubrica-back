from datetime import UTC, datetime


class DateTimeService:
    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(UTC)
