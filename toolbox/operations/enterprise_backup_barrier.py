"""Compact declared Rubrica restic history after an API erasure barrier.

Dry run is default. Apply requires an explicit destructive-history confirmation,
a fresh checked backup and complete removal of pre-barrier snapshots/archives.
"""
import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from tempfile import NamedTemporaryFile

import httpx


def parse_time(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Backup timestamps must have a timezone")
    return result.astimezone(UTC)


def obsolete_snapshots(snapshots, barrier, tag):
    result = []
    for snapshot in snapshots:
        if tag not in snapshot.get("tags", []):
            raise ValueError("The declared repository contains snapshots outside this Rubrica environment")
        identity = snapshot.get("id", "")
        if not re.fullmatch(r"[a-f0-9]{64}", identity):
            raise ValueError("Invalid snapshot identity")
        if source_started_at(snapshot) < barrier:
            result.append(identity)
    return result


def source_started_at(snapshot):
    # Uploading an old dump today does not make its contents post-erasure.
    starts = [parse_time(snapshot["time"])]
    if not snapshot.get("paths"):
        return datetime.min.replace(tzinfo=UTC)
    for path in snapshot["paths"]:
        name = Path(path).name
        if not re.fullmatch(r"\d{8}T\d{6}Z", name):
            return datetime.min.replace(tzinfo=UTC)
        starts.append(datetime.strptime(name, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC))
    return min(starts)


def managed_archives(root, barrier, *, preserve=None, project="rubrica"):
    root = Path(root).resolve(strict=True)
    if root in {Path("/"), Path.home(), Path.cwd()}:
        raise ValueError("A dedicated backup archive directory is required")
    selected = []
    for entry in root.iterdir():
        if entry.name.startswith(".") and entry.name.endswith(".lock"):
            continue
        if entry.is_symlink() or not entry.is_dir() or not re.fullmatch(r"\d{8}T\d{6}Z", entry.name):
            raise ValueError("Unmanaged archive content requires an explicit inventory adapter")
        manifest = entry / "manifest.txt"
        checksums = entry / "SHA256SUMS"
        if not manifest.is_file() or not checksums.is_file() or manifest.is_symlink() or checksums.is_symlink():
            raise ValueError("Archive ownership/checksum manifest is missing")
        metadata = dict(line.split("=", 1) for line in manifest.read_text().splitlines() if "=" in line)
        if metadata.get("compose_project") != project:
            raise ValueError("Archive belongs to a different Compose project")
        created = datetime.strptime(entry.name, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if created <= barrier and (preserve is None or entry.resolve() != Path(preserve).resolve()):
            selected.append(entry)
    return selected


def restic(*args, output=False):
    command = ["restic", "--repo", os.environ["RESTIC_REPOSITORY"], "--password-file", os.environ["RESTIC_PASSWORD_FILE"], *args]
    result = subprocess.run(command, check=True, capture_output=output, text=True)
    return json.loads(result.stdout) if output else None


def run(*, apply=False, confirmation=""):
    environment = os.environ["RUBRICA_BACKUP_ENVIRONMENT"]
    if environment not in {"development", "staging", "production"}:
        raise ValueError("Explicit Rubrica backup environment required")
    repository_identity = sha256(os.environ["RESTIC_REPOSITORY"].encode()).hexdigest()
    key = Path(os.environ["CORE_INTERNAL_SERVICE_KEY_FILE"]).read_text().strip()
    if not key:
        raise ValueError("Backup service key is empty")
    headers = {"X-Rubrica-Service": "retention_worker", "X-Rubrica-Service-Key": key}
    base = os.environ["ENTERPRISE_CORE_INTERNAL_URL"].rstrip("/") + "/internal/enterprise/backup-retention"
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        response = client.get(f"{base}/pending", headers=headers)
        response.raise_for_status()
        pending = response.json()
        if pending["environment"] != environment or repository_identity not in pending["repository_identities"]:
            raise ValueError("Repository inventory/environment is not registered in Core")
        if not pending["closures"]:
            return {"pending_closures": 0, "repository_identity": repository_identity}
        barrier = max(parse_time(item["barrier"]) for item in pending["closures"])
        if barrier > datetime.now(UTC):
            raise ValueError("Core/backup clocks must agree before retention compaction")
        snapshots = restic("snapshots", "--json", output=True)
        obsolete = obsolete_snapshots(snapshots, barrier, f"rubrica-{environment}")
        root = Path(os.environ["BACKUP_ROOT"]).resolve(strict=True)
        project = os.environ.get("COMPOSE_PROJECT_NAME", "rubrica")
        archives = managed_archives(root, barrier, project=project)
        summary = {"pending_closures": len(pending["closures"]), "obsolete_snapshots": len(obsolete),
                   "obsolete_local_archives": len(archives), "repository_identity": repository_identity}
        if not apply:
            return {"mode": "dry-run", **summary}
        if confirmation != "REPLACE_PRE_ERASURE_BACKUP_HISTORY":
            raise ValueError("Explicit backup history replacement confirmation required")
        if barrier.microsecond and datetime.now(UTC).replace(microsecond=0) <= barrier:
            time.sleep(1)
        # A shared database dump cannot be selectively edited inside an encrypted
        # snapshot. Preserve a new clean snapshot before removing older history.
        with NamedTemporaryFile() as path_file:
            subprocess.run(["toolbox/operations/backup.sh", str(root)], check=True,
                env=os.environ | {"BACKUP_PATH_OUTPUT": path_file.name, "BACKUP_INCLUDE_DOCUMENTS": "0"})
            fresh = Path(Path(path_file.name).read_text().strip()).resolve(strict=True)
        fresh.relative_to(root)
        subprocess.run(["sha256sum", "--check", "SHA256SUMS"], cwd=fresh, check=True, capture_output=True)
        restic("backup", "--tag", f"rubrica-{environment}", str(fresh))
        restic("check")
        snapshots = restic("snapshots", "--json", output=True)
        old = obsolete_snapshots(snapshots, barrier, f"rubrica-{environment}")
        clean = [snapshot for snapshot in snapshots if source_started_at(snapshot) >= barrier]
        if not clean:
            raise ValueError("A clean post-erasure snapshot was not verified")
        for identity in old:
            restic("forget", identity)
        restic("prune")
        restic("check")
        remaining = restic("snapshots", "--json", output=True)
        if not remaining or obsolete_snapshots(remaining, barrier, f"rubrica-{environment}"):
            raise ValueError("Pre-erasure snapshots remain; do not acknowledge erasure")
        for archive in managed_archives(root, barrier, preserve=fresh, project=project):
            shutil.rmtree(archive)
        oldest = min(source_started_at(snapshot) for snapshot in remaining)
        newest = max(remaining, key=lambda snapshot: parse_time(snapshot["time"]))
        for item in pending["closures"]:
            result = client.post(f"{base}/{item['closure_id']}/acknowledge", headers=headers, json={
                "environment": environment, "repository_identity": repository_identity, "snapshot_id": newest["id"],
                "snapshot_started_at": newest["time"], "oldest_retained_snapshot_at": oldest.isoformat(),
                "compacted_and_checked": True, "local_archives_removed": True, "current_objects_verified": True})
            result.raise_for_status()
        return {"mode": "apply", **summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    print(json.dumps(run(apply=args.apply, confirmation=args.confirm), sort_keys=True))


if __name__ == "__main__":
    main()
