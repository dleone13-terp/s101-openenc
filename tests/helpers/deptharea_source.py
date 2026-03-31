from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, List, Optional

from portrayal_engine.host import FeatureRecord, FeatureSource


@dataclass
class DepthAreaItem:
    ogc_fid: int
    feature: FeatureRecord
    geom_geojson: str
    drval1: float | None
    drval2: float | None
    cell_file: str


def load_deptharea_items(
    conn,
    *,
    limit: Optional[int] = None,
    cell_name: Optional[str] = None,
) -> List[DepthAreaItem]:
    """Pull DepthArea features from a PostGIS-like connection into host-friendly objects."""

    cursor = conn.cursor(cursor_factory=None)

    sql = "SELECT ogc_fid, ST_AsGeoJSON(geom) AS geom_json, drval1, drval2 FROM raw_s57.depare"
    params: tuple = ()
    if limit is not None:
        sql += " LIMIT %s"
        params = (limit,)

    cursor.execute(sql, params if params else None)

    items: List[DepthAreaItem] = []
    for row in cursor.fetchall():
        geom_json = row["geom_json"]
        if not geom_json:
            continue

        geo = json.loads(geom_json)
        geom_type = geo.get("type", "").lower()
        if geom_type not in {"polygon", "multipolygon"}:
            # DepthArea must be a surface; skip if not.
            continue

        foid_prefix = cell_name if cell_name else "DEPARE"
        foid = f"{foid_prefix}:{row['ogc_fid']}"

        drval1 = row.get("drval1")
        drval2 = row.get("drval2")

        feature = FeatureRecord(
            feature_id=foid,
            code="DepthArea",
            primitive="Surface",
            attributes={
                "depthRangeMinimumValue": float(drval1) if drval1 is not None else None,
                "depthRangeMaximumValue": float(drval2) if drval2 is not None else None,
            },
            spatial_id=foid,
        )

        items.append(
            DepthAreaItem(
                ogc_fid=int(row["ogc_fid"]),
                feature=feature,
                geom_geojson=geom_json,
                drval1=float(drval1) if drval1 is not None else None,
                drval2=float(drval2) if drval2 is not None else None,
                cell_file=cell_name or "unknown",
            )
        )

    return items


class DepthAreaSource(FeatureSource):
    """Feature source that yields DepthArea features from PostGIS (test helper)."""

    def __init__(
        self,
        conn,
        *,
        limit: Optional[int] = None,
        cell_name: Optional[str] = None,
    ) -> None:
        self.conn = conn
        self.limit = limit
        self.cell_name = cell_name
        self._items: List[DepthAreaItem] | None = None

    @property
    def items(self) -> List[DepthAreaItem]:
        if self._items is None:
            self._items = load_deptharea_items(
                self.conn, limit=self.limit, cell_name=self.cell_name
            )
        return self._items

    def __iter__(self) -> Iterable[FeatureRecord]:
        for item in self.items:
            yield item.feature
