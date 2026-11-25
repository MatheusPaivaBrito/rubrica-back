from hashlib import sha256
from pathlib import Path
import subprocess
import tarfile

import pytest


@pytest.mark.parametrize("corrupt", [False, True])
def test_document_backup_verifier_rejects_objects_changed_after_manifest(tmp_path, corrupt):
    document = tmp_path / "fixture.pdf"
    document.write_bytes(b"%PDF-test")
    archive = tmp_path / "documents.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(document, arcname=document.name)
    digest = sha256(archive.read_bytes()).hexdigest()
    (tmp_path / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")
    if corrupt:
        archive.write_bytes(archive.read_bytes() + b"tampered")
    script = Path(__file__).resolve().parents[1] / "toolbox/operations/verify_backup.sh"
    result = subprocess.run(["bash", script, tmp_path], capture_output=True, text=True, timeout=10)
    assert result.returncode == int(corrupt)
    assert ("document archive readable" in result.stdout) is not corrupt
