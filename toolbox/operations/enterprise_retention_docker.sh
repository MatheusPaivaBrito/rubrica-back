#!/usr/bin/env bash
# Explicit operator job: Docker socket access is privileged; never expose this via HTTP.
set -euo pipefail
umask 077
: "${RUBRICA_BACKUP_CONFIG:?Set the absolute path of this environment dedicated backup config}"
: "${RUBRICA_PROJECT_DIR:?Set the absolute Rubrica backend checkout path}"
: "${RUBRICA_BACKUP_SECRETS_DIR:?Set this environment absolute secrets directory}"
: "${BACKUP_ROOT:?Set the dedicated absolute local backup archive directory}"
: "${RUBRICA_BACKUP_NETWORK:?Set the Core internal Docker network for this environment}"
for directory in "$RUBRICA_PROJECT_DIR" "$RUBRICA_BACKUP_SECRETS_DIR" "$BACKUP_ROOT"; do
  [[ "$directory" = /* && -d "$directory" && "$directory" != / ]] || { echo '[error] Existing absolute dedicated directories required' >&2; exit 2; }
done
[[ "$RUBRICA_BACKUP_CONFIG" = /* && -f "$RUBRICA_BACKUP_CONFIG" ]] || exit 2
[[ -S /var/run/docker.sock ]] || { echo '[error] Docker socket is required' >&2; exit 2; }
image="rubrica-enterprise-retention-tools:local"
docker build -t "$image" -f "$RUBRICA_PROJECT_DIR/toolbox/operations/enterprise-retention.Dockerfile" "$RUBRICA_PROJECT_DIR"
docker run --rm --read-only --cap-drop=ALL --security-opt=no-new-privileges --pids-limit=64 \
  --memory=768m --cpus=1 --tmpfs /tmp:size=128m,mode=1777 \
  --network "$RUBRICA_BACKUP_NETWORK" \
  --mount "type=bind,src=$RUBRICA_PROJECT_DIR,dst=$RUBRICA_PROJECT_DIR,readonly" \
  --mount "type=bind,src=$RUBRICA_BACKUP_CONFIG,dst=$RUBRICA_BACKUP_CONFIG,readonly" \
  --mount "type=bind,src=$RUBRICA_BACKUP_SECRETS_DIR,dst=$RUBRICA_BACKUP_SECRETS_DIR,readonly" \
  --mount "type=bind,src=$BACKUP_ROOT,dst=$BACKUP_ROOT" \
  --mount type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock \
  --env "RUBRICA_BACKUP_CONFIG=$RUBRICA_BACKUP_CONFIG" \
  --env "RUBRICA_PROJECT_DIR=$RUBRICA_PROJECT_DIR" --env "BACKUP_ROOT=$BACKUP_ROOT" \
  --workdir "$RUBRICA_PROJECT_DIR" "$image" \
  bash toolbox/operations/r2_backup.sh retention "$@"
