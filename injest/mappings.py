"""Mapping tables from S-57 object/attribute codes to S-101 names.

This is intentionally minimal; extend as additional feature/attribute crosswalks are
needed. Unmapped features fall back to using the S-57 code as the S-101 feature name.
"""

from __future__ import annotations

from typing import Dict, Set, Tuple

# Map S-57 object acronyms to (S-101 feature code, S-101 primitive)
# Primitive must be one of: Point, Curve, Surface
FEATURE_MAP: Dict[str, Tuple[str, str]] = {
    "DEPARE": ("DepthArea", "Surface"),
    "DEPCNT": ("DepthContour", "Curve"),
    "SOUNDG": ("Sounding", "Point"),
    "OBSTRN": ("Obstruction", "Point"),
    "WRECKS": ("Wreck", "Point"),
    "UWTROC": ("UnderwaterAwashRock", "Point"),
    "SBDARE": ("SeabedArea", "Surface"),
    "SLCONS": ("ShorelineConstruction", "Curve"),
    "LNDARE": ("LandArea", "Surface"),
}

# Attribute crosswalks per S-57 object. Keys are S-57 attribute acronyms; values
# are S-101 attribute names.
ATTRIBUTE_MAP: Dict[str, Dict[str, str]] = {
    "DEPARE": {
        "DRVAL1": "depthRangeMinimumValue",
        "DRVAL2": "depthRangeMaximumValue",
        "QUAPOS": "qualityOfPosition",
        "TECSOU": "techniqueOfSoundingMeasurement",
    },
    "DEPCNT": {
        "VALDCO": "valueOfDepthContour",
        "QUAPOS": "qualityOfPosition",
    },
    "SOUNDG": {
        "VALSOU": "valueOfSounding",
        "QUASOU": "qualityOfSoundingMeasurement",
        "TECSOU": "techniqueOfSoundingMeasurement",
    },
    "OBSTRN": {
        "VALSOU": "valueOfSounding",
        "WATLEV": "waterLevelEffect",
        "CATOBS": "categoryOfObstruction",
        "QUASOU": "qualityOfSoundingMeasurement",
    },
    "WRECKS": {
        "VALSOU": "valueOfSounding",
        "WATLEV": "waterLevelEffect",
        "CATWRK": "categoryOfWreck",
        "QUASOU": "qualityOfSoundingMeasurement",
    },
    "UWTROC": {
        "VALSOU": "valueOfSounding",
        "WATLEV": "waterLevelEffect",
    },
    "SBDARE": {
        "NATSUR": "surfaceCharacteristics",
        "WATLEV": "waterLevelEffect",
        "QUAPOS": "qualityOfPosition",
    },
    "SLCONS": {
        "CATSLC": "categoryOfShorelineConstruction",
        "CONDTN": "condition",
        "WATLEV": "waterLevelEffect",
        "QUAPOS": "qualityOfPosition",
    },
}

# Attributes to drop entirely (not sent to portrayal) even if present in source.
DROP_ATTRIBUTES: Set[str] = {
    "RADARCONSPICUOUS",
    "RADCON",
}


def map_feature(s57_code: str, geom_primitive: str) -> tuple[str, str]:
    """Return (s101_code, primitive). Falls back to the S-57 code if unknown."""

    s57_upper = s57_code.upper()
    mapped = FEATURE_MAP.get(s57_upper)
    if mapped:
        return mapped
    return s57_upper, geom_primitive


def map_attributes(
    s57_code: str,
    attributes: Dict[str, object],
    *,
    include_unknown: bool = False,
    collect_unmapped: bool = False,
) -> tuple[Dict[str, object], Set[str]]:
    """Map S-57 attributes to S-101 names.

    Returns a tuple of (mapped_attributes, unmapped_keys).
    If include_unknown is True, unmapped attributes are returned prefixed with
    ``s57_``; otherwise they are omitted. When collect_unmapped is True, the
    names of unmapped attributes are returned so callers can log warnings.
    """

    s57_upper = s57_code.upper()
    crosswalk = ATTRIBUTE_MAP.get(s57_upper, {})
    mapped: Dict[str, object] = {}
    unmapped: Set[str] = set()

    for key, value in attributes.items():
        if value is None:
            continue
        if key.upper() in DROP_ATTRIBUTES:
            continue
        target = crosswalk.get(key.upper())
        if target:
            mapped[target] = value
        else:
            if include_unknown:
                mapped[f"s57_{key.lower()}"] = value
            if collect_unmapped:
                unmapped.add(key)

    return mapped, unmapped
