from enum import Enum
from pathlib import Path
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import Dict


class Theme(Enum):
    DAY = "Day"
    DUSK = "Dusk"
    NIGHT = "Night"


# Adjust if your project structure differs
PALETTE_DIR = Path("portrayal/PortrayalCatalog/ColorProfiles")
COLOR_PROFILE_FILE = "colorProfile.xml"

SYMBOLS_DIR = Path("portrayal/PortrayalCatalog/Symbols")

_THEME_CSS: dict[Theme, str] = {
    Theme.DAY:   "daySvgStyle.css",
    Theme.DUSK:  "duskSvgStyle.css",
    Theme.NIGHT: "nightSvgStyle.css",
}


@lru_cache(maxsize=3)
def load_theme_css(theme: Theme) -> str:
    """Return the full CSS text for the given theme's SVG style sheet.

    The CSS files ship alongside the IHO symbols and define every
    .fTOKEN / .sTOKEN class used by the SVG elements.
    """
    css_path = SYMBOLS_DIR / _THEME_CSS[theme]
    if not css_path.exists():
        raise FileNotFoundError(f"Theme CSS not found: {css_path}")
    return css_path.read_text(encoding="utf-8")


@lru_cache(maxsize=3)
def load_palette(theme: Theme) -> Dict[str, str]:
    """Load palette for a given theme from colorProfile.xml.

    Returns a mapping token -> "#RRGGBB".
    """
    xml_path = PALETTE_DIR / COLOR_PROFILE_FILE
    if not xml_path.exists():
        raise FileNotFoundError(f"Color profile not found: {xml_path}")

    root = ET.parse(xml_path).getroot()

    palette_elem = root.find(f"palette[@name='{theme.value}']")
    if palette_elem is None:
        raise ValueError(f"Palette '{theme.value}' not found in {xml_path}")

    def rgb_hex(item: ET.Element) -> str:
        srgb = item.find("srgb")
        if srgb is None:
            return "#000000"
        r = int(srgb.findtext("red", "0").strip())
        g = int(srgb.findtext("green", "0").strip())
        b = int(srgb.findtext("blue", "0").strip())
        return f"#{r:02X}{g:02X}{b:02X}"

    return {
        token.strip(): rgb_hex(item)
        for item in palette_elem.iterfind("item")
        if (token := item.get("token")) and item.find("srgb") is not None
    }