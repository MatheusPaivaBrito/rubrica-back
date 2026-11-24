import asyncio
import os
import subprocess
import sys
from unittest.mock import MagicMock
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from prometheus_client.openmetrics.parser import text_string_to_metric_families
import pytest

from core_api.bootstrap.app import create_app
from core_api.modules.billing.billing_service import BillingService
from core_api.modules.billing.providers.protocol import InvalidWebhookSignatureError
from core_api.modules.signature_request.workflow_service import WorkflowError


def payment_failure_sample():
    async def scrape():
        async with AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://test"
        ) as client:
            return await client.get("/metrics")

    response = asyncio.run(scrape())
    assert response.status_code == 200
    return next(
        sample
        for family in text_string_to_metric_families(response.text)
        for sample in family.samples
        if sample.name == "rubrica_payment_technical_failures_total"
    )


def test_checkout_counts_only_technical_failures(monkeypatch):
    service = BillingService()
    checkout = MagicMock(side_effect=[
        WorkflowError("Missing country", 409),
        WorkflowError("Stripe unavailable", 503),
        TimeoutError(),
    ])
    monkeypatch.setattr(service, "_create_checkout", checkout)
    initial = payment_failure_sample()
    assert initial.labels == {}

    for exception, delta in ((WorkflowError, 0), (WorkflowError, 1), (TimeoutError, 2)):
        with pytest.raises(exception):
            service.create_checkout(uuid4(), "test", "rubrica_base")
        assert payment_failure_sample().value == initial.value + delta


def test_webhook_counts_only_processing_errors_after_validation(monkeypatch):
    provider = MagicMock()
    provider.construct_webhook_event.side_effect = [
        InvalidWebhookSignatureError(),
        {"type": "invoice.payment_failed"},
        {"type": "invoice.payment_succeeded"},
    ]
    service = BillingService(provider)
    process = MagicMock(side_effect=[None, TimeoutError()])
    monkeypatch.setattr(service, "_process_webhook", process)
    initial = payment_failure_sample().value

    with pytest.raises(WorkflowError):
        service.receive_webhook(b"test", "invalid")
    process.assert_not_called()
    service.receive_webhook(b"test", "valid")
    assert payment_failure_sample().value == initial

    with pytest.raises(TimeoutError):
        service.receive_webhook(b"test", "valid")
    assert payment_failure_sample().value == initial + 1


def test_payment_counter_starts_at_zero_and_aggregates_workers(tmp_path):
    env = os.environ | {"PROMETHEUS_MULTIPROC_DIR": str(tmp_path)}
    script = (
        "from core_api.observability_metrics import PAYMENT_TECHNICAL_FAILURES as counter; "
        "from shared_kernel.observability.metrics import _registry; "
        "assert _registry(()).get_sample_value('rubrica_payment_technical_failures_total') == 0; "
        "counter.inc()"
    )
    subprocess.run([sys.executable, "-c", script], env=env, check=True)
    subprocess.run([
        sys.executable, "-c",
        "from core_api.observability_metrics import PAYMENT_TECHNICAL_FAILURES as counter; "
        "counter.inc(2); "
        "from shared_kernel.observability.metrics import _registry; "
        "assert _registry(()).get_sample_value('rubrica_payment_technical_failures_total') == 3",
    ], env=env, check=True)
