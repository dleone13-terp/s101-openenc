# Martin tileserver prep (sprites + styles)

This repo now includes minimal helpers to feed Martin with palette-specific sprites and Mapbox GL styles derived from S-101 drawing instructions stored in PostGIS.

## Sprites (SVG inputs)
- Script: `sprites/build_sprites.py`
- What it does: copies portrayal catalogue symbol SVGs, rewrites the `xml-stylesheet` to point at the chosen palette CSS (day/dusk/night), copies the CSS alongside, and writes a manifest with basic size metadata and pixel ratios (1x/2x by default).
- Output: `sprites/out/<palette>/` containing `symbols/*.svg`, `day|dusk|nightSvgStyle.css`, and `manifest.json`.
- Run examples:
  - All palettes: `python sprites/build_sprites.py`
  - Only night: `python sprites/build_sprites.py --palette night`

Martin can rasterize these SVGs into `sprite.png`/`sprite@2x.png` as needed. The manifest is informational; packing is left to Martin or an external spriter.

## Styles (Mapbox GL JSON)
- Script: `style/build_style.py`
- What it does: uses `psql` to read distinct drawing-instruction tokens from `s101.enc_area` and `s101.enc_line` (`di_jsonb`), maps tokens to palette colours via the portrayal CSS, and emits Mapbox GL styles with two simple layers (fill, line).
- Assumptions:
  - Martin serves vector layers named `enc_area` and `enc_line` (override with flags).
  - The tile query exposes DI properties named `ColorFill`, `LineColor`, `LineStyle`, `LineWidth` (e.g., `di_jsonb->0->>'ColorFill' AS "ColorFill"`).
  - Sprite URL base points to the output of `sprites/build_sprites.py` (default `/sprites/out`).
- Run examples:
  - All palettes: `python style/build_style.py`
  - Custom DB connection: `python style/build_style.py --db-host db --db-user postgres --db-password postgres --db-name postgres`
  - Only day: `python style/build_style.py --palette day`
- Output: `style/out/enc-day.json`, `enc-dusk.json`, `enc-night.json`.

## Martin container wiring
- The devcontainer docker-compose now includes a `martin` service with:
  - Official Martin image (`ghcr.io/maplibre/martin`) with no custom Martin Dockerfile.
  - Config is static and versioned at `martin/martin.yaml`.
  - Martin reads it with standard CLI usage: `martin --config /etc/martin/martin.yaml`.
  - Devcontainer compose explicitly mounts `martin/`, `sprites/`, `style/`, and `fonts/` into the Martin container as read-only paths.
  - Martin is started with `--config /etc/martin/martin.yaml`.
  - Healthchecks are enabled for both `db` and `martin`, and Martin starts only after DB is healthy.
- Config at [martin/martin.yaml](martin/martin.yaml) defines a PostGIS source `enc` with two layers:
  - `enc_area`, `enc_line`, `enc_point`, and `enc_sounding` are explicitly published from `s101`.
- No setup SQL file is required for Martin startup.
- Start Martin (inside devcontainer workspace root): `docker compose -p s101-openenc_devcontainer -f .devcontainer/docker-compose.yml up -d db martin`.
- Check Martin: `curl http://martin:3000/health` and `curl http://martin:3000/catalog`.

## Important limitation (Martin v1.3)
- Martin v1.3 does not support the older `sources: ... query:` config style used for arbitrary SQL layer queries in YAML.
- With no DB setup SQL, Martin can publish base tables, but flattened DI fields like `ColorFill`/`LineColor` are not directly exposed as first-class properties unless you add DB views/functions.
- Current no-setup-SQL mode is valid and running; style logic that depends on flattened DI keys may require either:
  - SQL views/functions in PostGIS, or
  - client-side handling of `di_jsonb`.

## End-to-end runbook
1. Ensure DB has ENC data:
  - `PGPASSWORD=postgres psql -h db -U postgres -d postgres -c "SELECT count(*) FROM s101.enc_area;"`
  - `PGPASSWORD=postgres psql -h db -U postgres -d postgres -c "SELECT count(*) FROM s101.enc_line;"`
2. Build sprite inputs:
  - `python sprites/build_sprites.py --palette all`
3. Build styles:
  - `python style/build_style.py --db-host db --db-user postgres --db-password postgres --db-name postgres --palette all`
4. Start Martin in compose:
  - `docker compose -p s101-openenc_devcontainer -f .devcontainer/docker-compose.yml up -d db martin`
5. Validate runtime:
  - `curl http://martin:3000/health` should return `OK`
  - `curl http://martin:3000/catalog` should list `enc_area` and `enc_line`
6. Optional tile smoke test:
  - `curl -I http://martin:3000/enc_area/0/0/0`
  - `curl -I http://martin:3000/enc_line/0/0/0`

## Defaults to adjust
- DB: host `db`, user `postgres`, db `postgres`, schema `s101` (flags available).
- Source URL: `martin://enc` (use `--source-url` to point at your service URL).
- Layers: `enc_area`, `enc_line` (override with `--area-layer`/`--line-layer`).
- Fill opacity: 0.85, line width fallback: 0.32mm.

## Next steps
- Wire Martin to serve tiles that surface the DI properties listed above.
- Add point/label layers and symbol references once the tile schema exposes their DI fields.
- Plug sprite packing into your Martin workflow if you want prebuilt `sprite.png`/`sprite@2x.png` assets.
