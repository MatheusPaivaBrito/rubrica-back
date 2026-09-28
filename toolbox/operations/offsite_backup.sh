#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  echo "Usage: RESTIC_REPOSITORY=s3:https://S3-ENDPOINT/BUCKET/PREFIX RESTIC_PASSWORD_FILE=/path/password AWS_ACCESS_KEY_ID_FILE=/path/key-id AWS_SECRET_ACCESS_KEY_FILE=/path/key toolbox/operations/offsite_backup.sh init|create|upload|check|restore [directory]" >&2
  exit 2
}

action="${1:-}"
case "$action" in init|create|upload|check|restore) ;; *) usage ;; esac

for variable in RESTIC_REPOSITORY RESTIC_PASSWORD_FILE AWS_ACCESS_KEY_ID_FILE AWS_SECRET_ACCESS_KEY_FILE; do
  if [[ -z "${!variable:-}" ]]; then
    echo "[error] $variable is required" >&2
    exit 2
  fi
done
if [[ "${RESTIC_REPOSITORY}" != s3:* ]]; then
  echo "[error] RESTIC_REPOSITORY must point to an S3-compatible repository" >&2
  exit 2
fi
for file in "$RESTIC_PASSWORD_FILE" "$AWS_ACCESS_KEY_ID_FILE" "$AWS_SECRET_ACCESS_KEY_FILE"; do
  if [[ ! -s "$file" ]]; then
    echo "[error] Required credential file is missing or empty: $file" >&2
    exit 2
  fi
done
if ! command -v restic >/dev/null; then
  echo "[error] Install restic before running an offsite backup" >&2
  exit 2
fi

export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
AWS_ACCESS_KEY_ID="$(cat "$AWS_ACCESS_KEY_ID_FILE")"
AWS_SECRET_ACCESS_KEY="$(cat "$AWS_SECRET_ACCESS_KEY_FILE")"
restic_cmd=(restic --repository "$RESTIC_REPOSITORY" --password-file "$RESTIC_PASSWORD_FILE")

case "$action" in
  init)
    "${restic_cmd[@]}" init
    ;;
  create)
    command -v flock >/dev/null || { echo "[error] flock is required" >&2; exit 2; }
    lock_file="${BACKUP_ROOT:-backups}/.offsite-backup.lock"
    mkdir -p "$(dirname "$lock_file")"
    exec 9>"$lock_file"
    flock -n 9 || { echo "[error] Another offsite backup is running" >&2; exit 1; }
    path_file="$(mktemp)"
    trap 'rm -f "$path_file"' EXIT
    BACKUP_INCLUDE_DOCUMENTS="${BACKUP_INCLUDE_DOCUMENTS:-1}" BACKUP_PATH_OUTPUT="$path_file" "$(dirname "$0")/backup.sh" "${BACKUP_ROOT:-backups}"
    backup_dir="$(cat "$path_file")"
    (cd "$backup_dir" && sha256sum --check SHA256SUMS)
    "${restic_cmd[@]}" backup --tag rubrica-production "$backup_dir"
    "${restic_cmd[@]}" forget --tag rubrica-production \
      --keep-daily "${RESTIC_KEEP_DAILY:-7}" \
      --keep-weekly "${RESTIC_KEEP_WEEKLY:-4}" \
      --keep-monthly "${RESTIC_KEEP_MONTHLY:-6}" --prune
    if [[ "${DELETE_LOCAL_AFTER_UPLOAD:-0}" == "1" ]]; then
      backup_root="$(cd "${BACKUP_ROOT:-backups}" && pwd)"
      [[ "$backup_dir" == "$backup_root"/* ]] || {
        echo "[error] Refusing to remove backup outside BACKUP_ROOT" >&2
        exit 1
      }
      rm -rf -- "$backup_dir"
    fi
    ;;
  upload)
    backup_dir="${2:-}"
    [[ -n "$backup_dir" && -d "$backup_dir" ]] || usage
    backup_dir="$(cd "$backup_dir" && pwd)"
    (cd "$backup_dir" && sha256sum --check SHA256SUMS)
    "${restic_cmd[@]}" backup --tag rubrica-production "$backup_dir"
    ;;
  check)
    "${restic_cmd[@]}" check
    ;;
  restore)
    target="${2:-}"
    [[ -n "$target" && ! -e "$target" ]] || { echo "[error] Restore target must not exist" >&2; exit 2; }
    "${restic_cmd[@]}" restore latest --target "$target"
    ;;
esac
