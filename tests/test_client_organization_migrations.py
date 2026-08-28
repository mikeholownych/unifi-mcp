"""Migration coverage for local client organization."""

import sqlite3

from unifi_mcp.runtime import SCHEMA_VERSION, RuntimeStore


async def test_v3_database_upgrades_to_v4_client_organization_schema(tmp_path):
    database_path = tmp_path / "runtime.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, '2026-08-28')",
            [(1,), (2,), (3,)],
        )

    store = RuntimeStore(database_path)
    try:
        await store.open()
        health = await store.health()
    finally:
        await store.close()

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

    assert SCHEMA_VERSION == 4
    assert health["schema_version"] == 4
    assert {
        "client_tags",
        "client_groups",
        "client_group_memberships",
        "client_qos_plans",
        "client_qos_targets",
    } <= tables
