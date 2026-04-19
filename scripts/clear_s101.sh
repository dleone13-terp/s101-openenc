#!/usr/bin/env bash
set -euo pipefail

# Drop and recreate the s101 schema to clear ingestion output tables.
# Uses POSTGRES_* env vars if set, otherwise defaults to the same values used by injest.
HOST=${POSTGRES_HOSTNAME:-localhost}
PORT=${POSTGRES_PORT:-5432}
DB=${POSTGRES_DB:-postgres}
USER=${POSTGRES_USER:-postgres}
PASS=${POSTGRES_PASSWORD:-postgres}
SCHEMA=${1:-s101}

export PGPASSWORD="$PASS"

psql "host=$HOST port=$PORT dbname=$DB user=$USER" -v ON_ERROR_STOP=1 <<SQL
DROP SCHEMA IF EXISTS "$SCHEMA" CASCADE;
CREATE SCHEMA "$SCHEMA";
SQL

echo "Cleared schema '$SCHEMA' on $HOST:$PORT/$DB"
