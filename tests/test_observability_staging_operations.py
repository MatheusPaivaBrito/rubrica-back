import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from toolbox.operations import observability_staging as operations


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(operations, "RUNTIME", tmp_path/"runtime")
    return operations.RUNTIME


def test_install_existing_key_copies_only_named_secret_without_generating_or_printing_value(runtime, monkeypatch, tmp_path, capsys):
    source = tmp_path/"operator-owned-existing-key"
    source.write_text("operator-registered-secret-never-display")
    monkeypatch.setattr(sys, "argv", ["tool", "install-secret", "--name", "platform_token", "--source", str(source)])
    operations.main()
    target = runtime/"secrets/platform_token"
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.parent.stat().st_mode & 0o777 == 0o700
    assert "operator-registered-secret" not in capsys.readouterr().out
    assert not list(target.parent.glob(".install-*"))


def test_tunnel_token_is_not_an_accepted_install_target(runtime, monkeypatch, tmp_path):
    source = tmp_path/"file"
    source.write_text("contents")
    monkeypatch.setattr(sys, "argv", ["tool", "install-secret", "--name", "cloudflare_tunnel_token", "--source", str(source)])
    with pytest.raises(SystemExit):
        operations.main()
    assert not runtime.exists()


def test_missing_platform_files_do_not_recreate_or_stop_existing_api(runtime, monkeypatch):
    calls = []
    monkeypatch.setattr(operations, "compose", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(sys, "argv", ["tool", "connect"])
    with pytest.raises(ValueError, match="platform_token"):
        operations.main()
    assert not calls


def test_read_only_ensure_only_executes_the_fixed_cli(runtime, monkeypatch, capsys):
    calls = []
    report = {"operational": False, "configured": False, "reason": "configuration_incomplete"}
    def compose(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 2, json.dumps(report), "never-copy-raw-stderr")
    monkeypatch.setattr(operations, "compose", compose)
    monkeypatch.setattr(sys, "argv", ["tool", "evidence"])
    with pytest.raises(SystemExit) as error:
        operations.main()
    assert error.value.code == 2
    assert calls == [("exec", "-T", "observability-api", "python", "-m", "observability_api.modules.platform_publish.ensure")]
    assert "never-copy" not in capsys.readouterr().out
    evidence = list((runtime/"evidence").glob("*.json"))
    assert len(evidence) == 1 and evidence[0].stat().st_mode & 0o777 == 0o600
    assert json.loads(evidence[0].read_text()) == report


def test_two_service_compose_preserves_existing_project_and_volume_names():
    root = Path(__file__).resolve().parents[1]
    base = yaml.safe_load((root/"compose/observability-staging-local.yml").read_text())
    overlay = yaml.safe_load((root/"compose/features/observability-platform.yml").read_text())
    assert set(base["services"]) == {"postgres", "observability-api"}
    assert base["name"] == "rubrica-observability-staging-local"
    assert set(base["volumes"]) == {"postgres_data", "api_logs"}
    assert not base["services"]["postgres"].get("ports")
    api = base["services"]["observability-api"]
    assert api["ports"] == ["127.0.0.1:8104:8000"]
    assert api["environment"]["PLATFORM_PUBLISH_ENABLED"] == "false"
    assert set(overlay["services"]) == {"observability-api"}
    assert set(overlay["secrets"]) == set(operations.NAMES)
    assert all("production" not in item["file"] for item in overlay["secrets"].values())
    assert "--workers 1" in api["command"][-1]


def test_historical_file_can_be_mounted_as_single_v2_secret_without_reading(runtime):
    (runtime/"secrets").mkdir(parents=True)
    old = runtime/"secrets/platform_ingest_token"
    old.touch(mode=0o600)
    assert operations.token_source() == old
    canonical = runtime/"secrets/platform_token"
    canonical.touch(mode=0o600)
    assert operations.token_source() == canonical
