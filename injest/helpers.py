from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Set, Tuple

from injest.mappings import map_attributes

# Geometry table definitions and primitives used for selection and DDL generation.
TABLE_SCHEMAS: Dict[str, Dict[str, str]] = {
    "enc_area": {"geometry": "MultiPolygon", "primitive": "Surface"},
    "enc_line": {"geometry": "MultiLineString", "primitive": "Curve"},
    "enc_point": {"geometry": "Point", "primitive": "Point"},
    "enc_sounding": {"geometry": "Point", "primitive": "Point"},
}

PX_PER_MM = 96.0 / 25.4

# Feature codes that require a depth value for portrayal safety.
HAZARD_CODES: Set[str] = {"UnderwaterAwashRock", "Obstruction", "Wreck"}


def _normalize_feature_names(value: Any) -> List[Dict[str, Any]]:
    """Return featureName as a list of tables with a ``name`` key.

    S-101 portrayal rules expect ``feature.featureName[1].name`` to exist. S-57
    ``OBJNAM`` is a simple string, so coerce it (and any other simple inputs) to
    the structured shape the catalogue expects.
    """

    names: List[Dict[str, Any]] = []

    def _to_entry(item: Any) -> Dict[str, Any] | None:
        if item is None:
            return None
        if isinstance(item, dict):
            name_val = item.get("name") or item.get("Name") or item.get("text") or item.get("value")
            if name_val is None and len(item) == 1:
                name_val = next(iter(item.values()))
            if name_val is None or name_val == "":
                return None
            entry: Dict[str, Any] = {"name": str(name_val)}
            if item.get("language"):
                entry["language"] = item["language"]
            if item.get("nameUsage") is not None:
                entry["nameUsage"] = item["nameUsage"]
            else:
                entry["nameUsage"] = 1
            return entry
        if isinstance(item, (str, int, float)):
            text = str(item).strip()
            return {"name": text, "nameUsage": 1} if text else None
        return {"name": str(item), "nameUsage": 1}

    if isinstance(value, (list, tuple, set)):
        for item in value:
            entry = _to_entry(item)
            if entry:
                names.append(entry)
    else:
        entry = _to_entry(value)
        if entry:
            names.append(entry)

    return names


def build_table_sql(schema: str) -> List[str]:
    """Generate per-table DDL statements for the S-101 output schema."""

    statements: List[str] = []
    for table, meta in TABLE_SCHEMAS.items():
        color_fill_col = "\n            color_fill  TEXT," if table == "enc_area" else ""
        statements.append(
            f"""
        CREATE TABLE IF NOT EXISTS {schema}.{table} (
            id          BIGSERIAL PRIMARY KEY,
            s57_code    TEXT NOT NULL,
            feature_code TEXT NOT NULL,
            cell_name   TEXT NOT NULL,
            foid        TEXT NOT NULL,
            geom        geometry({meta['geometry']}, 4326) NOT NULL,
            attr_jsonb  JSONB,
            di_jsonb    JSONB,{color_fill_col}
            drawing_priority INTEGER,
            line_width_px DOUBLE PRECISION
        );
        CREATE INDEX IF NOT EXISTS {table}_geom_idx ON {schema}.{table} USING GIST (geom);
        CREATE INDEX IF NOT EXISTS {table}_feature_idx ON {schema}.{table} (feature_code);
    """
        )

    return statements


def pick_table(s57_code: str, primitive: str) -> str:
    if s57_code.upper() == "SOUNDG":
        return "enc_sounding"
    if primitive == "Surface":
        return "enc_area"
    if primitive == "Curve":
        return "enc_line"
    return "enc_point"


def strip_meta_fields(raw_attrs: Dict[str, Any], meta_keys: Iterable[str] = ("RCID", "LNAM")) -> Dict[str, Any]:
    meta = {m.upper() for m in meta_keys}
    cleaned: Dict[str, Any] = {}
    for key, value in raw_attrs.items():
        if key.upper() in meta:
            continue
        cleaned[key] = value
    return cleaned


def extract_associations(raw_attrs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract association references (LNAM_REFS) from raw attributes.

    Removes consumed keys so they do not trigger unmapped warnings upstream.
    """

    associations: List[Dict[str, Any]] = []
    refs = raw_attrs.pop("LNAM_REFS", None) or raw_attrs.pop("lnam_refs", None)
    if not refs:
        return associations

    if isinstance(refs, str):
        ref_list = [r.strip() for r in refs.split(",") if r.strip()]
    elif isinstance(refs, (list, tuple, set)):
        ref_list = [str(r).strip() for r in refs if str(r).strip()]
    else:
        ref_list = [str(refs).strip()]

    for ref in ref_list:
        associations.append({"target_foid": ref, "source": "LNAM_REFS"})

    return associations


def apply_depth_enrichment(
    s57_code: str,
    s101_code: str,
    mapped_attrs: Dict[str, Any],
    depth_z: float | None,
) -> Dict[str, Any]:
    enriched = dict(mapped_attrs)

    if depth_z is not None:
        if s57_code.upper() == "SOUNDG" and "valueOfSounding" not in enriched:
            enriched["valueOfSounding"] = depth_z
        if s101_code in HAZARD_CODES:
            if "valueOfSounding" not in enriched and "defaultClearanceDepth" not in enriched:
                enriched["defaultClearanceDepth"] = depth_z

    if s101_code in HAZARD_CODES:
        if "valueOfSounding" not in enriched and "defaultClearanceDepth" not in enriched:
            enriched["defaultClearanceDepth"] = 0.0

    return enriched


def prepare_attributes(
    s57_code: str,
    s101_code: str,
    raw_attrs: Dict[str, Any],
    depth_z: float | None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Set[str], List[Dict[str, Any]]]:
    """Map and enrich attributes for storage and portrayal."""

    cleaned = strip_meta_fields(raw_attrs)
    associations = extract_associations(cleaned)

    mapped_attrs, unmapped = map_attributes(
        s57_code,
        cleaned,
        include_unknown=False,
        collect_unmapped=True,
    )

    # Coerce OBJNAM (and any other inputs) into the structured form the catalogue expects.
    mapped_attrs["featureName"] = _normalize_feature_names(mapped_attrs.get("featureName"))

    enriched = apply_depth_enrichment(s57_code, s101_code, mapped_attrs, depth_z)
    stored_attrs = dict(enriched)
    if associations:
        stored_attrs["associations"] = associations

    return enriched, stored_attrs, unmapped, associations


def group_rows_by_table(rows: Dict[str, Any], di_json: Dict[str, List[Dict[str, Any]]]):
    def _as_int_like(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                return None
        return None

    def _extract_drawing_priority(di_payload: List[Dict[str, Any]] | None) -> int:
        if not di_payload:
            return 0
        for instr in di_payload:
            if not isinstance(instr, dict):
                continue
            if "DrawingPriority" not in instr:
                continue
            parsed = _as_int_like(instr.get("DrawingPriority"))
            if parsed is not None:
                return parsed
        return 0

    def _extract_color_fill(di_payload: List[Dict[str, Any]] | None) -> str | None:
        if not di_payload:
            return None
        for instr in di_payload:
            if not isinstance(instr, dict):
                continue
            value = instr.get("ColorFill")
            if value is None:
                continue
            if isinstance(value, str):
                text = value.strip()
                if text:
                    return text
            else:
                text = str(value).strip()
                if text:
                    return text
        return None

    def _extract_line_width_px(di_payload: List[Dict[str, Any]] | None) -> float | None:
        if not di_payload:
            return None

        def _mm_to_px(mm: float) -> float:
            return mm * PX_PER_MM

        for instr in di_payload:
            if not isinstance(instr, dict):
                continue

            # Prefer explicit LineWidth if present.
            if "LineWidth" in instr:
                raw = instr.get("LineWidth")
                try:
                    mm = float(raw) if raw is not None else None
                except (TypeError, ValueError):
                    mm = None
                if mm is not None:
                    return _mm_to_px(mm)

            # Fallback: parse from LineStyle:_simple_,[dash],<width>,<color>
            line_style = instr.get("LineStyle")
            if isinstance(line_style, str):
                parts = [p.strip() for p in line_style.split(",")]
                if len(parts) >= 3 and parts[2] != "":
                    try:
                        mm = float(parts[2])
                        return _mm_to_px(mm)
                    except (TypeError, ValueError):
                        pass

        return None

    grouped: Dict[str, List[Tuple[Any, ...]]] = defaultdict(list)
    for fid, row in rows.items():
        di_payload = di_json.get(fid, []) or None
        color_fill = _extract_color_fill(di_payload)
        drawing_priority = _extract_drawing_priority(di_payload)
        line_width_px = _extract_line_width_px(di_payload)
        grouped[row.table].append(
            (
                row.s57_code,
                row.feature_code,
                row.cell_name,
                row.foid,
                row.geom_wkb,
                row.attr_json,
                di_payload,
                color_fill,
                drawing_priority,
                line_width_px,
            )
        )
    return grouped
