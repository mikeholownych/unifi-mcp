"""Tests for system metadata helpers."""

import json
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

import unifi_mcp
from unifi_mcp.runtime import SCHEMA_VERSION, RuntimeStore
from unifi_mcp.server import mcp
from unifi_mcp.tools.system import (
    DisabledPersistenceHealth,
    EnabledPersistenceHealth,
    ServiceHealth,
    build_server_health,
)
from unifi_mcp.version import get_version


def test_get_version_returns_installed_distribution_version():
    with patch("unifi_mcp.version.version", return_value="9.8.7"):
        assert get_version() == "9.8.7"


def test_get_version_falls_back_when_distribution_is_not_installed():
    with patch("unifi_mcp.version.version", side_effect=PackageNotFoundError):
        assert get_version() == "0+unknown"


def test_version_consumers_use_package_version():
    assert unifi_mcp.__version__ == get_version()
    assert mcp.version == get_version()


async def test_server_health_is_redaction_safe_when_persistence_is_disabled(mock_ctx):
    mock_ctx.settings.username = "fixture-user"
    mock_ctx.settings.password = "fixture-password"
    mock_ctx.settings.runtime_database = Path("/var/lib/unifi/fixture-runtime.db")

    health = await build_server_health(mock_ctx)
    dumped = health.model_dump()

    assert dumped == {
        "status": "ok",
        "version": get_version(),
        "transport": "stdio",
        "configured_devices": 1,
        "services": {"network": 1, "protect": 0},
        "persistence": {"enabled": False, "connected": False},
    }
    rendered = f"{health!r}\n{json.dumps(dumped)}"
    for secret in (
        "test-key",
        "10.0.0.1",
        "test-gw",
        str(mock_ctx.settings.data_dir),
        str(mock_ctx.settings.runtime_database_path),
        "fixture-user",
        "fixture-password",
    ):
        assert secret not in rendered


async def test_server_health_reports_enabled_runtime_without_database_path(mock_ctx, tmp_path):
    database_path = tmp_path / "private" / "runtime.db"
    runtime = RuntimeStore(database_path)
    await runtime.open()
    mock_ctx.runtime = runtime

    try:
        health = await build_server_health(mock_ctx)
    finally:
        await runtime.close()

    assert health.model_dump()["persistence"] == {
        "enabled": True,
        "connected": True,
        "schema_version": SCHEMA_VERSION,
        "journal_mode": "wal",
    }
    assert str(database_path) not in repr(health)


async def test_server_health_ignores_unexpected_runtime_health_fields(mock_ctx):
    mock_ctx.runtime = AsyncMock()
    mock_ctx.runtime.health.return_value = {
        "connected": True,
        "schema_version": SCHEMA_VERSION,
        "journal_mode": "wal",
        "path": "/private/runtime.db",
        "password": "runtime-secret",
    }

    health = await build_server_health(mock_ctx)

    assert health.model_dump()["persistence"] == {
        "enabled": True,
        "connected": True,
        "schema_version": SCHEMA_VERSION,
        "journal_mode": "wal",
    }


async def test_server_health_propagates_runtime_health_failure(mock_ctx):
    mock_ctx.runtime = AsyncMock()
    mock_ctx.runtime.health.side_effect = RuntimeError("runtime health unavailable")

    with pytest.raises(RuntimeError, match="runtime health unavailable"):
        await build_server_health(mock_ctx)


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (ServiceHealth, {"network": "1", "protect": 0}),
        (DisabledPersistenceHealth, {"enabled": 0, "connected": False}),
        (DisabledPersistenceHealth, {"enabled": False, "connected": 0}),
        (
            EnabledPersistenceHealth,
            {"enabled": 1, "connected": True, "schema_version": 1, "journal_mode": "wal"},
        ),
        (
            EnabledPersistenceHealth,
            {"enabled": True, "connected": 1, "schema_version": 1, "journal_mode": "wal"},
        ),
    ],
)
def test_health_models_reject_coerced_counts_and_booleans(model, values):
    with pytest.raises(ValidationError):
        model(**values)
