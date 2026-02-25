# S-101 → PostGIS / MVT / Mapbox GL: Minimal Implementation

## Scope

This document describes the **smallest possible working pipeline** that:
1. Runs the official S-101 Portrayal Catalogue Lua rules as the **only source of styling logic**
2. Stores pre-resolved portrayal output in PostGIS
3. Serves MVT tiles
4. Drives three Mapbox GL style JSONs (day / dusk / night) and matching sprite atlases

Context parameters are **fixed at ingest time** with opinionated defaults. No runtime context switching.

---

## The One Central Insight

The S-101 Lua rules work by calling a host function called `HostPortrayalEmit` once per feature. This function receives a **semicolon-delimited Drawing Instructions string** — a compact encoding of exactly what to draw for that feature. That string is the complete output of all portrayal logic. Every symbol reference, colour token, display priority, viewing group, and text string lives in it.

The job of this pipeline is simply: **run the Lua rules, capture the Drawing Instructions string per feature, parse it, and write the parsed values into PostGIS columns**. Everything downstream (MVT, Mapbox GL style) just reads those columns.

A Drawing Instructions string looks like this:

```
VG:27010;DP:7;AC:DEPDW;LC:DEPSC;SY:BOYCAN81;TX:feature_name,2.7,1.5,3,CHBLK,15
```

Where:
- `VG:27010` — viewing group
- `DP:7` — display priority
- `AC:DEPDW` — area colour fill (colour token)
- `LC:DEPSC` — line colour (colour token)
- `SY:BOYCAN81` — symbol reference
- `TX:...` — text instruction

These instruction codes come directly from the S-101 PC Lua rules via `PortrayalAPI.lua`.

---

## Fixed Context Parameters (Opinionated Defaults)

These are injected once into the Lua state before any rule runs. They never change.

```lua
portrayalContext.ContextParameters = {
    SafetyContour        = 30.0,   -- metres
    SafetyDepth          = 30.0,   -- metres
    ShallowContour       = 5.0,    -- metres
    DeepContour          = 30.0,   -- metres
    DisplayDepthUnits    = 1,      -- 1 = metres
    TwoDepthShades       = false,  -- four shades of blue
    SimplifiedSymbols    = false,  -- traditional (paper-chart) symbols
    DateEnd              = nil,    -- no time filtering
    DateStart            = nil,
}
```

That is it. No per-vessel parameters. No language switching. No display mode toggling during ingest. The rules run once with these values and produce a deterministic output.

---

## Repository Structure

```
s101-ingest/
├── portrayal/                  ← clone of iho-ohi/S-101_Portrayal-Catalogue
│   └── PortrayalCatalog/
│       ├── Rules/              ← *.lua  (one per feature type)
│       ├── symbols/            ← *.svg  (colour-token SVGs)
│       ├── colorProfiles/      ← day/dusk/night palette XMLs
│       └── portrayal_catalogue.xml
│
├── ingest/
│   ├── lua_host.py             ← Python: Lua runner + PostGIS writer
│   ├── parse_di.py             ← Drawing Instructions string parser
│   ├── palette.py              ← Colour token resolver
│   └── cell_reader.py          ← S-101 GML/HDF5 → feature dicts
│
├── sprites/
│   ├── build_sprites.py        ← SVG colour-sub + spritezero runner
│   └── out/
│       ├── day/sprite.{json,png,@2x.png}
│       ├── dusk/sprite.{json,png,@2x.png}
│       └── night/sprite.{json,png,@2x.png}
│
├── style/
│   ├── build_style.py          ← Generates the 3 Mapbox GL style JSONs
│   └── out/
│       ├── enc-day.json
│       ├── enc-dusk.json
│       └── enc-night.json
│
└── db/
    └── schema.sql
```

---

## Step 1 — PostGIS Schema

One table per geometry type. Portrayal output is stored as flat columns, not JSONB, so PostGIS tile functions can filter and project efficiently.

```sql
-- ============================================================
-- AREAS  (polygons: DEPARE, LNDARE, RESARE, DRGARE, ...)
-- ============================================================
CREATE TABLE enc_area (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL,          -- S-101 Feature Object Identifier
    feature_code    TEXT NOT NULL,          -- e.g. 'DepthArea'
    cell_file       TEXT NOT NULL,

    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL,

    -- From Drawing Instructions
    di_vg           INTEGER,               -- viewing group
    di_dp           SMALLINT,              -- display priority
    di_ac           TEXT,                  -- area colour token  e.g. 'DEPDW'
    di_ap           TEXT,                  -- area pattern symbol ref
    di_lc           TEXT,                  -- line colour token
    di_ls           TEXT,                  -- line style reference
    di_lw           NUMERIC(4,1),          -- line width (mm)

    -- Raw important attributes for client-side depth expressions
    drval1          NUMERIC(8,2),
    drval2          NUMERIC(8,2)
);
CREATE INDEX ON enc_area USING GIST (geom);
CREATE INDEX ON enc_area (di_vg);

-- ============================================================
-- LINES  (contours, boundaries, routes, cables, ...)
-- ============================================================
CREATE TABLE enc_line (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL,
    feature_code    TEXT NOT NULL,
    cell_file       TEXT NOT NULL,

    geom            GEOMETRY(MultiLineString, 4326) NOT NULL,

    di_vg           INTEGER,
    di_dp           SMALLINT,
    di_lc           TEXT,                  -- line colour token
    di_ls           TEXT,                  -- line style ref
    di_lw           NUMERIC(4,1),
    di_ac           TEXT                   -- fill colour for closed lines used as area outlines
);
CREATE INDEX ON enc_line USING GIST (geom);
CREATE INDEX ON enc_line (di_vg);

-- ============================================================
-- POINTS  (buoys, lights, beacons, wrecks, obstructions, ...)
-- ============================================================
CREATE TABLE enc_point (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL,
    feature_code    TEXT NOT NULL,
    cell_file       TEXT NOT NULL,

    geom            GEOMETRY(Point, 4326) NOT NULL,

    di_vg           INTEGER,
    di_dp           SMALLINT,
    di_sy           TEXT,                  -- symbol reference  e.g. 'LIGHTS81'
    di_sy_rot       NUMERIC(6,2),          -- symbol rotation degrees (true north)
    di_sy_rot_type  TEXT                   -- 'TrueNorth' | 'PortrayalContext' | NULL
);
CREATE INDEX ON enc_point USING GIST (geom);
CREATE INDEX ON enc_point (di_vg);
CREATE INDEX ON enc_point (di_sy);

-- ============================================================
-- SOUNDINGS  (high-volume, treated separately)
-- ============================================================
CREATE TABLE enc_sounding (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL,
    cell_file       TEXT NOT NULL,
    geom            GEOMETRY(Point, 4326) NOT NULL,
    depth_m         NUMERIC(8,3) NOT NULL,
    di_vg           INTEGER DEFAULT 33022,
    di_dp           SMALLINT DEFAULT 20
);
CREATE INDEX ON enc_sounding USING GIST (geom);

-- ============================================================
-- TEXT LABELS  (separate so they can be independently toggled)
-- ============================================================
CREATE TABLE enc_label (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL,          -- links back to parent feature
    cell_file       TEXT NOT NULL,
    geom            GEOMETRY(Point, 4326) NOT NULL,  -- anchor point

    di_vg           INTEGER,
    di_dp           SMALLINT,
    label_text      TEXT NOT NULL,
    offset_x        NUMERIC(5,2) DEFAULT 0,   -- mm
    offset_y        NUMERIC(5,2) DEFAULT 0,
    font_colour     TEXT,                       -- colour token e.g. 'CHBLK'
    font_size       SMALLINT DEFAULT 10
);
CREATE INDEX ON enc_label USING GIST (geom);
```

---

## Step 2 — Drawing Instructions Parser

The Lua rules emit a semicolon-delimited string via `HostPortrayalEmit`. Parse it into a structured dict.

```python
# ingest/parse_di.py

import re
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class DrawingInstructions:
    """Parsed output of one HostPortrayalEmit call."""
    vg: Optional[int] = None          # ViewingGroup
    dp: Optional[int] = None          # DrawingPriority
    ac: Optional[str] = None          # AreaColour token
    ap: Optional[str] = None          # AreaPattern symbol ref
    lc: Optional[str] = None          # LineColour token
    ls: Optional[str] = None          # LineStyle ref
    lw: Optional[float] = None        # LineWidth mm
    sy: Optional[str] = None          # Symbol reference
    sy_rot: Optional[float] = None    # Symbol rotation degrees
    sy_rot_type: Optional[str] = None
    texts: list = field(default_factory=list)  # list of TextInstruction dicts


def parse_drawing_instructions(di_string: str) -> DrawingInstructions:
    """
    Parse the semicolon-delimited Drawing Instructions string produced
    by the S-101 Portrayal Catalogue Lua rules via HostPortrayalEmit.

    Instruction codes used by S-101 PC:
      VG:<int>                  ViewingGroup
      DP:<int>                  DrawingPriority
      AC:<token>                AreaColour fill token
      AP:<symref>               AreaPattern symbol
      LC:<token>                LineColour token
      LS:<style>,<width>,<token> LineStyle (style name, width mm, colour token)
      SY:<symref>[,<rot>]       Symbol reference, optional rotation degrees
      TX:<text>,<ox>,<oy>,<hjust>,<colour>,<size>  Text
      CS:<proc>                 Conditional symbology procedure (ignore for ingest)
    """
    di = DrawingInstructions()
    if not di_string:
        return di

    for token in di_string.split(';'):
        token = token.strip()
        if not token or ':' not in token:
            continue

        code, _, value = token.partition(':')
        code = code.strip().upper()
        value = value.strip()

        if code == 'VG':
            di.vg = int(value)
        elif code == 'DP':
            di.dp = int(value)
        elif code == 'AC':
            di.ac = value
        elif code == 'AP':
            di.ap = value
        elif code == 'LC':
            di.lc = value
        elif code == 'LS':
            # LS:SOLD,1.0,CHBLK  or  LS:DASH,0.7,CHMGF
            parts = value.split(',')
            di.ls = parts[0] if len(parts) > 0 else None
            di.lw = float(parts[1]) if len(parts) > 1 else None
            di.lc = parts[2] if len(parts) > 2 else di.lc
        elif code == 'SY':
            parts = value.split(',')
            di.sy = parts[0]
            if len(parts) > 1:
                try:
                    di.sy_rot = float(parts[1])
                    di.sy_rot_type = 'TrueNorth'
                except ValueError:
                    di.sy_rot_type = parts[1]
        elif code == 'TX':
            parts = value.split(',', 5)
            di.texts.append({
                'text':   parts[0] if len(parts) > 0 else '',
                'offset_x': float(parts[1]) if len(parts) > 1 else 0.0,
                'offset_y': float(parts[2]) if len(parts) > 2 else 0.0,
                'hjust':  parts[3] if len(parts) > 3 else '1',
                'colour': parts[4] if len(parts) > 4 else 'CHBLK',
                'size':   int(parts[5]) if len(parts) > 5 else 10,
            })
        # CS: conditional symbology - resolved by the Lua rules themselves; ignore here

    return di
```

---

## Step 3 — Lua Host (The Core Engine)

This is the implementation of the **host side** of the S-100 Part 9 Lua portrayal API. The Lua rules call back into this host to emit their output.

```python
# ingest/lua_host.py

import lupa          # pip install lupa  (Python binding to LuaJIT or Lua 5.4)
from pathlib import Path
from parse_di import parse_drawing_instructions, DrawingInstructions
import psycopg2

RULES_DIR = Path('portrayal/PortrayalCatalog/Rules')

# Fixed context parameters — opinionated, never change
FIXED_CONTEXT = {
    'SafetyContour':     30.0,
    'SafetyDepth':       30.0,
    'ShallowContour':    5.0,
    'DeepContour':       30.0,
    'DisplayDepthUnits': 1,
    'TwoDepthShades':    False,
    'SimplifiedSymbols': False,
}


class LuaHost:
    """
    Minimal implementation of the S-100 Part 9 host-side Lua API.

    The Lua rules expect the host to provide:
      - portrayalContext.ContextParameters  (we inject fixed values)
      - portrayalContext.FeaturePortrayalItems  (we inject one feature at a time)
      - HostPortrayalEmit(featureRef, diString, observedParams) callback
      - Debug.Trace / Debug.StartPerformance stubs

    The output we care about is the diString passed to HostPortrayalEmit.
    """

    def __init__(self):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self._emitted: list[tuple[str, str]] = []  # (featureRef, diString)
        self._setup_lua_environment()

    def _setup_lua_environment(self):
        lua = self.lua

        # ---- Security: disable dangerous Lua stdlib ----
        lua.execute("""
            os = nil; io = nil; debug = nil
            package.loadlib = nil; loadfile = nil; dofile = nil
        """)

        # ---- Stub out Debug module ----
        lua.execute("""
            Debug = {}
            function Debug.Trace(msg) end
            function Debug.StartPerformance(label) end
            function Debug.StopPerformance(label) end
        """)

        # ---- Implement HostPortrayalEmit ----
        # This is the single most important host function.
        # The Lua rules call it once per feature with the complete Drawing Instructions string.
        captured = self._emitted
        def host_emit(feature_ref, di_string, observed_params=None):
            captured.append((str(feature_ref), str(di_string) if di_string else ''))
        lua.globals().HostPortrayalEmit = host_emit

        # ---- Stub HostFeatureNameParts (used by GetFeatureName helper in rules) ----
        def host_feature_name(feature_ref):
            return None  # labels from attributes handled in parse_di
        lua.globals().HostFeatureNameParts = host_feature_name

        # ---- Inject fixed context parameters ----
        lua.execute("""
            portrayalContext = {}
            portrayalContext.ContextParameters = {}
        """)
        ctx = lua.globals().portrayalContext.ContextParameters
        for k, v in FIXED_CONTEXT.items():
            ctx[k] = v

        # ---- Load the portrayal catalogue Lua modules ----
        # S100Scripting.lua, PortrayalModel.lua, PortrayalAPI.lua, Default.lua
        # These are the framework files that ship alongside the feature rules.
        for lua_file in ['S100Scripting', 'PortrayalModel', 'PortrayalAPI', 'Default']:
            path = RULES_DIR / f'{lua_file}.lua'
            if path.exists():
                lua.execute(path.read_text())

    def portray_feature(self, feature: dict) -> list[DrawingInstructions]:
        """
        Run the portrayal rule for a single feature and return parsed Drawing Instructions.

        feature dict keys (minimum required):
          'code'        S-101 feature type name e.g. 'DepthArea'
          'id'          feature object identifier string
          'geometry'    geometry type: 'Point' | 'Line' | 'Surface'
          'attributes'  dict of attribute name → value
        """
        self._emitted.clear()

        # Build a Lua feature object
        lua = self.lua
        lua.globals().currentFeature = lua.table(
            Code=feature['code'],
            ID=feature['id'],
            GeometryType=feature.get('geometry', 'Point'),
            Primitive=feature.get('geometry', 'Point'),
        )

        # Inject attributes into the Lua feature object
        attrs_table = lua.table()
        for k, v in feature.get('attributes', {}).items():
            attrs_table[k] = v
        lua.globals().currentFeature.Attributes = attrs_table

        # Load and execute the specific rule file for this feature type
        rule_file = RULES_DIR / f'{feature["code"]}.lua'
        if not rule_file.exists():
            # Fallback: use Default rule
            rule_file = RULES_DIR / 'Default.lua'

        try:
            lua.execute(f"""
                local feature = currentFeature
                local featurePortrayal = {{
                    FeatureReference = feature.ID,
                    DrawingInstructions = {{}}
                }}
                portrayalContext.FeaturePortrayalItems = {{ {{ Feature = feature, Portrayal = featurePortrayal }} }}
            """)
            lua.execute(rule_file.read_text())
        except Exception as e:
            # Rule error: return empty — don't crash the entire ingest
            print(f"  [WARN] Rule error for {feature['code']} id={feature['id']}: {e}")
            return []

        return [parse_drawing_instructions(di) for _, di in self._emitted]


class Ingester:
    """Runs LuaHost over all features and writes results to PostGIS."""

    def __init__(self, db_url: str):
        self.conn = psycopg2.connect(db_url)
        self.host = LuaHost()

    def ingest_feature(self, feature: dict, cell_file: str):
        dis = self.host.portray_feature(feature)
        if not dis:
            return

        # Merge all DIs for this feature (a feature can emit multiple)
        # Last-write-wins for scalar fields; texts accumulate.
        merged = DrawingInstructions()
        all_texts = []
        for di in dis:
            if di.vg is not None:  merged.vg = di.vg
            if di.dp is not None:  merged.dp = di.dp
            if di.ac is not None:  merged.ac = di.ac
            if di.ap is not None:  merged.ap = di.ap
            if di.lc is not None:  merged.lc = di.lc
            if di.ls is not None:  merged.ls = di.ls
            if di.lw is not None:  merged.lw = di.lw
            if di.sy is not None:  merged.sy = di.sy
            if di.sy_rot is not None: merged.sy_rot = di.sy_rot
            if di.sy_rot_type is not None: merged.sy_rot_type = di.sy_rot_type
            all_texts.extend(di.texts)

        geom_type = feature.get('geometry', 'Point')
        wkt       = feature['wkt']  # WKT geometry from cell reader
        foid      = feature['id']
        fcode     = feature['code']

        cur = self.conn.cursor()

        if geom_type == 'Surface':
            cur.execute("""
                INSERT INTO enc_area
                  (foid, feature_code, cell_file, geom,
                   di_vg, di_dp, di_ac, di_ap, di_lc, di_ls, di_lw,
                   drval1, drval2)
                VALUES (%s,%s,%s, ST_Multi(ST_GeomFromText(%s,4326)),
                        %s,%s,%s,%s,%s,%s,%s, %s,%s)
                ON CONFLICT (foid) DO UPDATE SET
                  di_vg=EXCLUDED.di_vg, di_dp=EXCLUDED.di_dp,
                  di_ac=EXCLUDED.di_ac, di_lc=EXCLUDED.di_lc
            """, (
                foid, fcode, cell_file, wkt,
                merged.vg, merged.dp, merged.ac, merged.ap,
                merged.lc, merged.ls, merged.lw,
                feature['attributes'].get('depthRangeMinimumValue'),
                feature['attributes'].get('depthRangeMaximumValue'),
            ))

        elif geom_type == 'Curve':
            cur.execute("""
                INSERT INTO enc_line
                  (foid, feature_code, cell_file, geom,
                   di_vg, di_dp, di_lc, di_ls, di_lw, di_ac)
                VALUES (%s,%s,%s, ST_Multi(ST_GeomFromText(%s,4326)),
                        %s,%s,%s,%s,%s,%s)
                ON CONFLICT (foid) DO UPDATE SET
                  di_vg=EXCLUDED.di_vg, di_dp=EXCLUDED.di_dp,
                  di_lc=EXCLUDED.di_lc
            """, (
                foid, fcode, cell_file, wkt,
                merged.vg, merged.dp, merged.lc, merged.ls, merged.lw, merged.ac,
            ))

        elif geom_type == 'Point':
            if fcode == 'Sounding':
                cur.execute("""
                    INSERT INTO enc_sounding (foid, cell_file, geom, depth_m)
                    VALUES (%s,%s, ST_GeomFromText(%s,4326), %s)
                """, (foid, cell_file, wkt,
                      feature['attributes'].get('valueOfSounding', 0)))
            else:
                cur.execute("""
                    INSERT INTO enc_point
                      (foid, feature_code, cell_file, geom,
                       di_vg, di_dp, di_sy, di_sy_rot, di_sy_rot_type)
                    VALUES (%s,%s,%s, ST_GeomFromText(%s,4326),
                            %s,%s,%s,%s,%s)
                    ON CONFLICT (foid) DO UPDATE SET
                      di_sy=EXCLUDED.di_sy, di_vg=EXCLUDED.di_vg
                """, (
                    foid, fcode, cell_file, wkt,
                    merged.vg, merged.dp, merged.sy, merged.sy_rot, merged.sy_rot_type,
                ))

        # Write text labels
        for txt in all_texts:
            if txt['text']:
                cur.execute("""
                    INSERT INTO enc_label
                      (foid, cell_file, geom, di_vg, di_dp,
                       label_text, offset_x, offset_y, font_colour, font_size)
                    VALUES (%s,%s, ST_GeomFromText(%s,4326), %s,%s, %s,%s,%s,%s,%s)
                """, (
                    foid, cell_file, wkt,
                    merged.vg, merged.dp,
                    txt['text'], txt['offset_x'], txt['offset_y'],
                    txt['colour'], txt['size'],
                ))

        self.conn.commit()
        cur.close()
```

---

## Step 4 — Sprite Builder (SVG → Three Atlases)

The portrayal catalogue SVGs use IHO colour tokens as fill/stroke values. This step substitutes them with real hex values from the three palette XMLs, then compiles sprites.

```python
# sprites/build_sprites.py

import re
import xml.etree.ElementTree as ET
from pathlib import Path
import subprocess

SYMBOLS_DIR = Path('portrayal/PortrayalCatalog/symbols')
PALETTE_DIR = Path('portrayal/PortrayalCatalog/colorProfiles')
OUT_DIR     = Path('sprites/out')

PALETTE_FILES = {
    'day':   'day.xml',    # actual filenames match the catalogue
    'dusk':  'dusk.xml',
    'night': 'night.xml',
}


def load_palette(xml_path: Path) -> dict[str, str]:
    """
    Parse a colour profile XML and return a dict of token → '#RRGGBB'.

    The XML structure in the S-101 PC is:
      <colorProfile>
        <color>
          <token>CHBLK</token>
          <r>0</r><g>0</g><b>0</b>
        </color>
        ...
      </colorProfile>
    (Exact element names vary slightly by PC version; adjust as needed.)
    """
    palette = {}
    tree = ET.parse(xml_path)
    for color in tree.findall('.//color'):
        token = color.findtext('token') or color.findtext('colorToken')
        r = int(color.findtext('r') or color.findtext('red') or 0)
        g = int(color.findtext('g') or color.findtext('green') or 0)
        b = int(color.findtext('b') or color.findtext('blue') or 0)
        if token:
            palette[token.strip()] = f'#{r:02X}{g:02X}{b:02X}'
    return palette


TOKEN_PATTERN = re.compile(
    r'((?:fill|stroke|stop-color|flood-color)\s*[=:]\s*["\']?)([A-Z]{5})(["\']?)'
)

def substitute_svg_colours(svg_text: str, palette: dict[str, str]) -> str:
    """Replace every IHO colour token in an SVG with its palette hex value."""
    def replacer(m):
        prefix, token, suffix = m.group(1), m.group(2), m.group(3)
        colour = palette.get(token, '#FF00FF')  # magenta = missing token (visible error)
        return f'{prefix}{colour}{suffix}'
    return TOKEN_PATTERN.sub(replacer, svg_text)


def build_sprites():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for palette_name, palette_file in PALETTE_FILES.items():
        palette_path = PALETTE_DIR / palette_file
        if not palette_path.exists():
            # Try to find palette by scanning the XML files
            for f in PALETTE_DIR.glob('*.xml'):
                if palette_name.lower() in f.stem.lower():
                    palette_path = f
                    break

        palette = load_palette(palette_path)

        # Output dir for resolved SVGs for this palette
        resolved_dir = OUT_DIR / f'{palette_name}_src'
        resolved_dir.mkdir(exist_ok=True)

        svg_files = list(SYMBOLS_DIR.glob('*.svg'))
        print(f"  Processing {len(svg_files)} symbols for palette '{palette_name}'")

        for svg_path in svg_files:
            resolved_svg = substitute_svg_colours(svg_path.read_text(), palette)
            (resolved_dir / svg_path.name).write_text(resolved_svg)

        # Run spritezero to compile atlas
        sprite_prefix = str(OUT_DIR / palette_name / 'sprite')
        Path(OUT_DIR / palette_name).mkdir(exist_ok=True)

        subprocess.run([
            'spritezero', sprite_prefix, str(resolved_dir)
        ], check=True)

        subprocess.run([
            'spritezero', f'{sprite_prefix}@2x', str(resolved_dir), '--retina'
        ], check=True)

        print(f"  ✓ Sprites for {palette_name}: {sprite_prefix}.{{json,png}}")


if __name__ == '__main__':
    build_sprites()
```

---

## Step 5 — Mapbox GL Style Generator

Generate all three style JSONs. The colour tokens are resolved directly from the palette XMLs into paint properties. Symbol references come from the sprite atlas.

```python
# style/build_style.py

import json
from pathlib import Path
from sprites.build_sprites import load_palette, PALETTE_DIR

TILE_BASE = 'https://tiles.example.com'

# ── Viewing group ranges → IMO display categories ──────────────────────
# Groups are integer IDs. These ranges are from the S-101 PC specification.
DISPLAY_BASE_GROUPS     = list(range(13000, 14999)) + list(range(26010, 26020))
STANDARD_DISPLAY_GROUPS = list(range(20000, 26010)) + list(range(26020, 27999))
OTHER_INFO_GROUPS       = list(range(28000, 40000))

ALL_GROUPS = DISPLAY_BASE_GROUPS + STANDARD_DISPLAY_GROUPS + OTHER_INFO_GROUPS


def hex_to_rgb_string(h: str) -> str:
    return h  # Mapbox GL accepts '#RRGGBB' directly


def build_style(palette_name: str, palette: dict[str, str]) -> dict:
    """Build a complete Mapbox GL style JSON for one palette."""

    def c(token: str) -> str:
        """Resolve a colour token to hex, with fallback."""
        return palette.get(token, '#FF00FF')

    style = {
        "version": 8,
        "name": f"S-101 ENC – {palette_name.capitalize()}",
        "sprite": f"{TILE_BASE}/sprites/{palette_name}/sprite",
        "glyphs": f"{TILE_BASE}/fonts/{{fontstack}}/{{range}}.pbf",
        "sources": {
            "enc-area":     {"type": "vector", "tiles": [f"{TILE_BASE}/enc_area/{{z}}/{{x}}/{{y}}.pbf"],     "minzoom": 4, "maxzoom": 18},
            "enc-line":     {"type": "vector", "tiles": [f"{TILE_BASE}/enc_line/{{z}}/{{x}}/{{y}}.pbf"],     "minzoom": 4, "maxzoom": 18},
            "enc-point":    {"type": "vector", "tiles": [f"{TILE_BASE}/enc_point/{{z}}/{{x}}/{{y}}.pbf"],    "minzoom": 4, "maxzoom": 18},
            "enc-sounding": {"type": "vector", "tiles": [f"{TILE_BASE}/enc_sounding/{{z}}/{{x}}/{{y}}.pbf"], "minzoom": 11, "maxzoom": 18},
            "enc-label":    {"type": "vector", "tiles": [f"{TILE_BASE}/enc_label/{{z}}/{{x}}/{{y}}.pbf"],    "minzoom": 7,  "maxzoom": 18},
        },
        "layers": []
    }

    layers = style["layers"]

    # ── Background ────────────────────────────────────────────────────────
    layers.append({
        "id": "background",
        "type": "background",
        "paint": {"background-color": c("NODTA")}
    })

    # ── Depth areas (drawn by the AC token stored in di_ac) ───────────────
    # Rather than one layer per depth class, use Mapbox GL match expression
    # against the di_ac token value stored in the tile. This way the style
    # faithfully reflects whatever colour the Lua rule decided on.
    layers.append({
        "id": "depth-areas",
        "type": "fill",
        "source": "enc-area",
        "source-layer": "enc_area",
        "filter": ["has", "di_ac"],
        "paint": {
            "fill-color": [
                "match", ["get", "di_ac"],
                # Map every token the DEPARE rule can produce to its resolved colour.
                # These are the standard S-101 depth area tokens:
                "DEPDW",  c("DEPDW"),    # deep water (white/very light blue in day)
                "DEPMD",  c("DEPMD"),    # medium depth
                "DEPMS",  c("DEPMS"),    # medium shallow
                "DEPVS",  c("DEPVS"),    # very shallow
                "DEPIT",  c("DEPIT"),    # intertidal
                "NODTA",  c("NODTA"),    # no-data
                c("NODTA")               # fallback
            ],
            "fill-opacity": 1.0
        }
    })

    # ── Land areas ────────────────────────────────────────────────────────
    layers.append({
        "id": "land-areas",
        "type": "fill",
        "source": "enc-area",
        "source-layer": "enc_area",
        "filter": ["==", ["get", "feature_code"], "LandArea"],
        "paint": {"fill-color": c("LANDA")}
    })

    # ── Other area fills (use di_ac token directly) ───────────────────────
    # For non-depth areas (restricted zones, dredged areas, etc.)
    layers.append({
        "id": "other-areas",
        "type": "fill",
        "source": "enc-area",
        "source-layer": "enc_area",
        "filter": ["all",
            ["has", "di_ac"],
            ["!in", "feature_code", "DepthArea", "LandArea"]
        ],
        "paint": {
            "fill-color": [
                "match", ["get", "di_ac"],
                "RESBL", c("RESBL"),   "CHMGF", c("CHMGF"),
                "CHWHT", c("CHWHT"),   "CHYLW", c("CHYLW"),
                "CHGRD", c("CHGRD"),   "CHGRF", c("CHGRF"),
                c("NODTA")
            ],
            "fill-opacity": 0.5
        }
    })

    # ── Area outlines (line colour from di_lc) ────────────────────────────
    layers.append({
        "id": "area-outlines",
        "type": "line",
        "source": "enc-area",
        "source-layer": "enc_area",
        "filter": ["has", "di_lc"],
        "paint": {
            "line-color": [
                "match", ["get", "di_lc"],
                "CHBLK", c("CHBLK"), "CHDGD", c("CHDGD"),
                "CHGRD", c("CHGRD"), "CHMGF", c("CHMGF"),
                c("CHBLK")
            ],
            "line-width": ["coalesce", ["get", "di_lw"], 1.0]
        }
    })

    # ── Safety contour (special highlight — safety_contour flag set by Lua) ─
    layers.append({
        "id": "safety-contour",
        "type": "line",
        "source": "enc-line",
        "source-layer": "enc_line",
        "filter": ["==", ["get", "feature_code"], "DepthContour"],  # refined by viewing group
        "paint": {
            "line-color": c("CHBLK"),
            "line-width": 2.0
        }
    })

    # ── Regular lines (depth contours, boundaries, routes) ───────────────
    layers.append({
        "id": "lines",
        "type": "line",
        "source": "enc-line",
        "source-layer": "enc_line",
        "filter": ["!=", ["get", "feature_code"], "DepthContour"],
        "paint": {
            "line-color": [
                "match", ["get", "di_lc"],
                "CHBLK", c("CHBLK"), "CHDGD", c("CHDGD"),
                "CHGRD", c("CHGRD"), "CHMGF", c("CHMGF"),
                "CHRED", c("CHRED"), "CHGRN", c("CHGRN"),
                "CHYLW", c("CHYLW"), "LITRD", c("LITRD"),
                "LITGN", c("LITGN"), "CHWHT", c("CHWHT"),
                c("CHBLK")
            ],
            "line-width": ["coalesce", ["get", "di_lw"], 1.0]
        }
    })

    # ── Soundings ─────────────────────────────────────────────────────────
    layers.append({
        "id": "soundings",
        "type": "symbol",
        "source": "enc-sounding",
        "source-layer": "enc_sounding",
        "minzoom": 12,
        "layout": {
            "text-field": [
                "concat",
                ["to-string", ["floor", ["get", "depth_m"]]],
                "\u00b7",
                ["to-string", ["%", ["round", ["*", ["get", "depth_m"], 10]], 10]]
            ],
            "text-font": ["Roboto Mono Regular"],
            "text-size": 11,
            "text-allow-overlap": False,
            "symbol-sort-key": ["get", "di_dp"]
        },
        "paint": {
            "text-color": c("CHBLK"),
            "text-halo-color": c("DEPDW"),
            "text-halo-width": 0.5
        }
    })

    # ── Point symbols (buoys, lights, beacons, wrecks, ...) ──────────────
    layers.append({
        "id": "nav-points",
        "type": "symbol",
        "source": "enc-point",
        "source-layer": "enc_point",
        "filter": ["has", "di_sy"],
        "layout": {
            "icon-image": ["get", "di_sy"],         # sprite ID = symbol reference from Lua rule
            "icon-rotation-alignment": "map",
            "icon-rotate": ["coalesce", ["get", "di_sy_rot"], 0],
            "icon-allow-overlap": True,
            "icon-ignore-placement": True,
            "symbol-sort-key": ["get", "di_dp"],    # higher priority number = drawn later = on top
        },
        "paint": {"icon-opacity": 1.0}
    })

    # ── Text labels ───────────────────────────────────────────────────────
    layers.append({
        "id": "labels",
        "type": "symbol",
        "source": "enc-label",
        "source-layer": "enc_label",
        "layout": {
            "text-field": ["get", "label_text"],
            "text-font": ["Roboto Regular"],
            "text-size": ["coalesce", ["get", "font_size"], 10],
            "text-offset": [
                ["get", "offset_x"],
                ["get", "offset_y"]
            ],
            "text-allow-overlap": False,
            "symbol-sort-key": ["get", "di_dp"]
        },
        "paint": {
            "text-color": [
                "match", ["get", "font_colour"],
                "CHBLK", c("CHBLK"), "CHRED", c("CHRED"),
                "CHGRN", c("CHGRN"), "CHYLW", c("CHYLW"),
                "CHDGD", c("CHDGD"),
                c("CHBLK")
            ],
            "text-halo-color": c("CHWHT"),
            "text-halo-width": 1.0
        }
    })

    return style


def build_all_styles():
    out = Path('style/out')
    out.mkdir(parents=True, exist_ok=True)

    for palette_name, palette_file in [
        ('day',   'day.xml'),
        ('dusk',  'dusk.xml'),
        ('night', 'night.xml'),
    ]:
        palette_path = PALETTE_DIR / palette_file
        palette = load_palette(palette_path)
        style = build_style(palette_name, palette)
        output_path = out / f'enc-{palette_name}.json'
        output_path.write_text(json.dumps(style, indent=2))
        print(f"  ✓ Style written: {output_path}")


if __name__ == '__main__':
    build_all_styles()
```

---

## Step 6 — MVT Tile Functions (pg_tileserv / Martin)

PostGIS function sources. One per table, returning MVT. The `di_*` columns are included in the tile payload so the Mapbox GL style expressions can reference them.

```sql
-- Served at /functions/tile_enc_area/{z}/{x}/{y}.pbf
CREATE OR REPLACE FUNCTION tile_enc_area(z int, x int, y int)
RETURNS bytea LANGUAGE plpgsql STABLE PARALLEL SAFE AS $$
DECLARE
  env  geometry := ST_TileEnvelope(z, x, y);
  mvt  bytea;
BEGIN
  SELECT ST_AsMVT(t.*, 'enc_area', 4096, 'mvt_geom') INTO mvt
  FROM (
    SELECT
      ST_AsMVTGeom(ST_Transform(geom, 3857), env, 4096, 64, true) AS mvt_geom,
      foid, feature_code,
      di_vg, di_dp, di_ac, di_ap, di_lc, di_ls, di_lw,
      drval1, drval2
    FROM enc_area
    WHERE geom && ST_Transform(env, 4326)
      AND ST_Intersects(geom, ST_Transform(env, 4326))
  ) t WHERE t.mvt_geom IS NOT NULL;
  RETURN mvt;
END;
$$;

CREATE OR REPLACE FUNCTION tile_enc_line(z int, x int, y int)
RETURNS bytea LANGUAGE plpgsql STABLE PARALLEL SAFE AS $$
DECLARE env geometry := ST_TileEnvelope(z, x, y); mvt bytea;
BEGIN
  SELECT ST_AsMVT(t.*, 'enc_line', 4096, 'mvt_geom') INTO mvt
  FROM (
    SELECT
      ST_AsMVTGeom(ST_Transform(geom, 3857), env, 4096, 16, true) AS mvt_geom,
      foid, feature_code, di_vg, di_dp, di_lc, di_ls, di_lw, di_ac
    FROM enc_line
    WHERE geom && ST_Transform(env, 4326)
  ) t WHERE t.mvt_geom IS NOT NULL;
  RETURN mvt;
END;
$$;

CREATE OR REPLACE FUNCTION tile_enc_point(z int, x int, y int)
RETURNS bytea LANGUAGE plpgsql STABLE PARALLEL SAFE AS $$
DECLARE env geometry := ST_TileEnvelope(z, x, y); mvt bytea;
BEGIN
  SELECT ST_AsMVT(t.*, 'enc_point', 4096, 'mvt_geom') INTO mvt
  FROM (
    SELECT
      ST_AsMVTGeom(ST_Transform(geom, 3857), env, 4096, 8, true) AS mvt_geom,
      foid, feature_code, di_vg, di_dp, di_sy, di_sy_rot, di_sy_rot_type
    FROM enc_point
    WHERE geom && ST_Transform(env, 4326)
  ) t WHERE t.mvt_geom IS NOT NULL;
  RETURN mvt;
END;
$$;

CREATE OR REPLACE FUNCTION tile_enc_sounding(z int, x int, y int)
RETURNS bytea LANGUAGE plpgsql STABLE PARALLEL SAFE AS $$
DECLARE env geometry := ST_TileEnvelope(z, x, y); mvt bytea;
BEGIN
  SELECT ST_AsMVT(t.*, 'enc_sounding', 4096, 'mvt_geom') INTO mvt
  FROM (
    SELECT
      ST_AsMVTGeom(ST_Transform(geom, 3857), env, 4096, 4, true) AS mvt_geom,
      foid, depth_m, di_vg, di_dp
    FROM enc_sounding
    WHERE geom && ST_Transform(env, 4326)
  ) t WHERE t.mvt_geom IS NOT NULL;
  RETURN mvt;
END;
$$;

CREATE OR REPLACE FUNCTION tile_enc_label(z int, x int, y int)
RETURNS bytea LANGUAGE plpgsql STABLE PARALLEL SAFE AS $$
DECLARE env geometry := ST_TileEnvelope(z, x, y); mvt bytea;
BEGIN
  SELECT ST_AsMVT(t.*, 'enc_label', 4096, 'mvt_geom') INTO mvt
  FROM (
    SELECT
      ST_AsMVTGeom(ST_Transform(geom, 3857), env, 4096, 4, true) AS mvt_geom,
      foid, di_vg, di_dp, label_text, offset_x, offset_y, font_colour, font_size
    FROM enc_label
    WHERE geom && ST_Transform(env, 4326)
  ) t WHERE t.mvt_geom IS NOT NULL;
  RETURN mvt;
END;
$$;
```

Configure `pg_tileserv` to expose these as function sources. No other configuration needed.

---

## Step 7 — Palette Switching on the Client

Switching between day / dusk / night is a single call:

```javascript
const STYLES = {
  day:   'https://tiles.example.com/styles/enc-day.json',
  dusk:  'https://tiles.example.com/styles/enc-dusk.json',
  night: 'https://tiles.example.com/styles/enc-night.json',
};

// Initialise
const map = new mapboxgl.Map({
  container: 'map',
  style: STYLES.day,
  center: [10.0, 57.0],
  zoom: 10
});

// Switch palette
document.getElementById('palette-select').addEventListener('change', (e) => {
  map.setStyle(STYLES[e.target.value]);
});
```

No tile re-fetching. The tiles carry colour tokens as string properties; the style JSON resolves those tokens to hex. Swapping the style changes the resolution, not the data.

---

## Complete Data Flow Summary

```
S-101 Cell (.000 / HDF5)
        │
        ▼
cell_reader.py          → iterates features as dicts with wkt + attributes
        │
        ▼
LuaHost.portray_feature()
  ├─ loads portrayal/PortrayalCatalog/Rules/<FeatureCode>.lua
  ├─ injects FIXED_CONTEXT (SafetyContour=30m, etc.)
  └─ Lua rule calls HostPortrayalEmit(featureRef, diString)
        │
        ▼
parse_drawing_instructions(diString)
  → DrawingInstructions(vg=27010, dp=7, sy='BOYCAN81', lc='CHBLK', ...)
        │
        ▼
Ingester.ingest_feature()
  → INSERT INTO enc_point/enc_area/enc_line/enc_label  (PostGIS)
        │
        ▼
pg_tileserv / Martin
  → tile_enc_*({z}/{x}/{y})  →  MVT .pbf
        │
        ▼
Mapbox GL client
  ├─ loads enc-day.json (or dusk/night)
  ├─ "icon-image": ["get", "di_sy"]       → sprite lookup by symbol ref
  ├─ "fill-color": ["match", "di_ac", …]  → colour token resolved to hex
  └─ renders chart
```

---

## Known Limitations of This Minimal Approach

**Line styles with embedded symbols.** Some S-101 line styles (e.g., `BOYISD` isolated danger line, recommended track lines) place symbols along their length at computed intervals. The `LS:` instruction in the DI string only captures colour and stroke width. These patterns are approximated as plain coloured lines. Full fidelity requires a custom Mapbox GL `line-pattern` layer per line style, backed by a pattern PNG extracted from the SVG.

**Conditional symbology (`CS:`)** calls appear in some rules — these are helper procedure calls within the Lua environment itself. They do not emit separate DI strings; they call further Lua code that eventually emits via `HostPortrayalEmit`. Handled automatically by the Lua runtime, no special treatment needed.

**Light arcs and sector lines.** `LIGHTS*.lua` rules emit geometry construction instructions for sector arcs as well as the light symbol itself. The arc geometry itself must be computed and stored as line geometry during ingest (not just a symbol reference). This requires additional handling in `cell_reader.py` — generate the arc polyline from sector bearing/range attributes — and a dedicated `enc_light_arc` table.

**Associations.** Some rules read associated features (e.g., a `LightAll` associated to a `BuoyLateral`). The `LuaHost` implementation above handles single features. Full association support requires passing a richer feature graph to the Lua rule via `portrayalContext`.

**Fonts.** Mapbox GL requires a self-hosted glyph server or use of MapLibre's public glyph endpoint. The S-101 PC specifies `'Roboto Bold'` and `'Roboto Regular'` for text. Host these via `font-maker` or the `fontnik` tool.
```