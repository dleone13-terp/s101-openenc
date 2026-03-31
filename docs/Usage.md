# Usage

## Sprite Generation

```bash
python -m sprites.build_sprites
```

This will create all of the sprites in colored svg format in the sprites/out/{Theme}_src directory and the png sprite map with sprite json in the sprites/out/{Theme} directory. This includes both regular and @2x versions.

## Style Generation

```bash
python -m style.build_style
```

This will create the three styles in style/out/{Theme}.json

## Portrayal Host (S-101)

The host now works with simple sources and sinks and emits parsed drawing instructions as JSON.

```python
from portrayal_engine.host import FeatureRecord, PortrayalHost
from portrayal_engine.postgis_io import PostgisFeatureSource, StdoutSink


def row_to_feature(row):
	return FeatureRecord(
		feature_id=f"DEPARE:{row['ogc_fid']}",
		code="DepthArea",
		primitive="Surface",
		attributes={"depthRangeMinimumValue": row.get("drval1"), "depthRangeMaximumValue": row.get("drval2")},
		spatial_id=f"DEPARE:{row['ogc_fid']}",
	)


source = PostgisFeatureSource(
	conn,
	"SELECT ogc_fid, ST_AsGeoJSON(geom) AS geom_json, drval1, drval2 FROM raw_s57.depare LIMIT 10",
	row_mapper=row_to_feature,
)

host = PortrayalHost()
stdout_sink = StdoutSink(show_raw=False, show_parsed=True)
result = host.portray_with_json(source, sinks=[stdout_sink])

# raw DEF strings per feature
raw_map = result.raw

# parsed JSON-friendly instructions
parsed = result.parsed_json  # compact dicts without nulls
```

You can implement your own sources (iterables yielding FeatureRecord) and sinks (objects with `write(feature_id, raw, parsed)`), then pass them into `portray_with_json` to stream output anywhere (database, files, stdout, etc.). PostGIS helpers (`PostgisFeatureSource`, `PostgisDrawingSink`, `StdoutSink`) cover common ingest-time flows.
