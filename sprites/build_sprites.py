import io
import json
import re
from pathlib import Path

import cairosvg
from PIL import Image

from utils.colors import load_theme_css, Theme, SYMBOLS_DIR

OUT_DIR = Path('sprites/out')

# Matches the XML stylesheet PI, e.g.:
#   <?xml-stylesheet href="daySvgStyle.css" type="text/css"?>
_PI_PATTERN = re.compile(r'<\?xml-stylesheet[^?]*\?>\n?')


def inline_svg_styles(svg_text: str, css: str) -> str:
    """Return svg_text with theme CSS inlined as a <style> block.

    The external <?xml-stylesheet?> processing instruction is stripped so
    sprite renderers (which ignore external CSS) see only the inline styles.
    """
    # Remove the external stylesheet PI
    svg_text = _PI_PATTERN.sub('', svg_text)
    # Inject <style> immediately after the opening <svg ...> tag
    svg_tag_end = svg_text.index('>', svg_text.index('<svg')) + 1
    style_block = f'\n  <style>\n{css}  </style>'
    return svg_text[:svg_tag_end] + style_block + svg_text[svg_tag_end:]


def build_atlas(resolved_dir: Path, sprite_prefix: str, scale: int = 1) -> None:
    """Rasterise every SVG in resolved_dir and pack them into a sprite atlas.

    Produces {sprite_prefix}.png  — RGBA sprite sheet
             {sprite_prefix}.json — Mapbox GL sprite manifest
    """
    # Rasterise each SVG at the requested scale
    symbols: list[tuple[str, Image.Image]] = []
    for svg_path in sorted(resolved_dir.glob('*.svg')):
        png_bytes = cairosvg.svg2png(url=svg_path.resolve().as_uri(), scale=scale)
        if png_bytes is not None:
            img = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
            symbols.append((svg_path.stem, img))

    if not symbols:
        return

    # Sort tallest-first for tighter row packing
    symbols.sort(key=lambda s: s[1].height, reverse=True)

    # Row-pack: advance x until a symbol overflows the max width, then wrap
    MAX_WIDTH = 2048
    cursor_x, cursor_y, row_h = 0, 0, 0
    positions: list[tuple[str, int, int, int, int]] = []  # name, x, y, w, h

    for name, img in symbols:
        w, h = img.size
        if cursor_x + w > MAX_WIDTH:
            cursor_y += row_h
            cursor_x = 0
            row_h = 0
        positions.append((name, cursor_x, cursor_y, w, h))
        row_h = max(row_h, h)
        cursor_x += w

    atlas_h = cursor_y + row_h

    # Build the atlas and the JSON manifest
    atlas = Image.new('RGBA', (MAX_WIDTH, atlas_h), (0, 0, 0, 0))
    img_by_name = dict(symbols)
    manifest: dict[str, dict] = {}

    for name, x, y, w, h in positions:
        atlas.paste(img_by_name[name], (x, y))
        manifest[name] = {'x': x, 'y': y, 'width': w, 'height': h,
                          'pixelRatio': scale, 'sdf': False}

    atlas.save(f'{sprite_prefix}.png')
    Path(f'{sprite_prefix}.json').write_text(
        json.dumps(manifest, indent=2), encoding='utf-8'
    )


def build_sprites():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for theme in Theme:
        css = load_theme_css(theme)

        # Output dir for resolved SVGs for this theme
        resolved_dir = OUT_DIR / f'{theme.value}_src'
        resolved_dir.mkdir(exist_ok=True)

        svg_files = list(SYMBOLS_DIR.glob('*.svg'))
        print(f"  Processing {len(svg_files)} symbols for theme '{theme.value}'")

        for svg_path in svg_files:
            resolved_svg = inline_svg_styles(svg_path.read_text(encoding='utf-8'), css)
            (resolved_dir / svg_path.name).write_text(resolved_svg, encoding='utf-8')

        # Build sprite atlas at 1x and 2x
        theme_dir = OUT_DIR / theme.value
        theme_dir.mkdir(exist_ok=True)
        sprite_prefix = str(theme_dir / 'sprite')

        build_atlas(resolved_dir, sprite_prefix, scale=1)
        build_atlas(resolved_dir, f'{sprite_prefix}@2x', scale=2)

        print(f"  ✓ Sprites for {theme.value}: {sprite_prefix}.{{json,png}}")


if __name__ == '__main__':
    build_sprites()