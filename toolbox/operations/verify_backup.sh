#!/usr/bin/env bash
set -euo pipefail

backup_dir="${1:-}"
if [[ -z "${backup_dir}" || ! -d "${backup_dir}" ]]; then
  echo "Usage: $0 backups/YYYYmmddTHHMMSSZ" >&2
  exit 2
fi

backup_dir="$(cd "${backup_dir}" && pwd)"
(
  cd "${backup_dir}"
  sha256sum --check SHA256SUMS
)

work="$(mktemp -d)"
container="rubrica-backup-verify-$(date +%s)-$$"
password="temporary-restore-password-$$"
cleanup() {
  docker rm -f "${container}" >/dev/null 2>&1 || true
  rm -rf -- "${work}"
}
trap cleanup EXIT

tar -C "${work}" -xzf "${backup_dir}/databases.tar.gz"
tar -tzf "${backup_dir}/documents.tar.gz" >/dev/null

docker run --detach --name "${container}" \
  --env POSTGRES_PASSWORD="${password}" \
  --volume "${work}:/backup:ro" \
  postgres:16-alpine >/dev/null

for _ in $(seq 1 30); do
  if docker exec "${container}" pg_isready --username postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "${container}" pg_isready --username postgres >/dev/null

if [[ -f "${work}/roles.sql" ]]; then
  docker exec -i "${container}" psql --username postgres --set ON_ERROR_STOP=1 < "${work}/roles.sql"
fi
restored=0
for dump in "${work}"/*.dump; do
  [[ -e "${dump}" ]] || continue
  database="$(basename "${dump}" .dump)"
  case "${database}" in *[!A-Za-z0-9_-]*) echo "[error] Unsafe database name" >&2; exit 1;; esac
  docker exec "${container}" createdb --username postgres "${database}"
  docker exec "${container}" pg_restore --username postgres --dbname "${database}" --exit-on-error "/backup/$(basename "${dump}")"
  restored=$((restored + 1))
done

if [[ "${restored}" -eq 0 ]]; then
  echo "[error] No database dumps found" >&2
  exit 1
fi

echo "[ok] Checksums valid; ${restored} databases restored in an isolated PostgreSQL container; document archive readable"
