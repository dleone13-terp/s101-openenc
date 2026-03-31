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

# Feature codes that require a depth value for portrayal safety.
HAZARD_CODES: Set[str] = {"UnderwaterAwashRock", "Obstruction", "Wreck"}


def build_table_sql(schema: str) -> List[str]:
    """Generate per-table DDL statements for the S-101 output schema."""

    statements: List[str] = []
    template = """
        CREATE TABLE IF NOT EXISTS {schema}.{table} (
            id          BIGSERIAL PRIMARY KEY,
            s57_code    TEXT NOT NULL,
            feature_code TEXT NOT NULL,
            cell_name   TEXT NOT NULL,
            foid        TEXT NOT NULL,
            geom        geometry({geometry}, 4326) NOT NULL,
            attr_jsonb  JSONB,
            di_jsonb    JSONB
        );
        CREATE INDEX IF NOT EXISTS {table}_geom_idx ON {schema}.{table} USING GIST (geom);
        CREATE INDEX IF NOT EXISTS {table}_feature_idx ON {schema}.{table} (feature_code);
    """

    for table, meta in TABLE_SCHEMAS.items():
        statements.append(
            template.format(schema=schema, table=table, geometry=meta["geometry"])
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

    enriched = apply_depth_enrichment(s57_code, s101_code, mapped_attrs, depth_z)
    stored_attrs = dict(enriched)
    if associations:
        stored_attrs["associations"] = associations

    return enriched, stored_attrs, unmapped, associations


def group_rows_by_table(rows: Dict[str, Any], di_json: Dict[str, List[Dict[str, Any]]]):
    grouped: Dict[str, List[Tuple[Any, ...]]] = defaultdict(list)
    for fid, row in rows.items():
        di_payload = di_json.get(fid, []) or None
        grouped[row.table].append(
            (
                row.s57_code,
                row.feature_code,
                row.cell_name,
                row.foid,
                row.geom_wkb,
                row.attr_json,
                di_payload,
            )
        )
    return grouped
