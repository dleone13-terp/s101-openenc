import json

from portrayal_engine.host import CollectingSink, PortrayalHost
from tests.helpers.deptharea_source import DepthAreaSource


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self, cursor_factory=None):  # cursor_factory ignored for test
        return FakeCursor(self.rows)


def _polygon_geojson():
    # Simple square polygon around a portion of US3WA01M for test purposes.
    coords = [
        [
            [-122.8, 48.6],
            [-122.6, 48.6],
            [-122.6, 48.7],
            [-122.8, 48.7],
            [-122.8, 48.6],
        ]
    ]
    return json.dumps({"type": "Polygon", "coordinates": coords})


def test_deptharea_portrayal_from_us3wa01m():
    rows = [
        {
            "ogc_fid": 1,
            "geom_json": _polygon_geojson(),
            "drval1": 2.0,
            "drval2": 15.0,
        }
    ]

    conn = FakeConnection(rows)
    source = DepthAreaSource(conn, cell_name="US3WA01M")

    host = PortrayalHost()
    sink = CollectingSink()

    result = host.portray_with_json(source, sinks=[sink])

    feature_id = "US3WA01M:1"
    assert feature_id in result.raw
    assert result.raw[feature_id]  # raw DEF exists

    parsed = sink.data.get(feature_id)
    assert parsed is not None and len(parsed) > 0

    parsed_json = result.parsed_json.get(feature_id)
    assert parsed_json is not None and len(parsed_json) > 0
    assert "DrawingPriority" in parsed_json[0]
    assert parsed_json[0]["DrawingPriority"] is not None

    # Ensure core DI fields are present and parsed
    first = parsed[0]
    assert "ViewingGroup" in first
    assert "DrawingPriority" in first
