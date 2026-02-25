import json
from pathlib import Path
from utils.colors import load_palette, Theme

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

    for theme in Theme:
        palette = load_palette(theme)
        palette_name = theme.value
        style = build_style(palette_name, palette)
        output_path = out / f'enc-{palette_name}.json'
        output_path.write_text(json.dumps(style, indent=2))
        print(f"  ✓ Style written: {output_path}")


if __name__ == '__main__':
    build_all_styles()