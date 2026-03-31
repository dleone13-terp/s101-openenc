#!/usr/bin/env python3
"""Run S-101 portrayal for DepthArea and store DEF strings in PostGIS."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

import psycopg2

# Ensure repository root is on sys.path when executed directly.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portrayal_engine.host import FeatureRecord, PortrayalHost
from portrayal_engine.postgis_io import PostgisDrawingSink, PostgisFeatureSource
from portrayal_engine.stdout_sink import StdoutSink


def default_db_url() -> str:
    env = os.environ
    host = env.get("POSTGRES_HOSTNAME", "localhost")
    port = env.get("POSTGRES_PORT", "5432")
    user = env.get("POSTGRES_USER", "postgres")
    password = env.get("POSTGRES_PASSWORD", "postgres")
    dbname = env.get("POSTGRES_DB", "postgres")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def ensure_di_def_column(conn: psycopg2.extensions.connection) -> None:
    cur = conn.cursor()
    cur.execute("ALTER TABLE raw_s57.depare ADD COLUMN IF NOT EXISTS di_def TEXT;")
    conn.commit()


def build_deptharea_source(
    conn: psycopg2.extensions.connection,
    *,
    limit: Optional[int],
    cell_name: Optional[str],
) -> PostgisFeatureSource:
    sql = "SELECT ogc_fid, ST_AsGeoJSON(geom) AS geom_json, drval1, drval2 FROM raw_s57.depare"
    params: tuple = ()
    if limit is not None:
        sql += " LIMIT %s"
        params = (limit,)

    def _row_mapper(row) -> FeatureRecord | None:
        geom_json = row["geom_json"]
        if not geom_json:
            return None

        geo = json.loads(geom_json)
        geom_type = geo.get("type", "").lower()
        if geom_type not in {"polygon", "multipolygon"}:
            return None

        prefix = cell_name if cell_name else "DEPARE"
        foid = f"{prefix}:{row['ogc_fid']}"

        drval1 = row.get("drval1")
        drval2 = row.get("drval2")

        return FeatureRecord(
            feature_id=foid,
            code="DepthArea",
            primitive="Surface",
            attributes={
                "depthRangeMinimumValue": float(drval1) if drval1 is not None else None,
                "depthRangeMaximumValue": float(drval2) if drval2 is not None else None,
            },
            spatial_id=foid,
        )

    def _id_getter(row):
        return int(row["ogc_fid"])

    return PostgisFeatureSource(
        conn,
        sql,
        params=params,
        row_mapper=_row_mapper,
        id_getter=_id_getter,
    )


def _serialize_parsed(parsed_map: dict[str, list]) -> dict[str, list]:
    return {
        feature_id: [di.to_json(compact=True) for di in instructions]
        for feature_id, instructions in parsed_map.items()
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=default_db_url(), help="PostgreSQL connection URL")
    parser.add_argument("--cell", default=None, help="Optional cell name to prefix FOIDs and store in cell_file")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of DepthArea features for a quick test")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write di_def into raw_s57.depare (default is dry-run)",
    )
    parser.add_argument(
        "--stdout-sink",
        action="store_true",
        help="Stream drawing instructions to stdout in addition to database writes",
    )
    parser.add_argument(
        "--stdout-file",
        default=None,
        help="If set, write stdout sink output to this file instead of console",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional path to write parsed drawing instructions as JSON ('-' for stdout)",
    )

    args = parser.parse_args(argv)

    conn = psycopg2.connect(args.db_url)

    print("Loading DepthArea features from raw_s57...")
    source = build_deptharea_source(conn, limit=args.limit, cell_name=args.cell)
    feature_count = len(source)
    print(f"Loaded {feature_count} features")

    if feature_count == 0:
        print("No features found; nothing to do")
        return 0

    print("Ensuring di_def column exists on raw_s57.depare...")
    ensure_di_def_column(conn)

    host = PortrayalHost()

    sinks = []
    stdout_stream = None
    if args.stdout_sink:
        if args.stdout_file:
            stdout_stream = open(args.stdout_file, "w", encoding="utf-8")
        sinks.append(StdoutSink(show_raw=True, show_parsed=True, stream=stdout_stream))

    sinks.append(
        PostgisDrawingSink(
            conn,
            table="raw_s57.depare",
            id_column="ogc_fid",
            di_column="di_def",
            json_column="di_jsonb",
            jsonb=True,
            feature_id_to_key=source.id_map,
            apply=args.apply,
        )
    )

    result = host.portray_with_json(source, sinks=sinks)
    di_map = result.raw
    parsed_map = result.parsed

    # Show a few DI samples for verification
    sample = list(di_map.items())[:5]
    if sample:
        print("Sample DEF output:")
        for feature_id, dis in sample:
            for di in dis:
                print(f"  {feature_id}: {di}")

    json_sample = next(iter(parsed_map.values()), [])
    if json_sample:
        print("Sample parsed JSON instruction:")
        print(json.dumps(json_sample[0].to_json(), indent=2))

    if args.json_out:
        payload = _serialize_parsed(parsed_map)
        if args.json_out == "-":
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            Path(args.json_out).write_text(json.dumps(payload, indent=2))
        print(f"Wrote parsed JSON to {args.json_out}")

    print("Finished portrayal. Database sink apply=%s" % args.apply)

    if stdout_stream:
        stdout_stream.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
