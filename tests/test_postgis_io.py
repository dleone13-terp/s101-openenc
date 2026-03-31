from __future__ import annotations

import io
import json

from portrayal_engine.host import FeatureRecord
from portrayal_engine.postgis_io import PostgisDrawingSink, PostgisFeatureSource
from portrayal_engine.stdout_sink import StdoutSink


class FakeCursor:
    def __init__(self, rows, conn):
        self.rows = rows
        self.conn = conn

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.commits = 0

    def cursor(self, cursor_factory=None):  # cursor_factory ignored for fake
        return FakeCursor(self.rows, self)

    def commit(self):
        self.commits += 1


def test_postgis_feature_source_maps_rows_and_ids():
    rows = [
        {"ogc_fid": 101, "geom_json": "{}", "drval1": 1.0, "drval2": 5.0}
    ]

    def mapper(row):
        return FeatureRecord(
            feature_id=f"DEPARE:{row['ogc_fid']}",
            code="DepthArea",
            primitive="Surface",
            attributes={"depthRangeMinimumValue": row.get("drval1"), "depthRangeMaximumValue": row.get("drval2")},
        )

    conn = FakeConnection(rows)
    source = PostgisFeatureSource(conn, "SELECT *", row_mapper=mapper, id_getter=lambda r: r["ogc_fid"])

    features = list(source)

    assert len(features) == 1
    assert source.id_map["DEPARE:101"] == 101
    assert conn.executed[0][0].startswith("SELECT")


def test_postgis_drawing_sink_updates_when_apply():
    conn = FakeConnection([])
    sink = PostgisDrawingSink(
        conn,
        table="raw_s57.depare",
        id_column="ogc_fid",
        json_column="di_json",
        feature_id_to_key={"DEPARE:1": 1},
        apply=True,
        jsonb=True,
    )

    instr = {"ViewingGroup": 23}
    sink.write("DEPARE:1", ["ViewingGroup:23"], [instr])

    assert conn.executed
    sql, params = conn.executed[0]
    assert "UPDATE raw_s57.depare" in sql
    assert params[-1] == 1

    payload = params[0]
    if hasattr(payload, "adapted"):
        payload = payload.adapted
    assert payload[0]["ViewingGroup"] == 23
    assert conn.commits == 1


def test_stdout_sink_prints_raw_and_parsed():
    stream = io.StringIO()
    sink = StdoutSink(show_raw=True, show_parsed=True, stream=stream)

    instr = {"ViewingGroup": 7}
    sink.write("DEPARE:2", ["ViewingGroup:7"], [instr])

    output = stream.getvalue()
    assert "ViewingGroup:7" in output
    assert "DEPARE:2 (parsed)" in output
