"""Tests for the optional SQLite runtime store."""

import asyncio
import sqlite3

import aiosqlite
import pytest

from unifi_mcp.exceptions import UniFiConfigError
from unifi_mcp.runtime import SCHEMA_VERSION, RuntimeStore


async def test_initialize_creates_runtime_schema(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")

    try:
        await store.open()
        health = await store.health()
    finally:
        await store.close()

    assert health == {
        "connected": True,
        "schema_version": SCHEMA_VERSION,
        "journal_mode": "wal",
    }


async def test_open_is_idempotent_and_close_marks_disconnected(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")

    try:
        await store.open()
        await store.open()
    finally:
        await store.close()

    assert store.connected is False


async def test_close_failure_keeps_connection_for_retry(tmp_path, monkeypatch):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    connection = store._connection
    assert connection is not None
    original_close = connection.close

    async def fail_close_once():
        raise RuntimeError("close failed")

    monkeypatch.setattr(connection, "close", fail_close_once)
    retry_closed = False

    try:
        with pytest.raises(RuntimeError, match="close failed"):
            await store.close()

        assert store.connected is True

        monkeypatch.setattr(connection, "close", original_close)
        await store.close()
        retry_closed = True
        assert store.connected is False
    finally:
        monkeypatch.setattr(connection, "close", original_close)
        if store.connected:
            await store.close()
        elif not retry_closed:
            await original_close()


async def test_cancelled_close_keeps_connection_for_retry(tmp_path, monkeypatch):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    connection = store._connection
    assert connection is not None
    original_close = connection.close

    async def cancel_close_once():
        raise asyncio.CancelledError

    monkeypatch.setattr(connection, "close", cancel_close_once)
    retry_closed = False

    try:
        with pytest.raises(asyncio.CancelledError):
            await store.close()

        assert store.connected is True

        monkeypatch.setattr(connection, "close", original_close)
        await store.close()
        retry_closed = True
        assert store.connected is False
    finally:
        monkeypatch.setattr(connection, "close", original_close)
        if store.connected:
            await store.close()
        elif not retry_closed:
            await original_close()


async def test_open_creates_parent_directories(tmp_path):
    database_path = tmp_path / "nested" / "runtime" / "runtime.db"
    store = RuntimeStore(database_path)

    try:
        await store.open()
    finally:
        await store.close()

    assert database_path.parent.is_dir()


async def test_health_raises_config_error_after_close(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    await store.close()

    with pytest.raises(UniFiConfigError, match=r"closed.*open\(\)"):
        await store.health()


async def test_connected_remains_false_until_open_completes(tmp_path, monkeypatch):
    store = RuntimeStore(tmp_path / "runtime.db")
    initialization_started = asyncio.Event()
    allow_initialization = asyncio.Event()
    original_execute = aiosqlite.Connection.execute

    async def delayed_execute(connection, sql, parameters=None):
        if sql == "PRAGMA journal_mode=WAL":
            initialization_started.set()
            await allow_initialization.wait()
        return await original_execute(connection, sql, parameters)

    monkeypatch.setattr(aiosqlite.Connection, "execute", delayed_execute)
    open_task = asyncio.create_task(store.open())

    try:
        await initialization_started.wait()
        assert store.connected is False
        allow_initialization.set()
        await open_task
    finally:
        allow_initialization.set()
        await open_task
        await store.close()


async def test_open_rejects_database_from_newer_schema_version(tmp_path):
    database_path = tmp_path / "runtime.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION + 1, "2026-01-01T00:00:00+00:00"),
        )

    store = RuntimeStore(database_path)

    with pytest.raises(
        UniFiConfigError,
        match=rf"schema version {SCHEMA_VERSION + 1}.*supports version {SCHEMA_VERSION}",
    ):
        await store.open()

    assert store.connected is False
