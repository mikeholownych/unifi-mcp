"""UniFi MCP Server - Main entry point."""

import logging
import sys
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from unifi_mcp.clients.base import create_app_lifespan
from unifi_mcp.config import settings
from unifi_mcp.tools import runtime as runtime_tools
from unifi_mcp.tools import system as system_tools
from unifi_mcp.tools.network import clients as client_tools
from unifi_mcp.tools.network import devices as device_tools
from unifi_mcp.tools.network import insights as insight_tools
from unifi_mcp.tools.network import multisite as multisite_tools
from unifi_mcp.tools.network import sites as site_tools
from unifi_mcp.tools.network import stats as stat_tools
from unifi_mcp.tools.protect import cameras as protect_tools
from unifi_mcp.version import get_version

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# Create the MCP server with lifespan management
mcp = MCPServer(
    name="UniFi MCP Server",
    version=get_version(),
    instructions="""
    Manage and analyze UniFi network and Protect infrastructure.

    This server provides tools for:
    - Device management (APs, switches, routers)
    - Client management (connected devices)
    - Site and network configuration
    - Network statistics and monitoring
    - AI-powered network analysis and troubleshooting
    - UniFi Protect camera management and snapshots
    - Multi-site orchestration (global inventory, health, client summary)

    Supports multiple UniFi devices. Use list_unifi_devices to see configured devices.
    Use the 'device' parameter to target specific devices when you have multiple.
    Use get_global_health / get_global_inventory for cross-device aggregation.

    Use the insight tools (analyze_network_issues, get_optimization_recommendations, etc.)
    for comprehensive network analysis and recommendations.
    """,
    lifespan=create_app_lifespan,
)

# =============================================================================
# System Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_server_health(ctx: Context) -> system_tools.ServerHealth:
    """Get redaction-safe UniFi MCP runtime health and service counts."""
    return await system_tools.build_server_health(ctx.request_context.lifespan_context)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_runtime_events(ctx: Context, limit: int = 100):
    """List normalized events retained by the optional runtime store."""
    return await runtime_tools.list_runtime_events(ctx, limit)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_event_polling_status(ctx: Context):
    """List event source capabilities and background polling state."""
    return await runtime_tools.get_event_polling_status(ctx)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def poll_events_now(ctx: Context, source: str | None = None, device_name: str | None = None):
    """Poll supported event sources now and durably deduplicate results."""
    return await runtime_tools.poll_events_now(ctx, source, device_name)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_schedules(ctx: Context):
    """List allowlisted interval schedules."""
    return await runtime_tools.list_schedules(ctx)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def create_interval_schedule(
    ctx: Context,
    name: str,
    job_name: str,
    interval_seconds: int,
    arguments: dict[str, Any] | None = None,
    confirm: bool = False,
):
    """Create an allowlisted recurring job. Requires confirm=true."""
    return await runtime_tools.create_interval_schedule(
        ctx, name, job_name, interval_seconds, arguments, confirm
    )


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def set_schedule_enabled(
    ctx: Context, schedule_id: str, enabled: bool, confirm: bool = False
):
    """Enable or pause a schedule. Requires confirm=true."""
    return await runtime_tools.set_schedule_enabled(ctx, schedule_id, enabled, confirm)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_schedule(ctx: Context, schedule_id: str, confirm: bool = False):
    """Delete a non-running schedule. Requires confirm=true."""
    return await runtime_tools.delete_schedule(ctx, schedule_id, confirm)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def run_schedule_now(ctx: Context, schedule_id: str, confirm: bool = False):
    """Run one allowlisted schedule immediately. Requires confirm=true."""
    return await runtime_tools.run_schedule_now(ctx, schedule_id, confirm)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_job_runs(ctx: Context, limit: int = 100):
    """List redacted background job run outcomes."""
    return await runtime_tools.list_job_runs(ctx, limit)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_webhook_destinations(ctx: Context):
    """List webhook destinations without secret values."""
    return await runtime_tools.list_webhook_destinations(ctx)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def create_webhook_destination(
    ctx: Context,
    name: str,
    url: str,
    secret_env_name: str | None = None,
    categories: list[str] | None = None,
    confirm: bool = False,
):
    """Create a filtered outbound webhook. Requires confirm=true."""
    return await runtime_tools.create_webhook_destination(
        ctx, name, url, secret_env_name, categories, confirm
    )


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def set_webhook_destination_enabled(
    ctx: Context, destination_id: str, enabled: bool, confirm: bool = False
):
    """Enable or pause a webhook destination. Requires confirm=true."""
    return await runtime_tools.set_webhook_destination_enabled(
        ctx, destination_id, enabled, confirm
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_webhook_destination(ctx: Context, destination_id: str, confirm: bool = False):
    """Delete a webhook destination and queued deliveries. Requires confirm=true."""
    return await runtime_tools.delete_webhook_destination(ctx, destination_id, confirm)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def test_webhook_destination(ctx: Context, destination_id: str, confirm: bool = False):
    """Send a synthetic payload to a webhook destination. Requires confirm=true."""
    return await runtime_tools.test_webhook_destination(ctx, destination_id, confirm)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_webhook_deliveries(ctx: Context, limit: int = 100):
    """List redacted webhook delivery and dead-letter state."""
    return await runtime_tools.list_webhook_deliveries(ctx, limit)


# =============================================================================
# Device Management Tools
# =============================================================================


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def list_devices(ctx: Context, site: str = "default", device: str | None = None):
    """List all UniFi network devices (APs, switches, routers)."""
    return await device_tools.list_devices(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_device_details(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
):
    """Get detailed information about a specific device."""
    return await device_tools.get_device_details(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def restart_device(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Restart a UniFi device."""
    return await device_tools.restart_device(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def locate_device(
    ctx: Context, mac: str, enabled: bool = True, site: str = "default", device: str | None = None
):
    """Enable/disable LED blinking to locate a device."""
    return await device_tools.locate_device(ctx, mac, enabled, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_device_stats(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
):
    """Get performance statistics for a device."""
    return await device_tools.get_device_stats(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def upgrade_device(ctx: Context, mac: str, site: str = "default", device: str | None = None):
    """Upgrade device firmware to the latest version."""
    return await device_tools.upgrade_device(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def provision_device(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
):
    """Force re-provision a device with current configuration."""
    return await device_tools.provision_device(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_device_ports(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
):
    """List the switch/gateway ports on a device (index, name, link, speed, VLAN)."""
    return await device_tools.get_device_ports(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
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
):
    """Configure a single switch port: native VLAN, PoE mode, name, or enable state."""
    return await device_tools.set_device_port(
        ctx,
        mac,
        port_idx,
        name,
        native_network,
        poe_mode,
        forward,
        enabled,
        site,
        device,
        confirm,
    )


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
async def get_client_details(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
):
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
async def get_client_traffic(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
):
    """Get traffic statistics for a specific client."""
    return await client_tools.get_client_traffic(ctx, mac, site, device)


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def reserve_client_ip(
    ctx: Context,
    client: str,
    ip: str | None = None,
    site: str = "default",
    device: str | None = None,
):
    """Reserve a device's current IP (or a specific one) via DHCP reservation."""
    return await client_tools.reserve_client_ip(ctx, client, ip, site, device)


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


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def create_network(
    ctx: Context,
    name: str,
    subnet: str | None = None,
    vlan: int | None = None,
    purpose: str = "corporate",
    domain_name: str | None = None,
    dhcp_start: str | None = None,
    dhcp_stop: str | None = None,
    dhcp_lease_time: int | None = None,
    site: str = "default",
    device: str | None = None,
    confirm: bool = False,
):
    """Create a new network/VLAN (corporate by default)."""
    return await site_tools.create_network(
        ctx,
        name,
        subnet,
        vlan,
        purpose,
        domain_name,
        dhcp_start,
        dhcp_stop,
        dhcp_lease_time,
        site,
        device,
        confirm,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def update_network(
    ctx: Context,
    name: str,
    name_new: str | None = None,
    subnet: str | None = None,
    vlan: int | None = None,
    domain_name: str | None = None,
    dhcp_start: str | None = None,
    dhcp_stop: str | None = None,
    dhcp_lease_time: int | None = None,
    enabled: bool | None = None,
    site: str = "default",
    device: str | None = None,
    confirm: bool = False,
):
    """Update a network/VLAN by name or ID - only provided fields change."""
    return await site_tools.update_network(
        ctx,
        name,
        name_new,
        subnet,
        vlan,
        domain_name,
        dhcp_start,
        dhcp_stop,
        dhcp_lease_time,
        enabled,
        site,
        device,
        confirm,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_network(
    ctx: Context,
    name: str,
    site: str = "default",
    device: str | None = None,
    confirm: bool = False,
):
    """Delete a network/VLAN by name or ID. Requires confirm=true."""
    return await site_tools.delete_network(ctx, name, site, device, confirm)


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


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def update_wlan(
    ctx: Context,
    wlan: str,
    enabled: bool | None = None,
    hide_ssid: bool | None = None,
    passphrase: str | None = None,
    wpa3_support: bool | None = None,
    wpa3_transition: bool | None = None,
    pmf_mode: str | None = None,
    bss_transition: bool | None = None,
    fast_roaming_enabled: bool | None = None,
    site: str = "default",
    device: str | None = None,
):
    """Update a wireless network (SSID) by ID or name - only provided fields change."""
    return await site_tools.update_wlan(
        ctx,
        wlan,
        enabled,
        hide_ssid,
        passphrase,
        wpa3_support,
        wpa3_transition,
        pmf_mode,
        bss_transition,
        fast_roaming_enabled,
        site,
        device,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def create_wlan(
    ctx: Context,
    name: str,
    passphrase: str,
    network_conf_id: str | None = None,
    wpa3_transition: bool = True,
    hide_ssid: bool = False,
    is_guest: bool = False,
    site: str = "default",
    device: str | None = None,
):
    """Create a wireless network (SSID) with WPA2/WPA3 transition security."""
    return await site_tools.create_wlan(
        ctx,
        name,
        passphrase,
        network_conf_id,
        wpa3_transition,
        hide_ssid,
        is_guest,
        site,
        device,
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_wlan(
    ctx: Context, wlan: str, confirm: bool = False, site: str = "default", device: str | None = None
):
    """Delete a wireless network (SSID). Requires confirm=true."""
    return await site_tools.delete_wlan(ctx, wlan, confirm, site, device)


@mcp.tool()
async def create_firewall_policy(
    ctx: Context,
    name: str,
    action: str,
    src_zone_id: str,
    dst_zone_id: str,
    protocol: str = "all",
    description: str | None = None,
    client_macs: list[str] | None = None,
    index: int | None = None,
    enabled: bool = True,
    site: str = "default",
    device: str | None = None,
):
    """Create a zone-based firewall policy (UniFi Network 9+)."""
    return await site_tools.create_firewall_policy(
        ctx,
        name,
        action,
        src_zone_id,
        dst_zone_id,
        protocol,
        description,
        client_macs,
        index,
        enabled,
        site,
        device,
    )


@mcp.tool(annotations=ToolAnnotations(idempotent_hint=True))
async def set_firewall_policy_enabled(
    ctx: Context, policy_id: str, enabled: bool, site: str = "default", device: str | None = None
):
    """Enable or disable a zone-based firewall policy."""
    return await site_tools.set_firewall_policy_enabled(ctx, policy_id, enabled, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_firewall_policy(
    ctx: Context,
    policy_id: str,
    confirm: bool = False,
    site: str = "default",
    device: str | None = None,
):
    """Delete a zone-based firewall policy. Requires confirm=true."""
    return await site_tools.delete_firewall_policy(ctx, policy_id, confirm, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_port_forwards(ctx: Context, site: str = "default", device: str | None = None):
    """Get all port forwarding rules (external port+protocol → internal IP+port)."""
    return await site_tools.get_port_forwards(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def create_port_forward(
    ctx: Context,
    name: str,
    dst_port: str,
    fwd_ip: str,
    fwd_port: str,
    proto: str = "tcp_udp",
    enabled: bool = True,
    site: str = "default",
    device: str | None = None,
):
    """Create a port forwarding rule on the gateway."""
    return await site_tools.create_port_forward(
        ctx, name, dst_port, fwd_ip, fwd_port, proto, enabled, site, device
    )


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
async def delete_port_forward(
    ctx: Context,
    rule_id: str,
    confirm: bool = False,
    site: str = "default",
    device: str | None = None,
):
    """Delete a port forwarding rule. Requires confirm=true."""
    return await site_tools.delete_port_forward(ctx, rule_id, confirm, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_all_sites_health(ctx: Context, device: str | None = None):
    """Get health overview across all sites."""
    return await insight_tools.get_all_sites_health(ctx, device)


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
async def get_recent_events(
    ctx: Context, limit: int = 50, site: str = "default", device: str | None = None
):
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
async def get_optimization_recommendations(
    ctx: Context, site: str = "default", device: str | None = None
):
    """
    Analyze network configuration and provide optimization recommendations.

    Checks channel selection, TX power, VLAN efficiency, port configurations,
    and bandwidth utilization patterns.
    """
    return await insight_tools.get_optimization_recommendations(ctx, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_client_experience_report(
    ctx: Context, site: str = "default", device: str | None = None
):
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
async def get_traffic_analysis(
    ctx: Context, hours: int = 24, site: str = "default", device: str | None = None
):
    """
    Analyze traffic patterns over the specified time period.

    Includes top talkers, application breakdown (DPI), bandwidth trends,
    and unusual activity.
    """
    return await insight_tools.get_traffic_analysis(ctx, hours, site, device)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def troubleshoot_client(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
):
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


# ---------------------------------------------------------------------------
# Multi-site orchestration tools
# ---------------------------------------------------------------------------


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_global_inventory(ctx: Context) -> dict:
    """
    Get a unified inventory of all devices across all configured controllers.

    Aggregates list_devices from every network-enabled UniFi device.
    Use this to see the full picture across gateways, sites, or locations.
    """
    return await multisite_tools.get_global_inventory(ctx)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_global_health(ctx: Context) -> dict:
    """
    Get health summary across all configured controllers.

    Collects site health from every network-enabled device and produces
    a unified health report with per-device breakdowns.
    """
    return await multisite_tools.get_global_health(ctx)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def get_global_client_summary(ctx: Context) -> dict:
    """
    Get a summary of all connected clients across all controllers.

    Aggregates client counts, top talkers, and blocked clients
    across the entire infrastructure.
    """
    return await multisite_tools.get_global_client_summary(ctx)


def main():
    """Run the MCP server."""
    logger.info("Starting UniFi MCP Server")
    device_count = len(settings.devices)
    if device_count > 0:
        logger.info(f"Configured devices: {settings.get_device_names()}")
    else:
        logger.warning("No devices configured!")
    mcp.run()


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
async def export_camera_clip(
    ctx: Context,
    camera: str,
    start_ts: int,
    end_ts: int,
    output_path: str,
    device: str | None = None,
):
    """Export a camera recording clip (MP4) to a local file. Requires Protect credentials."""
    return await protect_tools.export_camera_clip(
        ctx, camera, start_ts, end_ts, output_path, device
    )


if __name__ == "__main__":
    main()
