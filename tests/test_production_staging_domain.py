import json

import pytest

from toolbox.operations import production_staging_domain as switch

ORIGINAL = '''limit_req_zone $binary_remote_addr zone=test:10m rate=1r/s;
server {\n  listen 80;\n  listen [::]:80;\n  server_name rubricasignature.com;
location /auth/ { proxy_pass http://auth-api:8000; }
location / { root /usr/share/nginx/html; }
}
'''
MAINTENANCE = '''server {\nlisten 80;\nlisten [::]:80;\nserver_name _;
location = /billing/webhooks/stripe { proxy_pass http://core-api:8000; }
location = /ngsw.json { return 404; }
location / { return 503 "maintenance"; }
}
'''


def test_configs_expose_only_staging_and_internal_probe_and_keep_maintenance(tmp_path):
    switch.configs(ORIGINAL, MAINTENANCE, tmp_path)
    result = (tmp_path/"web-diagnostic.template").read_text()
    assert "server_name staging.rubricasignature.com web;" in result
    assert "listen 80 default_server;" in result and "listen [::]:80 default_server;" in result
    assert 'return 503 "maintenance"' in result and "/billing/webhooks/stripe" in result
    assert "/ngsw.json" in result
    overlay = json.loads((tmp_path/"domain.json").read_text())["services"]
    assert set(overlay) == set(switch.SERVICES)
    assert overlay["core-api"]["environment"]["PUBLIC_WEB_URL"] == "https://"+switch.DOMAIN
    assert (tmp_path/"web-maintenance.template").read_text().find("return 503") > 0
    assert (tmp_path/"web-original.conf").read_text() == ORIGINAL
    assert all(path.stat().st_mode & 0o077 == 0 for path in tmp_path.iterdir())


@pytest.mark.parametrize("original,maintenance", [(ORIGINAL, "server {}"), (MAINTENANCE, MAINTENANCE),
    (ORIGINAL+ORIGINAL, MAINTENANCE)])
def test_configs_refuse_missing_maintenance_or_invalid_original(tmp_path, original, maintenance):
    with pytest.raises(ValueError):
        switch.configs(original, maintenance, tmp_path)


def setup_validation(tmp_path, monkeypatch):
    metadata = {"images": {service: "sha256:"+service for service in switch.SERVICES},
        "bindings": {service: {"POSTGRES_HOST": "postgres", "CORE_POSTGRES_DB": "rubrica_core"}
            for service in ("auth-api", "core-api")},
        "mounts": {service: {"/run/secrets/postgres_password": "/etc/rubrica/secrets/postgres_password"}
            for service in switch.SERVICES}}
    (tmp_path/"state.json").write_text(json.dumps(metadata))
    config = {"services": {service: {"image": metadata["images"][service],
        "environment": metadata["bindings"].get(service, {}) | {"ENVIRONMENT": "production"},
        "secrets": [{"source": "postgres_password", "target": "postgres_password"}]} for service in switch.SERVICES},
        "secrets": {"postgres_password": {"file": "/etc/rubrica/secrets/postgres_password"}}}
    monkeypatch.setattr(switch, "compose", lambda *a, **kw: json.dumps(config))
    monkeypatch.setattr(switch, "inspect_value", lambda container, template: metadata["images"][container.removeprefix("rubrica-prod-").removesuffix("-1")])
    return config


@pytest.mark.parametrize("drift", ["database", "secret", "image", "environment"])
def test_validation_refuses_drift_before_touching_containers(tmp_path, monkeypatch, drift):
    config = setup_validation(tmp_path, monkeypatch)
    if drift == "database":
        config["services"]["core-api"]["environment"]["CORE_POSTGRES_DB"] = "staging_database"
    elif drift == "secret":
        config["secrets"]["postgres_password"]["file"] = "/some/staging/secret"
    elif drift == "image":
        config["services"]["web"]["image"] = "new-image"
    else:
        config["services"]["auth-api"]["environment"]["ENVIRONMENT"] = "staging"
    with pytest.raises(ValueError):
        switch.validate(tmp_path)


def test_apply_stops_only_old_staging_apps_keeps_tunnel_and_does_not_build(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(switch, "validate", lambda _: {})
    def run(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("docker", "ps"):
            return "stage-app\nstage-tunnel\n"
        return ""
    monkeypatch.setattr(switch, "run", run)
    def inspect(container, template):
        if container == "rubrica-prod-gateway-1":
            return "{}"
        return "cloudflared" if container == "stage-tunnel" else "core-api"
    monkeypatch.setattr(switch, "inspect_value", inspect)
    monkeypatch.setattr(switch, "compose", lambda *args, **kwargs: calls.append(("compose", *args)))
    switch.apply(tmp_path)
    assert ("docker", "stop", "stage-app") in calls
    assert not any(args[:2] == ("docker", "stop") and "stage-tunnel" in args for args in calls)
    apply = next(args for args in calls if args[0] == "compose")
    assert "--no-build" in apply and "--pull" in apply and "never" in apply
    assert not any("postgres" in args or "down" in args or "build" in args for args in calls)
    assert ("docker", "network", "connect", "--alias", "gateway", switch.NETWORK, "rubrica-prod-gateway-1") in calls


def test_rollback_keeps_maintenance_and_does_not_restart_old_staging(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(switch, "validate", lambda _: {})
    monkeypatch.setattr(switch, "compose", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(switch, "inspect_value", lambda *args: json.dumps({switch.NETWORK: {}}))
    monkeypatch.setattr(switch, "run", lambda *args, **kwargs: calls.append(args))
    switch.rollback(tmp_path)
    assert calls[0][1] == "maintenance.json"
    assert ("docker", "network", "disconnect", switch.NETWORK, "rubrica-prod-gateway-1") in calls
    assert not any("start" in args or "postgres" in args for args in calls)


def test_apply_has_no_docker_mutation_when_preflight_fails(tmp_path, monkeypatch):
    calls = []
    def invalid(_):
        raise ValueError("preflight failed")
    monkeypatch.setattr(switch, "validate", invalid)
    monkeypatch.setattr(switch, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError):
        switch.apply(tmp_path)
    assert not calls
