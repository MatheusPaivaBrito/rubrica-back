#!/usr/bin/env bash
set -euo pipefail
umask 077

config="${RUBRICA_BACKUP_CONFIG:-/etc/rubrica/backup-r2.env}"
[[ -r "$config" ]] || { echo "[error] Missing backup config: $config" >&2; exit 2; }
set -a
# shellcheck disable=SC1090
. "$config"
set +a

: "${RUBRICA_PROJECT_DIR:?RUBRICA_PROJECT_DIR is required}"
: "${R2_ENDPOINT_FILE:?R2_ENDPOINT_FILE is required}"
: "${R2_BACKUP_BUCKET_FILE:?R2_BACKUP_BUCKET_FILE is required}"
for file in "$R2_ENDPOINT_FILE" "$R2_BACKUP_BUCKET_FILE"; do
  [[ -s "$file" ]] || { echo "[error] Missing or empty file: $file" >&2; exit 2; }
done

endpoint="$(tr -d '\r\n' < "$R2_ENDPOINT_FILE")"
bucket="$(tr -d '\r\n' < "$R2_BACKUP_BUCKET_FILE")"
export RESTIC_REPOSITORY="s3:${endpoint%/}/${bucket}/restic"
export BACKUP_INCLUDE_DOCUMENTS=0
export DELETE_LOCAL_AFTER_UPLOAD="${DELETE_LOCAL_AFTER_UPLOAD:-1}"

cd "$RUBRICA_PROJECT_DIR"
exec toolbox/operations/offsite_backup.sh "${1:-create}"
