"""Tests for MCP server tool registration and lifespan."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from mcp import Client

from unifi_mcp.auth.local import UniFiLocalAuth
from unifi_mcp.clients.base import create_app_lifespan
from unifi_mcp.config import UniFiSettings
from unifi_mcp.runtime import RuntimeStore
from unifi_mcp.server import mcp


async def list_protocol_tools():
    settings = UniFiSettings(
        _env_file=None,
        mode="local_api_key",
        devices_json=(
            '[{"name":"test-gw","url":"https://10.0.0.1",'
            '"api_key":"test-key","services":["network"]}]'
        ),
        controller_url=None,
        cloud_api_key=None,
        runtime_enabled=False,
    )
    with patch("unifi_mcp.clients.base.settings", settings):
        async with Client(mcp) as client:
            return (await client.list_tools()).tools


class TestToolRegistration:
    async def test_all_tools_registered(self):
        tools = await list_protocol_tools()
        assert len(tools) >= 48

    async def test_every_tool_has_description(self):
        tools = await list_protocol_tools()
        for tool in tools:
            assert tool.description, f"tool {tool.name} missing description"

    async def test_network_tools_support_device_targeting(self):
        tools = {t.name: t for t in await list_protocol_tools()}
        for name, tool in tools.items():
            if name in (
                "list_unifi_devices",
                "get_global_inventory",
                "get_global_health",
                "get_global_client_summary",
            ):
                continue
            if name.startswith(
                (
                    "list_devices",
                    "get_device",
                    "restart_device",
                    "locate_device",
                    "upgrade_device",
                    "provision_device",
                    "set_device_port",
                    "list_clients",
                    "list_all_clients",
                    "block_client",
                    "unblock_client",
                    "kick_client",
                    "forget_client",
                    "get_client",
                    "list_sites",
                    "get_site",
                    "get_sysinfo",
                    "get_networks",
                    "get_wlans",
                    "create_network",
                    "update_network",
                    "delete_network",
                    "get_port_profiles",
                    "get_firewall_rules",
                    "get_routing_table",
                    "get_network_health",
                    "get_recent_events",
                    "get_alarms",
                    "archive_all_alarms",
                    "run_speed_test",
                    "get_speed_test_status",
                    "get_dpi_stats",
                    "get_traffic",
                    "analyze_network_issues",
                    "get_optimization_recommendations",
                    "troubleshoot_client",
                )
            ):
                assert "device" in tool.input_schema["properties"], f"{name} missing device param"

    async def test_protect_tools_support_device_targeting(self):
        tools = {t.name: t for t in await list_protocol_tools()}
        protect_tools = [
            n
            for n in tools
            if n.startswith(
                (
                    "list_cameras",
                    "get_camera",
                    "get_protect",
                    "get_liveviews",
                    "get_motion",
                    "get_smart",
                    "get_recent_protect",
                )
            )
        ]
        assert len(protect_tools) >= 10
        for name in protect_tools:
            assert "device" in tools[name].input_schema["properties"], (
                f"{name} missing device param"
            )


class TestLifespanConfigValidation:
    async def test_lifespan_starts_without_configuration(self):
        empty = UniFiSettings(
            _env_file=None,
            mode="local_api_key",
            devices_json=None,
            controller_url=None,
            cloud_api_key=None,
            runtime_enabled=False,
        )
        with patch("unifi_mcp.clients.base.settings", empty):
            async with Client(mcp):
                # Server must start and expose tools even without a device
                # configured, so it can be deployed and configured via env vars.
                assert len(mcp._tool_manager.list_tools()) > 0

    def test_settings_load_from_env_file(self):
        # The project .env should produce at least one device
        settings = UniFiSettings()
        assert isinstance(settings.devices, list)


class TestRuntimeLifespan:
    @pytest.fixture(autouse=True)
    def isolate_runtime_environment(self, monkeypatch):
        for name in (
            "UNIFI_MODE",
            "UNIFI_DEVICES",
            "UNIFI_CONTROLLER_URL",
            "UNIFI_CLOUD_API_KEY",
            "UNIFI_USERNAME",
            "UNIFI_PASSWORD",
            "UNIFI_RUNTIME_ENABLED",
            "UNIFI_DATA_DIR",
            "UNIFI_RUNTIME_DATABASE",
        ):
            monkeypatch.delenv(name, raising=False)

    async def test_registered_lifespan_does_not_create_database_when_disabled(self, tmp_path):
        data_dir = tmp_path / "runtime-data"
        settings = UniFiSettings(
            _env_file=None,
            mode="local_api_key",
            devices_json=(
                '[{"name":"test-gw","url":"https://10.0.0.1",'
                '"api_key":"test-key","services":["network"]}]'
            ),
            controller_url=None,
            cloud_api_key=None,
            runtime_enabled=False,
            data_dir=data_dir,
        )

        with patch("unifi_mcp.clients.base.settings", settings):
            async with Client(mcp) as client:
                await client.list_tools()

        assert not data_dir.exists()

    async def test_registered_lifespan_opens_and_closes_enabled_runtime(self, tmp_path):
        settings = UniFiSettings(
            _env_file=None,
            mode="local_api_key",
            devices_json=(
                '[{"name":"test-gw","url":"https://10.0.0.1",'
                '"api_key":"test-key","services":["network"]}]'
            ),
            controller_url=None,
            cloud_api_key=None,
            runtime_enabled=True,
            runtime_database=tmp_path / "runtime.db",
        )

        with (
            patch("unifi_mcp.clients.base.settings", settings),
            patch.object(RuntimeStore, "open", new_callable=AsyncMock) as open_runtime,
            patch.object(RuntimeStore, "close", new_callable=AsyncMock) as close_runtime,
        ):
            async with Client(mcp) as client:
                await client.list_tools()

        open_runtime.assert_awaited_once()
        close_runtime.assert_awaited_once()

    async def test_enabled_runtime_is_initialized_and_closed(self, tmp_path):
        database_path = tmp_path / "runtime" / "runtime.db"
        settings = UniFiSettings(
            _env_file=None,
            mode="local_api_key",
            devices_json=(
                '[{"name":"test-gw","url":"https://10.0.0.1",'
                '"api_key":"test-key","services":["network"]}]'
            ),
            controller_url=None,
            cloud_api_key=None,
            runtime_enabled=True,
            runtime_database=database_path,
        )

        with patch("unifi_mcp.clients.base.settings", settings):
            async with create_app_lifespan(mcp) as context:
                runtime = context.runtime
                assert runtime is not None
                assert runtime.connected is True
                assert database_path.is_file()

        assert runtime.connected is False

    async def test_runtime_open_failure_preserves_exception_when_http_close_fails(self, tmp_path):
        settings = UniFiSettings(
            _env_file=None,
            mode="local_api_key",
            devices_json=(
                '[{"name":"test-gw","url":"https://10.0.0.1",'
                '"api_key":"test-key","services":["network"]}]'
            ),
            controller_url=None,
            cloud_api_key=None,
            runtime_enabled=True,
            runtime_database=tmp_path / "runtime.db",
        )
        error = RuntimeError("runtime open failed")
        close_error = RuntimeError("http close failed")
        cleanup_events = []
        http_client = AsyncMock()

        async def fail_http_close():
            cleanup_events.append("http")
            raise close_error

        http_client.aclose.side_effect = fail_http_close

        with (
            patch("unifi_mcp.clients.base.settings", settings),
            patch("unifi_mcp.clients.base.httpx.AsyncClient", return_value=http_client),
            patch.object(RuntimeStore, "open", new_callable=AsyncMock, side_effect=error),
            patch.object(
                RuntimeStore,
                "close",
                new_callable=AsyncMock,
                side_effect=lambda: cleanup_events.append("runtime"),
            ),
            pytest.raises(RuntimeError) as raised,
        ):
            async with create_app_lifespan(mcp):
                pass

        assert raised.value is error
        assert cleanup_events == ["runtime", "http"]

    async def test_runtime_open_cancellation_closes_runtime_and_http_client(self, tmp_path):
        settings = UniFiSettings(
            _env_file=None,
            mode="local_api_key",
            devices_json=(
                '[{"name":"test-gw","url":"https://10.0.0.1",'
                '"api_key":"test-key","services":["network"]}]'
            ),
            controller_url=None,
            cloud_api_key=None,
            runtime_enabled=True,
            runtime_database=tmp_path / "runtime.db",
        )
        open_started = asyncio.Event()
        keep_open = asyncio.Event()
        http_client = AsyncMock()

        async def blocked_open(runtime):
            open_started.set()
            await keep_open.wait()

        async def enter_lifespan():
            async with create_app_lifespan(mcp):
                pass

        with (
            patch("unifi_mcp.clients.base.settings", settings),
            patch("unifi_mcp.clients.base.httpx.AsyncClient", return_value=http_client),
            patch.object(RuntimeStore, "open", blocked_open),
            patch.object(RuntimeStore, "close", new_callable=AsyncMock) as close_runtime,
        ):
            task = asyncio.create_task(enter_lifespan())
            try:
                await asyncio.wait_for(open_started.wait(), timeout=1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=1)
            finally:
                keep_open.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        close_runtime.assert_awaited_once()
        http_client.aclose.assert_awaited_once()

    async def test_login_failure_is_preserved_when_runtime_close_fails(self, tmp_path):
        settings = UniFiSettings(
            _env_file=None,
            mode="local",
            devices_json=None,
            controller_url="https://10.0.0.1",
            cloud_api_key=None,
            username="admin",
            password="password",
            runtime_enabled=True,
            runtime_database=tmp_path / "runtime.db",
        )
        error = RuntimeError("login failed")
        close_error = RuntimeError("runtime close failed")
        cleanup_events = []
        http_client = AsyncMock()
        http_client.aclose.side_effect = lambda: cleanup_events.append("http")

        async def fail_runtime_close():
            cleanup_events.append("runtime")
            raise close_error

        with (
            patch("unifi_mcp.clients.base.settings", settings),
            patch("unifi_mcp.clients.base.httpx.AsyncClient", return_value=http_client),
            patch.object(RuntimeStore, "open", new_callable=AsyncMock),
            patch.object(
                RuntimeStore,
                "close",
                new_callable=AsyncMock,
                side_effect=fail_runtime_close,
            ),
            patch.object(UniFiLocalAuth, "login", new_callable=AsyncMock, side_effect=error),
            patch.object(
                UniFiLocalAuth,
                "logout",
                new_callable=AsyncMock,
                side_effect=lambda: cleanup_events.append("logout"),
            ),
            pytest.raises(RuntimeError) as raised,
        ):
            async with create_app_lifespan(mcp):
                pass

        assert raised.value is error
        assert cleanup_events == ["runtime", "logout", "http"]

    async def test_shutdown_raises_first_cleanup_failure_and_attempts_later_cleanup(self, tmp_path):
        settings = UniFiSettings(
            _env_file=None,
            mode="local",
            devices_json=None,
            controller_url="https://10.0.0.1",
            cloud_api_key=None,
            username="admin",
            password="password",
            runtime_enabled=True,
            runtime_database=tmp_path / "runtime.db",
        )
        runtime_error = RuntimeError("runtime close failed")
        logout_error = RuntimeError("logout failed")
        cleanup_events = []
        http_client = AsyncMock()
        http_client.aclose.side_effect = lambda: cleanup_events.append("http")
        webhook_client = AsyncMock()
        webhook_client.aclose.side_effect = lambda: cleanup_events.append("webhook")

        async def fail_runtime_close():
            cleanup_events.append("runtime")
            raise runtime_error

        async def fail_logout():
            cleanup_events.append("logout")
            raise logout_error

        with (
            patch("unifi_mcp.clients.base.settings", settings),
            patch(
                "unifi_mcp.clients.base.httpx.AsyncClient",
                side_effect=[http_client, webhook_client],
            ),
            patch.object(RuntimeStore, "open", new_callable=AsyncMock),
            patch.object(
                RuntimeStore, "close", new_callable=AsyncMock, side_effect=fail_runtime_close
            ),
            patch.object(UniFiLocalAuth, "login", new_callable=AsyncMock),
            patch.object(UniFiLocalAuth, "logout", new_callable=AsyncMock, side_effect=fail_logout),
            pytest.raises(RuntimeError) as raised,
        ):
            async with create_app_lifespan(mcp):
                pass

        assert raised.value is runtime_error
        assert cleanup_events == ["webhook", "runtime", "logout", "http"]
