from __future__ import annotations

"""PostGIS-oriented sources and sinks for the portrayal host."""

from typing import Any, Callable, Dict, Hashable, Iterable, Mapping, Sequence

import psycopg2.extras

from .host import DrawingSink, FeatureRecord, FeatureSource


class PostgisFeatureSource(FeatureSource):
    """Generic PostGIS-backed feature source.

    Callers provide a SQL statement and a ``row_mapper`` that converts each row
    into a ``FeatureRecord`` (or ``None`` to skip the row). If ``id_getter`` is
    provided, the mapping from ``feature_id`` to a database key is captured in
    ``id_map`` for downstream sinks.
    """

    def __init__(
        self,
        conn: psycopg2.extensions.connection,
        sql: str,
        *,
        params: Sequence[Any] | None = None,
        row_mapper: Callable[[Mapping[str, Any]], FeatureRecord | None],
        id_getter: Callable[[Mapping[str, Any]], Hashable] | None = None,
    ) -> None:
        self.conn = conn
        self.sql = sql
        self.params = tuple(params) if params is not None else tuple()
        self.row_mapper = row_mapper
        self.id_getter = id_getter

        self._rows: list[Mapping[str, Any]] | None = None
        self._features: list[FeatureRecord] | None = None
        self.id_map: Dict[str, Hashable] = {}

    @property
    def rows(self) -> list[Mapping[str, Any]]:
        self._load()
        assert self._rows is not None
        return self._rows

    @property
    def features(self) -> list[FeatureRecord]:
        self._load()
        assert self._features is not None
        return self._features

    def __iter__(self) -> Iterable[FeatureRecord]:
        yield from self.features

    def __len__(self) -> int:
        return len(self.features)

    def _load(self) -> None:
        if self._features is not None:
            return

        cursor = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute(self.sql, self.params)

        self._rows = list(cursor.fetchall())
        self._features = []
        self.id_map = {}

        for row in self._rows:
            feature = self.row_mapper(row)
            if feature is None:
                continue

            self._features.append(feature)
            if self.id_getter:
                self.id_map[feature.feature_id] = self.id_getter(row)


class PostgisDrawingSink(DrawingSink):
    """Write drawing instructions back into PostGIS via simple UPDATEs."""

    def __init__(
        self,
        conn: psycopg2.extensions.connection,
        *,
        table: str,
        id_column: str,
        json_column: str | None = None,
        feature_id_to_key: Callable[[str], Any] | Mapping[str, Any] | None = None,
        apply: bool = False,
        jsonb: bool = False,
    ) -> None:
        self.conn = conn
        self.table = table
        self.id_column = id_column
        self.json_column = json_column
        self.feature_id_to_key = feature_id_to_key
        self.apply = apply
        self.written = 0
        self.jsonb = jsonb

    def write(
        self, feature_id: str, raw_instructions: list[str], instructions: list[Dict[str, Any]]
    ) -> None:
        key = self._resolve_key(feature_id)
        if key is None:
            print(f"[PostGIS sink] skipping {feature_id}: no key")
            return

        json_payload = None
        if self.json_column:
            json_payload = psycopg2.extras.Json(instructions)

        if not self.apply:
            print(
                f"[PostGIS sink dry-run] {self.table}.{self.id_column}={key} di_json={bool(self.json_column)}"
            )
            return

        cursor = self.conn.cursor()
        if self.json_column:
            clause = f"{self.json_column} = %s"
            if self.jsonb:
                clause = clause + "::jsonb"
            sql = f"UPDATE {self.table} SET {clause} WHERE {self.id_column} = %s"
            params = [json_payload, key]
        else:
            sql = f"UPDATE {self.table} SET {self.id_column} = {self.id_column} WHERE {self.id_column} = %s"
            params = [key]
        cursor.execute(sql, params)
        self.conn.commit()
        self.written += 1

    def _resolve_key(self, feature_id: str) -> Any:
        if callable(self.feature_id_to_key):
            return self.feature_id_to_key(feature_id)
        if isinstance(self.feature_id_to_key, Mapping):
            return self.feature_id_to_key.get(feature_id)
        return feature_id
