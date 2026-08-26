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


async def get_firewall_policies(ctx: Context, site: str = "default", device: str | None = None) -> list[dict[str, Any]]:
    """Get zone-based firewall policies (UniFi Network 9+).

    Modern UniFi OS controllers use zone-based policies instead of legacy
    firewall rules. Policies are evaluated in index order; the auto-generated
    "(Return)" companions for custom policies appear with predefined=True.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        List of firewall policies with source/destination zones and targets.
    """
    client = _get_client(ctx, device)
    policies = await client.get_firewall_policies(site)

    def _side(side: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "zone_id": side.get("zone_id"),
            "matching_target": side.get("matching_target"),
            "port_matching_type": side.get("port_matching_type"),
        }
        for extra in ("client_macs", "firewall_group_ids", "address_groups", "port_groups"):
            if side.get(extra):
                out[extra] = side[extra]
        return out

    return [
        {
            "name": p.get("name", ""),
            "description": p.get("description") or None,
            "index": p.get("index"),
            "enabled": p.get("enabled", True),
            "action": p.get("action", ""),
            "protocol": p.get("protocol", "all"),
            "ip_version": p.get("ip_version", ""),
            "predefined": p.get("predefined", False),
            "logging": p.get("logging", False),
            "hits": p.get("hits"),
            "schedule": (p.get("schedule") or {}).get("mode"),
            "source": _side(p.get("source") or {}),
            "destination": _side(p.get("destination") or {}),
        }
        for p in policies
    ]


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


async def _resolve_wlan(client: UniFiNetworkClient, wlan_id_or_name: str, site: str) -> str:
    """Resolve a WLAN identifier (ID or SSID name) to its ID."""
    wlans = await client.get_wlans(site)
    for w in wlans:
        if w.get("_id") == wlan_id_or_name or w.get("name") == wlan_id_or_name:
            return w["_id"]
    raise KeyError(f"WLAN not found: {wlan_id_or_name}")


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
) -> dict[str, Any]:
    """Update a wireless network (SSID) by ID or name.

    Only provided fields are changed. pmf_mode: disabled|optional|required.
    Enabling WPA3 transition keeps WPA2 compatibility for legacy clients.

    Args:
        ctx: MCP context
        wlan: WLAN ID or SSID name
        enabled: Enable/disable the SSID
        hide_ssid: Hide the SSID from broadcast
        passphrase: New WiFi password (min 8 chars)
        wpa3_support: Enable WPA3 support
        wpa3_transition: WPA2/WPA3 transition mode
        pmf_mode: Protected Management Frames mode
        bss_transition: 802.11k/v band/AP steering
        fast_roaming_enabled: 802.11r fast roaming
        site: Site name

    Returns:
        Updated WLAN configuration summary
    """
    client = _get_client(ctx, device)
    wid = await _resolve_wlan(client, wlan, site)

    data: dict[str, Any] = {}
    for key, val in [
        ("enabled", enabled), ("hide_ssid", hide_ssid), ("x_passphrase", passphrase),
        ("wpa3_support", wpa3_support), ("wpa3_transition", wpa3_transition),
        ("pmf_mode", pmf_mode), ("bss_transition", bss_transition),
        ("fast_roaming_enabled", fast_roaming_enabled),
    ]:
        if val is not None:
            data[key] = val
    if not data:
        return {"success": False, "message": "No fields to update provided"}

    result = await client.update_wlan(wid, data, site)
    return {
        "success": True,
        "name": result.get("name"),
        "applied": {k: result.get(k) for k in data},
    }


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
) -> dict[str, Any]:
    """Create a wireless network (SSID).

    Uses WPA2/WPA3 transition security by default. Passphrase must be 8-63 chars.

    Args:
        ctx: MCP context
        name: SSID name
        passphrase: WiFi password (8-63 chars)
        network_conf_id: Network ID to attach to (defaults to main network)
        wpa3_transition: Use WPA2/WPA3 transition mode
        hide_ssid: Broadcast hidden
        is_guest: Mark as guest network
        site: Site name

    Returns:
        Created WLAN configuration summary
    """
    client = _get_client(ctx, device)
    if not (8 <= len(passphrase) <= 63):
        return {"success": False, "message": "Passphrase must be 8-63 characters"}

    data: dict[str, Any] = {
        "name": name,
        "x_passphrase": passphrase,
        "security": "wpapsk",
        "wpa_mode": "wpa2",
        "wpa_enc": "ccmp",
        "enabled": True,
        "hide_ssid": hide_ssid,
        "is_guest": is_guest,
        "wlan_band": "both",
        "bc_filter_enabled": False,
    }
    if network_conf_id:
        data["networkconf_id"] = network_conf_id
    if wpa3_transition:
        data.update({"wpa3_support": True, "wpa3_transition": True, "pmf_mode": "optional"})

    # Mirror an existing WLAN's AP group assignment so the new SSID lands on
    # the same AP set; Network 10 rejects creates without a valid group.
    existing = await client.get_wlans(site)
    if existing:
        for key in ("ap_group_ids", "ap_group_mode"):
            val = existing[0].get(key)
            if val is not None:
                data[key] = val

    result = await client.create_wlan(data, site)
    return {
        "success": bool(result),
        "id": result.get("_id"),
        "name": result.get("name"),
    }


async def delete_wlan(
    ctx: Context,
    wlan: str,
    confirm: bool = False,
    site: str = "default",
    device: str | None = None,
) -> dict[str, Any]:
    """Delete a wireless network (SSID). Requires confirm=True.

    Args:
        ctx: MCP context
        wlan: WLAN ID or SSID name
        confirm: Must be True to actually delete
        site: Site name

    Returns:
        Deletion status
    """
    if not confirm:
        return {"success": False, "message": "Set confirm=true to delete. This disconnects all clients on that SSID."}
    client = _get_client(ctx, device)
    wid = await _resolve_wlan(client, wlan, site)
    await client.delete_wlan(wid, site)
    return {"success": True, "deleted": wlan}


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
) -> dict[str, Any]:
    """Create a zone-based firewall policy (UniFi Network 9+).

    Zone IDs come from get_firewall_policies. action: ALLOW|BLOCK|REJECT.
    protocol: all|tcp|udp|tcp_udp|icmp|igmp|icmpv6.
    client_macs restricts the source to specific devices (matching_target=CLIENT).

    Args:
        ctx: MCP context
        name: Policy name
        action: ALLOW, BLOCK, or REJECT
        src_zone_id: Source zone ID
        dst_zone_id: Destination zone ID
        protocol: Protocol selector
        description: Optional description
        client_macs: Restrict source to these MAC addresses
        index: Rule order index (lower evaluates earlier)
        enabled: Create enabled or disabled
        site: Site name

    Returns:
        Created policy summary
    """
    client = _get_client(ctx, device)
    action_u = action.upper()
    if action_u not in ("ALLOW", "BLOCK", "REJECT"):
        return {"success": False, "message": "action must be ALLOW, BLOCK, or REJECT"}

    policy: dict[str, Any] = {
        "action": action_u,
        "protocol": protocol,
        "enabled": enabled,
        "ip_version": "BOTH",
        "connection_state_type": "ALL",
        "connection_states": [],
        "create_allow_respond": True,
        "logging": False,
        "name": name,
        "schedule": {"mode": "ALWAYS"},
        "source": {
            "match_opposite_ports": False,
            "matching_target": "CLIENT" if client_macs else "ANY",
            "port_matching_type": "ANY",
            "zone_id": src_zone_id,
        },
        "destination": {
            "match_opposite_ports": False,
            "matching_target": "ANY",
            "port_matching_type": "ANY",
            "zone_id": dst_zone_id,
        },
    }
    if client_macs:
        policy["source"]["client_macs"] = [m.lower() for m in client_macs]
    if description:
        policy["description"] = description
    # Note: explicit indexes in the 30000+ range are rejected by the controller;
    # only send an index when the caller explicitly provides one.
    if index is not None:
        policy["index"] = index

    try:
        created = await client.create_firewall_policy(policy, site)
    except Exception as e:
        return {"success": False, "message": f"Controller rejected policy: {e}"}

    return {
        "success": True,
        "id": created.get("_id"),
        "name": created.get("name"),
        "action": created.get("action"),
        "src_zone": src_zone_id[-4:],
        "dst_zone": dst_zone_id[-4:],
        "note": "An auto-generated '(Return)' companion rule is typically added by the controller.",
    }


async def set_firewall_policy_enabled(
    ctx: Context,
    policy_id: str,
    enabled: bool,
    site: str = "default",
    device: str | None = None,
) -> dict[str, Any]:
    """Enable or disable a zone-based firewall policy.

    Args:
        ctx: MCP context
        policy_id: Policy ID (from get_firewall_policies)
        enabled: True to enable, False to disable
        site: Site name

    Returns:
        Update status
    """
    client = _get_client(ctx, device)
    policies = await client.get_firewall_policies(site)
    target = next((p for p in policies if p.get("_id") == policy_id), None)
    if target is None:
        return {"success": False, "message": f"Policy not found: {policy_id}"}

    merged = {**target, "enabled": enabled}
    merged.pop("hits", None)
    merged.pop("last_hit", None)
    await client.update_firewall_policy(policy_id, merged, site)
    return {"success": True, "policy": target.get("name"), "enabled": enabled}


async def delete_firewall_policy(
    ctx: Context,
    policy_id: str,
    confirm: bool = False,
    site: str = "default",
    device: str | None = None,
) -> dict[str, Any]:
    """Delete a zone-based firewall policy. Requires confirm=True.

    Args:
        ctx: MCP context
        policy_id: Policy ID
        confirm: Must be True to actually delete
        site: Site name

    Returns:
        Deletion status
    """
    if not confirm:
        return {"success": False, "message": "Set confirm=true to delete this firewall policy."}
    client = _get_client(ctx, device)
    policies = await client.get_firewall_policies(site)
    target = next((p for p in policies if p.get("_id") == policy_id), None)
    if target is None:
        return {"success": False, "message": f"Policy not found: {policy_id}"}
    if target.get("predefined"):
        return {"success": False, "message": "Refusing to delete a predefined controller policy."}
    await client.delete_firewall_policy(policy_id, site)
    return {"success": True, "deleted": target.get("name")}
