# Ingestion Runbook

A concise guide to convert S-57 ENCs into minimal S-101 tables and driving portrayal output.

## Overview
- Reads ENC cells directly via the GDAL/OGR S-57 driver (no raw_s57 staging required).
- Maps S-57 object/attribute codes into S-101 names using injest/mappings.py.
- Normalizes geometries to WGS84 and coerces primitives (Surface/Curve/Point) for table targets.
- Optionally runs the S-101 portrayal catalogue to store drawing instructions as JSONB.
- Writes four PostGIS tables: enc_area, enc_line, enc_point, enc_sounding (schema defaults to s101).

## Prerequisites
- Postgres with PostGIS (connection values read from POSTGRES_* env vars, default postgres/postgres@localhost:5432).
- GDAL/OGR with S-57 support (provided in the devcontainer).
- Portrayal assets already present under portrayal/PortrayalCatalog/.
- Devcontainer will auto-create a local `.venv` and install the project in editable mode; use `.venv/bin/python` (or `source .venv/bin/activate`).

## Running the converter
```
# Dry run: parse and portray without writing
.venv/bin/python -m injest.s57_to_s101 test_encs/US3WA01M/US3WA01M.000 --limit 10 --debug

# Apply to PostGIS with default schema (s101)
.venv/bin/python -m injest.s57_to_s101 test_encs/US3WA01M/US3WA01M.000 --apply

# Target a different schema and feature subset
.venv/bin/python -m injest.s57_to_s101 test_encs/US3WA01M/US3WA01M.000 --schema my_s101 --only-feature DEPARE --apply

# Skip portrayal when you only want geometry + attributes
.venv/bin/python -m injest.s57_to_s101 test_encs/US3WA01M/US3WA01M.000 --skip-portrayal --apply
```

Key flags:
- `--apply`: actually write to PostGIS (otherwise print planned inserts).
- `--skip-portrayal`: bypass portrayal and leave di_jsonb null.
- `--only-feature CODE`: filter by S-57 code (e.g., DEPARE, DEPCNT).
- `--limit N`: stop after N features (debugging aid).
- `--debug`: echo raw/mapped attributes and association refs.

## Outputs
- Tables live under the target schema (default `s101`): enc_area, enc_line, enc_point, enc_sounding.
- Each row carries S-57 code, S-101 feature name, FOID, WGS84 geometry, attribute JSON, and optional drawing instruction JSON.

## Smoke check
1. Run with `--apply` against `test_encs/US3WA01M/US3WA01M.000`.
2. Verify row counts per table in Postgres (e.g., `SELECT COUNT(*) FROM s101.enc_area;`).
3. If portrayal is enabled, confirm `di_jsonb` is non-null for populated features.

## Testing runbook
- Full suite: `.venv/bin/pytest -q` (or `pytest -q` after activating the venv).
- Targeted helpers: `.venv/bin/pytest -q tests/test_injest_helpers.py`.
- Optional end-to-end smoke: rerun the converter with `--apply` and inspect PostGIS tables as above.

## Extending mappings
- Add new feature/attribute crosswalks in `injest/mappings.py`.
- Hazard features that need depth defaults are listed in `injest/helpers.py` (HAZARD_CODES).
- Geometry/table metadata lives in `injest/helpers.py` (TABLE_SCHEMAS) and drives DDL creation.
