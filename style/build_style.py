"""
Generate Mapbox GL style JSONs (day/dusk/night) backed by drawing instructions stored in PostGIS.

This script:
- Uses psql to discover distinct drawing-instruction tokens from enc_area/enc_line di_jsonb.
- Reads palette CSS (day/dusk/night) to map IHO colour tokens to hex values.
- Emits minimal styles with two layers: area fill and line, driven by DI properties
  expected on the vector tiles (ColorFill, LineColor, LineStyle, LineWidth).

Assumptions
- Martin serves layers named enc_area and enc_line (override via flags).
- The tile query exposes DI properties with the same names as the DI keys,
  e.g. `di_jsonb->0->>'ColorFill' AS "ColorFill"`.
- Sprite URL pattern points to palette-specific sprite built by sprites/build_sprites.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

PALETTES = {
    "day": "portrayal/PortrayalCatalog/Symbols/daySvgStyle.css",
    "dusk": "portrayal/PortrayalCatalog/Symbols/duskSvgStyle.css",
    "night": "portrayal/PortrayalCatalog/Symbols/nightSvgStyle.css",
}

SYMBOLS_DIR = Path("portrayal/PortrayalCatalog/Symbols")


def mm_to_px(mm: float) -> float:
    """Convert millimeters to CSS pixels at 96 DPI."""
    return mm * (96.0 / 25.4)


def load_palette_colors(css_path: Path) -> Dict[str, str]:
    """Parse .sTOKEN {stroke:#HEX} rules from the palette CSS."""
    text = css_path.read_text()
    token_re = re.compile(r"\.s([A-Z0-9]+)\s*\{stroke:#([0-9A-Fa-f]{6})\}")
    return {m.group(1): f"#{m.group(2).upper()}" for m in token_re.finditer(text)}


def run_psql(query: str, args: argparse.Namespace) -> List[str]:
    cmd = [
        "psql",
        "-q",
        "-t",
        "-A",
        "-F",
        "|",
    ]
    if args.db_host:
        cmd += ["-h", args.db_host]
    if args.db_port:
        cmd += ["-p", str(args.db_port)]
    if args.db_user:
        cmd += ["-U", args.db_user]
    if args.db_name:
        cmd += ["-d", args.db_name]
    cmd += ["-c", query]

    env = os.environ.copy()
    if args.db_password:
        env["PGPASSWORD"] = args.db_password

    output = subprocess.check_output(cmd, text=True, env=env)
    return [line.strip() for line in output.splitlines() if line.strip()]


def collect_fill_tokens(args: argparse.Namespace) -> List[str]:
    query = (
        f"SELECT DISTINCT di->>'ColorFill' AS token "
        f"FROM {args.schema}.{args.area_table} "
        f"CROSS JOIN LATERAL jsonb_array_elements(di_jsonb) di "
        f"WHERE di ? 'ColorFill' AND di->>'ColorFill' IS NOT NULL"
    )
    tokens: list[str] = []
    for raw in run_psql(query, args):
        token = raw.split(",", 1)[0].strip()
        if token:
            tokens.append(token)
    return sorted(set(tokens))


def collect_area_pattern_tokens(args: argparse.Namespace) -> List[str]:
    query = (
        f"SELECT DISTINCT di->>'AreaFillReference' AS token "
        f"FROM {args.schema}.{args.area_table} "
        "CROSS JOIN LATERAL jsonb_array_elements(di_jsonb) di "
        "WHERE di ? 'AreaFillReference' AND di->>'AreaFillReference' IS NOT NULL"
    )
    return run_psql(query, args)


def collect_line_tokens(args: argparse.Namespace) -> List[str]:
    query = (
        "WITH styles AS ("
        f"SELECT di->>'LineStyle' AS token FROM {args.schema}.{args.line_table} "
        "CROSS JOIN LATERAL jsonb_array_elements(di_jsonb) di "
        "WHERE di ? 'LineStyle' AND di->>'LineStyle' IS NOT NULL "
        "UNION ALL "
        f"SELECT di->>'LineStyle' AS token FROM {args.schema}.{args.area_table} "
        "CROSS JOIN LATERAL jsonb_array_elements(di_jsonb) di "
        "WHERE di ? 'LineStyle' AND di->>'LineStyle' IS NOT NULL"
        ") "
        "SELECT DISTINCT token FROM styles"
    )
    raw_tokens = run_psql(query, args)
    color_tokens: list[str] = []
    for entry in raw_tokens:
        parts = entry.split(',')
        if parts:
            token = parts[-1].strip()
            if token:
                color_tokens.append(token)

    # Also include direct LineColor instructions from both area and line features.
    color_query = (
        "WITH colors AS ("
        f"SELECT di->>'LineColor' AS token FROM {args.schema}.{args.line_table} "
        "CROSS JOIN LATERAL jsonb_array_elements(di_jsonb) di "
        "WHERE di ? 'LineColor' AND di->>'LineColor' IS NOT NULL "
        "UNION ALL "
        f"SELECT di->>'LineColor' AS token FROM {args.schema}.{args.area_table} "
        "CROSS JOIN LATERAL jsonb_array_elements(di_jsonb) di "
        "WHERE di ? 'LineColor' AND di->>'LineColor' IS NOT NULL"
        ") "
        "SELECT DISTINCT token FROM colors"
    )
    color_tokens.extend(run_psql(color_query, args))

    return sorted(set(color_tokens))


def collect_dash_tokens(args: argparse.Namespace) -> List[str]:
    query = (
        "WITH raw_dash AS ("
        f"SELECT COALESCE(NULLIF(di->>'Dash', ''), CASE WHEN NULLIF(split_part(di->>'LineStyle', ',', 2), '') IS NOT NULL THEN '0,' || split_part(di->>'LineStyle', ',', 2) END) AS token FROM {args.schema}.{args.line_table} "
        "CROSS JOIN LATERAL jsonb_array_elements(di_jsonb) di "
        "UNION ALL "
        f"SELECT COALESCE(NULLIF(di->>'Dash', ''), CASE WHEN NULLIF(split_part(di->>'LineStyle', ',', 2), '') IS NOT NULL THEN '0,' || split_part(di->>'LineStyle', ',', 2) END) AS token FROM {args.schema}.{args.area_table} "
        "CROSS JOIN LATERAL jsonb_array_elements(di_jsonb) di"
        ") "
        "SELECT DISTINCT token FROM raw_dash WHERE token IS NOT NULL"
    )
    return run_psql(query, args)


def collect_point_symbol_tokens(args: argparse.Namespace) -> List[str]:
    query = (
        f"SELECT DISTINCT di->>'PointInstruction' AS token "
        f"FROM {args.schema}.enc_point "
        "CROSS JOIN LATERAL jsonb_array_elements(di_jsonb) di "
        "WHERE di ? 'PointInstruction' AND di->>'PointInstruction' IS NOT NULL"
    )
    return run_psql(query, args)


def dash_token_to_dasharray(token: str) -> list[float] | None:
    parts = [part.strip() for part in token.split(",")]
    if len(parts) < 2:
        return None
    try:
        gap = float(parts[1])
    except ValueError:
        return None

    if gap <= 0:
        return None

    # Dots in catalogue rules are represented by very small dash/gap values.
    if gap < 1.0:
        return [1.0, max(1.0, round(gap * 3.0, 2))]

    return [max(1.0, round(gap * 1.5, 2)), max(1.0, round(gap, 2))]


def build_dash_match_expr(dash_tokens: Iterable[str]) -> list:
    expr: list = ["match", ["coalesce", ["get", "Dash"], ""]]
    has_entries = False
    for token in sorted(set(dash_tokens)):
        dash = dash_token_to_dasharray(token)
        if not dash:
            continue
        expr.extend([token, ["literal", dash]])
        has_entries = True

    if not has_entries:
        return ["literal", [1.0, 0.0]]

    expr.append(["literal", [1.0, 0.0]])
    return expr


def text_color_expr(colors: Dict[str, str]) -> list:
    default_text = colors.get("CHBLK", "#202020")
    token_map: Dict[str, str] = {}
    for token, hex_value in colors.items():
        token_map[token] = hex_value
    return build_match_expr(["coalesce", ["get", "FontColor"], ""], token_map, default_text)


def load_available_sprite_ids() -> set[str]:
    if not SYMBOLS_DIR.exists():
        return set()
    # Martin exposes sprite entries using the relative path in the sprite source.
    return {f"symbols/{path.stem}" for path in SYMBOLS_DIR.glob("*.svg")}


def map_area_patterns_to_sprites(tokens: Iterable[str], sprite_ids: set[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for token in sorted(set(tok for tok in tokens if tok)):
        candidates = [f"symbols/{token}", f"symbols/{token}P"]
        for candidate in candidates:
            if candidate in sprite_ids:
                mapping[token] = candidate
                break
    return mapping


def map_point_symbols_to_sprites(tokens: Iterable[str], sprite_ids: set[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for token in sorted(set(tok for tok in tokens if tok)):
        candidates = [f"symbols/{token}", token]
        for candidate in candidates:
            if candidate in sprite_ids:
                mapping[token] = candidate
                break
    return mapping


def collect_data_center(args: argparse.Namespace) -> list[float]:
    """Compute map center from the combined extent of area/line geometries."""
    query = (
        "WITH geoms AS ("
        f"SELECT geom FROM {args.schema}.{args.area_table} WHERE geom IS NOT NULL "
        "UNION ALL "
        f"SELECT geom FROM {args.schema}.{args.line_table} WHERE geom IS NOT NULL"
        "), extent AS ("
        "SELECT ST_Extent(geom) AS bbox FROM geoms"
        ") "
        "SELECT ST_XMin(bbox), ST_YMin(bbox), ST_XMax(bbox), ST_YMax(bbox) "
        "FROM extent WHERE bbox IS NOT NULL"
    )
    rows = run_psql(query, args)
    if not rows:
        return [0.0, 0.0]

    parts = rows[0].split("|")
    if len(parts) != 4:
        return [0.0, 0.0]

    xmin, ymin, xmax, ymax = (float(value) for value in parts)
    center_x = round((xmin + xmax) / 2.0, 6)
    center_y = round((ymin + ymax) / 2.0, 6)

    # MapLibre center is [lng, lat]. Some source datasets can arrive with
    # swapped axes; fix obvious cases to avoid invalid latitude errors.
    lng, lat = center_x, center_y
    if abs(lat) > 90 and abs(lng) <= 90:
        lng, lat = lat, lng

    if abs(lat) > 90 or abs(lng) > 180:
        return [0.0, 0.0]
    return [lng, lat]


def build_match_expr(key_expr: list, token_map: Dict[str, str], default_color: str) -> list:
    expr: list = ["match", key_expr]
    for token, hex_value in sorted(token_map.items()):
        expr.extend([token, hex_value])
    expr.append(default_color)
    return expr


def build_style(
    palette: str,
    colors: Dict[str, str],
    fill_tokens: Iterable[str],
    area_pattern_tokens: Iterable[str],
    line_tokens: Iterable[str],
    dash_tokens: Iterable[str],
    point_symbols: Iterable[str],
    center: list[float],
    args: argparse.Namespace,
) -> dict:
    default_fill = colors.get("NODTA", "#93AEBB")
    default_line = colors.get("DEPCN", "#768C97")

    fill_map = {tok: colors.get(tok, default_fill) for tok in fill_tokens if tok}
    line_map = {tok: colors.get(tok, default_line) for tok in line_tokens if tok}
    sprite_ids = load_available_sprite_ids()
    area_pattern_map = map_area_patterns_to_sprites(area_pattern_tokens, sprite_ids)
    known_point_symbol_map = map_point_symbols_to_sprites(point_symbols, sprite_ids)

    # Keep expressions MapLibre-compatible in Maputnik.
    line_color_key = ["coalesce", ["get", "LineColor"], ""]
    line_width_expr = ["coalesce", ["to-number", ["get", "LineWidth"]], mm_to_px(args.default_line_width)]
    line_dash_expr = build_dash_match_expr(dash_tokens)
    text_size_expr = ["coalesce", ["to-number", ["get", "FontSize"]], 11]
    text_offset_expr = ["literal", [0.0, 0.0]]
    text_rotation_expr = ["coalesce", ["to-number", ["get", "TextRotation"]], 0]
    text_justify_expr = [
        "match",
        ["downcase", ["coalesce", ["get", "TextAlignHorizontal"], "center"]],
        "left",
        "left",
        "right",
        "right",
        "center",
    ]

    tiles_base = args.tiles_base_url.rstrip("/")
    area_tiles = f"{tiles_base}/{args.area_layer}/{{z}}/{{x}}/{{y}}"
    line_tiles = f"{tiles_base}/{args.line_layer}/{{z}}/{{x}}/{{y}}"
    point_tiles = f"{tiles_base}/{args.point_layer}/{{z}}/{{x}}/{{y}}"

    # DrawingPriority defines rendering order. Higher values draw on top.
    priority_sort_key = ["get", "DrawingPriority"]

    style = {
        "version": 8,
        "name": f"ENC {palette}",
        "center": center,
        "zoom": args.default_zoom,
        "sprite": f"{args.sprite_base_url.rstrip('/')}/{palette}",
        "sources": {
            "enc_area_src": {
                "type": "vector",
                "tiles": [area_tiles],
                "minzoom": 0,
                "maxzoom": 22,
            },
            "enc_line_src": {
                "type": "vector",
                "tiles": [line_tiles],
                "minzoom": 0,
                "maxzoom": 22,
            },
            "enc_point_src": {
                "type": "vector",
                "tiles": [point_tiles],
                "minzoom": 0,
                "maxzoom": 22,
            }
        },
        "layers": [
            {
                "id": "background",
                "type": "background",
                "paint": {
                    "background-color": "#eef5ff"
                }
            },
            {
                "id": "enc-area-fill",
                "type": "fill",
                "source": "enc_area_src",
                "source-layer": args.area_layer,
                "filter": ["has", "ColorFill"],
                "layout": {
                    "fill-sort-key": priority_sort_key,
                },
                "paint": {
                    "fill-color": build_match_expr(["get", "ColorFill"], fill_map, default_fill),
                    "fill-opacity": ["coalesce", ["to-number", ["get", "ColorFillOpacity"]], 1.0],
                },
            },
            *(
                [
                    {
                        "id": "enc-area-pattern",
                        "type": "fill",
                        "source": "enc_area_src",
                        "source-layer": args.area_layer,
                        "filter": [
                            "all",
                            ["has", "AreaFillReference"],
                            [
                                "in",
                                ["get", "AreaFillReference"],
                                ["literal", sorted(area_pattern_map.keys())],
                            ],
                        ],
                        "layout": {
                            "fill-sort-key": priority_sort_key,
                        },
                        "paint": {
                            "fill-pattern": [
                                "match",
                                ["get", "AreaFillReference"],
                                *[
                                    item
                                    for token, sprite_id in sorted(area_pattern_map.items())
                                    for item in (token, sprite_id)
                                ],
                                next(iter(area_pattern_map.values())),
                            ],
                            "fill-opacity": ["coalesce", ["to-number", ["get", "ColorFillOpacity"]], 1.0],
                        },
                    }
                ]
                if area_pattern_map
                else []
            ),
            {
                "id": "enc-area-line",
                "type": "line",
                "source": "enc_area_src",
                "source-layer": args.area_layer,
                "filter": ["any", ["has", "LineColor"], ["has", "LineStyle"], ["has", "LineWidth"]],
                "layout": {
                    "line-sort-key": priority_sort_key,
                },
                "paint": {
                    "line-color": build_match_expr(line_color_key, line_map, default_line),
                    "line-width": line_width_expr,
                    "line-dasharray": line_dash_expr,
                },
            },
            {
                "id": "enc-line",
                "type": "line",
                "source": "enc_line_src",
                "source-layer": args.line_layer,
                "filter": ["any", ["has", "LineColor"], ["has", "LineStyle"]],
                "layout": {
                    "line-sort-key": priority_sort_key,
                },
                "paint": {
                    "line-color": build_match_expr(line_color_key, line_map, default_line),
                    "line-width": line_width_expr,
                    "line-dasharray": line_dash_expr,
                },
            },
            {
                "id": "enc-point-symbol",
                "type": "symbol",
                "source": "enc_point_src",
                "source-layer": args.point_layer,
                "filter": [
                    "all",
                    ["has", "PointInstruction"],
                    ["in", ["get", "PointInstruction"], ["literal", sorted(known_point_symbol_map.keys())]],
                ],
                "layout": {
                    "icon-image": [
                        "match",
                        ["get", "PointInstruction"],
                        *[
                            item
                            for token, sprite_id in sorted(known_point_symbol_map.items())
                            for item in (token, sprite_id)
                        ],
                        next(iter(known_point_symbol_map.values()), ""),
                    ],
                    "icon-size": 1.0,
                    "icon-allow-overlap": True,
                    "symbol-sort-key": priority_sort_key,
                },
            },
            {
                "id": "enc-point-fallback",
                "type": "circle",
                "source": "enc_point_src",
                "source-layer": args.point_layer,
                "filter": [
                    "any",
                    ["!", ["has", "PointInstruction"]],
                    ["!", ["in", ["get", "PointInstruction"], ["literal", sorted(known_point_symbol_map.keys())]]],
                ],
                "layout": {
                    "circle-sort-key": priority_sort_key,
                },
                "paint": {
                    "circle-radius": 2.0,
                    "circle-color": "#d1495b",
                    "circle-stroke-color": "#ffffff",
                    "circle-stroke-width": 0.6,
                },
            },
            {
                "id": "enc-point-text",
                "type": "symbol",
                "source": "enc_point_src",
                "source-layer": args.point_layer,
                "filter": ["has", "TextInstruction"],
                "layout": {
                    "text-field": ["get", "TextInstruction"],
                    "text-size": text_size_expr,
                    "text-anchor": "center",
                    "text-justify": text_justify_expr,
                    "text-offset": text_offset_expr,
                    "text-rotate": text_rotation_expr,
                    "symbol-sort-key": priority_sort_key,
                    "text-allow-overlap": False,
                },
                "paint": {
                    "text-color": text_color_expr(colors),
                },
            },
            {
                "id": "enc-line-text",
                "type": "symbol",
                "source": "enc_line_src",
                "source-layer": args.line_layer,
                "filter": ["has", "TextInstruction"],
                "layout": {
                    "symbol-placement": "line",
                    "text-field": ["get", "TextInstruction"],
                    "text-size": text_size_expr,
                    "text-justify": text_justify_expr,
                    "text-offset": text_offset_expr,
                    "text-rotate": text_rotation_expr,
                    "symbol-sort-key": priority_sort_key,
                },
                "paint": {
                    "text-color": text_color_expr(colors),
                },
            },
            {
                "id": "enc-area-text",
                "type": "symbol",
                "source": "enc_area_src",
                "source-layer": args.area_layer,
                "filter": ["has", "TextInstruction"],
                "layout": {
                    "text-field": ["get", "TextInstruction"],
                    "text-size": text_size_expr,
                    "text-justify": text_justify_expr,
                    "text-offset": text_offset_expr,
                    "text-rotate": text_rotation_expr,
                    "symbol-sort-key": priority_sort_key,
                },
                "paint": {
                    "text-color": text_color_expr(colors),
                },
            },
        ],
    }
    return style


def write_style(style: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(style, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Mapbox GL styles from PostGIS DI data")
    parser.add_argument("--db-host", default="db", help="Postgres host")
    parser.add_argument("--db-port", type=int, default=5432, help="Postgres port")
    parser.add_argument("--db-name", default="postgres", help="Database name")
    parser.add_argument("--db-user", default="postgres", help="Database user")
    parser.add_argument("--db-password", default=os.environ.get("PGPASSWORD"), help="Database password")
    parser.add_argument("--schema", default="s101", help="Schema containing ENC tables")
    parser.add_argument("--area-table", default="enc_area", help="Area table/view name for DI token discovery")
    parser.add_argument("--line-table", default="enc_line", help="Line table/view name for DI token discovery")
    parser.add_argument("--area-layer", default="enc_area", help="Vector tile layer name for areas")
    parser.add_argument("--line-layer", default="enc_line", help="Vector tile layer name for lines")
    parser.add_argument("--point-layer", default="enc_point", help="Vector tile layer name for points")
    parser.add_argument(
        "--tiles-base-url",
        default="http://localhost:3000",
        help="Base URL for Martin HTTP tile endpoints",
    )
    parser.add_argument(
        "--sprite-base-url",
        default="http://localhost:3000/sprite",
        help="Base URL for Martin sprite endpoint (for example: http://localhost:3000/sprite)",
    )
    parser.add_argument("--out-dir", default="style/out", help="Output directory for style JSONs")
    parser.add_argument(
        "--palette", choices=["day", "dusk", "night", "all"], default="all", help="Palette to build"
    )
    parser.add_argument("--default-zoom", type=float, default=8.5, help="Initial map zoom level")
    parser.add_argument(
        "--default-line-width",
        type=float,
        default=0.32,
        help="Fallback line width in millimeters (converted to pixels)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    target_palettes = list(PALETTES.keys()) if args.palette == "all" else [args.palette]

    fill_tokens = collect_fill_tokens(args)
    area_pattern_tokens = collect_area_pattern_tokens(args)
    line_tokens = collect_line_tokens(args)
    dash_tokens = collect_dash_tokens(args)
    point_symbols = collect_point_symbol_tokens(args)
    center = collect_data_center(args)

    for palette in target_palettes:
        css_path = Path(PALETTES[palette])
        colors = load_palette_colors(css_path)
        style = build_style(
            palette,
            colors,
            fill_tokens,
            area_pattern_tokens,
            line_tokens,
            dash_tokens,
            point_symbols,
            center,
            args,
        )
        out_path = Path(args.out_dir) / f"enc-{palette}.json"
        write_style(style, out_path)
        print(f"[{palette}] wrote {out_path}")


if __name__ == "__main__":
    main()
