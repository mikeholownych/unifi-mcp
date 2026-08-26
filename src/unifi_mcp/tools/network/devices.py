"""Device management tools for UniFi Network."""

from typing import Any

from mcp.server.fastmcp import Context

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient, is_device_online


def _get_client(ctx: Context, device: str | None = None) -> UniFiNetworkClient:
    """Get the UniFi Network client from context, optionally targeting a device."""
    app_ctx: AppContext = ctx.request_context.lifespan_context
    return UniFiNetworkClient(app_ctx, device_name=device)


def _format_device_summary(device: dict[str, Any]) -> dict[str, Any]:
    """Format device data into a clean summary."""
    # Handle both API formats: traditional ("mac"/"version") and
    # Integration API ("macAddress"/"firmwareVersion")
    return {
        "name": device.get("name", "Unknown"),
        "mac": device.get("mac") or device.get("macAddress", ""),
        "model": device.get("model", ""),
        "type": device.get("type", ""),
        "ip": device.get("ip", ""),
        "state": "online" if is_device_online(device) else "offline",
        "adopted": device.get("adopted", True),
        "uptime": device.get("uptime", 0),
        "version": device.get("version") or device.get("firmwareVersion", ""),
        "upgradable": bool(device.get("upgradable") or device.get("firmwareUpdatable")),
    }


def _format_device_details(device: dict[str, Any]) -> dict[str, Any]:
    """Format detailed device information."""
    base = _format_device_summary(device)

    # Add extended information
    base.update({
        "serial": device.get("serial", ""),
        "config_network": device.get("config_network", {}),
        "ethernet_table": device.get("ethernet_table", []),
        "port_table": device.get("port_table", []),
        "radio_table": device.get("radio_table", []),
        "uplink": device.get("uplink", {}),
        "system_stats": {
            "cpu": device.get("system-stats", {}).get("cpu", "N/A"),
            "mem": device.get("system-stats", {}).get("mem", "N/A"),
            "uptime": device.get("system-stats", {}).get("uptime", "N/A"),
        },
        "temperatures": device.get("temperatures", []),
        "fan_level": device.get("fan_level"),
        "total_bytes": device.get("bytes", 0),
        "tx_bytes": device.get("tx_bytes", 0),
        "rx_bytes": device.get("rx_bytes", 0),
        "num_sta": device.get("num_sta", 0),
        "user_num_sta": device.get("user-num_sta", 0),
        "guest_num_sta": device.get("guest-num_sta", 0),
    })

    return base


async def list_devices(ctx: Context, site: str = "default") -> list[dict[str, Any]]:
    """List all UniFi network devices (APs, switches, routers).

    Args:
        ctx: MCP context
        site: Site name (default: "default")

    Returns:
        List of devices with summary information including name, MAC,
        model, type, IP, state, uptime, and firmware version.
    """
    client = _get_client(ctx)
    devices = await client.get_devices(site)

    return [_format_device_summary(d) for d in devices]


async def get_device_details(
    ctx: Context, mac: str, site: str = "default"
) -> dict[str, Any]:
    """Get detailed information about a specific device.

    Args:
        ctx: MCP context
        mac: Device MAC address (any format: aa:bb:cc:dd:ee:ff or aabbccddeeff)
        site: Site name

    Returns:
        Detailed device information including ports, radios, uplink,
        system stats, temperatures, and traffic statistics.
    """
    client = _get_client(ctx)
    device = await client.get_device(mac, site)

    return _format_device_details(device)


async def restart_device(
    ctx: Context, mac: str, site: str = "default"
) -> dict[str, Any]:
    """Restart a UniFi device.

    Args:
        ctx: MCP context
        mac: Device MAC address
        site: Site name

    Returns:
        Command result indicating success or failure.
    """
    client = _get_client(ctx)
    result = await client.restart_device(mac, site)

    return {
        "success": result.get("meta", {}).get("rc") == "ok",
        "message": f"Restart command sent to device {mac}",
        "device_mac": mac,
    }


async def locate_device(
    ctx: Context, mac: str, enabled: bool = True, site: str = "default"
) -> dict[str, Any]:
    """Enable or disable LED blinking to locate a device.

    Args:
        ctx: MCP context
        mac: Device MAC address
        enabled: True to start LED blinking, False to stop
        site: Site name

    Returns:
        Command result.
    """
    client = _get_client(ctx)
    result = await client.locate_device(mac, enabled, site)

    action = "started" if enabled else "stopped"
    return {
        "success": result.get("meta", {}).get("rc") == "ok",
        "message": f"LED blinking {action} on device {mac}",
        "device_mac": mac,
        "locate_enabled": enabled,
    }


async def get_device_stats(
    ctx: Context, mac: str, site: str = "default"
) -> dict[str, Any]:
    """Get performance statistics for a device.

    Args:
        ctx: MCP context
        mac: Device MAC address
        site: Site name

    Returns:
        Device performance metrics including CPU, memory, temperatures,
        client count, and traffic statistics.
    """
    client = _get_client(ctx)
    device = await client.get_device(mac, site)

    # Extract system stats
    sys_stats = device.get("system-stats", {})

    stats = {
        "device_name": device.get("name", "Unknown"),
        "mac": device.get("mac", ""),
        "model": device.get("model", ""),
        "uptime_seconds": device.get("uptime", 0),
        "performance": {
            "cpu_percent": sys_stats.get("cpu", "N/A"),
            "memory_percent": sys_stats.get("mem", "N/A"),
        },
        "temperatures": device.get("temperatures", []),
        "fan_level": device.get("fan_level"),
        "clients": {
            "total": device.get("num_sta", 0),
            "user": device.get("user-num_sta", 0),
            "guest": device.get("guest-num_sta", 0),
        },
        "traffic": {
            "total_bytes": device.get("bytes", 0),
            "tx_bytes": device.get("tx_bytes", 0),
            "rx_bytes": device.get("rx_bytes", 0),
        },
        "satisfaction": device.get("satisfaction", None),
    }

    # Add radio stats for APs
    if device.get("type") == "uap":
        radio_stats = []
        for radio in device.get("radio_table_stats", []):
            radio_stats.append({
                "name": radio.get("name", ""),
                "channel": radio.get("channel"),
                "tx_power": radio.get("tx_power"),
                "satisfaction": radio.get("satisfaction"),
                "num_sta": radio.get("num_sta", 0),
            })
        stats["radios"] = radio_stats

    return stats


async def upgrade_device(
    ctx: Context, mac: str, site: str = "default"
) -> dict[str, Any]:
    """Upgrade device firmware to the latest version.

    Args:
        ctx: MCP context
        mac: Device MAC address
        site: Site name

    Returns:
        Command result.
    """
    client = _get_client(ctx)
    result = await client.upgrade_device(mac, site)

    return {
        "success": result.get("meta", {}).get("rc") == "ok",
        "message": f"Firmware upgrade initiated for device {mac}",
        "device_mac": mac,
    }


async def provision_device(
    ctx: Context, mac: str, site: str = "default"
) -> dict[str, Any]:
    """Force re-provision a device with current configuration.

    Args:
        ctx: MCP context
        mac: Device MAC address
        site: Site name

    Returns:
        Command result.
    """
    client = _get_client(ctx)
    result = await client.provision_device(mac, site)

    return {
        "success": result.get("meta", {}).get("rc") == "ok",
        "message": f"Provision command sent to device {mac}",
        "device_mac": mac,
    }
