#!/usr/bin/env bash
set -euo pipefail
umask 077

compose_file="${COMPOSE_FILE:-compose/local.yml}"
env_file="${ENV_FILE:-.env}"
project_name="${COMPOSE_PROJECT_NAME:-rubrica}"
backup_root="${1:-backups}"
include_databases="${BACKUP_INCLUDE_DATABASES:-1}"
include_documents="${BACKUP_INCLUDE_DOCUMENTS:-1}"
database_selector="${BACKUP_DATABASE:-all}"
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
if [[ "$include_databases" != "1" && "$include_documents" != "1" ]]; then
  echo "[error] Backup must include databases, files, or both" >&2
  exit 2
fi

if [[ "$include_databases" == "1" ]]; then
  case "$database_selector" in
    all|core|auth|eventing|notification) ;;
    *) echo "[error] Unknown database: $database_selector (use all, core, auth, eventing, or notification)" >&2; exit 2 ;;
  esac
  "${compose[@]}" ps --status running postgres >/dev/null
  "${compose[@]}" exec -T -e BACKUP_DATABASE_SELECTOR="$database_selector" postgres sh -ec '
  work="$(mktemp -d)"
  trap "rm -rf -- $work" EXIT
  pg_dumpall --roles-only --username "$POSTGRES_USER" > "$work/roles.sql"
  databases="$POSTGRES_MULTIPLE_DATABASES"
  if [ "$BACKUP_DATABASE_SELECTOR" != all ]; then
    case "$BACKUP_DATABASE_SELECTOR" in
      core) wanted=1 ;;
      auth) wanted=2 ;;
      eventing) wanted=3 ;;
      notification) wanted=4 ;;
    esac
    selected=""
    position=1
    old_ifs="$IFS"
    IFS=","
    for database in $databases; do
      if [ "$position" -eq "$wanted" ]; then selected="$database"; break; fi
      position=$((position + 1))
    done
    IFS="$old_ifs"
    [ -n "$selected" ] || { echo "database alias is not configured" >&2; exit 1; }
    databases="$selected"
  fi
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
fi

if [[ "$include_documents" == "1" ]]; then
  "${compose[@]}" ps --status running core-api >/dev/null
  "${compose[@]}" exec -T core-api \
    python -m core_api.infrastructure.backup_export > "${target}/documents.tar.gz"
fi

{
  echo "created_at=${timestamp}"
  echo "compose_project=${project_name}"
  echo "compose_file=${compose_file}"
  echo "databases=$([[ -f "${target}/databases.tar.gz" ]] && echo "$database_selector" || echo none)"
  echo "database_format=$([[ -f "${target}/databases.tar.gz" ]] && echo pg_dump_custom || echo none)"
  echo "documents_format=$([[ -f "${target}/documents.tar.gz" ]] && echo verified_object_tar_gzip || echo none)"
} > "${target}/manifest.txt"

(
  cd "${target}"
  files=(manifest.txt)
  [[ ! -f databases.tar.gz ]] || files+=(databases.tar.gz)
  [[ ! -f documents.tar.gz ]] || files+=(documents.tar.gz)
  sha256sum "${files[@]}" > SHA256SUMS
)
chmod -R go-rwx "${target}"
if [[ -n "${BACKUP_PATH_OUTPUT:-}" ]]; then
  printf '%s\n' "${target}" > "$BACKUP_PATH_OUTPUT"
fi
trap - EXIT
echo "[ok] Backup created: ${target}"
