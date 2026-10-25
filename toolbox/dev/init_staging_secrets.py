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
    values = read_env(env_path)
    root = staging_secrets_dir(values.get("SECRETS_DIR", "../.secrets/staging"))
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    for name in REQUIRED_SECRETS:
        path = root / name
        if path.exists():
            continue
        value = (
            "sk_test_staging_placeholder_replace_me"
            if name == "stripe_secret_key"
            else "staging_" + secrets.token_urlsafe(48)
        )
        path.write_text(value, encoding="utf-8")
        path.chmod(0o600)
        print(f"[created] {path}")
    if values.get("DOCUMENT_STORAGE_PROVIDER") == "r2":
        encryption_key = root / "document_storage_encryption_key"
        if not encryption_key.exists():
            encryption_key.write_text(secrets.token_urlsafe(48), encoding="utf-8")
            encryption_key.chmod(0o600)
            print(f"[created] {encryption_key}")
    print("[ok] staging-only secrets initialized; existing files were preserved")


if __name__ == "__main__":
    main()
