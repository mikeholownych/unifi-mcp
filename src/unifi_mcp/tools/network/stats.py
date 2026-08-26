"""Statistics and monitoring tools for UniFi Network."""

from typing import Any

from mcp.server.fastmcp import Context

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient, is_device_online, is_wireless_client


def _get_client(ctx: Context, device: str | None = None) -> UniFiNetworkClient:
    """Get the UniFi Network client from context, optionally targeting a device."""
    app_ctx: AppContext = ctx.request_context.lifespan_context
    return UniFiNetworkClient(app_ctx, device_name=device)


async def get_network_health(ctx: Context, site: str = "default") -> dict[str, Any]:
    """Get overall network health summary.

    Provides a quick overview of network status including device counts,
    client counts, and any active issues.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        Network health summary with device and client statistics.
    """
    client = _get_client(ctx)

    # Get health data
    health_data = await client.get_site_health(site)

    # Get device counts
    devices = await client.get_devices_basic(site)

    # Get client count
    clients = await client.get_clients(site)

    # Summarize device status
    device_counts = {
        "total": len(devices),
        "online": sum(1 for d in devices if is_device_online(d)),
        "offline": sum(1 for d in devices if not is_device_online(d)),
        "pending": sum(1 for d in devices if not d.get("adopted", True)),
    }

    # Summarize clients
    wireless_clients = sum(1 for c in clients if is_wireless_client(c))
    wired_clients = sum(1 for c in clients if not is_wireless_client(c))

    client_counts = {
        "total": len(clients),
        "wireless": wireless_clients,
        "wired": wired_clients,
    }

    # Extract WAN status
    wan_status = {}
    for subsystem in health_data:
        if subsystem.get("subsystem") == "wan":
            wan_status = {
                "status": subsystem.get("status", "unknown"),
                "wan_ip": subsystem.get("wan_ip"),
                "isp_name": subsystem.get("isp_name"),
                "latency": subsystem.get("latency"),
                "upload_speed": subsystem.get("xput_up"),
                "download_speed": subsystem.get("xput_down"),
            }
            break

    # Check for issues
    issues = []
    for subsystem in health_data:
        if subsystem.get("status") != "ok":
            issues.append({
                "subsystem": subsystem.get("subsystem"),
                "status": subsystem.get("status"),
            })

    return {
        "site": site,
        "overall_status": "healthy" if not issues else "issues_detected",
        "devices": device_counts,
        "clients": client_counts,
        "wan": wan_status,
        "issues": issues,
    }


async def get_recent_events(
    ctx: Context, limit: int = 50, site: str = "default", device: str | None = None
) -> list[dict[str, Any]]:
    """Get recent network events.

    Args:
        ctx: MCP context
        limit: Maximum number of events to return (max 3000)
        site: Site name

    Returns:
        List of recent events with timestamp, type, and details.
    """
    client = _get_client(ctx)
    events = await client.get_events(limit, site)

    result = []
    for event in events:
        result.append({
            "time": event.get("time", 0),
            "datetime": event.get("datetime", ""),
            "key": event.get("key", ""),
            "msg": event.get("msg", ""),
            "subsystem": event.get("subsystem", ""),
            "site_id": event.get("site_id", ""),
            "user": event.get("user"),
            "ap": event.get("ap"),
            "ap_name": event.get("ap_name"),
            "client": event.get("client"),
            "hostname": event.get("hostname"),
            "ssid": event.get("ssid"),
            "channel": event.get("channel"),
        })

    return result


async def get_alarms(ctx: Context, site: str = "default") -> list[dict[str, Any]]:
    """Get active alarms.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        List of active alarms with severity, type, and details.
    """
    client = _get_client(ctx)
    alarms = await client.get_alarms(site)

    result = []
    for alarm in alarms:
        result.append({
            "time": alarm.get("time", 0),
            "datetime": alarm.get("datetime", ""),
            "key": alarm.get("key", ""),
            "msg": alarm.get("msg", ""),
            "subsystem": alarm.get("subsystem", ""),
            "archived": alarm.get("archived", False),
            "device_mac": alarm.get("ap") or alarm.get("gw") or alarm.get("sw"),
            "device_name": alarm.get("ap_name") or alarm.get("gw_name") or alarm.get("sw_name"),
        })

    return result


async def archive_all_alarms(ctx: Context, site: str = "default") -> dict[str, Any]:
    """Archive all active alarms.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        Command result.
    """
    client = _get_client(ctx)
    result = await client.archive_alarms(site)

    return {
        "success": result.get("meta", {}).get("rc") == "ok",
        "message": "All alarms have been archived",
    }


async def run_speed_test(ctx: Context, site: str = "default") -> dict[str, Any]:
    """Initiate a WAN speed test.

    Starts a speed test on the gateway device. Results can be retrieved
    using get_speed_test_status after the test completes.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        Speed test initiation result.
    """
    client = _get_client(ctx)
    result = await client.run_speed_test(site)

    return {
        "success": result.get("meta", {}).get("rc") == "ok",
        "message": "Speed test initiated. Use get_speed_test_status to check results.",
    }


async def get_speed_test_status(ctx: Context, site: str = "default") -> dict[str, Any]:
    """Get speed test status and results.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        Speed test status and results including upload/download speeds.
    """
    client = _get_client(ctx)
    result = await client.get_speed_test_status(site)

    data = result.get("data", [{}])[0] if result.get("data") else {}

    return {
        "status": data.get("status_summary", "unknown"),
        "server": {
            "host": data.get("server", {}).get("host"),
            "city": data.get("server", {}).get("city"),
            "country": data.get("server", {}).get("country"),
            "provider": data.get("server", {}).get("provider"),
        },
        "results": {
            "download_mbps": data.get("xput_download"),
            "upload_mbps": data.get("xput_upload"),
            "latency_ms": data.get("latency"),
        },
        "last_run": data.get("rundate"),
    }


async def get_dpi_stats(ctx: Context, site: str = "default") -> dict[str, Any]:
    """Get Deep Packet Inspection statistics for the site.

    Shows traffic breakdown by application category and specific applications.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        DPI statistics with application breakdown.
    """
    client = _get_client(ctx)
    dpi_data = await client.get_dpi_stats(site)

    # Organize by category
    categories = {}
    applications = []

    for item in dpi_data:
        cat_name = item.get("cat_name", "Unknown")
        app_name = item.get("app_name", "Unknown")

        if cat_name not in categories:
            categories[cat_name] = {
                "tx_bytes": 0,
                "rx_bytes": 0,
                "apps": [],
            }

        categories[cat_name]["tx_bytes"] += item.get("tx_bytes", 0)
        categories[cat_name]["rx_bytes"] += item.get("rx_bytes", 0)
        categories[cat_name]["apps"].append(app_name)

        applications.append({
            "category": cat_name,
            "application": app_name,
            "tx_bytes": item.get("tx_bytes", 0),
            "rx_bytes": item.get("rx_bytes", 0),
        })

    # Sort by total bytes
    sorted_apps = sorted(
        applications,
        key=lambda x: x["tx_bytes"] + x["rx_bytes"],
        reverse=True
    )

    return {
        "site": site,
        "categories": categories,
        "top_applications": sorted_apps[:20],  # Top 20 apps
    }


async def get_traffic_summary(ctx: Context, site: str = "default") -> dict[str, Any]:
    """Get traffic summary for the site.

    Provides aggregate traffic statistics from all devices and clients.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        Traffic summary with total bytes and per-device breakdown.
    """
    client = _get_client(ctx)

    # Get device traffic
    devices = await client.get_devices(site)

    total_tx = 0
    total_rx = 0
    device_traffic = []

    for device in devices:
        tx = device.get("tx_bytes", 0)
        rx = device.get("rx_bytes", 0)
        total_tx += tx
        total_rx += rx

        if tx > 0 or rx > 0:
            device_traffic.append({
                "name": device.get("name", "Unknown"),
                "mac": device.get("mac", ""),
                "type": device.get("type", ""),
                "tx_bytes": tx,
                "rx_bytes": rx,
                "clients": device.get("num_sta", 0),
            })

    # Sort by total traffic
    device_traffic.sort(key=lambda x: x["tx_bytes"] + x["rx_bytes"], reverse=True)

    return {
        "site": site,
        "total": {
            "tx_bytes": total_tx,
            "rx_bytes": total_rx,
        },
        "by_device": device_traffic,
    }
