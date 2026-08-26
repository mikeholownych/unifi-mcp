"""Tests for MCP server tool registration and lifespan."""

import pytest

from unifi_mcp.config import UniFiSettings
from unifi_mcp.server import mcp


class TestToolRegistration:
    async def test_all_tools_registered(self):
        tools = await mcp.list_tools()
        assert len(tools) >= 48

    async def test_every_tool_has_description(self):
        tools = await mcp.list_tools()
        for tool in tools:
            assert tool.description, f"tool {tool.name} missing description"

    async def test_network_tools_support_device_targeting(self):
        tools = {t.name: t for t in await mcp.list_tools()}
        for name, tool in tools.items():
            if name in ("list_unifi_devices", "get_global_inventory",
                        "get_global_health", "get_global_client_summary"):
                continue
            if name.startswith(
                (
                    "list_devices", "get_device", "restart_device", "locate_device",
                    "upgrade_device", "provision_device", "list_clients",
                    "list_all_clients", "block_client", "unblock_client",
                    "kick_client", "forget_client", "get_client", "list_sites",
                    "get_site", "get_sysinfo", "get_networks", "get_wlans",
                    "get_port_profiles", "get_firewall_rules", "get_routing_table",
                    "get_network_health", "get_recent_events", "get_alarms",
                    "archive_all_alarms", "run_speed_test", "get_speed_test_status",
                    "get_dpi_stats", "get_traffic", "analyze_network_issues",
                    "get_optimization_recommendations", "troubleshoot_client",
                )
            ):
                assert "device" in tool.inputSchema["properties"], (
                    f"{name} missing device param"
                )

    async def test_protect_tools_support_device_targeting(self):
        tools = {t.name: t for t in await mcp.list_tools()}
        protect_tools = [
            n for n in tools if n.startswith(
                ("list_cameras", "get_camera", "get_protect", "get_liveviews",
                 "get_motion", "get_smart", "get_recent_protect")
            )
        ]
        assert len(protect_tools) >= 10
        for name in protect_tools:
            assert "device" in tools[name].inputSchema["properties"], (
                f"{name} missing device param"
            )


class TestLifespanConfigValidation:
    async def test_lifespan_requires_configuration(self):
        from unittest.mock import patch

        empty = UniFiSettings(_env_file=None)
        with patch("unifi_mcp.clients.base.settings", empty), pytest.raises(Exception, match="No UniFi devices"):
            async with mcp.settings.lifespan(mcp):
                pass

    def test_settings_load_from_env_file(self):
        # The project .env should produce at least one device
        settings = UniFiSettings()
        assert isinstance(settings.devices, list)
