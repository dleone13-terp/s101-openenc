from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Set
import xml.etree.ElementTree as ET

DEFAULT_OUT_DIR = Path("style/out")
DEFAULT_THEMES = ("day", "dusk", "night")

# Minimal fallback tokens used when palette XMLs are unavailable.
FALLBACK_PALETTES: Dict[str, Dict[str, str]] = {
    "day": {
        "NODTA": "#f2f2f2",
        "DEPDW": "#dff6ff",
        "DEPMD": "#bde7fb",
        "DEPMS": "#95d4f4",
        "DEPVS": "#6cb9ec",
        "DEPIT": "#d0f0ff",
        "LANDA": "#f3e6c9",
        "CHBLK": "#1b1f23",
        "CHGRD": "#6e7278",
        "CHGRF": "#6c8779",
    },
    "dusk": {
        "NODTA": "#262533",
        "DEPDW": "#1f3854",
        "DEPMD": "#275173",
        "DEPMS": "#2e6890",
        "DEPVS": "#3f82aa",
        "DEPIT": "#5a9bb4",
        "LANDA": "#6d5e4b",
        "CHBLK": "#f6f3ef",
        "CHGRD": "#aaa4a0",
        "CHGRF": "#97a88c",
    },
    "night": {
        "NODTA": "#11131b",
        "DEPDW": "#13273b",
        "DEPMD": "#1b3550",
        "DEPMS": "#244667",
        "DEPVS": "#2f5d82",
        "DEPIT": "#3c7599",
        "LANDA": "#433f3a",
        "CHBLK": "#f5f8ff",
        "CHGRD": "#8790a2",
        "CHGRF": "#7f9e90",
    },
}

DEFAULT_TOKEN_SETS: Dict[str, Set[str]] = {
    "fill": {"DEPDW", "DEPMD", "DEPMS", "DEPVS", "DEPIT", "NODTA", "LANDA"},
    "line": {"CHBLK", "CHGRD", "CHGRF"},
    "font": {"CHBLK"},
}


def load_palette_xml(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}

    tree = ET.parse(path)
    root = tree.getroot()
    palette: Dict[str, str] = {}

    for element in root.iter():
        token = element.attrib.get("token") or element.attrib.get("name")
        rgb = (
            element.attrib.get("rgb")
            or element.attrib.get("value")
            or element.attrib.get("hex")
        )
        if not token or not rgb:
            continue

        value = rgb.strip()
        if not value:
            continue
        if not value.startswith("#"):
            value = f"#{value}"
        palette[token.strip()] = value

    return palette


def collect_tokens(di_payload: Any) -> Dict[str, Set[str]]:
    tokens = {
        "fill": set(DEFAULT_TOKEN_SETS["fill"]),
        "line": set(DEFAULT_TOKEN_SETS["line"]),
        "font": set(DEFAULT_TOKEN_SETS["font"]),
        "point_symbols": set(),
    }

    for instruction in _iter_instruction_dicts(di_payload):
        fill = instruction.get("ColorFill")
        if isinstance(fill, str):
            tokens["fill"].add(fill)

        line = instruction.get("LineColor")
        if isinstance(line, str):
            tokens["line"].add(line)

        font = instruction.get("FontColor")
        if isinstance(font, str):
            tokens["font"].add(font)

        symbol = instruction.get("PointInstruction")
        if isinstance(symbol, str):
            tokens["point_symbols"].add(symbol)

    return tokens


def _iter_instruction_dicts(payload: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, dict):
        if any(isinstance(v, list) for v in payload.values()):
            for value in payload.values():
                yield from _iter_instruction_dicts(value)
        else:
            yield payload
        return
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_instruction_dicts(item)


def build_style(
    *,
    theme: str,
    palette: Mapping[str, str],
    tile_base_url: str,
    token_sets: Mapping[str, Set[str]],
) -> Dict[str, Any]:
    def color(token: str) -> str:
        return palette.get(token, "#ff00ff")

    fill_match = _build_match_expr("ColorFill", token_sets.get("fill", set()), color, "NODTA")
    line_match = _build_match_expr("LineColor", token_sets.get("line", set()), color, "CHBLK")
    font_match = _build_match_expr("FontColor", token_sets.get("font", set()), color, "CHBLK")

    return {
        "version": 8,
        "name": f"OpenENC {theme}",
        "glyphs": f"{tile_base_url}/fonts/{{fontstack}}/{{range}}.pbf",
        "sprite": f"{tile_base_url}/sprites/{theme}/sprite",
        "sources": {
            "enc_area": {"type": "vector", "tiles": [f"{tile_base_url}/enc_area/{{z}}/{{x}}/{{y}}.pbf"]},
            "enc_line": {"type": "vector", "tiles": [f"{tile_base_url}/enc_line/{{z}}/{{x}}/{{y}}.pbf"]},
            "enc_point": {"type": "vector", "tiles": [f"{tile_base_url}/enc_point/{{z}}/{{x}}/{{y}}.pbf"]},
        },
        "layers": [
            {
                "id": "background",
                "type": "background",
                "paint": {"background-color": color("NODTA")},
            },
            {
                "id": "enc-area-fill",
                "type": "fill",
                "source": "enc_area",
                "source-layer": "enc_area",
                "paint": {"fill-color": fill_match, "fill-opacity": 1.0},
            },
            {
                "id": "enc-line",
                "type": "line",
                "source": "enc_line",
                "source-layer": "enc_line",
                "paint": {
                    "line-color": line_match,
                    "line-width": ["coalesce", ["get", "LineWidth"], 1.0],
                },
            },
            {
                "id": "enc-point-symbols",
                "type": "symbol",
                "source": "enc_point",
                "source-layer": "enc_point",
                "filter": ["has", "PointInstruction"],
                "layout": {
                    "icon-image": ["get", "PointInstruction"],
                    "icon-allow-overlap": True,
                    "icon-ignore-placement": True,
                    "symbol-sort-key": ["coalesce", ["get", "DrawingPriority"], 0],
                },
            },
            {
                "id": "enc-labels",
                "type": "symbol",
                "source": "enc_point",
                "source-layer": "enc_point",
                "filter": ["has", "TextInstruction"],
                "layout": {
                    "text-field": ["get", "TextInstruction"],
                    "text-font": ["Roboto Regular"],
                    "text-size": ["coalesce", ["get", "FontSize"], 10],
                },
                "paint": {
                    "text-color": font_match,
                    "text-halo-color": color("NODTA"),
                    "text-halo-width": 0.5,
                },
            },
        ],
    }


def _build_match_expr(
    key: str,
    tokens: Iterable[str],
    resolver,
    fallback_token: str,
) -> List[Any]:
    unique = sorted({token for token in tokens if token})
    expr: List[Any] = ["match", ["get", key]]
    for token in unique:
        expr.extend([token, resolver(token)])
    expr.append(resolver(fallback_token))
    return expr


def build_all_styles(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    tile_base_url: str = "http://localhost:3000",
    palette_dir: Path | None = None,
    tokens_payload: Any = None,
) -> List[Path]:
    token_sets = collect_tokens(tokens_payload or {})
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []

    for theme in DEFAULT_THEMES:
        palette = dict(FALLBACK_PALETTES[theme])
        if palette_dir:
            palette.update(load_palette_xml(palette_dir / f"{theme}.xml"))

        style = build_style(
            theme=theme,
            palette=palette,
            tile_base_url=tile_base_url.rstrip("/"),
            token_sets=token_sets,
        )
        output = out_dir / f"enc-{theme}.json"
        output.write_text(json.dumps(style, indent=2), encoding="utf-8")
        written.append(output)

    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build day/dusk/night MapLibre styles for OpenENC.")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR.as_posix(), help="Output directory")
    parser.add_argument("--tile-base-url", default="http://localhost:3000", help="Base URL for Martin endpoints")
    parser.add_argument(
        "--palette-dir",
        default=None,
        help="Optional directory with day.xml/dusk.xml/night.xml colour tables",
    )
    parser.add_argument(
        "--tokens-json",
        default=None,
        help="Optional JSON payload of parsed drawing instructions for token discovery",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tokens_payload = None
    if args.tokens_json:
        tokens_payload = json.loads(Path(args.tokens_json).read_text(encoding="utf-8"))

    outputs = build_all_styles(
        out_dir=Path(args.out_dir),
        tile_base_url=args.tile_base_url,
        palette_dir=Path(args.palette_dir) if args.palette_dir else None,
        tokens_payload=tokens_payload,
    )
    for output in outputs:
        print(f"[style] wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

