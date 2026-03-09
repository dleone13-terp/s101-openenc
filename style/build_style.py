import json
from pathlib import Path
from utils.colors import load_palette, Theme

# Martin tile server base URL (see martin/martin.yaml and .devcontainer/docker-compose.yml).
# Martin runs on port 3000 inside the devcontainer and is forwarded to the host.
MARTIN_BASE = 'http://localhost:3000'

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

    def make_match(field: str, fallback_token: str) -> list:
        """Match expression covering every palette token."""
        expr = ["match", ["get", field]]
        for token, hex_color in sorted(palette.items()):
            expr.append(token)
            expr.append(hex_color)
        expr.append(palette.get(fallback_token, "#FF00FF"))
        return expr

    style = {
        "version": 8,
        "name": f"S-101 ENC – {palette_name.capitalize()}",
        # Sprite key matches the sprite name defined in martin/martin.yaml.
        "sprite": f"{MARTIN_BASE}/sprites/{palette_name}/sprite",
        # Martin serves PBF font shards at /fonts/{fontstack}/{range}.pbf
        "glyphs": f"{MARTIN_BASE}/fonts/{{fontstack}}/{{range}}.pbf",
        # Default map view – Chesapeake Bay
        "center": [-76.35, 37.95],
        "zoom": 10,
        "sources": {
            # Martin auto-publishes enc_* tables; tiles at /{table}/{z}/{x}/{y}
            "enc-area":     {"type": "vector", "tiles": [f"{MARTIN_BASE}/enc_area/{{z}}/{{x}}/{{y}}"],     "minzoom": 4, "maxzoom": 18},
            "enc-line":     {"type": "vector", "tiles": [f"{MARTIN_BASE}/enc_line/{{z}}/{{x}}/{{y}}"],     "minzoom": 4, "maxzoom": 18},
            "enc-point":    {"type": "vector", "tiles": [f"{MARTIN_BASE}/enc_point/{{z}}/{{x}}/{{y}}"],    "minzoom": 4, "maxzoom": 18},
            "enc-sounding": {"type": "vector", "tiles": [f"{MARTIN_BASE}/enc_sounding/{{z}}/{{x}}/{{y}}"], "minzoom": 11, "maxzoom": 18},
            "enc-label":    {"type": "vector", "tiles": [f"{MARTIN_BASE}/enc_label/{{z}}/{{x}}/{{y}}"],    "minzoom": 7,  "maxzoom": 18},
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

    # ── Depth areas (drawn by the AC token stored in di_color_fill) ───────────────
    # Rather than one layer per depth class, use Mapbox GL match expression
    # against the di_color_fill token value stored in the tile. This way the style
    # faithfully reflects whatever colour the Lua rule decided on.
    layers.append({
        "id": "depth-areas",
        "type": "fill",
        "source": "enc-area",
        "source-layer": "enc_area",
        "filter": ["has", "di_color_fill"],
        "paint": {
            "fill-color": make_match("di_color_fill", "NODTA"),
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

    # ── Other area fills (use di_color_fill token directly) ───────────────────────
    # For non-depth areas (restricted zones, dredged areas, etc.)
    layers.append({
        "id": "other-areas",
        "type": "fill",
        "source": "enc-area",
        "source-layer": "enc_area",
        "filter": ["all",
            ["has", "di_color_fill"],
            ["!in", "feature_code", "DepthArea", "LandArea"]
        ],
        "paint": {
            "fill-color": make_match("di_color_fill", "NODTA"),
            "fill-opacity": 0.5
        }
    })

    # ── Area outlines (line colour from di_line_color) ────────────────────────────
    layers.append({
        "id": "area-outlines",
        "type": "line",
        "source": "enc-area",
        "source-layer": "enc_area",
        "filter": ["has", "di_line_color"],
        "paint": {
            "line-color": make_match("di_line_color", "CHBLK"),
            "line-width": ["coalesce", ["get", "di_line_width"], 1.0]
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
            "line-color": make_match("di_line_color", "CHBLK"),
            "line-width": ["coalesce", ["get", "di_line_width"], 1.0]
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
            "text-font": ["Roboto Bold"],
            "text-size": 11,
            "text-allow-overlap": False,
            "symbol-sort-key": ["get", "di_drawing_priority"]
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
        "filter": ["has", "di_symbol_ref"],
        "layout": {
            "icon-image": ["get", "di_symbol_ref"],         # sprite ID = symbol reference from Lua rule
            "icon-rotation-alignment": "map",
            "icon-rotate": ["coalesce", ["get", "di_symbol_rotation"], 0],
            "icon-allow-overlap": True,
            "icon-ignore-placement": True,
            "symbol-sort-key": ["get", "di_drawing_priority"],    # higher priority number = drawn later = on top
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
            "text-offset": [0, 0],
            "text-allow-overlap": False,
            "symbol-sort-key": ["get", "di_drawing_priority"]
        },
        "paint": {
            "text-color": make_match("font_colour", "CHBLK"),
            "text-halo-color": c("CHWHT"),
            "text-halo-width": 1.0
        }
    })

    return style


def build_all_styles():
    out = Path('style/out')
    out.mkdir(parents=True, exist_ok=True)

    for theme in Theme:
        palette = load_palette(theme)
        palette_name = theme.value
        style = build_style(palette_name, palette)
        output_path = out / f'{palette_name}.json'
        output_path.write_text(json.dumps(style, indent=2))
        print(f"  ✓ Style written: {output_path}")


if __name__ == '__main__':
    build_all_styles()