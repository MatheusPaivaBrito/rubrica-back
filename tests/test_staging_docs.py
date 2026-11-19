import os
import re
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import urlsplit

import pytest
import yaml

from toolbox.docs import local_accounts

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def portal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("LOCAL_TEST_ACCOUNT_PASSWORD", "fictional-test-password")
    (tmp_path/"docs").symlink_to(ROOT/"docs", target_is_directory=True)
    assets = tmp_path/"toolbox/docs"
    assets.mkdir(parents=True)
    (assets/"assets").symlink_to(ROOT/"toolbox/docs/assets", target_is_directory=True)
    def copy(source, target):
        value = str(source)
        if value.startswith("../rubrica-web/"):
            source = ROOT.parent/"rubrica-front"/value.removeprefix("../rubrica-web/")
        return shutil.copyfile(source, target)
    monkeypatch.setattr(local_accounts, "copyfile", copy)
    legacy = tmp_path/".artifacts/local-docs/accounts.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("obsolete-generated-credentials")
    local_accounts.main()
    return tmp_path/".artifacts/local-docs"


def test_portal_generates_account_subpage_and_preserves_api_link(portal):
    assert "(test-accounts.md)" in (portal/"index.md").read_text()
    assert "(/docs/api/)" in (portal/"index.md").read_text()
    assert "fictional-test-password" in (portal/"test-accounts.md").read_text()
    assert not (portal/"accounts.md").exists()


def test_mkdocs_serves_nested_pages_and_assets_under_docs_prefix(portal, tmp_path):
    config = (ROOT/"mkdocs.local.yml").read_text()
    config = config.replace("docs_dir: .artifacts/local-docs", f"docs_dir: {portal}")
    config = config.replace("site_dir: .artifacts/local-docs-site", f"site_dir: {tmp_path/'site'}")
    config_path = tmp_path/"mkdocs.yml"
    config_path.write_text(config)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ | {"LOCAL_DOCS_SITE_URL": "https://staging.rubricasignature.com/docs/"}
    with (tmp_path/"server.log").open("w+") as log:
        process = subprocess.Popen([sys.executable, "-m", "mkdocs", "serve", "-f", str(config_path),
            "--dev-addr", f"127.0.0.1:{port}", "--no-livereload"], env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic()+25
            while True:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/docs/", timeout=1) as response:
                        home = response.read().decode()
                    break
                except URLError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        log.seek(0)
                        pytest.fail("MkDocs failed to serve its configured prefix: "+log.read()[-1500:])
                    time.sleep(.1)
            canonical = re.search(r'<link rel="canonical" href="([^"]+)"', home)
            assert canonical and urlsplit(canonical.group(1)).path == "/docs/"
            with urlopen(f"http://127.0.0.1:{port}/docs/test-accounts/", timeout=3) as response:
                accounts = response.read().decode()
            assert "fictional-test-password" in accounts
            assert '../assets/local_accounts.css' in accounts
            with urlopen(f"http://127.0.0.1:{port}/docs/assets/local_accounts.css", timeout=3) as response:
                assert "text/css" in response.headers["Content-Type"]
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_staging_healthcheck_matches_mkdocs_mount_path():
    config = yaml.safe_load((ROOT/"compose/staging.yml").read_text())
    service = config["services"]["docs"]
    assert service["environment"]["LOCAL_DOCS_SITE_URL"].endswith("/docs/")
    assert "http://127.0.0.1:8000/docs/" in service["healthcheck"]["test"][-1]
