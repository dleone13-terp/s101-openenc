#!/usr/bin/env python3
"""Convert S-57 ENCs (via GDAL/OGR) into minimal S-101-ready tables.

- Reads ENC cells directly with the OGR S-57 driver (no raw_s57 dependency).
- Maps S-57 object/attribute codes to S-101 names (see mappings.py).
- Runs the S-101 portrayal catalogue and stores drawing instructions as JSONB.
- Writes per-geometry tables with attr_jsonb and di_jsonb.

This is a starter pipeline; extend the crosswalks in mappings.py as needed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
import math
from typing import Any, Dict, Iterable, List, Set, Tuple

from osgeo import gdal, ogr, osr
import psycopg2
import psycopg2.extras

from portrayal_engine.host import FeatureRecord, PortrayalHost
from injest.helpers import (
    build_table_sql,
    group_rows_by_table,
    pick_table,
    prepare_attributes,
)
from injest.mappings import map_feature

# Keep S-57 driver options aligned with import_test_enc.sh
S57_OPTIONS = "RETURN_PRIMITIVES=ON,RETURN_LINKAGES=ON,LNAM_REFS=ON,SPLIT_MULTIPOINT=ON,ADD_SOUNDG_DEPTH=ON"

# Geometry type constants
SURFACE_TYPES = {ogr.wkbPolygon, ogr.wkbPolygon25D, ogr.wkbMultiPolygon, ogr.wkbMultiPolygon25D}
CURVE_TYPES = {
    ogr.wkbLineString,
    ogr.wkbLineString25D,
    ogr.wkbMultiLineString,
    ogr.wkbMultiLineString25D,
}
POINT_TYPES = {ogr.wkbPoint, ogr.wkbPoint25D, ogr.wkbMultiPoint, ogr.wkbMultiPoint25D}

# Topology/meta layers from S-57 that should be ignored for portrayal output.
# Some information coverages (M_QUAL, M_COVR, NEWOBJ, M_* info) lack rules in the
# bundled portrayal catalogue and would throw module load errors, so skip them as well.
SKIP_LAYERS = {
    "ISOLATEDNODE",
    "CONNECTEDNODE",
    "EDGE",
    "M_QUAL",
    "NEWOBJ",
    "M_COVR",
    "M_NPUB",
    "M_NSYS",
    "M_SDAT",
    "M_VDAT",
    # Not covered by bundled portrayal catalogue and cause module load failures.
    "TSSBND",
    "TSSLPT",
    "TSEZNE",
    "SBDARE",
    "SLOGRD",
    "TESARE",
}


@dataclass
class PendingRow:
    feature: FeatureRecord
    table: str
    cell_name: str
    s57_code: str
    feature_code: str
    foid: str
    geom_wkb: bytes
    attr_json: Dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="S-57 → S-101 minimal converter")
    parser.add_argument("enc_paths", nargs="+", help="Path(s) to S-57 ENC .000 files or directories")
    parser.add_argument("--schema", default="s101", help="Target schema (default: s101)")
    parser.add_argument("--apply", action="store_true", help="Write to PostGIS (default: dry-run)")
    parser.add_argument("--skip-portrayal", action="store_true", help="Skip portrayal; leave di_def/di_jsonb null")
    parser.add_argument(
        "--dsn",
        default=None,
        help="Postgres DSN (defaults to env POSTGRES_* vars)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit features processed (debug)")
    parser.add_argument(
        "--only-feature",
        dest="only_feature",
        help="Process only this S-57 feature code (e.g., DEPARE or DEPCNT). Case-insensitive.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print per-feature attribute inputs/outputs and associations to stdout",
    )
    return parser.parse_args()


def default_dsn() -> str:
    host = os.getenv("POSTGRES_HOSTNAME", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "postgres")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    return f"host={host} port={port} dbname={db} user={user} password={password}"


def ensure_schema(conn, schema: str) -> None:
    cursor = conn.cursor()
    cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    conn.commit()


def ensure_tables(conn, schema: str) -> None:
    cursor = conn.cursor()
    for statement in build_table_sql(schema):
        cursor.execute(statement)

    # Migration-safe: existing tables may predate the drawing_priority column.
    for table in ("enc_area", "enc_line", "enc_point", "enc_sounding"):
        if table == "enc_area":
            cursor.execute(f"ALTER TABLE {schema}.{table} ADD COLUMN IF NOT EXISTS color_fill TEXT")
        else:
            cursor.execute(f"ALTER TABLE {schema}.{table} DROP COLUMN IF EXISTS color_fill")
        cursor.execute(f"ALTER TABLE {schema}.{table} ADD COLUMN IF NOT EXISTS drawing_priority INTEGER")
        cursor.execute(f"ALTER TABLE {schema}.{table} ADD COLUMN IF NOT EXISTS line_width_px DOUBLE PRECISION")
        cursor.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_drawing_priority_idx ON {schema}.{table} (drawing_priority)"
        )

        if table == "enc_area":
            cursor.execute(
                f"""
                UPDATE {schema}.{table} t
                SET color_fill = (
                    SELECT NULLIF(elem->>'ColorFill', '')
                    FROM jsonb_array_elements(COALESCE(t.di_jsonb, '[]'::jsonb)) elem
                    WHERE elem ? 'ColorFill'
                    LIMIT 1
                )
                WHERE t.color_fill IS NULL
                """
            )

        cursor.execute(
            f"""
            UPDATE {schema}.{table} t
            SET drawing_priority = COALESCE(
                (
                    SELECT CASE
                        WHEN (elem->>'DrawingPriority') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$' THEN (elem->>'DrawingPriority')::numeric::int
                        ELSE NULL
                    END
                    FROM jsonb_array_elements(COALESCE(t.di_jsonb, '[]'::jsonb)) elem
                    WHERE elem ? 'DrawingPriority'
                    LIMIT 1
                ),
                0
            )
            WHERE t.drawing_priority IS NULL
            """
        )

        cursor.execute(
            f"""
            UPDATE {schema}.{table} t
            SET line_width_px = (
                SELECT COALESCE(
                    CASE
                        WHEN (elem->>'LineWidth') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                            THEN (elem->>'LineWidth')::double precision
                        ELSE NULL
                    END,
                    CASE
                        WHEN NULLIF(split_part((elem->>'LineStyle'), ',', 3), '') IS NOT NULL
                             AND split_part((elem->>'LineStyle'), ',', 3) ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                            THEN split_part((elem->>'LineStyle'), ',', 3)::double precision
                        ELSE NULL
                    END
                ) * (96.0 / 25.4)
                FROM jsonb_array_elements(COALESCE(t.di_jsonb, '[]'::jsonb)) elem
                WHERE (elem ? 'LineWidth') OR (elem ? 'LineStyle')
                LIMIT 1
            )
            WHERE t.line_width_px IS NULL
            """
        )

    conn.commit()


def ensure_mvt_views(conn, schema: str) -> None:
    cursor = conn.cursor()

    # Recreate views from scratch so column shape changes are applied cleanly.
    cursor.execute(f"DROP VIEW IF EXISTS {schema}.enc_area_mvt")
    cursor.execute(f"DROP VIEW IF EXISTS {schema}.enc_line_mvt")
    cursor.execute(f"DROP VIEW IF EXISTS {schema}.enc_point_mvt")
    cursor.execute(f"DROP VIEW IF EXISTS {schema}.enc_sounding_mvt")

    cursor.execute(
        f"""
        CREATE OR REPLACE VIEW {schema}.enc_area_mvt AS
        SELECT
            a.id,
            a.feature_code,
            a.di_jsonb,
            NULLIF(split_part(COALESCE(a.color_fill, di.color_fill), ',', 1), '') AS "ColorFill",
            COALESCE(di.color_fill_opacity, 1.0) AS "ColorFillOpacity",
            di.area_fill_reference AS "AreaFillReference",
            di.line_instruction AS "LineInstruction",
            di.line_style AS "LineStyle",
            COALESCE(di.line_color, NULLIF(split_part(di.line_style, ',', 4), '')) AS "LineColor",
            di.dash_pattern AS "Dash",
            COALESCE(
                a.line_width_px,
                CASE
                    WHEN NULLIF(split_part(di.line_style, ',', 3), '') IS NOT NULL
                        THEN (split_part(di.line_style, ',', 3))::double precision * (96.0 / 25.4)
                    ELSE NULL
                END
            ) AS "LineWidth",
            di.text_instruction AS "TextInstruction",
            di.text_align_horizontal AS "TextAlignHorizontal",
            di.text_align_vertical AS "TextAlignVertical",
            di.local_offset_x AS "TextOffsetX",
            di.local_offset_y AS "TextOffsetY",
            di.rotation AS "TextRotation",
            di.font_color AS "FontColor",
            di.font_size_px AS "FontSize",
            COALESCE(a.drawing_priority, 0) AS "DrawingPriority",
            COALESCE(di.viewing_group, 0) AS "ViewingGroup",
            ST_SetSRID(ST_FlipCoordinates(a.geom), 4326) AS geom
        FROM {schema}.enc_area a
        LEFT JOIN LATERAL (
            SELECT
                (elem.value ->> 'ColorFill') AS color_fill,
                CASE
                    WHEN NULLIF(split_part((elem.value ->> 'ColorFill'), ',', 2), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN split_part((elem.value ->> 'ColorFill'), ',', 2)::double precision
                    ELSE NULL
                END AS color_fill_opacity,
                (elem.value ->> 'AreaFillReference') AS area_fill_reference,
                (elem.value ->> 'LineInstruction') AS line_instruction,
                (elem.value ->> 'LineStyle') AS line_style,
                (elem.value ->> 'LineColor') AS line_color,
                COALESCE(
                    NULLIF((elem.value ->> 'Dash'), ''),
                    CASE
                        WHEN NULLIF(split_part((elem.value ->> 'LineStyle'), ',', 2), '') IS NOT NULL
                            THEN '0,' || split_part((elem.value ->> 'LineStyle'), ',', 2)
                        ELSE NULL
                    END
                ) AS dash_pattern,
                (elem.value ->> 'TextInstruction') AS text_instruction,
                (elem.value ->> 'TextAlignHorizontal') AS text_align_horizontal,
                (elem.value ->> 'TextAlignVertical') AS text_align_vertical,
                CASE
                    WHEN NULLIF(split_part((elem.value ->> 'LocalOffset'), ',', 1), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN split_part((elem.value ->> 'LocalOffset'), ',', 1)::double precision
                    ELSE NULL
                END AS local_offset_x,
                CASE
                    WHEN NULLIF(split_part((elem.value ->> 'LocalOffset'), ',', 2), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN split_part((elem.value ->> 'LocalOffset'), ',', 2)::double precision
                    ELSE NULL
                END AS local_offset_y,
                CASE
                    WHEN NULLIF((elem.value ->> 'Rotation'), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN (elem.value ->> 'Rotation')::double precision
                    ELSE NULL
                END AS rotation,
                COALESCE(
                    NULLIF((elem.value ->> 'FontColor'), ''),
                    NULLIF((elem.value ->> 'FontColour'), '')
                ) AS font_color,
                CASE
                    WHEN NULLIF((elem.value ->> 'FontSize'), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN (elem.value ->> 'FontSize')::double precision * (96.0 / 25.4)
                    ELSE NULL
                END AS font_size_px,
                CASE
                    WHEN (elem.value ? 'DrawingPriority')
                        THEN (NULLIF(split_part((elem.value ->> 'DrawingPriority'), ',', 1), ''))::integer
                    ELSE NULL
                END AS drawing_priority,
                CASE
                    WHEN (elem.value ? 'ViewingGroup')
                        THEN (NULLIF(split_part((elem.value ->> 'ViewingGroup'), ',', 1), ''))::integer
                    ELSE NULL
                END AS viewing_group
            FROM jsonb_array_elements(COALESCE(a.di_jsonb, '[]'::jsonb)) elem(value)
            LIMIT 1
        ) di ON true
        """
    )

    cursor.execute(
        f"""
        CREATE OR REPLACE VIEW {schema}.enc_line_mvt AS
        SELECT
            l.id,
            l.feature_code,
            l.di_jsonb,
            di.line_instruction AS "LineInstruction",
            di.line_style AS "LineStyle",
            COALESCE(di.line_color, NULLIF(split_part(di.line_style, ',', 4), '')) AS "LineColor",
            di.dash_pattern AS "Dash",
            COALESCE(
                l.line_width_px,
                CASE
                    WHEN NULLIF(split_part(di.line_style, ',', 3), '') IS NOT NULL
                        THEN (split_part(di.line_style, ',', 3))::double precision * (96.0 / 25.4)
                    ELSE NULL
                END
            ) AS "LineWidth",
            di.text_instruction AS "TextInstruction",
            di.text_align_horizontal AS "TextAlignHorizontal",
            di.text_align_vertical AS "TextAlignVertical",
            di.local_offset_x AS "TextOffsetX",
            di.local_offset_y AS "TextOffsetY",
            di.rotation AS "TextRotation",
            di.font_color AS "FontColor",
            di.font_size_px AS "FontSize",
            COALESCE(l.drawing_priority, 0) AS "DrawingPriority",
            COALESCE(di.viewing_group, 0) AS "ViewingGroup",
            ST_SetSRID(ST_FlipCoordinates(l.geom), 4326) AS geom
        FROM {schema}.enc_line l
        LEFT JOIN LATERAL (
            SELECT
                (elem.value ->> 'LineInstruction') AS line_instruction,
                (elem.value ->> 'LineStyle') AS line_style,
                (elem.value ->> 'LineColor') AS line_color,
                COALESCE(
                    NULLIF((elem.value ->> 'Dash'), ''),
                    CASE
                        WHEN NULLIF(split_part((elem.value ->> 'LineStyle'), ',', 2), '') IS NOT NULL
                            THEN '0,' || split_part((elem.value ->> 'LineStyle'), ',', 2)
                        ELSE NULL
                    END
                ) AS dash_pattern,
                (elem.value ->> 'TextInstruction') AS text_instruction,
                (elem.value ->> 'TextAlignHorizontal') AS text_align_horizontal,
                (elem.value ->> 'TextAlignVertical') AS text_align_vertical,
                CASE
                    WHEN NULLIF(split_part((elem.value ->> 'LocalOffset'), ',', 1), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN split_part((elem.value ->> 'LocalOffset'), ',', 1)::double precision
                    ELSE NULL
                END AS local_offset_x,
                CASE
                    WHEN NULLIF(split_part((elem.value ->> 'LocalOffset'), ',', 2), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN split_part((elem.value ->> 'LocalOffset'), ',', 2)::double precision
                    ELSE NULL
                END AS local_offset_y,
                CASE
                    WHEN NULLIF((elem.value ->> 'Rotation'), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN (elem.value ->> 'Rotation')::double precision
                    ELSE NULL
                END AS rotation,
                COALESCE(
                    NULLIF((elem.value ->> 'FontColor'), ''),
                    NULLIF((elem.value ->> 'FontColour'), '')
                ) AS font_color,
                CASE
                    WHEN NULLIF((elem.value ->> 'FontSize'), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN (elem.value ->> 'FontSize')::double precision * (96.0 / 25.4)
                    ELSE NULL
                END AS font_size_px,
                CASE
                    WHEN (elem.value ? 'DrawingPriority')
                        THEN (NULLIF(split_part((elem.value ->> 'DrawingPriority'), ',', 1), ''))::integer
                    ELSE NULL
                END AS drawing_priority,
                CASE
                    WHEN (elem.value ? 'ViewingGroup')
                        THEN (NULLIF(split_part((elem.value ->> 'ViewingGroup'), ',', 1), ''))::integer
                    ELSE NULL
                END AS viewing_group
            FROM jsonb_array_elements(COALESCE(l.di_jsonb, '[]'::jsonb)) elem(value)
            LIMIT 1
        ) di ON true
        """
    )

    cursor.execute(
        f"""
        CREATE OR REPLACE VIEW {schema}.enc_point_mvt AS
        SELECT
            p.id,
            p.feature_code,
            p.di_jsonb,
            di.point_instruction AS "PointInstruction",
            di.text_instruction AS "TextInstruction",
            di.text_align_horizontal AS "TextAlignHorizontal",
            di.text_align_vertical AS "TextAlignVertical",
            di.local_offset_x AS "TextOffsetX",
            di.local_offset_y AS "TextOffsetY",
            di.rotation AS "TextRotation",
            di.font_color AS "FontColor",
            di.font_size_px AS "FontSize",
            COALESCE(p.drawing_priority, 0) AS "DrawingPriority",
            COALESCE(di.viewing_group, 0) AS "ViewingGroup",
            ST_SetSRID(ST_FlipCoordinates(p.geom), 4326) AS geom
        FROM {schema}.enc_point p
        LEFT JOIN LATERAL (
            SELECT
                (elem.value ->> 'PointInstruction') AS point_instruction,
                (elem.value ->> 'TextInstruction') AS text_instruction,
                (elem.value ->> 'TextAlignHorizontal') AS text_align_horizontal,
                (elem.value ->> 'TextAlignVertical') AS text_align_vertical,
                CASE
                    WHEN NULLIF(split_part((elem.value ->> 'LocalOffset'), ',', 1), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN split_part((elem.value ->> 'LocalOffset'), ',', 1)::double precision
                    ELSE NULL
                END AS local_offset_x,
                CASE
                    WHEN NULLIF(split_part((elem.value ->> 'LocalOffset'), ',', 2), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN split_part((elem.value ->> 'LocalOffset'), ',', 2)::double precision
                    ELSE NULL
                END AS local_offset_y,
                CASE
                    WHEN NULLIF((elem.value ->> 'Rotation'), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN (elem.value ->> 'Rotation')::double precision
                    ELSE NULL
                END AS rotation,
                COALESCE(
                    NULLIF((elem.value ->> 'FontColor'), ''),
                    NULLIF((elem.value ->> 'FontColour'), '')
                ) AS font_color,
                CASE
                    WHEN NULLIF((elem.value ->> 'FontSize'), '') ~ '^[-+]?[0-9]+(\\.[0-9]+)?$'
                        THEN (elem.value ->> 'FontSize')::double precision * (96.0 / 25.4)
                    ELSE NULL
                END AS font_size_px,
                CASE
                    WHEN (elem.value ? 'DrawingPriority')
                        THEN (NULLIF(split_part((elem.value ->> 'DrawingPriority'), ',', 1), ''))::integer
                    ELSE NULL
                END AS drawing_priority,
                CASE
                    WHEN (elem.value ? 'ViewingGroup')
                        THEN (NULLIF(split_part((elem.value ->> 'ViewingGroup'), ',', 1), ''))::integer
                    ELSE NULL
                END AS viewing_group
            FROM jsonb_array_elements(COALESCE(p.di_jsonb, '[]'::jsonb)) elem(value)
            LIMIT 1
        ) di ON true
        """
    )

    cursor.execute(
        f"""
        CREATE OR REPLACE VIEW {schema}.enc_sounding_mvt AS
        SELECT
            s.id,
            s.feature_code,
            s.di_jsonb,
            COALESCE(s.drawing_priority, 0) AS "DrawingPriority",
            ST_SetSRID(ST_FlipCoordinates(s.geom), 4326) AS geom
        FROM {schema}.enc_sounding s
        """
    )

    conn.commit()


def _warn_unmapped(cell_name: str, fid: str, s57_code: str, unmapped: Set[str]) -> None:
    if not unmapped:
        return
    keys = ", ".join(sorted(unmapped))
    print(
        f"[WARN] dropped unmapped attributes for {cell_name}:{fid} ({s57_code}): {keys}",
        file=sys.stderr,
    )


def collect_enc_files(paths: Iterable[str]) -> List[Path]:
    files: List[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(p.rglob("*.000")))
        elif p.suffix.lower() == ".000":
            files.append(p)
    return files


def geometry_primitive(geom: ogr.Geometry) -> str:
    gtype = ogr.GT_Flatten(geom.GetGeometryType())
    if gtype in SURFACE_TYPES:
        return "Surface"
    if gtype in CURVE_TYPES:
        return "Curve"
    return "Point"


def normalize_geometry(geom: ogr.Geometry, target: str, wgs84: osr.SpatialReference) -> tuple[bytes | None, str]:
    """Transform geometry to WGS84 and coerce to expected primitive; downgrade if needed."""

    if geom is None:
        return None, target

    geometry = geom.Clone()
    if geometry.GetSpatialReference():
        geometry.TransformTo(wgs84)
    else:
        geometry.AssignSpatialReference(wgs84)

    primitive = target
    gtype = ogr.GT_Flatten(geometry.GetGeometryType())

    if target == "Surface":
        if gtype not in SURFACE_TYPES:
            geometry = ogr.ForceToMultiPolygon(geometry)
        gtype = ogr.GT_Flatten(geometry.GetGeometryType())
        if gtype not in SURFACE_TYPES:
            geometry = ogr.ForceToMultiLineString(geometry)
            primitive = "Curve"
            gtype = ogr.GT_Flatten(geometry.GetGeometryType())

    if primitive == "Curve":
        if gtype not in CURVE_TYPES:
            geometry = ogr.ForceToMultiLineString(geometry)
            gtype = ogr.GT_Flatten(geometry.GetGeometryType())
        if gtype not in CURVE_TYPES:
            primitive = "Point"

    if primitive == "Point":
        if gtype in {ogr.wkbMultiPoint, ogr.wkbMultiPoint25D}:
            geometry = geometry.GetGeometryRef(0).Clone()
        elif geometry.GetPointCount() > 0:
            x, y, z = geometry.GetPoint(0)
            point = ogr.Geometry(ogr.wkbPoint25D if geometry.Is3D() else ogr.wkbPoint)
            point.AddPoint(x, y, z)
            geometry = point
        gtype = ogr.GT_Flatten(geometry.GetGeometryType())

    # Normalize single to multi forms
    gtype = ogr.GT_Flatten(geometry.GetGeometryType())
    if primitive == "Surface" and gtype == ogr.wkbPolygon:
        geometry = ogr.ForceToMultiPolygon(geometry)
    if primitive == "Curve" and gtype == ogr.wkbLineString:
        geometry = ogr.ForceToMultiLineString(geometry)

    # Drop Z to match 2D PostGIS column definitions
    geometry.SetCoordinateDimension(2)

    return bytes(geometry.ExportToWkb()), primitive


def depth_from_geometry(geom: ogr.Geometry) -> float | None:
    """Extract a representative depth value from geometry Z when present."""

    try:
        if not geom or not geom.Is3D():
            return None
        gtype = ogr.GT_Flatten(geom.GetGeometryType())
        if gtype in {ogr.wkbPoint, ogr.wkbPoint25D, ogr.wkbLineString, ogr.wkbLineString25D}:
            _, _, z = geom.GetPoint(0)
            return float(z) if z is not None else None
        if gtype in {ogr.wkbMultiPoint, ogr.wkbMultiPoint25D, ogr.wkbMultiLineString, ogr.wkbMultiLineString25D}:
            part = geom.GetGeometryRef(0)
            if part and part.Is3D():
                _, _, z = part.GetPoint(0)
                return float(z) if z is not None else None
    except Exception:
        return None
    return None


def feature_id(cell_name: str, s57_code: str, feat: ogr.Feature) -> str:
    lnam_idx = feat.GetFieldIndex("LNAM")
    lnam = feat.GetField(lnam_idx) if lnam_idx != -1 else None

    rcid_idx = feat.GetFieldIndex("RCID")
    rcid = feat.GetField(rcid_idx) if rcid_idx != -1 else None

    if lnam:
        return str(lnam)
    if rcid is not None:
        return f"{cell_name}:{s57_code}:{rcid}"
    return f"{cell_name}:{s57_code}:{feat.GetFID()}"


def ogr_feature_attributes(feat: ogr.Feature) -> Dict[str, Any]:
    attrs: Dict[str, Any] = {}
    for key, value in feat.items().items():
        if key.lower() == "geom":
            continue
        attrs[key] = value
    return attrs


def load_features(
    enc_file: Path,
    wgs84: osr.SpatialReference,
    limit: int | None,
    only_features: Set[str] | None,
    debug: bool,
) -> Tuple[List[FeatureRecord], Dict[str, PendingRow]]:
    gdal.UseExceptions()
    gdal.SetConfigOption("OGR_S57_OPTIONS", S57_OPTIONS)
    datasource = ogr.Open(enc_file.as_posix())
    if datasource is None:
        print(f"[WARN] Unable to open {enc_file}", file=sys.stderr)
        return [], {}

    features: List[FeatureRecord] = []
    pending: Dict[str, PendingRow] = {}
    cell_name = enc_file.stem
    count = 0

    for layer_index in range(datasource.GetLayerCount()):
        layer = datasource.GetLayerByIndex(layer_index)
        s57_code = layer.GetName().upper()

        if s57_code in SKIP_LAYERS:
            continue

        if only_features and s57_code not in only_features:
            continue

        layer.ResetReading()
        for feat in layer:
            geom = feat.GetGeometryRef()
            if geom is None:
                continue

            depth_z = depth_from_geometry(geom)

            primitive_guess = geometry_primitive(geom)
            s101_code, primitive = map_feature(s57_code, primitive_guess)
            geom_wkb, primitive = normalize_geometry(geom, primitive, wgs84)
            if not geom_wkb:
                continue

            raw_attrs_debug = ogr_feature_attributes(feat)
            mapped_attrs, stored_attrs, unmapped, associations = prepare_attributes(
                s57_code,
                s101_code,
                dict(raw_attrs_debug),
                depth_z,
            )

            fid = feature_id(cell_name, s57_code, feat)
            feature = FeatureRecord(
                feature_id=fid,
                code=s101_code,
                primitive=primitive,
                attributes=mapped_attrs,
                spatial_id=None,
            )

            table = pick_table(s57_code, primitive)
            pending[fid] = PendingRow(
                feature=feature,
                table=table,
                cell_name=cell_name,
                s57_code=s57_code,
                feature_code=s101_code,
                foid=fid,
                geom_wkb=geom_wkb,
                attr_json=stored_attrs,
            )
            features.append(feature)
            count += 1

            if debug:
                print(
                    json.dumps(
                        {
                            "cell": cell_name,
                            "fid": fid,
                            "s57": s57_code,
                            "s101": s101_code,
                            "primitive": primitive,
                            "raw_attributes": raw_attrs_debug,
                            "mapped_attributes": mapped_attrs,
                            "associations": associations,
                            "unmapped_dropped": sorted(unmapped),
                        },
                        ensure_ascii=True,
                    )
                )

            _warn_unmapped(cell_name, fid, s57_code, unmapped)

            if limit and count >= limit:
                return features, pending

    return features, pending


def insert_rows(conn, schema: str, rows: Dict[str, PendingRow], di_json: Dict[str, List[Dict[str, Any]]], apply: bool) -> None:
    if not rows:
        return

    def _sanitize(value: Any) -> Any:
        """Recursively replace NaN/Infinity with None for JSON compatibility."""

        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, list):
            return [_sanitize(v) for v in value]
        if isinstance(value, tuple):
            return tuple(_sanitize(v) for v in value)
        if isinstance(value, dict):
            return {k: _sanitize(v) for k, v in value.items()}
        return value

    grouped = group_rows_by_table(rows, di_json)
    tables: Dict[str, List[Tuple[Any, ...]]] = {}
    for table_name, payloads in grouped.items():
        if table_name == "enc_area":
            tables[table_name] = [
                (
                    s57_code,
                    feature_code,
                    cell_name,
                    foid,
                    geom_wkb,
                    psycopg2.extras.Json(_sanitize(attr_json)) if attr_json else None,
                    psycopg2.extras.Json(_sanitize(di_payload)) if di_payload is not None else None,
                    color_fill,
                    drawing_priority,
                    line_width_px,
                )
                for (
                    s57_code,
                    feature_code,
                    cell_name,
                    foid,
                    geom_wkb,
                    attr_json,
                    di_payload,
                    color_fill,
                    drawing_priority,
                    line_width_px,
                ) in payloads
            ]
        else:
            tables[table_name] = [
                (
                    s57_code,
                    feature_code,
                    cell_name,
                    foid,
                    geom_wkb,
                    psycopg2.extras.Json(_sanitize(attr_json)) if attr_json else None,
                    psycopg2.extras.Json(_sanitize(di_payload)) if di_payload is not None else None,
                    drawing_priority,
                    line_width_px,
                )
                for (
                    s57_code,
                    feature_code,
                    cell_name,
                    foid,
                    geom_wkb,
                    attr_json,
                    di_payload,
                    _color_fill,
                    drawing_priority,
                    line_width_px,
                ) in payloads
            ]

    if not apply:
        for table_name, payloads in tables.items():
            if not payloads:
                continue
            print(f"[dry-run] would insert {len(payloads)} rows into {schema}.{table_name}")
        return

    cursor = conn.cursor()
    for table_name, payloads in tables.items():
        if not payloads:
            continue
        if table_name == "enc_area":
            sql = (
                f"INSERT INTO {schema}.{table_name} "
                "(s57_code, feature_code, cell_name, foid, geom, attr_jsonb, di_jsonb, color_fill, drawing_priority, line_width_px) "
                "VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromWKB(%s), 4326), %s, %s, %s, %s, %s)"
            )
        else:
            sql = (
                f"INSERT INTO {schema}.{table_name} "
                "(s57_code, feature_code, cell_name, foid, geom, attr_jsonb, di_jsonb, drawing_priority, line_width_px) "
                "VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromWKB(%s), 4326), %s, %s, %s, %s)"
            )
        psycopg2.extras.execute_batch(cursor, sql, payloads, page_size=500)
        print(f"[apply] inserted {len(payloads)} rows into {schema}.{table_name}")

    conn.commit()


def main() -> int:
    args = parse_args()
    dsn = args.dsn or default_dsn()

    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)

    only_features = {args.only_feature.upper()} if args.only_feature else None

    enc_files = collect_enc_files(args.enc_paths)
    if not enc_files:
        print("No ENC .000 files found", file=sys.stderr)
        return 1

    conn = psycopg2.connect(dsn)
    ensure_schema(conn, args.schema)
    ensure_tables(conn, args.schema)
    ensure_mvt_views(conn, args.schema)

    host = None if args.skip_portrayal else PortrayalHost()

    for enc_file in enc_files:
        print(f"[INFO] processing {enc_file}")
        features, pending = load_features(
            enc_file,
            wgs84,
            args.limit,
            only_features,
            args.debug,
        )
        if not features:
            print(f"[INFO] no features found in {enc_file}")
            continue

        if host:
            result = host.portray_with_json(features, sinks=None)
            di_json = result.parsed_json or {}
        else:
            di_json = {}

        insert_rows(
            conn=conn,
            schema=args.schema,
            rows=pending,
            di_json=di_json,
            apply=args.apply,
        )

        if args.limit and len(features) >= args.limit:
            break

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
