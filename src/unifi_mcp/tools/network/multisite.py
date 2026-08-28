"""Multi-site orchestration tools for UniFi Network.

Aggregate operations across all configured UniFi devices/controllers.
"""

from typing import Any

from mcp.server.mcpserver import Context

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient


def _get_client(ctx: Context, device: str | None = None) -> UniFiNetworkClient:
    """Get the UniFi Network client from context."""
    app_ctx: AppContext = ctx.request_context.lifespan_context
    return UniFiNetworkClient(app_ctx, device_name=device)


def _get_all_network_devices(ctx: Context) -> list[tuple[str, str]]:
    """Return list of (device_name, site) for all network-enabled devices."""
    app_ctx: AppContext = ctx.request_context.lifespan_context
    return [(d.name, d.site or "default") for d in app_ctx.settings.get_network_devices()]


async def get_global_inventory(ctx: Context) -> dict[str, Any]:
    """Get a unified inventory of all devices across all configured controllers.

    Aggregates list_devices from every network-enabled UniFi device into
    a single view. Useful for seeing the full picture across gateways,
    sites, or locations.

    Returns:
        Combined device list with source device name for each entry.
    """
    all_devices: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for device_name, site in _get_all_network_devices(ctx):
        try:
            client = _get_client(ctx, device_name)
            devices = await client.get_devices(site)
            for d in devices:
                d["_source_device"] = device_name
            all_devices.extend(devices)
        except Exception as e:
            errors.append({"device": device_name, "error": str(e)})

    return {
        "total_devices": len(all_devices),
        "devices": all_devices,
        "errors": errors if errors else None,
    }


async def get_global_health(ctx: Context) -> dict[str, Any]:
    """Get health summary across all configured controllers.

    Collects site health from every network-enabled device and produces
    a unified health report with per-device breakdowns.

    Returns:
        Aggregated health data across all devices.
    """
    device_health: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for device_name, site in _get_all_network_devices(ctx):
        try:
            client = _get_client(ctx, device_name)
            health = await client.get_site_health(site)
            subsystems = {}
            for sub in health:
                name = sub.get("subsystem", "unknown")
                subsystems[name] = {
                    "status": sub.get("status"),
                    "health": sub.get("health"),
                    "users": sub.get("num_user"),
                    "ap": sub.get("num_ap"),
                    "switch": sub.get("num_sw"),
                    "gateway": sub.get("num_gateway"),
                }
            device_health.append(
                {
                    "device": device_name,
                    "site": site,
                    "subsystems": subsystems,
                }
            )
        except Exception as e:
            errors.append({"device": device_name, "error": str(e)})

    # Determine overall status
    all_ok = all(
        all(s.get("status") == "ok" for s in dh["subsystems"].values())
        for dh in device_health
        if dh["subsystems"]
    )

    return {
        "overall_status": "healthy" if all_ok else "degraded",
        "device_count": len(device_health),
        "devices": device_health,
        "errors": errors if errors else None,
    }


async def get_global_client_summary(ctx: Context) -> dict[str, Any]:
    """Get a summary of all connected clients across all controllers.

    Aggregates client counts, lists top talkers, and identifies
    potentially problematic clients across the entire infrastructure.

    Returns:
        Unified client summary with per-device breakdowns.
    """
    all_clients: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for device_name, site in _get_all_network_devices(ctx):
        try:
            client = _get_client(ctx, device_name)
            clients = await client.get_active_clients(site)
            for c in clients:
                c["_source_device"] = device_name
            all_clients.extend(clients)
        except Exception as e:
            errors.append({"device": device_name, "error": str(e)})

    # Aggregate stats
    total = len(all_clients)
    wireless = sum(1 for c in all_clients if c.get("is_wired") is False)
    wired = total - wireless
    blocked = sum(1 for c in all_clients if c.get("blocked"))

    # Top talkers by usage
    def _bytes(c: dict) -> int:
        return (c.get("rx_bytes") or 0) + (c.get("tx_bytes") or 0)

    top_talkers = sorted(all_clients, key=_bytes, reverse=True)[:10]

    return {
        "total_clients": total,
        "wireless": wireless,
        "wired": wired,
        "blocked": blocked,
        "top_talkers": [
            {
                "hostname": c.get("hostname") or c.get("name") or "unknown",
                "mac": c.get("mac"),
                "ip": c.get("ip"),
                "usage_mb": round(_bytes(c) / 1_048_576, 1),
                "source_device": c.get("_source_device"),
            }
            for c in top_talkers
        ],
        "per_device": {
            dn: sum(1 for c in all_clients if c.get("_source_device") == dn)
            for dn in {c.get("_source_device") for c in all_clients}
        },
        "errors": errors if errors else None,
    }
