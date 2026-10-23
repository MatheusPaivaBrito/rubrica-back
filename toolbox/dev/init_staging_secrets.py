"""Explicitly create non-production staging secrets without overwriting files."""

from __future__ import annotations

import secrets
import os
from pathlib import Path

from toolbox.checks.production_readiness import read_env
from toolbox.checks.staging_readiness import REQUIRED_SECRETS, staging_secrets_dir


def main() -> None:
    env_path = Path(os.environ.get("STAGING_ENV_FILE", ".env.staging"))
    if not env_path.is_file():
        raise SystemExit("[error] .env.staging is missing; copy .env.staging.example first")
    root = staging_secrets_dir(read_env(env_path).get("SECRETS_DIR", "../.secrets/staging"))
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    for name in REQUIRED_SECRETS:
        path = root / name
        if path.exists():
            continue
        prefix = "sk_test_" if name == "stripe_secret_key" else "staging_"
        path.write_text(prefix + secrets.token_urlsafe(48), encoding="utf-8")
        path.chmod(0o600)
        print(f"[created] {path}")
    print("[ok] staging-only secrets initialized; existing files were preserved")


if __name__ == "__main__":
    main()
