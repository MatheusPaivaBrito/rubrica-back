"""Temporarily expose the existing production application through the staging tunnel.

No builds, migrations, seed, secret reads, database copies or public maintenance removal.
Run prepare first, then apply explicitly on the server. Only the operator invokes Docker.
"""
import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DOMAIN = "staging.rubricasignature.com"
NETWORK = "rubrica-staging_rubrica_internal"
SERVICES = ("auth-api", "core-api", "web")
FILES = ("compose/production.yml", "compose/features/r2-documents.yml", "compose/features/serpro-timestamp.yml")
BINDING_FIELDS = ("POSTGRES_USER", "POSTGRES_HOST", "POSTGRES_PORT", "AUTH_POSTGRES_DB", "CORE_POSTGRES_DB",
                  "DOCUMENT_STORAGE_PROVIDER", "DOCUMENT_STORAGE_PATH", "R2_DOCUMENTS_PREFIX")


def run(*args, capture=False):
    # Do not inherit exported development/provider settings from Make or the shell.
    env = {key: os.environ[key] for key in ("PATH", "HOME", "DOCKER_CONFIG") if key in os.environ}
    env["DOCKER_HOST"] = "unix:///var/run/docker.sock"
    return subprocess.run(args, cwd=ROOT, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def inspect_value(container, template):
    return run("docker", "inspect", "--format", template, container, capture=True).strip()


def compose(state, overlay, *args, capture=False):
    cmd = ["docker", "compose", "--project-name", "rubrica-prod", "--env-file", str(ROOT/".env.production")]
    for filename in FILES:
        cmd += ["-f", str(ROOT/filename)]
    cmd += ["-f", str(state/"images.json"), "-f", str(state/overlay)]
    return run(*cmd, *args, capture=capture)


def save(path, value):
    if path.exists():
        raise ValueError("State file already exists; use a new state directory")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(value)


def configs(original, maintenance, state):
    if "return 503" not in maintenance or "/billing/webhooks/stripe" not in maintenance:
        raise ValueError("The public maintenance configuration must already be active")
    if "/auth/" not in original or "return 503" in original:
        raise ValueError("Original application configuration is missing or is not the pre-maintenance backup")
    app, count = re.subn(r"(?m)^(\s*server_name\s+)[^;]+;", rf"\g<1>{DOMAIN} web;", original)
    if count != 1:
        raise ValueError("Expected exactly one application server; inspect the configuration manually")
    # Only the staging hostname (and the internal web health probe) reaches the app.
    maintenance = re.sub(r"listen 80(?: default_server)?;", "listen 80 default_server;", maintenance)
    maintenance = re.sub(r"listen \[::\]:80(?: default_server)?;", "listen [::]:80 default_server;", maintenance)
    save(state/"web-diagnostic.template", app+"\n"+maintenance)
    save(state/"web-maintenance.template", maintenance)
    save(state/"web-original.conf", original)
    domain = {"services": {
        "auth-api": {"environment": {"AUTH_PUBLIC_WEB_URL": f"https://{DOMAIN}"}},
        "core-api": {"environment": {"PUBLIC_WEB_URL": f"https://{DOMAIN}", "SIGNING_APP_URL": f"https://{DOMAIN}/signing"}},
        "web": {"environment": {"RUBRICA_DOMAIN": DOMAIN}, "volumes": [{"type": "bind",
            "source": str(state/"web-diagnostic.template"), "target": "/etc/nginx/templates/default.conf.template", "read_only": True}]},
    }}
    save(state/"domain.json", json.dumps(domain, indent=2)+"\n")
    # This rollback keeps the public application in maintenance; it does not reopen payments.
    rollback = {"services": {"web": {"volumes": [{"type": "bind", "source": str(state/"web-maintenance.template"),
        "target": "/etc/nginx/templates/default.conf.template", "read_only": True}]}}}
    save(state/"maintenance.json", json.dumps(rollback, indent=2)+"\n")


def bindings(container):
    values = {}
    for key in BINDING_FIELDS:
        length = str(len(key)+1)
        template = '{{range .Config.Env}}{{if ge (len .) '+length+'}}{{if eq (slice . 0 '+length+') "'+key+'="}}{{println .}}{{end}}{{end}}{{end}}'
        line = inspect_value(container, template)
        values[key] = line.partition("=")[2] if line else ""
    return values


def validate(state):
    config = json.loads(compose(state, "domain.json", "config", "--format", "json", capture=True))
    metadata = json.loads((state/"state.json").read_text())
    for service in SERVICES:
        proposed = config["services"][service]
        current = inspect_value(f"rubrica-prod-{service}-1", "{{.Image}}")
        if current != metadata["images"][service]:
            raise ValueError("A production image changed since preparation; prepare a new plan")
        if proposed["image"] != metadata["images"][service]:
            raise ValueError("Image drift detected; prepare a new plan")
        if service != "web":
            if proposed.get("environment", {}).get("ENVIRONMENT") != "production":
                raise ValueError("The runtime environment must remain production")
            for key, value in metadata["bindings"][service].items():
                if str(proposed.get("environment", {}).get(key, "") or "") != value:
                    raise ValueError(f"Production storage/database setting differs: {service}/{key}; no switch performed")
        # Match every mounted secret to its existing host source without opening it.
        for secret in proposed.get("secrets", []):
            source = secret["source"] if isinstance(secret, dict) else secret
            target = secret.get("target", source) if isinstance(secret, dict) else source
            target = target if target.startswith("/") else "/run/secrets/"+target
            expected = metadata["mounts"][service].get(target)
            actual = config["secrets"][source].get("file")
            if expected is None or actual is None or os.path.abspath(actual) != os.path.abspath(expected):
                raise ValueError(f"Production secret mount differs: {service}/{source}; no switch performed")
    return metadata


def prepare(state):
    if run("git", "branch", "--show-current", capture=True).strip() != "main":
        raise ValueError("Select main before preparing the production switch")
    if state.exists():
        raise ValueError("State directory already exists; choose a new path")
    run("docker", "network", "inspect", "--format", "{{.Name}}", NETWORK, capture=True)
    if inspect_value("rubrica-staging-cloudflared-1", '{{index .Config.Labels "com.docker.compose.project"}}') != "rubrica-staging":
        raise ValueError("The existing staging tunnel was not identified")
    if inspect_value("rubrica-prod-gateway-1", '{{index .Config.Labels "com.docker.compose.project"}}') != "rubrica-prod":
        raise ValueError("The production gateway was not identified")
    state.mkdir(parents=True, mode=0o700)
    images, mounted, old_bindings = {}, {}, {}
    for service in SERVICES:
        container = f"rubrica-prod-{service}-1"
        if inspect_value(container, '{{index .Config.Labels "com.docker.compose.project"}}') != "rubrica-prod":
            raise ValueError("Unexpected project identity")
        images[service] = inspect_value(container, "{{.Image}}")
        run("docker", "image", "inspect", "--format", "{{.Id}}", images[service], capture=True)
        mounted[service] = json.loads(inspect_value(container, '{{json .Mounts}}'))
        mounted[service] = {item["Destination"]: item["Source"] for item in mounted[service]}
        if service != "web":
            old_bindings[service] = bindings(container)
    original = run("docker", "exec", "rubrica-prod-web-1", "cat", "/tmp/rubrica-before-maintenance.conf", capture=True)
    maintenance = run("docker", "exec", "rubrica-prod-web-1", "cat", "/etc/nginx/conf.d/default.conf", capture=True)
    configs(original, maintenance, state)
    save(state/"images.json", json.dumps({"services": {name: {"image": image, "pull_policy": "never"}
        for name, image in images.items()}}, indent=2)+"\n")
    save(state/"state.json", json.dumps({"prepared_at": datetime.now(UTC).isoformat(),
        "images": images, "bindings": old_bindings, "mounts": mounted}, indent=2)+"\n")
    validate(state)
    # Parse the new Nginx configuration with the exact existing web image before downtime.
    run("docker", "run", "--rm", "--pull=never", "--network", "rubrica-prod_rubrica_internal",
        "--mount", f"type=bind,source={state/'web-diagnostic.template'},target=/etc/nginx/conf.d/default.conf,readonly",
        "--entrypoint", "nginx", images["web"], "-t")
    print("[ok] Prepared: same images, production database/storage bindings and secret sources; no existing container changed")
    print("[ok] State directory:", state)


def apply(state):
    validate(state)
    # Stop every running old staging service except its existing tunnel.
    identities = run("docker", "ps", "-q", "--filter", "label=com.docker.compose.project=rubrica-staging", capture=True).split()
    stopped = []
    for identity in identities:
        service = inspect_value(identity, '{{index .Config.Labels "com.docker.compose.service"}}')
        if service != "cloudflared":
            stopped.append(identity)
    if stopped:
        run("docker", "stop", *stopped)
    networks = json.loads(inspect_value("rubrica-prod-gateway-1", "{{json .NetworkSettings.Networks}}"))
    if NETWORK not in networks:
        run("docker", "network", "connect", "--alias", "gateway", NETWORK, "rubrica-prod-gateway-1")
    compose(state, "domain.json", "up", "-d", "--no-deps", "--no-build", "--pull", "never",
            "--force-recreate", "--wait", *SERVICES)
    run("docker", "start", "rubrica-staging-cloudflared-1")
    run("docker", "exec", "rubrica-prod-web-1", "nginx", "-t")
    print("[ok] Switched application access to https://"+DOMAIN)
    print("[ok] Public maintenance and the Stripe webhook remain configured; no migration/seed/build performed")
    print("[note] Gateway's extra staging network is temporary; do not recreate it or use production-up during this diagnostic")


def rollback(state):
    validate(state)
    compose(state, "maintenance.json", "up", "-d", "--no-deps", "--no-build", "--pull", "never",
            "--force-recreate", "--wait", *SERVICES)
    networks = json.loads(inspect_value("rubrica-prod-gateway-1", "{{json .NetworkSettings.Networks}}"))
    if NETWORK in networks:
        run("docker", "network", "disconnect", NETWORK, "rubrica-prod-gateway-1")
    print("[ok] Original URL settings restored; the public site stays in maintenance and data is not rolled back")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "apply", "rollback"))
    parser.add_argument("--state-dir", required=True, type=Path)
    args = parser.parse_args()
    state = args.state_dir.expanduser().resolve()
    {"prepare": prepare, "apply": apply, "rollback": rollback}[args.action](state)


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print("[error]", str(error))
        raise SystemExit(2) from None
    except (OSError, subprocess.CalledProcessError):
        print("[error] Switch operation failed. Inspect the previous command error and container status; no database restore is performed.")
        raise SystemExit(2) from None
