#!/usr/bin/env bash
set -euo pipefail

compose_file="${COMPOSE_FILE:-docker-compose.yml}"
env_file="${ENV_FILE:-.env}"
project_name="${COMPOSE_PROJECT_NAME:-rubrica}"
backup_root="${1:-backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="${backup_root%/}/${timestamp}"

if [[ -e "${target}" ]]; then
  echo "[error] Backup target already exists: ${target}" >&2
  exit 1
fi
if [[ ! -f "${compose_file}" || ! -f "${env_file}" ]]; then
  echo "[error] Compose or environment file not found" >&2
  exit 1
fi

mkdir -p "${target}"
cleanup_incomplete() {
  if [[ ! -f "${target}/SHA256SUMS" ]]; then
    echo "[error] Incomplete backup kept for inspection: ${target}" >&2
  fi
}
trap cleanup_incomplete EXIT

compose=(docker compose --project-name "${project_name}" --env-file "${env_file}" -f "${compose_file}")
"${compose[@]}" ps --status running postgres core-api >/dev/null

"${compose[@]}" exec -T postgres sh -ec '
  work="$(mktemp -d)"
  trap "rm -rf -- $work" EXIT
  pg_dumpall --roles-only --username "$POSTGRES_USER" > "$work/roles.sql"
  databases="$POSTGRES_DB,$POSTGRES_MULTIPLE_DATABASES"
  old_ifs="$IFS"
  IFS=","
  for database in $databases; do
    IFS="$old_ifs"
    database="$(printf "%s" "$database" | xargs)"
    [ -n "$database" ] || continue
    case "$database" in *[!A-Za-z0-9_-]*) echo "unsafe database name" >&2; exit 1;; esac
    pg_dump --format=custom --no-owner --no-acl --username "$POSTGRES_USER" --dbname "$database" --file "$work/$database.dump"
    IFS=","
  done
  IFS="$old_ifs"
  tar -C "$work" -czf - .
' > "${target}/databases.tar.gz"

"${compose[@]}" exec -T core-api \
  tar -C /var/lib/rubrica/documents -czf - . > "${target}/documents.tar.gz"

{
  echo "created_at=${timestamp}"
  echo "compose_project=${project_name}"
  echo "compose_file=${compose_file}"
  echo "database_format=pg_dump_custom"
  echo "documents_format=tar_gzip"
} > "${target}/manifest.txt"

(
  cd "${target}"
  sha256sum databases.tar.gz documents.tar.gz manifest.txt > SHA256SUMS
)
chmod -R go-rwx "${target}"
trap - EXIT
echo "[ok] Backup created: ${target}"
