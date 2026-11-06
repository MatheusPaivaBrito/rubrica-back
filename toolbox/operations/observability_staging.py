"""Local-only staging operations. No remote SSH, credential issuance or volume removal."""
import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".runtime/observability-staging"
NAMES = ("platform_token",)


def token_source():
    canonical = RUNTIME/"secrets/platform_token"
    historical = RUNTIME/"secrets/platform_ingest_token"
    return canonical if canonical.exists() or not historical.exists() else historical


def protected_files(names):
    missing = []
    for name in names:
        path = token_source() if name == "platform_token" else RUNTIME/"secrets"/name
        if not path.is_file() or not path.stat().st_size or path.stat().st_mode & 0o077:
            missing.append(name)
    if missing:
        raise ValueError("Install protected staging files (0600): "+", ".join(missing))


def compose(*args, remote=False, capture=False):
    command = ["docker", "compose", "--project-name", "rubrica-observability-staging-local", "--env-file", str(RUNTIME/"runtime.env"),
        "-f", str(ROOT/"compose/observability-staging-local.yml")]
    if remote:
        command += ["-f", str(ROOT/"compose/features/observability-platform.yml")]
    # Do not inherit exported .env development settings from the root Makefile.
    env = {name: os.environ[name] for name in ("PATH", "HOME", "DOCKER_CONFIG") if name in os.environ}
    env["DOCKER_HOST"] = "unix:///var/run/docker.sock"
    env["OBSERVABILITY_STAGING_SECRETS_DIR"] = str(RUNTIME/"secrets")
    env["OBSERVABILITY_STAGING_PLATFORM_TOKEN_SOURCE"] = str(token_source())
    return subprocess.run(command+list(args), cwd=ROOT, env=env, check=not capture, capture_output=capture, text=capture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "connect", "disconnect", "status", "logs", "ensure", "evidence", "test", "install-secret"])
    parser.add_argument("--name", choices=NAMES, default="platform_token")
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME/"secrets").mkdir(exist_ok=True, mode=0o700)
    (RUNTIME/"secrets").chmod(0o700)
    (RUNTIME/"runtime.env").touch(exist_ok=True)
    if args.action == "install-secret":
        if not args.name or not args.source or not args.source.is_file() or not args.source.stat().st_size:
            parser.error("Use --name NAME --source EXISTING_LOCAL_FILE; do not pass secret contents")
        destination = RUNTIME/"secrets"/args.name
        if args.source.resolve() != destination.resolve():
            # Atomic replacement of a named secret only; never issue/generate a key.
            descriptor, filename = tempfile.mkstemp(prefix=".install-", dir=destination.parent)
            temporary = Path(filename)
            try:
                with os.fdopen(descriptor, "wb") as target, args.source.open("rb") as source:
                    shutil.copyfileobj(source, target)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        destination.chmod(0o600)
        print("[ok] protected staging file installed:", args.name)
        return
    if args.action in {"ensure", "evidence", "test"}:
        result = compose("exec", "-T", "observability-api", "python", "-m", "observability_api.modules.platform_publish."+("validation" if args.action == "test" else "ensure"), capture=True)
        try:
            report = json.loads(result.stdout)
        except (ValueError, TypeError):
            report = {"operational": False, "reason": "ensure_process_unavailable"}
        if args.action == "evidence":
            directory = RUNTIME/"evidence"
            directory.mkdir(exist_ok=True, mode=0o700)
            path = directory/(datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")+".json")
            # Only the allowlisted result of our ensure, never stderr or config.
            path.write_text(json.dumps(report, indent=2)+"\n")
            path.chmod(0o600)
            print("[ok] evidence:", path)
        print(json.dumps(report, sort_keys=True))
        raise SystemExit(0 if result.returncode == 0 and report.get("operational") is True else 2)
    if args.action == "up":
        protected_files(("postgres_password", "observability_internal_service_key"))
        compose("up", "-d", "--wait", "postgres")
        compose("build", "observability-api")
        compose("run", "--rm", "--no-deps", "observability-api", "python", "-m", "alembic", "-c", "apps/observability_api/alembic.ini", "upgrade", "head")
        compose("up", "-d", "--no-deps", "--force-recreate", "--wait", "observability-api")
    elif args.action == "connect":
        protected_files(NAMES)
        compose("up", "-d", "--no-deps", "--force-recreate", "--wait", "observability-api", remote=True)
    elif args.action == "disconnect":
        compose("up", "-d", "--no-deps", "--force-recreate", "--wait", "observability-api")
    elif args.action == "status":
        compose("ps")
    elif args.action == "logs":
        compose("logs", "--tail", "100", "observability-api")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        if isinstance(error, ValueError):
            print("[error]", str(error), file=sys.stderr)
        else:
            print("[error] local staging operation failed; inspect service health", file=sys.stderr)
        raise SystemExit(2) from None
