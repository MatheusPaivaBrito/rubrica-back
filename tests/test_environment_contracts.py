from __future__ import annotations

import pytest

from toolbox.checks.compose_contract import validate
from toolbox.dev.dependencies import parse_services


def test_dev_service_selection_is_deduplicated_and_ordered() -> None:
    assert parse_services("postgres,loki,postgres") == ("postgres", "loki")


def test_dev_service_selection_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match="unknown dev service"):
        parse_services("postgres,core-api")


def test_production_contract_rejects_host_ports_and_dev_tools() -> None:
    errors = validate(
        "production",
        {"services": {"gateway": {"ports": [{"published": "8080"}]}, "cloudflared": {}, "docs": {}}},
    )
    assert "production contains forbidden services: docs" in errors
    assert "production service publishes host ports: gateway" in errors


def test_staging_contract_allows_only_gateway_host_port() -> None:
    assert validate("staging", {"services": {"gateway": {"ports": [{"published": "7271"}]}, "core-api": {}}}) == []
    assert validate("staging", {"services": {"gateway": {}, "core-api": {"ports": [{"published": "8100"}]}}}) == [
        "only staging gateway may publish a host port: core-api"
    ]
