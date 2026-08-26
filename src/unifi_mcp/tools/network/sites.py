"""Site management tools for UniFi Network."""

from typing import Any

from mcp.server.fastmcp import Context

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient


def _get_client(ctx: Context, device: str | None = None) -> UniFiNetworkClient:
    """Get the UniFi Network client from context, optionally targeting a device."""
    app_ctx: AppContext = ctx.request_context.lifespan_context
    return UniFiNetworkClient(app_ctx, device_name=device)


async def list_sites(ctx: Context, device: str | None = None) -> list[dict[str, Any]]:
    """List all UniFi sites accessible to the current user.

    Returns:
        List of sites with name, description, and role information.
    """
    client = _get_client(ctx, device)
    sites = await client.get_sites()

    result = []
    for site in sites:
        result.append({
            "name": site.get("name", ""),
            "desc": site.get("desc", ""),
            "role": site.get("role", ""),
            "role_hotspot": site.get("role_hotspot", False),
            "attr_hidden_id": site.get("attr_hidden_id", ""),
            "attr_no_delete": site.get("attr_no_delete", False),
        })

    return result


async def get_site_health(ctx: Context, site: str = "default", device: str | None = None) -> dict[str, Any]:
    """Get comprehensive health status for a site.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        Health status broken down by subsystem (WAN, LAN, WLAN)
        including connectivity, speed, and issues.
    """
    client = _get_client(ctx, device)
    health_data = await client.get_site_health(site)

    # Organize by subsystem
    health = {}
    issues = []

    for subsystem in health_data:
        name = subsystem.get("subsystem", "unknown")
        status = subsystem.get("status", "unknown")

        health[name] = {
            "status": status,
            "num_adopted": subsystem.get("num_adopted"),
            "num_pending": subsystem.get("num_pending"),
            "num_disabled": subsystem.get("num_disabled"),
            "num_disconnected": subsystem.get("num_disconnected"),
            "num_sta": subsystem.get("num_sta"),
            "num_user": subsystem.get("num_user"),
            "num_guest": subsystem.get("num_guest"),
        }

        # WAN specific
        if name == "wan":
            health[name].update({
                "wan_ip": subsystem.get("wan_ip"),
                "gateways": subsystem.get("gateways", []),
                "nameservers": subsystem.get("nameservers", []),
                "isp_name": subsystem.get("isp_name"),
                "isp_organization": subsystem.get("isp_organization"),
                "tx_bytes-r": subsystem.get("tx_bytes-r"),
                "rx_bytes-r": subsystem.get("rx_bytes-r"),
                "speedtest_lastrun": subsystem.get("speedtest_lastrun"),
                "speedtest_status": subsystem.get("speedtest_status"),
                "xput_up": subsystem.get("xput_up"),
                "xput_down": subsystem.get("xput_down"),
                "latency": subsystem.get("latency"),
            })

        # Collect issues
        if status != "ok":
            issues.append({
                "subsystem": name,
                "status": status,
            })

    return {
        "site": site,
        "overall_status": "healthy" if not issues else "issues_detected",
        "subsystems": health,
        "issues": issues,
    }


async def get_site_settings(ctx: Context, site: str = "default", device: str | None = None) -> dict[str, Any]:
    """Get site configuration settings.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        Site settings organized by category.
    """
    client = _get_client(ctx, device)
    settings = await client.get_site_settings(site)

    # Organize settings by key
    organized = {}
    for setting in settings:
        key = setting.get("key", "unknown")
        organized[key] = setting

    return {
        "site": site,
        "settings": organized,
    }


async def get_sysinfo(ctx: Context, site: str = "default", device: str | None = None) -> dict[str, Any]:
    """Get system information for the site controller.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        System information including version, uptime, and build info.
    """
    client = _get_client(ctx, device)
    sysinfo = await client.get_sysinfo(site)

    return {
        "site": site,
        "version": sysinfo.get("version", ""),
        "build": sysinfo.get("build", ""),
        "timezone": sysinfo.get("timezone", ""),
        "hostname": sysinfo.get("hostname", ""),
        "name": sysinfo.get("name", ""),
        "uptime": sysinfo.get("uptime", 0),
        "autobackup": sysinfo.get("autobackup", False),
        "ip_addrs": sysinfo.get("ip_addrs", []),
        "update_available": sysinfo.get("update_available", False),
        "update_downloaded": sysinfo.get("update_downloaded", False),
    }


async def get_networks(ctx: Context, site: str = "default", device: str | None = None) -> list[dict[str, Any]]:
    """Get all network/VLAN configurations.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        List of network configurations including VLANs, IP ranges,
        and DHCP settings.
    """
    client = _get_client(ctx, device)
    networks = await client.get_networks(site)

    result = []
    for network in networks:
        result.append({
            "name": network.get("name", ""),
            "purpose": network.get("purpose", ""),
            "vlan": network.get("vlan"),
            "vlan_enabled": network.get("vlan_enabled", False),
            "subnet": network.get("ip_subnet", ""),
            "dhcp_enabled": network.get("dhcp_enabled", False),
            "dhcp_start": network.get("dhcp_start"),
            "dhcp_stop": network.get("dhcp_stop"),
            "dhcp_lease_time": network.get("dhcp_lease_time"),
            "domain_name": network.get("domain_name"),
            "igmp_snooping": network.get("igmp_snooping", False),
            "enabled": network.get("enabled", True),
        })

    return result


async def get_wlans(ctx: Context, site: str = "default", device: str | None = None) -> list[dict[str, Any]]:
    """Get all wireless network (SSID) configurations.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        List of WLAN configurations including SSIDs, security settings,
        and associated networks.
    """
    client = _get_client(ctx, device)
    wlans = await client.get_wlans(site)

    result = []
    for wlan in wlans:
        result.append({
            "name": wlan.get("name", ""),
            "ssid": wlan.get("essid", wlan.get("name", "")),
            "enabled": wlan.get("enabled", True),
            "is_guest": wlan.get("is_guest", False),
            "security": wlan.get("security", ""),
            "wpa_mode": wlan.get("wpa_mode", ""),
            "wpa_enc": wlan.get("wpa_enc", ""),
            "network_id": wlan.get("networkconf_id"),
            "vlan": wlan.get("vlan"),
            "hide_ssid": wlan.get("hide_ssid", False),
            "mac_filter_enabled": wlan.get("mac_filter_enabled", False),
            "mac_filter_policy": wlan.get("mac_filter_policy"),
            "schedule_enabled": wlan.get("schedule_enabled", False),
            "band_steering": wlan.get("band_steering", "off"),
        })

    return result


async def get_port_profiles(ctx: Context, site: str = "default", device: str | None = None) -> list[dict[str, Any]]:
    """Get switch port profile configurations.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        List of port profiles with VLAN and PoE settings.
    """
    client = _get_client(ctx, device)
    profiles = await client.get_port_profiles(site)

    result = []
    for profile in profiles:
        result.append({
            "name": profile.get("name", ""),
            "native_networkconf_id": profile.get("native_networkconf_id"),
            "forward": profile.get("forward", ""),
            "poe_mode": profile.get("poe_mode", "auto"),
            "stormctrl_enabled": profile.get("stormctrl_enabled", False),
            "stp_port_mode": profile.get("stp_port_mode", True),
            "lldpmed_enabled": profile.get("lldpmed_enabled", True),
            "tagged_vlan_mgmt": profile.get("tagged_vlan_mgmt"),
        })

    return result


async def get_firewall_rules(ctx: Context, site: str = "default", device: str | None = None) -> list[dict[str, Any]]:
    """Get firewall rule configurations.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        List of firewall rules with action, protocol, and port details.
    """
    client = _get_client(ctx, device)
    rules = await client.get_firewall_rules(site)

    result = []
    for rule in rules:
        result.append({
            "name": rule.get("name", ""),
            "enabled": rule.get("enabled", True),
            "ruleset": rule.get("ruleset", ""),
            "rule_index": rule.get("rule_index"),
            "action": rule.get("action", ""),
            "protocol": rule.get("protocol", "all"),
            "src_firewallgroup_ids": rule.get("src_firewallgroup_ids", []),
            "dst_firewallgroup_ids": rule.get("dst_firewallgroup_ids", []),
            "dst_port": rule.get("dst_port"),
            "logging": rule.get("logging", False),
        })

    return result


async def get_routing_table(ctx: Context, site: str = "default", device: str | None = None) -> list[dict[str, Any]]:
    """Get the current routing table.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        List of routes with destination, gateway, and interface.
    """
    client = _get_client(ctx, device)
    routes = await client.get_routing(site)

    result = []
    for route in routes:
        result.append({
            "destination": route.get("pfx", ""),
            "gateway": route.get("nh", []),
            "type": route.get("type", ""),
            "interface": route.get("intf", ""),
            "metric": route.get("metric"),
            "static": route.get("static", False),
        })

    return result
