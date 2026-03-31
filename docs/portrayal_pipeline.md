# Portrayal Pipeline (DepthArea pilot)

This pipeline runs the S-101 Lua portrayal catalogue against S-57 data imported into PostGIS and stores the resulting Drawing Instructions (DEF string) back into the ENC tables. The initial pilot is limited to **DepthArea** features.

## Prerequisites
- PostGIS database reachable via the usual env vars (`POSTGRES_HOSTNAME`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`). Defaults are set for the devcontainer.
- S-57 cells imported into `raw_s57` using `scripts/import_test_enc.sh`.
- Python packages: `psycopg2-binary`, `lupa` (Lua bridge). Install with `pip install psycopg2-binary lupa` in the dev environment.

## Schema updates
- `db/schema.sql` now includes a `di_def` TEXT column on all `enc_*` tables to hold the full DEF string emitted by the Lua rules.
- A patch is provided at `db/patches/001_add_di_def.sql` to alter existing databases.

## How to run (DepthArea only)
1. Import test data (optional):
   ```bash
   ./scripts/import_test_enc.sh
   ```
2. Run portrayal for DepthArea and write DEF strings:
   ```bash
   ./scripts/portray_deptharea.py --limit 50 --cell US3WA01M
   ```
   - `--cell` prefixes the FOID and is stored in `cell_file` (helpful when the raw table lacks a cell name column).
   - `--limit` lets you start small for quick validation.
   - `--apply` commits DB writes; omit to dry-run.

The script queries `raw_s57.depare`, maps `drval1/drval2` to S-101 `depthRangeMinimumValue/MaximumValue`, runs the Lua catalogue via `PortrayalHost`, and writes the emitted DEF string into `raw_s57.depare.di_def`.

## Files of interest
- `portrayal_engine/host.py` — minimal S-101 host implementation that executes `PortrayalMain` from the catalogue and captures DEF strings.
- `portrayal_engine/postgis_io.py` — generic PostGIS feature source, DB sink, and stdout sink helpers.
- `scripts/portray_deptharea.py` — CLI entry point for portraying DepthArea and persisting DEF strings.
- `portrayal/PortrayalCatalog/Rules/` — official S-101 portrayal catalogue (Lua).

## Limitations / next steps
- Spatial associations are stubbed to a single surface placeholder per feature; this is enough to run the catalogue but does not yet expose detailed boundary associations. If boundary-driven styling differences are needed, enhance `HostGetSpatial`/`HostFeatureGetSpatialAssociations` to build full rings/curves from geometry.
- Only DepthArea is wired; add more adapters for additional features (e.g., CardinalBeacon, Wreck) by mapping raw attributes to S-101 names and reusing `PortrayalHost`.
- DEF parsing back into the `di_*` columns is not yet performed; only `di_def` is populated in this pilot.
