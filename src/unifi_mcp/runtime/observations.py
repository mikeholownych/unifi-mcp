"""SQLite repository and explicit-gap trend queries for aggregate observations."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from unifi_mcp.observability.models import Observation, TrendBucket
from unifi_mcp.runtime.store import RuntimeStore

_METRICS_BY_KIND = {
    "site_health": {"subsystem_total", "healthy", "issues"},
    "device_counts": {"total", "online", "offline"},
    "client_counts": {"total", "wired", "wireless"},
    "traffic": {"rx_bytes", "tx_bytes"},
    "protect_health": {"total", "online", "offline"},
}


class ObservationRepository:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    async def insert_batch(self, observations: list[Observation]) -> int:
        created_at = datetime.now(UTC).isoformat()
        inserted = 0
        async with self._store.transaction() as connection:
            for observation in observations:
                result = await connection.execute(
                    """
                    INSERT OR IGNORE INTO observations (
                        id, source, controller, site, kind, status,
                        observed_at, metrics_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        observation.source,
                        observation.controller,
                        observation.site,
                        observation.kind,
                        observation.status,
                        observation.observed_at.isoformat(),
                        json.dumps(
                            observation.metrics.model_dump(mode="json"),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        created_at,
                    ),
                )
                inserted += result.rowcount
        return inserted

    async def query_trend(
        self,
        *,
        kind: str,
        metric: str,
        start: datetime,
        end: datetime,
        bucket_seconds: int,
        source: str | None = None,
        controller: str | None = None,
        site: str | None = None,
    ) -> list[TrendBucket]:
        if kind not in _METRICS_BY_KIND or metric not in _METRICS_BY_KIND[kind]:
            raise ValueError("metric is not valid for the requested observation kind")
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("trend start/end must be timezone-aware and increasing")
        if not 60 <= bucket_seconds <= 86_400:
            raise ValueError("bucket_seconds must be between 60 and 86400")
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        bucket_count = int((end - start).total_seconds() // bucket_seconds)
        if bucket_count < 1 or bucket_count > 1000:
            raise ValueError("trend query must contain between 1 and 1000 complete buckets")

        clauses = ["kind = ?", "observed_at >= ?", "observed_at < ?"]
        parameters: list[object] = [kind, start.isoformat(), end.isoformat()]
        for column, value in (("source", source), ("controller", controller), ("site", site)):
            if value is not None:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        async with self._store.transaction() as connection:
            result = await connection.execute(
                f"SELECT observed_at, metrics_json FROM observations WHERE {' AND '.join(clauses)} ORDER BY observed_at",  # noqa: S608
                parameters,
            )
            rows = await result.fetchall()

        values: dict[int, list[float]] = {}
        for observed_at, metrics_json in rows:
            timestamp = datetime.fromisoformat(observed_at).astimezone(UTC)
            index = int((timestamp - start).total_seconds() // bucket_seconds)
            if 0 <= index < bucket_count:
                value = json.loads(metrics_json).get(metric)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values.setdefault(index, []).append(float(value))

        buckets = []
        for index in range(bucket_count):
            bucket_start = start + timedelta(seconds=index * bucket_seconds)
            samples = values.get(index, [])
            buckets.append(
                TrendBucket(
                    start=bucket_start,
                    end=bucket_start + timedelta(seconds=bucket_seconds),
                    present=bool(samples),
                    value=sum(samples) / len(samples) if samples else None,
                    sample_count=len(samples),
                )
            )
        return buckets

    async def list_scopes(self) -> list[dict[str, str]]:
        async with self._store.transaction() as connection:
            result = await connection.execute(
                """
                SELECT DISTINCT source, controller, site, kind
                FROM observations ORDER BY source, controller, site, kind LIMIT 1000
                """
            )
            rows = await result.fetchall()
        return [
            {"source": row[0], "controller": row[1], "site": row[2], "kind": row[3]} for row in rows
        ]

    async def retention_status(self) -> dict[str, object]:
        async with self._store.transaction() as connection:
            result = await connection.execute(
                "SELECT COUNT(*), MIN(observed_at), MAX(observed_at) FROM observations"
            )
            row = await result.fetchone()
        return {"count": row[0], "oldest_at": row[1], "newest_at": row[2]}
