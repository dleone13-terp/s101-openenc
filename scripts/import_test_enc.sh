#!/usr/bin/env bash
# import_test_enc.sh
# Imports all S-57 ENC cells from test_encs/ into PostGIS under the raw_s57 schema.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Environment variables are injected by docker-compose via .devcontainer/.env

# ogr2ogr reads PGPASSWORD from the environment automatically
export PGPASSWORD="$POSTGRES_PASSWORD"

PG_DSN="host=$POSTGRES_HOSTNAME port=$POSTGRES_PORT dbname=$POSTGRES_DB user=$POSTGRES_USER password=$POSTGRES_PASSWORD"
TARGET_SCHEMA="raw_s57"
ENC_DIR="$REPO_ROOT/test_encs"

# ---------------------------------------------------------------------------
# Ensure the target schema exists
# ---------------------------------------------------------------------------
echo "Creating schema '$TARGET_SCHEMA' if it does not already exist..."
psql \
  --host="$POSTGRES_HOSTNAME" \
  --port="$POSTGRES_PORT" \
  --username="$POSTGRES_USER" \
  --dbname="$POSTGRES_DB" \
  --command="CREATE SCHEMA IF NOT EXISTS $TARGET_SCHEMA;"

# ---------------------------------------------------------------------------
# Find all base S-57 cell files (.000 extension = the primary exchange set)
# ---------------------------------------------------------------------------
mapfile -t S57_FILES < <(find "$ENC_DIR" -maxdepth 3 -iname "*.000" | sort)

if [[ ${#S57_FILES[@]} -eq 0 ]]; then
  echo "No .000 S-57 cell files found under $ENC_DIR" >&2
  exit 1
fi

echo "Found ${#S57_FILES[@]} S-57 cell file(s) to import."

# ---------------------------------------------------------------------------
# Common ogr2ogr options for S-57 import
# ---------------------------------------------------------------------------
OGR_S57_OPTIONS="RETURN_PRIMITIVES=ON,RETURN_LINKAGES=ON,LNAM_REFS=ON,SPLIT_MULTIPOINT=ON,ADD_SOUNDG_DEPTH=ON"

# ---------------------------------------------------------------------------
# Import each cell
# ---------------------------------------------------------------------------
FIRST=true
for CELL in "${S57_FILES[@]}"; do
  CELL_NAME="$(basename "$CELL")"
  echo ""
  echo "Importing: $CELL_NAME"

  if [[ "$FIRST" == true ]]; then
    # First file: create/overwrite tables in the schema
    APPEND_FLAG=""
    FIRST=false
  else
    # Subsequent files: append into existing tables
    APPEND_FLAG="-append"
  fi

  ogr2ogr \
    -f "PostgreSQL" \
    "PG:$PG_DSN" \
    --config OGR_S57_OPTIONS "$OGR_S57_OPTIONS" \
    -lco SCHEMA="$TARGET_SCHEMA" \
    -lco GEOMETRY_NAME=geom \
    -lco FID=ogc_fid \
    -lco PRECISION=NO \
    -nlt PROMOTE_TO_MULTI \
    -t_srs EPSG:4326 \
    -overwrite \
    $APPEND_FLAG \
    "$CELL"

  echo "  Done: $CELL_NAME"
done

echo ""
echo "Import complete. All cells loaded into schema '$TARGET_SCHEMA' in database '$POSTGRES_DB'."
