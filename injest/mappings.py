"""Mapping tables from S-57 object/attribute codes to S-101 names.

This is intentionally minimal; extend as additional feature/attribute crosswalks are
needed. Unmapped features fall back to using the S-57 code as the S-101 feature name.
"""

from __future__ import annotations

from typing import Dict, Set, Tuple

# Map S-57 object acronyms to (S-101 feature code, S-101 primitive)
# Primitive must be one of: Point, Curve, Surface; use None to preserve input primitive
# Sources: S-101 Annex A DCEG (docs/S-101PT12_2024_05.1AA_EN_S-101_Annex_A_DCEG_Edition_2.0.0.20240211_Working_V1.pdf)
FEATURE_MAP: Dict[str, Tuple[str, str | None]] = {
    "DEPARE": ("DepthArea", "Surface"),
    "DEPCNT": ("DepthContour", "Curve"),
    "DRGARE": ("DredgedArea", "Surface"),
    "SOUNDG": ("Sounding", "Pointset"),
    "COALNE": ("Coastline", "Curve"),
    "SLCONS": ("ShorelineConstruction", None),
    "ACHARE": ("AnchorageArea", None),
    "SEAARE": ("SeaAreaNamedWaterArea", None),
    "LNDARE": ("LandArea", "Surface"),
    "UNSARE": ("UnsurveyedArea", "Surface"),
    # OBSTRN supports multiple primitives in S-57; preserve primitive so points/lines route correctly.
    "OBSTRN": ("Obstruction", None),
    "WRECKS": ("Wreck", None),
    "UWTROC": ("UnderwaterAwashRock", None),
    "WEDKLP": ("WeedKelp", None),
    "BOYLAT": ("LateralBuoy", "Point"),
    "BOYCAR": ("CardinalBuoy", "Point"),
    "BOYISD": ("IsolatedDangerBuoy", "Point"),
    "BOYSAW": ("SafeWaterBuoy", "Point"),
    "BOYSPP": ("SpecialPurposeGeneralBuoy", "Point"),
    "RIVERS": ("River", None),
}

# Attribute crosswalks per S-57 object. Keys are S-57 attribute acronyms; values
# are S-101 attribute names.
ATTRIBUTE_MAP: Dict[str, Dict[str, str]] = {
    "DEPARE": {
        "DRVAL1": "depthRangeMinimumValue",
        "DRVAL2": "depthRangeMaximumValue",
        "TECSOU": "techniqueOfSoundingMeasurement",
    },
    "DRGARE": {
        "DRVAL1": "depthRangeMinimumValue",
        "DRVAL2": "depthRangeMaximumValue",
        "DREDGE": "dredgedDate",
    },
    "SOUNDG": {
        "VALSOU": "valueOfSounding",
        "QUASOU": "qualityOfSoundingMeasurement",
    },
    "COALNE": {
        "CATCOA": "categoryOfCoastline",
    },
    "SLCONS": {
        "CATSLC": "categoryOfShorelineConstruction",
        "CONDTN": "condition",
        "WATLEV": "waterLevelEffect",
    },
    "ACHARE": {
        "CATACH": "categoryOfAnchorage",
    },
    "DEPCNT": {
        "VALDCO": "valueOfDepthContour",
    },
    "OBSTRN": {
        "VALSOU": "valueOfSounding",
        "WATLEV": "waterLevelEffect",
        "CATOBS": "categoryOfObstruction",
    },
    "WRECKS": {
        "VALSOU": "valueOfSounding",
        "WATLEV": "waterLevelEffect",
        "CATWRK": "categoryOfWreck",
        "EXPSOU": "qualityOfSoundingMeasurement",
    },
    "UWTROC": {
        "VALSOU": "valueOfSounding",
        "WATLEV": "waterLevelEffect",
        "QUASOU": "qualityOfSoundingMeasurement",
    },
    "WEDKLP": {
        "CATWED": "categoryOfWeedKelp",
    },
    "BOYLAT": {
        "BOYSHP": "buoyShape",
        "CATLAM": "categoryOfLateralMark",
        "COLOUR": "colour",
        "COLOUR2": "colour",
        "COLOUR3": "colour",
    },
    "BOYCAR": {
        "BOYSHP": "buoyShape",
        "CATCAR": "categoryOfCardinalMark",
        "COLOUR": "colour",
        "COLOUR2": "colour",
        "COLOUR3": "colour",
    },
    "BOYISD": {
        "BOYSHP": "buoyShape",
        "COLOUR": "colour",
        "COLOUR2": "colour",
        "COLOUR3": "colour",
    },
    "BOYSAW": {
        "BOYSHP": "buoyShape",
        "COLOUR": "colour",
        "COLOUR2": "colour",
        "COLOUR3": "colour",
    },
    "BOYSPP": {
        "BOYSHP": "buoyShape",
        "CATSUP": "categoryOfSpecialPurposeMark",
        "COLOUR": "colour",
        "COLOUR2": "colour",
        "COLOUR3": "colour",
    },
    "RIVERS": {},
}

# Attributes mapped for every feature (Annex A common fields)
GLOBAL_ATTRIBUTE_MAP: Dict[str, str] = {
    "OBJNAM": "featureName",
    "INFORM": "information",
    "SORDAT": "date",
    "QUAPOS": "qualityOfPosition",
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
        code, primitive = mapped
        return code, primitive or geom_primitive
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

    numeric_pref_keys = {
        "DRVAL1",
        "DRVAL2",
        "VALDCO",
        "VALSOU",
        "QUASOU",
        "QUAPOS",
        "WATLEV",
        "CATOBS",
        "CATWRK",
        "CATWED",
        "BOYSHP",
        "CATLAM",
        "CATCAR",
        "CATSUP",
        "COLOUR",
        "COLOUR2",
        "COLOUR3",
        "CATCOA",
        "CATSLC",
        "CONDTN",
        "CATACH",
        "EXPSOU",
        "TECSOU",
    }

    def _coerce_numeric(key: str, value: object) -> object:
        if key not in numeric_pref_keys:
            return value

        if isinstance(value, (list, tuple)):
            coerced_list = []
            for v in value:
                coerced_list.append(_coerce_numeric(key, v))
            return coerced_list

        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8", "ignore")
            except Exception:
                return value

        if isinstance(value, str):
            stripped = value.strip()
            try:
                as_float = float(stripped)
                if as_float.is_integer():
                    return int(as_float)
                return as_float
            except (TypeError, ValueError):
                return value

        return value

    for key, value in attributes.items():
        if value is None:
            continue
        if key.upper() in DROP_ATTRIBUTES:
            continue
        key_upper = key.upper()
        value = _coerce_numeric(key_upper, value)
        target = crosswalk.get(key_upper) or GLOBAL_ATTRIBUTE_MAP.get(key_upper)
        if target:
            if target == "colour":
                # Ensure colours are stored as integers for portrayal rules.
                def _to_int(v: object) -> object:
                    try:
                        if isinstance(v, bytes):
                            v = v.decode("utf-8", "ignore")
                        return int(v)
                    except Exception:
                        return v

                if isinstance(value, list):
                    value = [_to_int(v) for v in value]
                else:
                    value = _to_int(value)
            if target in mapped:
                existing = mapped[target]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    mapped[target] = [existing, value]
            else:
                mapped[target] = value
        else:
            if include_unknown:
                mapped[f"s57_{key.lower()}"] = value
            if collect_unmapped:
                unmapped.add(key)

    return mapped, unmapped
