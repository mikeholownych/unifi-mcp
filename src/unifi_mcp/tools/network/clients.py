"""Client management tools for UniFi Network."""

from typing import Any

from mcp.server.fastmcp import Context

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient


def _get_client(ctx: Context, device: str | None = None) -> UniFiNetworkClient:
    """Get the UniFi Network client from context, optionally targeting a device."""
    app_ctx: AppContext = ctx.request_context.lifespan_context
    return UniFiNetworkClient(app_ctx, device_name=device)


def _format_client_summary(client: dict[str, Any]) -> dict[str, Any]:
    """Format client data into a clean summary."""
    # Determine connection type
    is_wired = client.get("is_wired", False)
    connection_type = "wired" if is_wired else "wireless"

    return {
        "name": client.get("name") or client.get("hostname") or "Unknown",
        "mac": client.get("mac", ""),
        "ip": client.get("ip", ""),
        "connection_type": connection_type,
        "network": client.get("network", ""),
        "vlan": client.get("vlan"),
        "connected": client.get("is_online", True),
        "uptime": client.get("uptime", 0),
        "last_seen": client.get("last_seen", 0),
        "signal": client.get("signal") if not is_wired else None,
        "rssi": client.get("rssi") if not is_wired else None,
        "ap_mac": client.get("ap_mac") if not is_wired else None,
        "essid": client.get("essid") if not is_wired else None,
        "switch_mac": client.get("sw_mac") if is_wired else None,
        "switch_port": client.get("sw_port") if is_wired else None,
        "tx_bytes": client.get("tx_bytes", 0),
        "rx_bytes": client.get("rx_bytes", 0),
    }


def _format_client_details(client: dict[str, Any]) -> dict[str, Any]:
    """Format detailed client information."""
    base = _format_client_summary(client)

    # Add extended information
    is_wired = client.get("is_wired", False)

    base.update({
        "oui": client.get("oui", ""),
        "hostname": client.get("hostname", ""),
        "fingerprint": {
            "os_name": client.get("os_name"),
            "dev_cat": client.get("dev_cat"),
            "dev_family": client.get("dev_family"),
            "dev_vendor": client.get("dev_vendor"),
        },
        "blocked": client.get("blocked", False),
        "noted": client.get("noted", False),
        "note": client.get("note"),
        "fixed_ip": client.get("use_fixedip", False),
        "fixed_ip_address": client.get("fixed_ip") if client.get("use_fixedip") else None,
        "satisfaction": client.get("satisfaction"),
        "traffic": {
            "tx_bytes": client.get("tx_bytes", 0),
            "rx_bytes": client.get("rx_bytes", 0),
            "tx_packets": client.get("tx_packets", 0),
            "rx_packets": client.get("rx_packets", 0),
            "tx_retries": client.get("tx_retries", 0),
        },
    })

    # Wireless-specific details
    if not is_wired:
        base.update({
            "channel": client.get("channel"),
            "radio": client.get("radio"),
            "radio_proto": client.get("radio_proto"),
            "tx_rate": client.get("tx_rate"),
            "rx_rate": client.get("rx_rate"),
            "noise": client.get("noise"),
            "ccq": client.get("ccq"),
            "roam_count": client.get("roam_count", 0),
        })

    return base


async def list_clients(ctx: Context, site: str = "default", device: str | None = None) -> list[dict[str, Any]]:
    """List all currently connected clients.

    Args:
        ctx: MCP context
        site: Site name (default: "default")

    Returns:
        List of connected clients with summary information including
        name, MAC, IP, connection type, signal strength, and traffic.
    """
    client = _get_client(ctx, device)
    clients = await client.get_clients(site)

    return [_format_client_summary(c) for c in clients]


async def list_all_clients(ctx: Context, site: str = "default", device: str | None = None) -> list[dict[str, Any]]:
    """List all known clients (including offline).

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        List of all known clients with historical connection information.
    """
    client = _get_client(ctx, device)
    clients = await client.get_all_clients(site)

    result = []
    for c in clients:
        summary = {
            "name": c.get("name") or c.get("hostname") or "Unknown",
            "mac": c.get("mac", ""),
            "oui": c.get("oui", ""),
            "first_seen": c.get("first_seen", 0),
            "last_seen": c.get("last_seen", 0),
            "blocked": c.get("blocked", False),
            "noted": c.get("noted", False),
            "note": c.get("note"),
        }
        result.append(summary)

    return result


async def get_client_details(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    """Get detailed information about a specific client.

    Args:
        ctx: MCP context
        mac: Client MAC address
        site: Site name

    Returns:
        Detailed client information including connection quality,
        traffic statistics, device fingerprint, and network details.
    """
    client = _get_client(ctx, device)
    client_data = await client.get_client(mac, site)

    return _format_client_details(client_data)


async def block_client(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    """Block a client from the network.

    The client will be immediately disconnected and prevented from
    reconnecting until unblocked.

    Args:
        ctx: MCP context
        mac: Client MAC address
        site: Site name

    Returns:
        Command result indicating success or failure.
    """
    client = _get_client(ctx, device)
    result = await client.block_client(mac, site)

    return {
        "success": result.get("meta", {}).get("rc") == "ok",
        "message": f"Client {mac} has been blocked",
        "client_mac": mac,
        "action": "blocked",
    }


async def unblock_client(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    """Unblock a previously blocked client.

    The client will be able to reconnect to the network.

    Args:
        ctx: MCP context
        mac: Client MAC address
        site: Site name

    Returns:
        Command result.
    """
    client = _get_client(ctx, device)
    result = await client.unblock_client(mac, site)

    return {
        "success": result.get("meta", {}).get("rc") == "ok",
        "message": f"Client {mac} has been unblocked",
        "client_mac": mac,
        "action": "unblocked",
    }


async def kick_client(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    """Disconnect a client from the network.

    The client can immediately reconnect (unlike blocking).
    Useful for forcing a client to re-authenticate or reconnect.

    Args:
        ctx: MCP context
        mac: Client MAC address
        site: Site name

    Returns:
        Command result.
    """
    client = _get_client(ctx, device)
    result = await client.kick_client(mac, site)

    return {
        "success": result.get("meta", {}).get("rc") == "ok",
        "message": f"Client {mac} has been disconnected",
        "client_mac": mac,
        "action": "kicked",
    }


async def forget_client(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    """Remove a client from the known clients list.

    This removes the client's history and any saved notes/configuration.
    The client will appear as a new device if it reconnects.

    Args:
        ctx: MCP context
        mac: Client MAC address
        site: Site name

    Returns:
        Command result.
    """
    client = _get_client(ctx, device)
    result = await client.forget_client(mac, site)

    return {
        "success": result.get("meta", {}).get("rc") == "ok",
        "message": f"Client {mac} has been removed from known clients",
        "client_mac": mac,
        "action": "forgotten",
    }


async def get_client_traffic(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    """Get traffic statistics for a specific client.

    Includes Deep Packet Inspection (DPI) data if available.

    Args:
        ctx: MCP context
        mac: Client MAC address
        site: Site name

    Returns:
        Traffic statistics including bytes sent/received and
        application breakdown from DPI.
    """
    client = _get_client(ctx, device)

    # Get client details for basic traffic
    client_data = await client.get_client(mac, site)

    # Get DPI stats if available
    try:
        dpi_stats = await client.get_client_dpi_stats(mac, site)
    except Exception:
        dpi_stats = []

    return {
        "client_name": client_data.get("name") or client_data.get("hostname") or "Unknown",
        "mac": mac,
        "traffic": {
            "tx_bytes": client_data.get("tx_bytes", 0),
            "rx_bytes": client_data.get("rx_bytes", 0),
            "tx_packets": client_data.get("tx_packets", 0),
            "rx_packets": client_data.get("rx_packets", 0),
        },
        "dpi_applications": dpi_stats,
    }
