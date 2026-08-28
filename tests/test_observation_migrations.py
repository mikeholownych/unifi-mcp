"""Migration coverage for aggregate observation history."""

import sqlite3

from unifi_mcp.runtime import SCHEMA_VERSION, RuntimeStore


async def test_v2_database_upgrades_to_latest_with_observation_schema(tmp_path):
    database_path = tmp_path / "runtime.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (1, '2026-08-27')"
        )
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (2, '2026-08-28')"
        )

    store = RuntimeStore(database_path)
    try:
        await store.open()
        health = await store.health()
    finally:
        await store.close()

    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(observations)")}
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]

    assert SCHEMA_VERSION == 4
    assert health["schema_version"] == 4
    assert versions == [1, 2, 3, 4]
    assert {"source", "controller", "site", "kind", "observed_at", "metrics_json"} <= columns
