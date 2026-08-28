"""Migration coverage for durable events and automation state."""

import sqlite3

from unifi_mcp.runtime import SCHEMA_VERSION, RuntimeStore


async def test_v1_database_upgrades_to_v2_without_losing_metadata(tmp_path):
    database_path = tmp_path / "runtime.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)",
            ("2026-08-27T00:00:00+00:00",),
        )
        connection.execute(
            "INSERT INTO runtime_metadata (key, value, updated_at) VALUES (?, ?, ?)",
            ("release", "phase-1", "2026-08-27T00:00:00+00:00"),
        )

    store = RuntimeStore(database_path)
    try:
        await store.open()
        health = await store.health()
    finally:
        await store.close()

    with sqlite3.connect(database_path) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
        metadata = connection.execute(
            "SELECT value FROM runtime_metadata WHERE key = 'release'"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

    assert SCHEMA_VERSION == 2
    assert health["schema_version"] == 2
    assert versions == [1, 2]
    assert metadata == ("phase-1",)
    assert {
        "events",
        "event_cursors",
        "schedules",
        "job_runs",
        "webhook_destinations",
        "webhook_deliveries",
    } <= tables
