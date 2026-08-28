"""Device management tools for UniFi Network."""

import logging
import re
from typing import Any

from mcp.server.mcpserver import Context

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient, is_device_online
from unifi_mcp.exceptions import UniFiConnectionError, UniFiDeliveryUnknownError
from unifi_mcp.tools.network._verification import (
    accepted_unverified,
    delivery_unknown,
    normalize_field,
    preflight_failed,
    requested_observation,
    verify_eventually,
)
from unifi_mcp.tools.network.sites import AmbiguousNetworkError, _find_network

logger = logging.getLogger(__name__)

_MAC_PATTERN = re.compile(
    r"^(?:[0-9A-Fa-f]{12}|[0-9A-Fa-f]{2}(?P<sep>[:-])(?:[0-9A-Fa-f]{2}(?P=sep)){4}[0-9A-Fa-f]{2})$"
)


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
    base.update(
        {
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
        }
    )

    return base


async def list_devices(
    ctx: Context, site: str = "default", device: str | None = None
) -> list[dict[str, Any]]:
    """List all UniFi network devices (APs, switches, routers).

    Args:
        ctx: MCP context
        site: Site name (default: "default")

    Returns:
        List of devices with summary information including name, MAC,
        model, type, IP, state, uptime, and firmware version.
    """
    client = _get_client(ctx, device)
    devices = await client.get_devices(site)

    return [_format_device_summary(d) for d in devices]


async def get_device_details(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
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
    client = _get_client(ctx, device)
    device = await client.get_device(mac, site)

    return _format_device_details(device)


async def restart_device(ctx: Context, mac: str, site: str = "default") -> dict[str, Any]:
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


async def get_device_stats(ctx: Context, mac: str, site: str = "default") -> dict[str, Any]:
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
            radio_stats.append(
                {
                    "name": radio.get("name", ""),
                    "channel": radio.get("channel"),
                    "tx_power": radio.get("tx_power"),
                    "satisfaction": radio.get("satisfaction"),
                    "num_sta": radio.get("num_sta", 0),
                }
            )
        stats["radios"] = radio_stats

    return stats


async def upgrade_device(ctx: Context, mac: str, site: str = "default") -> dict[str, Any]:
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


async def provision_device(ctx: Context, mac: str, site: str = "default") -> dict[str, Any]:
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


async def get_device_ports(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
) -> list[dict[str, Any]]:
    """List the switch/gateway ports on a device.

    Returns each port with its index, name, media (GE/SFP), link state, speed,
    current native network (VLAN) ID, and peer connection info where known.

    Args:
        ctx: MCP context
        mac: Device MAC address
        site: Site name
        device: Device name

    Returns:
        List of port summaries
    """
    client = _get_client(ctx, device)
    ports = await client.get_device_port_table(mac, site)
    return [
        {
            "port_idx": p.get("port_idx"),
            "name": p.get("name", f"Port {p.get('port_idx', '')}"),
            "media": p.get("media", ""),
            "op_mode": p.get("op_mode", ""),
            "up": bool(p.get("up", False)),
            "speed": p.get("speed", 0),
            "full_duplex": p.get("full_duplex", False),
            "is_uplink": bool(p.get("is_uplink", False)),
            "native_networkconf_id": p.get("native_networkconf_id"),
            "forward": p.get("forward", ""),
            "poe_mode": p.get("poe_mode", p.get("port_poe") and "auto"),
            "setting_preference": p.get("setting_preference", "auto"),
            "connected_mac": (p.get("last_connection") or {}).get("mac"),
            "connected_ip": (p.get("last_connection") or {}).get("ip"),
        }
        for p in ports
    ]


async def set_device_port(
    ctx: Context,
    mac: str,
    port_idx: int,
    name: str | None = None,
    native_network: str | None = None,
    poe_mode: str | None = None,
    forward: str | None = None,
    enabled: bool | None = None,
    site: str = "default",
    device: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Configure a single switch port (native VLAN, PoE, name, enable state).

    Only the fields you provide are changed. ``native_network`` can be a network
    name or its record ID (the controller stores the ID on the port), and is
    what determines the untagged VLAN traffic on that port.

    Args:
        ctx: MCP context
        mac: Device MAC address
        port_idx: Port number to configure (1-based, e.g. 1-24 or SFP 25/26)
        name: Custom port name (e.g. "Cameras")
        native_network: Network name or ID to assign as the port's native VLAN
        poe_mode: PoE mode: auto, on, off, or passv24 (PoE switches only)
        forward: "all" to allow all VLANs, or "customize" for a custom set
        enabled: Enable or disable the port
        confirm: Must be True because a port change can disconnect attached devices
        site: Site name
        device: Device name

    Returns:
        Summary of the update, or an error
    """
    if not confirm:
        return {
            "success": False,
            "message": "Port changes require confirm=true because they can disrupt connectivity "
            "for the attached device or downstream network.",
        }

    if not _MAC_PATTERN.fullmatch(mac.strip()):
        return {
            "success": False,
            "message": "Device MAC must be a canonical 12-hex MAC address.",
        }
    if isinstance(port_idx, bool) or port_idx <= 0:
        return {"success": False, "message": "port_idx must be a positive integer."}
    if name is not None and not name.strip():
        return {"success": False, "message": "Port name must be nonblank when supplied."}
    if poe_mode is not None and poe_mode not in {"auto", "on", "off", "passv24"}:
        return {
            "success": False,
            "message": "poe_mode must be auto, on, off, or passv24.",
        }
    if forward is not None and forward not in {"all", "customize"}:
        return {"success": False, "message": "forward must be all or customize."}
    if enabled is not None and not isinstance(enabled, bool):
        return {"success": False, "message": "enabled must be a boolean."}

    if native_network is not None and not native_network.strip():
        return {
            "success": False,
            "message": "native_network must be a nonblank network name or ID.",
        }

    if all(value is None for value in (name, native_network, poe_mode, forward, enabled)):
        return {
            "success": False,
            "message": "Port update requires at least one field to change.",
        }

    client = _get_client(ctx, device)

    # Resolve a native network name to its record ID if supplied.
    native_id: str | None = None
    if native_network:
        try:
            network = await _find_network(client, native_network, site, fresh=True)
        except AmbiguousNetworkError:
            return {
                "success": False,
                "message": "Native network name is ambiguous; provide its stable ID.",
            }
        except Exception as exc:
            logger.warning("Failed to resolve native network (%s)", type(exc).__name__)
            return {
                "success": False,
                "message": "Unable to resolve native network; check server logs.",
            }
        if network is None:
            return {
                "success": False,
                "message": f"Network '{native_network}' not found",
            }
        native_id = network.get("_id") or network.get("id")
        if not native_id:
            return {
                "success": False,
                "message": "Native network has no stable ID; refusing port update.",
            }

    change: dict[str, Any] = {"port_idx": port_idx}
    if name is not None:
        change["name"] = name.strip()
    if native_id is not None:
        change["native_networkconf_id"] = native_id
        change["setting_preference"] = "manual"
    if poe_mode is not None:
        change["poe_mode"] = poe_mode
        change["setting_preference"] = "manual"
    if forward is not None:
        change["forward"] = forward
        change["setting_preference"] = "manual"
    if enabled is not None:
        change["enabled"] = enabled
        change["setting_preference"] = "manual"

    try:
        await client.update_device_ports(mac, [change], site)
    except UniFiDeliveryUnknownError:
        logger.warning("Port update delivery outcome is unknown")
        return delivery_unknown("port update")
    except UniFiConnectionError:
        logger.warning("Port update preflight failed before dispatch")
        return preflight_failed("port update")
    except Exception as exc:
        logger.warning("Controller rejected port update (%s)", type(exc).__name__)
        return {
            "success": False,
            "message": "Controller rejected port update; check server logs.",
        }

    requested = {k: v for k, v in change.items() if k != "port_idx"}
    observed_port: dict[str, Any] | None = None

    def evaluate(ports: list[dict[str, Any]]) -> tuple[bool, Any]:
        nonlocal observed_port
        observed_port = next(
            (
                port
                for port in ports
                if normalize_field("port_idx", port.get("port_idx")) == port_idx
            ),
            None,
        )
        return requested_observation(observed_port, requested)

    verification = await verify_eventually(
        lambda: client.get_device_port_table(mac, site, fresh=True),
        evaluate,
        operation="port update",
        logger=logger,
        attempts=client.ctx.settings.mutation_verify_attempts,
        initial_delay=client.ctx.settings.mutation_verify_initial_delay,
        max_delay=client.ctx.settings.mutation_verify_max_delay,
    )
    if not verification.matched:
        return accepted_unverified(requested, verification.observed)

    return {
        "success": True,
        "device_mac": mac,
        "port_idx": port_idx,
        "message": f"Port {port_idx} updated",
        "changes": verification.observed,
    }
