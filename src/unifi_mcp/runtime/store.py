"""SQLite-backed runtime persistence lifecycle."""

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from unifi_mcp.exceptions import UniFiConfigError

SCHEMA_VERSION = 1


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
