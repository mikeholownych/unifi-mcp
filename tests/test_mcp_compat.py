"""Compatibility contract for the supported MCP stack."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from mcp import Client, StdioServerParameters

from unifi_mcp.config import UniFiSettings

EXPECTED_CORE_TOOLS = {
    "get_server_health",
    "list_unifi_devices",
    "list_devices",
    "get_device_details",
    "list_clients",
    "get_client_details",
    "get_networks",
    "get_wlans",
    "get_firewall_policies",
    "analyze_network_issues",
    "list_cameras",
    "get_camera_snapshot",
    "get_global_inventory",
    "get_global_health",
    "get_global_client_summary",
}
CONTRACT_FIELDS = ("name", "description", "inputSchema", "outputSchema", "annotations")
CONTRACT_FIXTURE = Path(__file__).parent / "fixtures" / "tool_contracts.json"
COPIED_NETWORK_TOOLS = {
    "get_device_ports",
    "set_device_port",
    "reserve_client_ip",
    "create_network",
    "update_network",
    "delete_network",
}


def normalize_tool_contracts(tools):
    """Return the stable, public portion of native Tool serialization."""
    contracts = []
    for tool in tools:
        wire_tool = tool.model_dump(by_alias=True)
        contracts.append({field: wire_tool.get(field) for field in CONTRACT_FIELDS})
    return sorted(contracts, key=lambda contract: contract["name"])


def test_server_imports_with_supported_mcp_stack():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from unifi_mcp.server import mcp; print(mcp.name)",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "UniFi MCP Server"


async def test_module_stdio_server_registers_export_camera_clip():
    env = os.environ.copy()
    env.update(
        {
            "UNIFI_MODE": "local_api_key",
            "UNIFI_DEVICES": (
                '[{"name":"stdio-test","url":"https://192.0.2.1",'
                '"api_key":"stdio-test-key","services":["network"]}]'
            ),
            "UNIFI_CONTROLLER_URL": "",
            "UNIFI_CLOUD_API_KEY": "stdio-cloud-test-key",
            "UNIFI_USERNAME": "stdio-test-user",
            "UNIFI_PASSWORD": "stdio-test-password",
            "UNIFI_RUNTIME_ENABLED": "false",
        }
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "unifi_mcp.server"],
        cwd=Path(__file__).parents[1],
        env=env,
    )

    async with asyncio.timeout(10):
        async with Client(parameters, read_timeout_seconds=5) as client:
            # Entering the native client performs the initialize handshake.
            tools = (await client.list_tools()).tools

    assert "export_camera_clip" in {tool.name for tool in tools}


async def test_public_tool_wire_contracts_match_fixture():
    from unifi_mcp.server import mcp

    settings = UniFiSettings(
        _env_file=None,
        devices_json=(
            '[{"name":"test-gw","url":"https://10.0.0.1",'
            '"api_key":"test-key","services":["network"]}]'
        ),
        runtime_enabled=False,
    )
    with patch("unifi_mcp.clients.base.settings", settings):
        async with Client(mcp) as client:
            tools = (await client.list_tools()).tools

    runtime_contracts = normalize_tool_contracts(tools)
    fixture_contracts = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))

    assert runtime_contracts == fixture_contracts, (
        "Public MCP tool contracts changed. Review the protocol diff, then intentionally "
        "regenerate tests/fixtures/tool_contracts.json from native Tool.model_dump(by_alias=True)."
    )


async def test_tool_contract_fixture_names_cover_runtime_and_phase_one_tools():
    from unifi_mcp.server import mcp

    settings = UniFiSettings(
        _env_file=None,
        devices_json=(
            '[{"name":"test-gw","url":"https://10.0.0.1",'
            '"api_key":"test-key","services":["network"]}]'
        ),
        runtime_enabled=False,
    )
    with patch("unifi_mcp.clients.base.settings", settings):
        async with Client(mcp) as client:
            runtime_names = {tool.name for tool in (await client.list_tools()).tools}

    fixture_names = {
        contract["name"] for contract in json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))
    }
    required_names = COPIED_NETWORK_TOOLS | {
        "export_camera_clip",
        "get_plugin_status",
        "get_server_health",
    }

    assert fixture_names == runtime_names
    assert required_names <= fixture_names


async def test_existing_tool_contract_is_preserved():
    from unifi_mcp.server import mcp

    settings = UniFiSettings(
        _env_file=None,
        devices_json=(
            '[{"name":"test-gw","url":"https://10.0.0.1",'
            '"api_key":"test-key","services":["network"]}]'
        ),
    )
    with patch("unifi_mcp.clients.base.settings", settings):
        async with Client(mcp) as client:
            result = await client.list_tools()

    tools = {tool.name: tool for tool in result.tools}

    missing = EXPECTED_CORE_TOOLS - tools.keys()
    assert not missing, f"Missing tools: {sorted(missing)}"

    list_devices = tools["list_devices"]
    wire_tool = list_devices.model_dump(by_alias=True)
    assert set(wire_tool["inputSchema"]["properties"]) == {"site", "device"}
    assert wire_tool["annotations"]["readOnlyHint"] is True
    assert "ctx" not in wire_tool["inputSchema"]["properties"]

    server_health = tools["get_server_health"]
    wire_health = server_health.model_dump(by_alias=True)
    assert wire_health["inputSchema"]["properties"] == {}
    assert server_health.description == (
        "Get redaction-safe UniFi MCP runtime health and service counts."
    )
    assert server_health.annotations.read_only_hint is True
    assert wire_health["annotations"]["readOnlyHint"] is True

    output_schema = wire_health["outputSchema"]
    assert set(output_schema["properties"]) == {
        "status",
        "version",
        "transport",
        "configured_devices",
        "services",
        "persistence",
    }
    assert set(output_schema["required"]) == {
        "status",
        "version",
        "transport",
        "configured_devices",
        "services",
        "persistence",
    }
    assert output_schema["additionalProperties"] is False

    def resolve(schema):
        reference = schema.get("$ref")
        if reference is None:
            return schema
        assert reference.startswith("#/$defs/")
        return output_schema["$defs"][reference.removeprefix("#/$defs/")]

    services_schema = resolve(output_schema["properties"]["services"])
    assert set(services_schema["properties"]) == {"network", "protect"}
    assert set(services_schema["required"]) == {"network", "protect"}
    assert services_schema["additionalProperties"] is False

    persistence_schema = output_schema["properties"]["persistence"]
    persistence_variants = persistence_schema["oneOf"]
    expected_refs = {
        "#/$defs/DisabledPersistenceHealth",
        "#/$defs/EnabledPersistenceHealth",
    }
    assert {variant["$ref"] for variant in persistence_variants} == expected_refs
    discriminator = persistence_schema["discriminator"]
    assert discriminator["propertyName"] == "enabled"
    assert discriminator["mapping"] == {
        "False": "#/$defs/DisabledPersistenceHealth",
        "True": "#/$defs/EnabledPersistenceHealth",
    }
    resolved_variants = [resolve(variant) for variant in persistence_variants]
    assert {frozenset(variant["properties"]) for variant in resolved_variants} == {
        frozenset({"enabled", "connected"}),
        frozenset({"enabled", "connected", "schema_version", "journal_mode"}),
    }
    assert all(variant["additionalProperties"] is False for variant in resolved_variants)
    variants_by_enabled = {
        variant["properties"]["enabled"]["const"]: variant for variant in resolved_variants
    }
    assert set(variants_by_enabled[False]["required"]) == {"enabled", "connected"}
    assert set(variants_by_enabled[True]["required"]) == {
        "enabled",
        "connected",
        "schema_version",
        "journal_mode",
    }


async def test_server_health_returns_structured_content_through_native_client():
    from unifi_mcp.server import mcp

    settings = UniFiSettings(
        _env_file=None,
        devices_json=(
            '[{"name":"test-gw","url":"https://10.0.0.1",'
            '"api_key":"test-key","services":["network"]}]'
        ),
        runtime_enabled=False,
    )
    with patch("unifi_mcp.clients.base.settings", settings):
        async with Client(mcp) as client:
            result = await client.call_tool("get_server_health", {})

    assert result.is_error is False
    assert result.structured_content == {
        "status": "ok",
        "version": mcp.version,
        "transport": "stdio",
        "configured_devices": 1,
        "services": {"network": 1, "protect": 0},
        "persistence": {"enabled": False, "connected": False},
    }
