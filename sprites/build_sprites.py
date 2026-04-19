"""
Generate palette-specific SVG sprite inputs for Martin.

- Copies portrayal catalogue symbol SVGs into palette-specific output trees.
- Rewrites the xml-stylesheet href to the palette CSS (day/dusk/night).
- Copies the palette CSS alongside the sprites.
- Emits a manifest with basic size metadata and requested pixel ratios (@1x/@2x).

Martin can later rasterize these SVGs into sprite.png/sprite@2x.png using its
sprite pipeline; this script only prepares the palette-coloured SVG inputs.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

PALETTES = {
    "day": "daySvgStyle.css",
    "dusk": "duskSvgStyle.css",
    "night": "nightSvgStyle.css",
}

WIDTH_RE = re.compile(r'width="([0-9.]+)mm"')
HEIGHT_RE = re.compile(r'height="([0-9.]+)mm"')
STYLESHEET_RE = re.compile(r"href=\"[^\"]*SvgStyle\.css\"")


@dataclass
class SymbolMeta:
    name: str
    width_mm: float | None
    height_mm: float | None
    file: Path


def extract_size(svg_text: str) -> tuple[float | None, float | None]:
    width = WIDTH_RE.search(svg_text)
    height = HEIGHT_RE.search(svg_text)
    width_mm = float(width.group(1)) if width else None
    height_mm = float(height.group(1)) if height else None
    return width_mm, height_mm


def rewrite_stylesheet(svg_text: str, css_name: str) -> str:
    """Point the xml-stylesheet href at the palette CSS."""
    return STYLESHEET_RE.sub(f'href="{css_name}"', svg_text, count=1)


def copy_symbols(
    symbols_dir: Path,
    css_name: str,
    out_dir: Path,
) -> list[SymbolMeta]:
    metas: list[SymbolMeta] = []
    out_symbols_dir = out_dir / "symbols"
    out_symbols_dir.mkdir(parents=True, exist_ok=True)

    for svg_path in sorted(symbols_dir.glob("*.svg")):
        text = svg_path.read_text()
        width_mm, height_mm = extract_size(text)
        rewritten = rewrite_stylesheet(text, css_name)

        dst = out_symbols_dir / svg_path.name
        dst.write_text(rewritten)

        metas.append(
            SymbolMeta(
                name=svg_path.stem,
                width_mm=width_mm,
                height_mm=height_mm,
                file=dst.relative_to(out_dir),
            )
        )

    return metas


def copy_css(css_dir: Path, css_name: str, out_dir: Path) -> Path:
    src = css_dir / css_name
    dst = out_dir / css_name
    shutil.copyfile(src, dst)
    return dst


def build_manifest(palette: str, metas: Iterable[SymbolMeta], pixel_ratios: List[int]) -> dict:
    return {
        "palette": palette,
        "pixelRatios": pixel_ratios,
        "symbols": [
            {
                "name": m.name,
                "file": str(m.file).replace("\\", "/"),
                "width_mm": m.width_mm,
                "height_mm": m.height_mm,
            }
            for m in metas
        ],
    }


def write_manifest(manifest: dict, out_dir: Path) -> Path:
    out_path = out_dir / "manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2))
    return out_path


def run(palette: str, args: argparse.Namespace) -> None:
    css_name = PALETTES[palette]
    out_dir = Path(args.out_dir) / palette
    out_dir.mkdir(parents=True, exist_ok=True)

    metas = copy_symbols(Path(args.symbols_dir), css_name, out_dir)
    copy_css(Path(args.css_dir), css_name, out_dir)
    manifest = build_manifest(palette, metas, args.pixel_ratios)
    write_manifest(manifest, out_dir)
    print(f"[{palette}] wrote {len(metas)} symbols to {out_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare palette-specific SVG sprites for Martin")
    parser.add_argument(
        "--symbols-dir",
        default="portrayal/PortrayalCatalog/Symbols",
        help="Directory containing source symbol SVGs",
    )
    parser.add_argument(
        "--css-dir",
        default="portrayal/PortrayalCatalog/Symbols",
        help="Directory containing palette CSS files",
    )
    parser.add_argument(
        "--out-dir",
        default="sprites/out",
        help="Output directory (palette subfolders are created inside)",
    )
    parser.add_argument(
        "--palette",
        choices=["day", "dusk", "night", "all"],
        default="all",
        help="Palette to build (default: all)",
    )
    parser.add_argument(
        "--pixel-ratios",
        nargs="+",
        type=int,
        default=[1, 2],
        help="Pixel ratios to advertise in manifest.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    palettes = list(PALETTES.keys()) if args.palette == "all" else [args.palette]
    for palette in palettes:
        run(palette, args)


if __name__ == "__main__":
    main()
