"""SQLite repository for normalized events and source cursors."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from unifi_mcp.events.models import NormalizedEvent, StoredEvent
from unifi_mcp.runtime.store import RuntimeStore


@dataclass(frozen=True)
class IngestResult:
    """Counts from one atomic source page ingestion."""

    inserted: int
    duplicates: int


class EventRepository:
    """Persist normalized events and source progress."""

    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    async def insert_batch(
        self,
        events: list[NormalizedEvent],
        *,
        source: str,
        device_name: str = "",
        site: str = "",
        cursor: dict[str, object],
    ) -> IngestResult:
        now = datetime.now(UTC).isoformat()
        inserted = 0
        async with self._store.transaction() as connection:
            destination_result = await connection.execute(
                """
                SELECT id, categories_json FROM webhook_destinations
                WHERE enabled = 1
                """
            )
            destinations = await destination_result.fetchall()
            for event in events:
                event_id = str(uuid4())
                result = await connection.execute(
                    """
                    INSERT OR IGNORE INTO events (
                        id, source, source_key, device_name, site, category, severity,
                        occurred_at, observed_at, summary, subject_type, subject_id,
                        details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        event.source,
                        event.source_key,
                        event.device_name,
                        event.site,
                        event.category,
                        event.severity,
                        event.occurred_at.isoformat(),
                        event.observed_at.isoformat(),
                        event.summary,
                        event.subject_type,
                        event.subject_id,
                        json.dumps(event.details, sort_keys=True, separators=(",", ":")),
                        now,
                    ),
                )
                inserted += result.rowcount
                if result.rowcount:
                    for destination_id, categories_json in destinations:
                        categories = json.loads(categories_json)
                        if categories and event.category not in categories:
                            continue
                        await connection.execute(
                            """
                            INSERT INTO webhook_deliveries (
                                id, event_id, destination_id, status, attempt_count,
                                next_attempt_at, created_at, updated_at
                            ) VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)
                            """,
                            (str(uuid4()), event_id, destination_id, now, now, now),
                        )

            await connection.execute(
                """
                INSERT INTO event_cursors (
                    source, device_name, site, cursor_json, watermark_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (source, device_name, site) DO UPDATE SET
                    cursor_json = excluded.cursor_json,
                    watermark_at = excluded.watermark_at,
                    updated_at = excluded.updated_at
                """,
                (
                    source,
                    device_name,
                    site,
                    json.dumps(cursor, sort_keys=True, separators=(",", ":")),
                    now,
                    now,
                ),
            )

        return IngestResult(inserted=inserted, duplicates=len(events) - inserted)

    async def get_cursor(
        self, source: str, device_name: str = "", site: str = ""
    ) -> dict[str, object] | None:
        async with self._store.transaction() as connection:
            result = await connection.execute(
                """
                SELECT cursor_json FROM event_cursors
                WHERE source = ? AND device_name = ? AND site = ?
                """,
                (source, device_name, site),
            )
            row = await result.fetchone()
        return json.loads(row[0]) if row else None

    async def list_events(self, *, limit: int = 100) -> list[StoredEvent]:
        bounded_limit = max(1, min(limit, 1000))
        async with self._store.transaction() as connection:
            result = await connection.execute(
                """
                SELECT id, source, source_key, device_name, site, category, severity,
                       occurred_at, observed_at, summary, subject_type, subject_id,
                       details_json, created_at
                FROM events
                ORDER BY occurred_at DESC, id DESC
                LIMIT ?
                """,
                (bounded_limit,),
            )
            rows = await result.fetchall()

        return [
            StoredEvent(
                id=row[0],
                source=row[1],
                source_key=row[2],
                device_name=row[3],
                site=row[4],
                category=row[5],
                severity=row[6],
                occurred_at=row[7],
                observed_at=row[8],
                summary=row[9],
                subject_type=row[10],
                subject_id=row[11],
                details=json.loads(row[12]),
                created_at=row[13],
            )
            for row in rows
        ]
