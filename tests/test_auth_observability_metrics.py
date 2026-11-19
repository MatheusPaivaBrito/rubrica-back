from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from auth_api import observability_metrics


@pytest.mark.parametrize("created_at", [None, datetime(2026, 11, 19, 12, tzinfo=UTC)])
def test_last_signup_metric_only_contains_a_timestamp(monkeypatch, created_at):
    session = MagicMock()
    session.__enter__.return_value = session
    session.scalar.side_effect = [2, 0, 1, 2, 2, created_at]
    monkeypatch.setattr(observability_metrics, "Session", lambda _engine: session)

    metrics = {metric.name: metric.samples for metric in observability_metrics.collect_business_metrics()}

    assert metrics["rubrica_users_created_window"][0].value == 1
    latest = metrics.get("rubrica_users_last_created_timestamp_seconds", [])
    if created_at is None:
        assert latest == []
    else:
        assert len(latest) == 1
        assert latest[0].labels == {}
        assert latest[0].value == created_at.timestamp()
