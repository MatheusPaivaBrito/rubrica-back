#!/usr/bin/env bash
set -euo pipefail

if [ -z "${POSTGRES_MULTIPLE_DATABASES:-}" ]; then
  exit 0
fi

echo "Creating databases: ${POSTGRES_MULTIPLE_DATABASES}"

for database in $(echo "${POSTGRES_MULTIPLE_DATABASES}" | tr ',' ' '); do
  database="$(echo "${database}" | xargs)"
  if [ -z "${database}" ]; then
    continue
  fi

  if ! psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" --tuples-only --no-align --command "SELECT 1 FROM pg_database WHERE datname = '${database}'" | grep -qx 1; then
    psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" --command "CREATE DATABASE \"${database}\""
  fi
done
