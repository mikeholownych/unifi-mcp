"""SQLite-backed runtime persistence lifecycle."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from unifi_mcp.exceptions import UniFiConfigError

SCHEMA_VERSION = 4


async def _apply_v2(connection: aiosqlite.Connection) -> None:
    statements = (
        """
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_key TEXT NOT NULL,
            device_name TEXT NOT NULL DEFAULT '',
            site TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            summary TEXT NOT NULL,
            subject_type TEXT,
            subject_id TEXT,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE (source, device_name, site, source_key)
        )
        """,
        """
        CREATE TABLE event_cursors (
            source TEXT NOT NULL,
            device_name TEXT NOT NULL DEFAULT '',
            site TEXT NOT NULL DEFAULT '',
            cursor_json TEXT NOT NULL,
            watermark_at TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (source, device_name, site)
        )
        """,
        """
        CREATE TABLE schedules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            job_name TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL CHECK (interval_seconds >= 10),
            arguments_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            running INTEGER NOT NULL DEFAULT 0 CHECK (running IN (0, 1)),
            next_run_at TEXT NOT NULL,
            last_run_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE job_runs (
            id TEXT PRIMARY KEY,
            schedule_id TEXT REFERENCES schedules(id) ON DELETE SET NULL,
            job_name TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT,
            error_json TEXT,
            attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
            started_at TEXT NOT NULL,
            finished_at TEXT
        )
        """,
        """
        CREATE TABLE webhook_destinations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            url TEXT NOT NULL,
            secret_env_name TEXT,
            categories_json TEXT NOT NULL DEFAULT '[]',
            enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE webhook_deliveries (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            destination_id TEXT NOT NULL REFERENCES webhook_destinations(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            next_attempt_at TEXT NOT NULL,
            http_status INTEGER,
            error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (event_id, destination_id)
        )
        """,
        "CREATE INDEX events_occurred_at_idx ON events (occurred_at DESC)",
        "CREATE INDEX events_category_occurred_at_idx ON events (category, occurred_at DESC)",
        "CREATE INDEX schedules_due_idx ON schedules (enabled, running, next_run_at)",
        "CREATE INDEX job_runs_finished_at_idx ON job_runs (finished_at)",
        """
        CREATE INDEX webhook_deliveries_due_idx
        ON webhook_deliveries (status, next_attempt_at)
        """,
    )
    for statement in statements:
        await connection.execute(statement)


async def _apply_v3(connection: aiosqlite.Connection) -> None:
    statements = (
        """
        CREATE TABLE observations (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            controller TEXT NOT NULL DEFAULT '',
            site TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (source, controller, site, kind, observed_at)
        )
        """,
        """
        CREATE INDEX observations_scope_time_idx
        ON observations (kind, source, controller, site, observed_at DESC)
        """,
        "CREATE INDEX observations_retention_idx ON observations (observed_at)",
    )
    for statement in statements:
        await connection.execute(statement)


async def _apply_v4(connection: aiosqlite.Connection) -> None:
    statements = (
        """
        CREATE TABLE client_tags (
            controller TEXT NOT NULL,
            site TEXT NOT NULL DEFAULT '',
            client_key TEXT NOT NULL,
            tag TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (controller, site, client_key, tag)
        )
        """,
        """
        CREATE TABLE client_groups (
            id TEXT PRIMARY KEY,
            controller TEXT NOT NULL,
            site TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL COLLATE NOCASE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (controller, site, name),
            UNIQUE (controller, site, id)
        )
        """,
        """
        CREATE TABLE client_group_memberships (
            controller TEXT NOT NULL,
            site TEXT NOT NULL DEFAULT '',
            client_key TEXT NOT NULL,
            group_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (controller, site, client_key),
            FOREIGN KEY (controller, site, group_id)
                REFERENCES client_groups(controller, site, id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX client_tags_lookup_idx ON client_tags (controller, site, tag, client_key)",
        """
        CREATE INDEX client_group_memberships_lookup_idx
        ON client_group_memberships (controller, site, group_id, client_key)
        """,
        """
        CREATE TABLE client_qos_plans (
            token TEXT PRIMARY KEY,
            controller TEXT NOT NULL,
            site TEXT NOT NULL DEFAULT '',
            selector_type TEXT NOT NULL CHECK (selector_type IN ('client', 'tag', 'group')),
            selector_value TEXT NOT NULL,
            download_kbps INTEGER NOT NULL CHECK (download_kbps > 0),
            upload_kbps INTEGER NOT NULL CHECK (upload_kbps > 0),
            targets_hash TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('planned', 'applying', 'complete', 'partial')),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE client_qos_targets (
            plan_token TEXT NOT NULL REFERENCES client_qos_plans(token) ON DELETE CASCADE,
            client_key TEXT NOT NULL,
            position INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'applied', 'failed')),
            previous_json TEXT,
            applied_json TEXT,
            error_code TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (plan_token, client_key),
            UNIQUE (plan_token, position)
        )
        """,
        """
        CREATE INDEX client_qos_plans_scope_idx
        ON client_qos_plans (controller, site, created_at DESC)
        """,
    )
    for statement in statements:
        await connection.execute(statement)


async def _initialize_connection(connection: aiosqlite.Connection) -> None:
    await connection.execute("PRAGMA journal_mode=WAL")
    await connection.execute("PRAGMA foreign_keys=ON")
    await connection.execute("PRAGMA busy_timeout=5000")
    await _migrate(connection)


async def _migrate(connection: aiosqlite.Connection) -> None:
    await connection.execute("BEGIN IMMEDIATE")
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cursor = await connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
    row = await cursor.fetchone()
    current_version = int(row[0])

    if current_version > SCHEMA_VERSION:
        raise UniFiConfigError(
            f"Runtime database schema version {current_version} is newer than "
            f"this application supports version {SCHEMA_VERSION}; upgrade "
            "unifi-mcp before using this database"
        )

    if current_version < 1:
        await connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (1, datetime.now(timezone.utc).isoformat()),  # noqa: UP017
        )

    if current_version < 2:
        await _apply_v2(connection)
        await connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (2, datetime.now(timezone.utc).isoformat()),  # noqa: UP017
        )

    if current_version < 3:
        await _apply_v3(connection)
        await connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (3, datetime.now(timezone.utc).isoformat()),  # noqa: UP017
        )

    if current_version < 4:
        await _apply_v4(connection)
        await connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (4, datetime.now(timezone.utc).isoformat()),  # noqa: UP017
        )

    await connection.commit()


class RuntimeStore:
    """Own and initialize an optional SQLite runtime database."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Return whether the store currently owns an open connection."""
        return self._connection is not None

    async def open(self) -> None:
        """Open the database and apply supported schema migrations."""
        async with self._lock:
            if self._connection is not None:
                return

            connection: aiosqlite.Connection | None = None
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                connection = await aiosqlite.connect(self._path)
                await _initialize_connection(connection)
                self._connection = connection
            except BaseException:
                self._connection = None
                if connection is not None:
                    with suppress(Exception):
                        await connection.close()
                raise

    async def close(self) -> None:
        """Close the database connection if it is open."""
        async with self._lock:
            connection = self._connection
            if connection is None:
                return

            await connection.close()
            self._connection = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Yield the open connection inside a serialized write transaction."""
        async with self._lock:
            connection = self._connection
            if connection is None:
                raise UniFiConfigError("Runtime store is closed; call open() before transaction()")

            await connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                await connection.rollback()
                raise
            else:
                await connection.commit()

    async def health(self) -> dict[str, bool | int | str]:
        """Return database-derived health details for an open store.

        Raises:
            UniFiConfigError: If the store has not been opened or is already closed.
        """
        async with self._lock:
            connection = self._connection
            if connection is None:
                raise UniFiConfigError("Runtime store is closed; call open() before health()")

            cursor = await connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            )
            version_row = await cursor.fetchone()
            cursor = await connection.execute("PRAGMA journal_mode")
            journal_row = await cursor.fetchone()

            return {
                "connected": True,
                "schema_version": int(version_row[0]),
                "journal_mode": str(journal_row[0]).lower(),
            }
