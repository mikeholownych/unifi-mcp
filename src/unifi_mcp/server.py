"""UniFi MCP Server - Main entry point."""

import logging
import sys

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from unifi_mcp.clients.base import create_app_lifespan
from unifi_mcp.config import settings
from unifi_mcp.tools.network import clients as client_tools
from unifi_mcp.tools.network import devices as device_tools
from unifi_mcp.tools.network import insights as insight_tools
from unifi_mcp.tools.network import sites as site_tools
from unifi_mcp.tools.network import stats as stat_tools
from unifi_mcp.tools.protect import cameras as protect_tools

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# Create the MCP server with lifespan management
mcp = FastMCP(
    name="UniFi MCP Server",
    instructions="""
    Manage and analyze UniFi network and Protect infrastructure.

    This server provides tools for:
    - Device management (APs, switches, routers)
    - Client management (connected devices)
    - Site and network configuration
    - Network statistics and monitoring
    - AI-powered network analysis and troubleshooting
    - UniFi Protect camera management and snapshots

    Supports multiple UniFi devices. Use list_unifi_devices to see configured devices.
    Use the 'device' parameter to target specific devices when you have multiple.

    Use the insight tools (analyze_network_issues, get_optimization_recommendations, etc.)
    for comprehensive network analysis and recommendations.
    """,
    lifespan=create_app_lifespan,
)

# =============================================================================
# Device Management Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_devices(ctx: Context, site: str = "default", device: str | None = None):
    """List all UniFi network devices (APs, switches, routers)."""
    return await device_tools.list_devices(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_device_details(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Get detailed information about a specific device."""
    return await device_tools.get_device_details(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def restart_device(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Restart a UniFi device."""
    return await device_tools.restart_device(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def locate_device(ctx: Context, mac: str, enabled: bool = True, site: str = "default", device: str | None = None):
    """Enable/disable LED blinking to locate a device."""
    return await device_tools.locate_device(ctx, mac, enabled, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_device_stats(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Get performance statistics for a device."""
    return await device_tools.get_device_stats(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def upgrade_device(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Upgrade device firmware to the latest version."""
    return await device_tools.upgrade_device(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def provision_device(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Force re-provision a device with current configuration."""
    return await device_tools.provision_device(ctx, mac, site, device)


# =============================================================================
# Client Management Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_clients(ctx: Context, site: str = "default", device: str | None = None):
    """List all currently connected clients."""
    return await client_tools.list_clients(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_all_clients(ctx: Context, site: str = "default", device: str | None = None):
    """List all known clients (including offline)."""
    return await client_tools.list_all_clients(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_client_details(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Get detailed information about a specific client."""
    return await client_tools.get_client_details(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def block_client(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Block a client from the network."""
    return await client_tools.block_client(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def unblock_client(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Unblock a previously blocked client."""
    return await client_tools.unblock_client(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def kick_client(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Disconnect a client (they can reconnect)."""
    return await client_tools.kick_client(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def forget_client(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Remove a client from the known clients list."""
    return await client_tools.forget_client(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_client_traffic(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Get traffic statistics for a specific client."""
    return await client_tools.get_client_traffic(ctx, mac, site, device)


# =============================================================================
# Site Management Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_sites(ctx: Context, device: str | None = None):
    """List all UniFi sites accessible to the current user."""
    return await site_tools.list_sites(ctx, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_site_health(ctx: Context, site: str = "default", device: str | None = None):
    """Get comprehensive health status for a site."""
    return await site_tools.get_site_health(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_site_settings(ctx: Context, site: str = "default", device: str | None = None):
    """Get site configuration settings."""
    return await site_tools.get_site_settings(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_sysinfo(ctx: Context, site: str = "default", device: str | None = None):
    """Get system information for the site controller."""
    return await site_tools.get_sysinfo(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_networks(ctx: Context, site: str = "default", device: str | None = None):
    """Get all network/VLAN configurations."""
    return await site_tools.get_networks(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_wlans(ctx: Context, site: str = "default", device: str | None = None):
    """Get all wireless network (SSID) configurations."""
    return await site_tools.get_wlans(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_port_profiles(ctx: Context, site: str = "default", device: str | None = None):
    """Get switch port profile configurations."""
    return await site_tools.get_port_profiles(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_firewall_rules(ctx: Context, site: str = "default", device: str | None = None):
    """Get firewall rule configurations."""
    return await site_tools.get_firewall_rules(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_firewall_policies(ctx: Context, site: str = "default", device: str | None = None):
    """Get zone-based firewall policies (UniFi Network 9+)."""
    return await site_tools.get_firewall_policies(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_routing_table(ctx: Context, site: str = "default", device: str | None = None):
    """Get the current routing table."""
    return await site_tools.get_routing_table(ctx, site, device)


# =============================================================================
# Statistics & Monitoring Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_network_health(ctx: Context, site: str = "default", device: str | None = None):
    """Get overall network health summary."""
    return await stat_tools.get_network_health(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_recent_events(ctx: Context, limit: int = 50, site: str = "default", device: str | None = None):
    """Get recent network events."""
    return await stat_tools.get_recent_events(ctx, limit, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_alarms(ctx: Context, site: str = "default", device: str | None = None):
    """Get active alarms."""
    return await stat_tools.get_alarms(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def archive_all_alarms(ctx: Context, site: str = "default", device: str | None = None):
    """Archive all active alarms."""
    return await stat_tools.archive_all_alarms(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def run_speed_test(ctx: Context, site: str = "default", device: str | None = None):
    """Initiate a WAN speed test."""
    return await stat_tools.run_speed_test(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_speed_test_status(ctx: Context, site: str = "default", device: str | None = None):
    """Get speed test status and results."""
    return await stat_tools.get_speed_test_status(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_dpi_stats(ctx: Context, site: str = "default", device: str | None = None):
    """Get Deep Packet Inspection statistics for the site."""
    return await stat_tools.get_dpi_stats(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_traffic_summary(ctx: Context, site: str = "default", device: str | None = None):
    """Get traffic summary for the site."""
    return await stat_tools.get_traffic_summary(ctx, site, device)


# =============================================================================
# AI Insight Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def analyze_network_issues(ctx: Context, site: str = "default", device: str | None = None):
    """
    Analyze the network for potential issues and return a structured report.

    Aggregates device health, client connection issues, interference,
    firmware status, and recent alarms into an AI-friendly summary.
    """
    return await insight_tools.analyze_network_issues(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_optimization_recommendations(ctx: Context, site: str = "default", device: str | None = None):
    """
    Analyze network configuration and provide optimization recommendations.

    Checks channel selection, TX power, VLAN efficiency, port configurations,
    and bandwidth utilization patterns.
    """
    return await insight_tools.get_optimization_recommendations(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_client_experience_report(ctx: Context, site: str = "default", device: str | None = None):
    """
    Generate a client experience report with connection quality metrics.

    Includes signal strength distribution, roaming stats, failed connections,
    and problematic clients.
    """
    return await insight_tools.get_client_experience_report(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_device_health_summary(ctx: Context, site: str = "default", device: str | None = None):
    """
    Summarize device health across all APs, switches, and routers.

    Includes uptime, load, memory, temperature, firmware versions,
    and devices needing attention.
    """
    return await insight_tools.get_device_health_summary(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_traffic_analysis(ctx: Context, hours: int = 24, site: str = "default", device: str | None = None):
    """
    Analyze traffic patterns over the specified time period.

    Includes top talkers, application breakdown (DPI), bandwidth trends,
    and unusual activity.
    """
    return await insight_tools.get_traffic_analysis(ctx, hours, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def troubleshoot_client(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """
    Deep-dive troubleshooting for a specific client.

    Includes connection history, signal quality, AP associations,
    roaming events, and potential issues.
    """
    return await insight_tools.troubleshoot_client(ctx, mac, site, device)


# =============================================================================
# UniFi Protect Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_cameras(ctx: Context, device: str | None = None):
    """List all UniFi Protect cameras with status."""
    return await protect_tools.list_cameras(ctx, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_camera_details(ctx: Context, camera_id: str, device: str | None = None):
    """Get detailed information about a specific camera."""
    return await protect_tools.get_camera_details(ctx, camera_id, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_camera_snapshot(
    ctx: Context,
    camera_id: str,
    device: str | None = None,
    width: int | None = None,
    height: int | None = None,
):
    """
    Get a snapshot from a camera.

    Returns a base64-encoded JPEG image.
    """
    return await protect_tools.get_camera_snapshot(ctx, camera_id, device, width, height)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_protect_system_info(ctx: Context, device: str | None = None):
    """Get UniFi Protect system information including camera and accessory counts."""
    return await protect_tools.get_protect_system_info(ctx, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_camera_health_summary(ctx: Context, device: str | None = None):
    """
    Get a health summary of all cameras.

    Provides an overview of camera status, connectivity, and potential issues.
    """
    return await protect_tools.get_camera_health_summary(ctx, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_liveviews(ctx: Context, device: str | None = None):
    """Get all configured Protect liveviews."""
    return await protect_tools.get_liveviews(ctx, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_protect_accessories(ctx: Context, device: str | None = None):
    """Get all Protect accessories (lights, sensors, chimes, viewers)."""
    return await protect_tools.get_protect_accessories(ctx, device)


# =============================================================================
# UniFi Protect Event Tools (require username/password)
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_motion_events(
    ctx: Context,
    hours: int = 24,
    limit: int = 50,
    camera_id: str | None = None,
    device: str | None = None,
):
    """
    Get recent motion events from cameras.

    Requires username and password configured for the Protect device.
    """
    return await protect_tools.get_motion_events(ctx, hours, limit, camera_id, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_smart_detections(
    ctx: Context,
    hours: int = 24,
    limit: int = 50,
    detection_type: str | None = None,
    device: str | None = None,
):
    """
    Get smart detection events (person, vehicle, animal, package).

    Requires username and password configured for the Protect device.
    """
    return await protect_tools.get_smart_detections(ctx, hours, limit, detection_type, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_protect_event_summary(ctx: Context, hours: int = 24, device: str | None = None):
    """
    Get a summary of all Protect events for the time period.

    Shows motion count, smart detections breakdown, and doorbell activity.
    Requires username and password configured for the Protect device.
    """
    return await protect_tools.get_event_summary(ctx, hours, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_recent_protect_activity(ctx: Context, limit: int = 20, device: str | None = None):
    """
    Get recent activity across all cameras.

    Provides a quick overview of the most recent events.
    Requires username and password configured for the Protect device.
    """
    return await protect_tools.get_recent_activity(ctx, limit, device)


# =============================================================================
# Multi-Device Management Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_unifi_devices(ctx: Context):
    """
    List all configured UniFi devices.

    Shows device names, URLs, and available services (network, protect).
    Use the device name with other tools to target specific devices.
    """
    devices = settings.devices
    return {
        "total_devices": len(devices),
        "devices": [
            {
                "name": d.name,
                "url": d.url,
                "services": d.services,
                "site": d.site,
            }
            for d in devices
        ],
        "network_devices": [d.name for d in settings.get_network_devices()],
        "protect_devices": [d.name for d in settings.get_protect_devices()],
    }


def main():
    """Run the MCP server."""
    logger.info("Starting UniFi MCP Server")
    device_count = len(settings.devices)
    if device_count > 0:
        logger.info(f"Configured devices: {settings.get_device_names()}")
    else:
        logger.warning("No devices configured!")
    mcp.run()


if __name__ == "__main__":
    main()
