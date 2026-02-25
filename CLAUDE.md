# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

s101-openenc is a minimal S-101 Electronic Navigation Chart (ENC) to PostGIS/MVT/Mapbox GL pipeline. It transforms nautical chart data from binary S-101 format into web-renderable maps using the official IHO Portrayal Catalogue Lua rules for styling, PostGIS for storage, Martin for MVT tile serving, and Mapbox GL for rendering with three color themes (Day/Dusk/Night).

`claude_oneshot.md` is a comprehensive technical specification (~1100 lines) — read it for detailed design decisions and implementation context.

## Commands

All commands run inside the devcontainer (Python 3.11 + LuaJIT).

```bash
# Generate sprite atlases (Day/Dusk/Night) → sprites/out/
python -m sprites.build_sprites

# Generate Mapbox GL style JSONs → style/out/
python -m style.build_style

# Initialize database schema
psql -h db -U postgres -d postgres < db/schema.sql

# Ingest S-101 cells (requires cell_reader.py, not yet implemented)
python -m injest.lua_host <cell_file>

# Run tests
pytest
```

## Architecture

### Data Pipeline

```
S-101 binary cell
  → cell_reader (not yet in repo) → feature dicts {code, geometry, attributes}
  → LuaHost.portray_feature() [injest/lua_host.py]
      loads portrayal/PortrayalCatalog/Rules/<FeatureCode>.lua
      Lua rule calls HostPortrayalEmit(featureRef, drawingInstructionString)
  → parse_drawing_instructions() [injest/parse_di.py]
      parses semicolon-delimited DI string → DrawingInstructions dataclass
  → Ingester.ingest_feature() [injest/lua_host.py]
      INSERT into PostGIS tables by geometry type
  → PostGIS MVT functions [db/schema.sql]
      tile_enc_*(z,x,y) → ST_AsMVT → .pbf tiles
  → Martin tile server → Mapbox GL client
```

### Key Design Decisions

- **Color tokens stored as strings, not resolved hex**: `di_ac`, `di_lc`, `font_colour` columns store IHO color token names (e.g., `DEPDW`, `CHBLK`). Mapbox GL style JSONs resolve tokens to hex at render time. This means tiles are palette-agnostic — switching Day/Dusk/Night is a single `map.setStyle()` call with no tile re-fetch.

- **Flat columns, not JSONB**: Drawing Instruction fields are individual columns so PostGIS can filter/project efficiently before MVT serialization.

- **Separate tables by geometry type**: `enc_area`, `enc_line`, `enc_point`, `enc_sounding`, `enc_label` — each with its own GIST index and MVT tile function.

- **Fixed portrayal context**: Safety parameters (SafetyContour=30m, etc.) are fixed at ingest time. No runtime context switching.

- **Official Lua rules as source of truth**: The `portrayal/` directory contains the IHO S-101 Portrayal Catalogue. Lua rules are executed by LuaHost via `lupa` (Python↔Lua FFI) with a security sandbox (os/io/debug disabled).

### Drawing Instructions (DI) String Format

Compact semicolon-delimited encoding emitted by Lua portrayal rules:
```
VG:27010;DP:7;AC:DEPDW;LC:DEPSC;SY:BOYCAN81;TX:feature_name,2.7,1.5,3,CHBLK,15
```
Tokens: VG (viewing group), DP (priority), AC (area colour), LC (line colour), SY (symbol), TX (text), AP (area pattern), LS (line style).

### Docker Services

Defined in `.devcontainer/docker-compose.yml`:
- **app**: Python 3.11 dev container
- **db**: PostgreSQL 16 + PostGIS 3.5 (port 5432)
- **martin**: MapLibre Martin tile server (port 3000)
- **adminer**: Database admin UI (port 8080)

Database credentials: `postgres/postgres` on host `db`.

## Key Files

| File | Purpose |
|------|---------|
| `injest/lua_host.py` | LuaHost (Lua runtime + S-100 Part 9 API) and Ingester (PostGIS writer) |
| `injest/parse_di.py` | Drawing Instructions parser (regex → DrawingInstructions dataclass) |
| `sprites/build_sprites.py` | SVG→PNG rasterization via cairosvg + Pillow sprite atlas packing |
| `style/build_style.py` | Generates 3 Mapbox GL style JSONs with match expressions for color tokens |
| `utils/colors.py` | Theme enum + palette loader from portrayal colorProfile.xml |
| `db/schema.sql` | 5 geometry tables + MVT tile functions |
| `portrayal/PortrayalCatalog/Rules/` | One Lua file per S-101 feature type (official IHO rules) |

## Known Gaps

- `cell_reader.py` (S-101 binary → feature dict) is referenced but not yet implemented
- Line styles with embedded symbols are approximated as plain lines
- Light arc/sector geometry computation not yet handled
- Feature associations (e.g., Light associated with Buoy) not yet supported
- Glyph server for Mapbox GL text rendering (Roboto Bold/Regular) not configured
