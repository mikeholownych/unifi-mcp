"""Site management tools for UniFi Network."""

import ipaddress
import logging
from typing import Any

from mcp.server.mcpserver import Context

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient
from unifi_mcp.exceptions import UniFiConnectionError
from unifi_mcp.tools.network._verification import (
    accepted_unverified,
    delivery_unknown,
    normalize_field,
    requested_observation,
    verify_eventually,
)

logger = logging.getLogger(__name__)


class AmbiguousNetworkError(ValueError):
    """Raised when a network name maps to more than one stable record."""


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
        result.append(
            {
                "name": site.get("name", ""),
                "desc": site.get("desc", ""),
                "role": site.get("role", ""),
                "role_hotspot": site.get("role_hotspot", False),
                "attr_hidden_id": site.get("attr_hidden_id", ""),
                "attr_no_delete": site.get("attr_no_delete", False),
            }
        )

    return result


async def get_site_health(
    ctx: Context, site: str = "default", device: str | None = None
) -> dict[str, Any]:
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
            health[name].update(
                {
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
                }
            )

        # Collect issues
        if status != "ok":
            issues.append(
                {
                    "subsystem": name,
                    "status": status,
                }
            )

    return {
        "site": site,
        "overall_status": "healthy" if not issues else "issues_detected",
        "subsystems": health,
        "issues": issues,
    }


async def get_site_settings(
    ctx: Context, site: str = "default", device: str | None = None
) -> dict[str, Any]:
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


async def get_sysinfo(
    ctx: Context, site: str = "default", device: str | None = None
) -> dict[str, Any]:
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


async def get_networks(
    ctx: Context, site: str = "default", device: str | None = None
) -> list[dict[str, Any]]:
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
        result.append(
            {
                "name": network.get("name", ""),
                "purpose": network.get("purpose", ""),
                "vlan": network.get("vlan"),
                "vlan_enabled": network.get("vlan_enabled", False),
                "subnet": network.get("ip_subnet", ""),
                "dhcp_enabled": network.get("dhcpd_enabled", False),
                "dhcp_start": network.get("dhcpd_start"),
                "dhcp_stop": network.get("dhcpd_stop"),
                "dhcp_lease_time": network.get("dhcpd_leasetime"),
                "domain_name": network.get("domain_name"),
                "igmp_snooping": network.get("igmp_snooping", False),
                "enabled": network.get("enabled", True),
            }
        )

    return result


async def _find_network(
    client: UniFiNetworkClient,
    name_or_id: str,
    site: str,
    *,
    fresh: bool = False,
) -> dict[str, Any] | None:
    """Resolve a network by name or ID.

    Networks are matched case-insensitively by name (e.g. "servers", "DNS
    Servers") or by exact record ID. Returns None if no match is found,
    letting callers raise a friendly error.

    Args:
        client: Network client
        name_or_id: Network name or record ID
        site: Site name
        fresh: Bypass cached network state

    Returns:
        The matching network record, or None
    """
    networks = await client.get_networks(site, fresh=fresh)
    for network in networks:
        if (network.get("_id") or network.get("id")) == name_or_id:
            return network

    normalized = name_or_id.strip().lower()
    matches = []
    for network in networks:
        raw_name = network.get("name", "")
        if raw_name.strip().lower() == normalized:
            matches.append(network)
    if len(matches) > 1:
        raise AmbiguousNetworkError("Network name is ambiguous; use a stable ID.")
    return matches[0] if matches else None


def _network_id(network: dict[str, Any]) -> str | None:
    """Return the stable controller identifier for a network record."""
    return network.get("_id") or network.get("id")


def _normalize_network(network: dict[str, Any]) -> dict[str, Any]:
    """Project controller network fields into the public tool vocabulary."""
    return {
        "name": normalize_field("name", network.get("name")),
        "network_id": _network_id(network),
        "purpose": network.get("purpose"),
        "vlan": normalize_field("vlan", network.get("vlan")),
        "subnet": normalize_field("ip_subnet", network.get("ip_subnet")),
        "domain_name": normalize_field("domain_name", network.get("domain_name")),
        "dhcp_enabled": normalize_field("dhcpd_enabled", network.get("dhcpd_enabled")),
        "dhcp_start": normalize_field("dhcpd_start", network.get("dhcpd_start")),
        "dhcp_stop": normalize_field("dhcpd_stop", network.get("dhcpd_stop")),
        "dhcp_lease_time": normalize_field("dhcpd_leasetime", network.get("dhcpd_leasetime")),
        "enabled": network.get("enabled"),
    }


def _parse_subnet(value: str) -> ipaddress.IPv4Interface | ipaddress.IPv6Interface:
    return ipaddress.ip_interface(value.strip())


def _validate_dhcp_range(start: str, stop: str, subnet: str | None) -> str | None:
    if subnet is None:
        return "DHCP address changes require a known effective subnet."
    try:
        start_ip = ipaddress.ip_address(start.strip())
        stop_ip = ipaddress.ip_address(stop.strip())
        interface = _parse_subnet(subnet)
        network = interface.network
    except ValueError:
        return "DHCP start and stop must be valid IP addresses and subnet must be valid CIDR."
    if start_ip.version != stop_ip.version:
        return "DHCP start and stop must use the same IP version."
    if start_ip not in network or stop_ip not in network:
        return "DHCP start and stop must be within the effective subnet."
    if interface.ip in (start_ip, stop_ip):
        return "DHCP start and stop cannot use the gateway/interface IP."
    if isinstance(network, ipaddress.IPv4Network):
        if network.network_address in (start_ip, stop_ip):
            return "DHCP start and stop cannot use the IPv4 network address."
        if network.broadcast_address in (start_ip, stop_ip):
            return "DHCP start and stop cannot use the IPv4 broadcast address."
    if start_ip > stop_ip:
        return "DHCP start must be less than or equal to DHCP stop."
    return None


def _verification_failure(requested: dict[str, Any], result: Any) -> dict[str, Any]:
    return accepted_unverified(requested, result.observed)


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
) -> dict[str, Any]:
    """Create a new network/VLAN (corporate by default).

    Creates a LAN segment on the gateway. Use ``subnet`` in CIDR form
    (e.g. "192.168.50.1/24") and set ``vlan`` to tag the network on a VLAN.
    DHCP can be enabled by passing dhcp_start + dhcp_stop (and optionally
    dhcp_lease_time in seconds).

    Args:
        ctx: MCP context
        name: Network name (e.g. "IoT")
        subnet: Subnet in CIDR form (e.g. "192.168.50.1/24")
        vlan: VLAN ID (1-4094) if this should be a tagged segment
        purpose: Network purpose - corporate, guest, or wan
        domain_name: DNS domain name for clients (e.g. "example.local")
        dhcp_start: DHCP pool start IP (enables DHCP)
        dhcp_stop: DHCP pool end IP
        dhcp_lease_time: DHCP lease time in seconds (default 86400)
        confirm: Must be True because creating a LAN/VLAN can disrupt routing and DHCP
        site: Site name
        device: Device name

    Returns:
        Summary of the created network, or an error
    """
    if not confirm:
        return {
            "success": False,
            "message": "Network creation requires confirm=true because routing, VLAN, and DHCP "
            "changes can disrupt network connectivity.",
        }

    if not name.strip():
        return {"success": False, "message": "Network name must be nonblank."}
    if purpose not in {"corporate", "guest", "wan"}:
        return {
            "success": False,
            "message": "Network purpose must be corporate, guest, or wan.",
        }
    if isinstance(vlan, bool):
        return {
            "success": False,
            "message": "VLAN must be an integer ID, not a bool.",
        }
    if vlan is not None and not 1 <= vlan <= 4094:
        return {"success": False, "message": "VLAN must be between 1 and 4094."}
    if subnet is not None:
        try:
            _parse_subnet(subnet)
        except ValueError:
            return {"success": False, "message": "Subnet must be a valid CIDR interface."}
    if dhcp_lease_time is not None and dhcp_lease_time <= 0:
        return {"success": False, "message": "DHCP lease time must be positive."}

    dhcp_supplied = any(value is not None for value in (dhcp_start, dhcp_stop, dhcp_lease_time))
    if dhcp_supplied and not (dhcp_start and dhcp_stop):
        return {
            "success": False,
            "message": "DHCP configuration requires both non-empty dhcp_start and dhcp_stop.",
        }
    if dhcp_start and dhcp_stop:
        validation_error = _validate_dhcp_range(dhcp_start, dhcp_stop, subnet)
        if validation_error:
            return {"success": False, "message": validation_error}

    client = _get_client(ctx, device)

    data: dict[str, Any] = {
        "name": name.strip(),
        "purpose": purpose,
        "vlan_enabled": vlan is not None,
    }
    if vlan is not None:
        data["vlan"] = vlan
    if subnet:
        data["ip_subnet"] = subnet
    if domain_name:
        data["domain_name"] = domain_name
    if dhcp_start and dhcp_stop:
        data["dhcpd_enabled"] = True
        data["dhcpd_start"] = dhcp_start
        data["dhcpd_stop"] = dhcp_stop
        data["dhcpd_leasetime"] = dhcp_lease_time if dhcp_lease_time is not None else 86400
    else:
        data["dhcpd_enabled"] = False

    try:
        created = await client.create_network(data, site)
    except UniFiConnectionError:
        logger.warning("Network creation delivery outcome is unknown")
        return delivery_unknown("network creation", duplicate_risk=True)
    except Exception as exc:
        logger.warning("Controller rejected network creation (%s)", type(exc).__name__)
        return {
            "success": False,
            "message": "Controller rejected network creation; check server logs.",
        }

    created_id = _network_id(created)
    if created_id is None:
        return accepted_unverified(
            data,
            None,
            message=(
                "Controller accepted network creation but returned no stable ID, so persistence "
                "could not be verified. Retrying may create a duplicate network; check server "
                "logs and controller state."
            ),
        )

    observed_record: dict[str, Any] | None = None

    def evaluate(networks: list[dict[str, Any]]) -> tuple[bool, Any]:
        nonlocal observed_record
        observed_record = next(
            (network for network in networks if _network_id(network) == created_id), None
        )
        return requested_observation(observed_record, data)

    verification = await verify_eventually(
        lambda: client.get_networks(site, fresh=True),
        evaluate,
        operation="network creation",
        logger=logger,
        attempts=client.ctx.settings.mutation_verify_attempts,
        initial_delay=client.ctx.settings.mutation_verify_initial_delay,
        max_delay=client.ctx.settings.mutation_verify_max_delay,
    )
    if not verification.matched or observed_record is None:
        return _verification_failure(data, verification)

    return {
        "success": True,
        "name": normalize_field("name", observed_record.get("name")),
        "network_id": _network_id(observed_record),
        "purpose": normalize_field("purpose", observed_record.get("purpose")),
        "vlan": normalize_field("vlan", observed_record.get("vlan")),
        "subnet": normalize_field("ip_subnet", observed_record.get("ip_subnet")),
    }


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
) -> dict[str, Any]:
    """Update a network/VLAN by name or ID - only provided fields change.

    Pass only the fields you want to change. A single DHCP endpoint or lease-time
    update preserves DHCP's current enabled state. To enable DHCP, provide both
    non-empty endpoints; to disable it, pass empty strings for both endpoints.

    Args:
        ctx: MCP context
        name: Network name or record ID to update
        name_new: Rename the network
        subnet: Subnet in CIDR form (e.g. "192.168.50.1/24")
        vlan: VLAN ID (1-4094); pass -1 to disable VLAN tagging
        domain_name: DNS domain name
        dhcp_start: DHCP pool start IP
        dhcp_stop: DHCP pool end IP
        dhcp_lease_time: DHCP lease time in seconds
        enabled: Enable/disable the network
        confirm: Must be True because network changes can disconnect clients or services
        site: Site name
        device: Device name

    Returns:
        Updated network summary, or an error
    """
    if not confirm:
        return {
            "success": False,
            "message": "Network updates require confirm=true because routing, VLAN, DHCP, or "
            "enable-state changes can disrupt clients and services.",
        }

    if not name.strip():
        return {"success": False, "message": "Network name or ID must be nonblank."}
    if name_new is not None and not name_new.strip():
        return {"success": False, "message": "Network name_new must be nonblank."}
    if isinstance(vlan, bool):
        return {
            "success": False,
            "message": "VLAN must be an integer ID, not a bool.",
        }
    if vlan is not None and vlan != -1 and not 1 <= vlan <= 4094:
        return {
            "success": False,
            "message": "VLAN must be -1 or between 1 and 4094.",
        }
    if subnet is not None:
        try:
            _parse_subnet(subnet)
        except ValueError:
            return {"success": False, "message": "Subnet must be a valid CIDR interface."}
    if dhcp_lease_time is not None and dhcp_lease_time <= 0:
        return {"success": False, "message": "DHCP lease time must be positive."}
    for label, address in (("dhcp_start", dhcp_start), ("dhcp_stop", dhcp_stop)):
        if address:
            try:
                ipaddress.ip_address(address.strip())
            except ValueError:
                return {"success": False, "message": f"{label} must be a valid IP address."}
    if (dhcp_start == "") != (dhcp_stop == ""):
        return {
            "success": False,
            "message": "DHCP start and stop must be valid IP addresses, or both empty to disable.",
        }
    if all(
        value is None
        for value in (
            name_new,
            subnet,
            vlan,
            domain_name,
            dhcp_start,
            dhcp_stop,
            dhcp_lease_time,
            enabled,
        )
    ):
        return {"success": False, "message": "No fields to update - provide at least one"}

    client = _get_client(ctx, device)
    try:
        network = await _find_network(client, name, site, fresh=True)
    except AmbiguousNetworkError:
        return {
            "success": False,
            "message": "Network name is ambiguous; provide its stable ID.",
        }
    except Exception as exc:
        logger.warning("Failed to resolve network for update (%s)", type(exc).__name__)
        return {"success": False, "message": "Unable to resolve network; check server logs."}
    if network is None:
        return {"success": False, "message": f"Network '{name}' not found"}

    network_id = _network_id(network)
    if network_id is None:
        return {
            "success": False,
            "message": "Network has no stable ID; refusing to update it safely.",
        }

    if subnet is not None and dhcp_start is None and dhcp_stop is None:
        existing_start = network.get("dhcpd_start")
        existing_stop = network.get("dhcpd_stop")
        if network.get("dhcpd_enabled") or existing_start or existing_stop:
            if not existing_start or not existing_stop:
                return {
                    "success": False,
                    "message": "Existing DHCP pool is incomplete; refusing the new subnet.",
                }
            validation_error = _validate_dhcp_range(str(existing_start), str(existing_stop), subnet)
            if validation_error:
                return {
                    "success": False,
                    "message": f"Existing DHCP pool is invalid for the new subnet: "
                    f"{validation_error}",
                }
    data: dict[str, Any] = {}
    if name_new is not None:
        data["name"] = name_new.strip()
    if subnet is not None:
        data["ip_subnet"] = subnet
    if vlan is not None:
        data["vlan_enabled"] = vlan > 0
        if vlan > 0:
            data["vlan"] = vlan
    if domain_name is not None:
        data["domain_name"] = domain_name
    if dhcp_start is not None:
        data["dhcpd_start"] = dhcp_start
    if dhcp_stop is not None:
        data["dhcpd_stop"] = dhcp_stop
    if dhcp_lease_time is not None:
        data["dhcpd_leasetime"] = dhcp_lease_time
    if dhcp_start is not None and dhcp_stop is not None:
        if dhcp_start and dhcp_stop:
            data["dhcpd_enabled"] = True
        elif dhcp_start == "" and dhcp_stop == "":
            data["dhcpd_enabled"] = False
    if enabled is not None:
        data["enabled"] = enabled

    if dhcp_start is not None or dhcp_stop is not None:
        if dhcp_start == "" and dhcp_stop == "":
            pass
        else:
            effective_start = dhcp_start if dhcp_start is not None else network.get("dhcpd_start")
            effective_stop = dhcp_stop if dhcp_stop is not None else network.get("dhcpd_stop")
            effective_subnet = subnet if subnet is not None else network.get("ip_subnet")
            if not effective_start or not effective_stop:
                return {
                    "success": False,
                    "message": "DHCP address changes require both effective start and stop addresses.",
                }
            validation_error = _validate_dhcp_range(
                str(effective_start), str(effective_stop), effective_subnet
            )
            if validation_error:
                return {"success": False, "message": validation_error}

    try:
        await client.update_network(network_id, data, site)
    except UniFiConnectionError:
        logger.warning("Network update delivery outcome is unknown")
        return delivery_unknown("network update")
    except Exception as exc:
        logger.warning("Controller rejected network update (%s)", type(exc).__name__)
        return {
            "success": False,
            "message": "Controller rejected network update; check server logs.",
        }

    observed_record: dict[str, Any] | None = None

    def evaluate(networks: list[dict[str, Any]]) -> tuple[bool, Any]:
        nonlocal observed_record
        observed_record = next((item for item in networks if _network_id(item) == network_id), None)
        return requested_observation(observed_record, data)

    verification = await verify_eventually(
        lambda: client.get_networks(site, fresh=True),
        evaluate,
        operation="network update",
        logger=logger,
        attempts=client.ctx.settings.mutation_verify_attempts,
        initial_delay=client.ctx.settings.mutation_verify_initial_delay,
        max_delay=client.ctx.settings.mutation_verify_max_delay,
    )
    if not verification.matched or observed_record is None:
        return _verification_failure(data, verification)

    return {"success": True, **_normalize_network(observed_record)}


async def delete_network(
    ctx: Context,
    name: str,
    site: str = "default",
    device: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a network/VLAN by name or ID.

    Deleting a network is irreversible and will disconnect any clients or
    services assigned to it. WAN networks and VLANs still in use by an SSID
    or port profile cannot be removed - the controller will reject the delete.

    Args:
        ctx: MCP context
        name: Network name or record ID to delete
        confirm: Must be True to delete
        site: Site name
        device: Device name

    Returns:
        Success/error summary
    """
    if not confirm:
        return {
            "success": False,
            "message": "Deletion requires confirm=true. Deleting a network is irreversible and "
            "may disconnect clients or break services using it.",
        }

    if not name.strip():
        return {"success": False, "message": "Network name or ID must be nonblank."}

    client = _get_client(ctx, device)
    try:
        network = await _find_network(client, name, site, fresh=True)
    except AmbiguousNetworkError:
        return {
            "success": False,
            "message": "Network name is ambiguous; provide its stable ID.",
        }
    except Exception as exc:
        logger.warning("Failed to resolve network for deletion (%s)", type(exc).__name__)
        return {"success": False, "message": "Unable to resolve network; check server logs."}
    if network is None:
        return {"success": False, "message": f"Network '{name}' not found"}

    network_id = _network_id(network)
    if network_id is None:
        return {
            "success": False,
            "message": "Network has no stable ID; refusing to delete it safely.",
        }
    network_name = network.get("name", name)
    try:
        await client.delete_network(network_id, site)
    except UniFiConnectionError:
        logger.warning("Network deletion delivery outcome is unknown")
        return delivery_unknown("network deletion")
    except Exception as exc:
        logger.warning("Controller rejected network deletion (%s)", type(exc).__name__)
        return {
            "success": False,
            "message": "Controller rejected network deletion; check server logs.",
        }

    def evaluate(networks: list[dict[str, Any]]) -> tuple[bool, Any]:
        observed = next((item for item in networks if _network_id(item) == network_id), None)
        return observed is None, _normalize_network(observed) if observed is not None else None

    requested = {"network_id": network_id}
    verification = await verify_eventually(
        lambda: client.get_networks(site, fresh=True),
        evaluate,
        operation="network deletion",
        logger=logger,
        attempts=client.ctx.settings.mutation_verify_attempts,
        initial_delay=client.ctx.settings.mutation_verify_initial_delay,
        max_delay=client.ctx.settings.mutation_verify_max_delay,
    )
    if not verification.matched:
        return _verification_failure(requested, verification)

    return {"success": True, "message": f"Network '{network_name}' deleted"}


async def get_wlans(
    ctx: Context, site: str = "default", device: str | None = None
) -> list[dict[str, Any]]:
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
        result.append(
            {
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
                "wpa3_support": wlan.get("wpa3_support"),
                "wpa3_transition": wlan.get("wpa3_transition"),
                "pmf_mode": wlan.get("pmf_mode"),
                "bss_transition": wlan.get("bss_transition"),
            }
        )

    return result


async def get_port_profiles(
    ctx: Context, site: str = "default", device: str | None = None
) -> list[dict[str, Any]]:
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
        result.append(
            {
                "name": profile.get("name", ""),
                "native_networkconf_id": profile.get("native_networkconf_id"),
                "forward": profile.get("forward", ""),
                "poe_mode": profile.get("poe_mode", "auto"),
                "stormctrl_enabled": profile.get("stormctrl_enabled", False),
                "stp_port_mode": profile.get("stp_port_mode", True),
                "lldpmed_enabled": profile.get("lldpmed_enabled", True),
                "tagged_vlan_mgmt": profile.get("tagged_vlan_mgmt"),
            }
        )

    return result


async def get_firewall_rules(
    ctx: Context, site: str = "default", device: str | None = None
) -> list[dict[str, Any]]:
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
        result.append(
            {
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
            }
        )

    return result


async def get_firewall_policies(
    ctx: Context, site: str = "default", device: str | None = None
) -> list[dict[str, Any]]:
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


async def get_routing_table(
    ctx: Context, site: str = "default", device: str | None = None
) -> list[dict[str, Any]]:
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
        result.append(
            {
                "destination": route.get("pfx", ""),
                "gateway": route.get("nh", []),
                "type": route.get("type", ""),
                "interface": route.get("intf", ""),
                "metric": route.get("metric"),
                "static": route.get("static", False),
            }
        )

    return result


async def _resolve_wlan(client: UniFiNetworkClient, wlan_id_or_name: str, site: str) -> str:
    """Resolve a WLAN identifier (ID or SSID name) to its ID."""
    wlans = await client.get_wlans(site, fresh=True)
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
        ("enabled", enabled),
        ("hide_ssid", hide_ssid),
        ("x_passphrase", passphrase),
        ("wpa3_support", wpa3_support),
        ("wpa3_transition", wpa3_transition),
        ("pmf_mode", pmf_mode),
        ("bss_transition", bss_transition),
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


async def get_port_forwards(
    ctx: Context, site: str = "default", device: str | None = None
) -> list[dict[str, Any]]:
    """Get all port forwarding rules.

    Returns the configured port forwards (external port+protocol → internal
    IP+port on the gateway). Useful for diagnosing why a self-hosted service
    is unreachable externally or for planning new forwards.

    Args:
        ctx: MCP context
        site: Site name

    Returns:
        List of port forward rules with name, ports, target IP, and protocol
    """
    client = _get_client(ctx, device)
    rules = await client.get_port_forwards(site)
    return [
        {
            "name": r.get("name", ""),
            "enabled": r.get("enabled", True),
            "dst_port": r.get("dst_port", ""),
            "fwd_ip": r.get("fwd_ip", ""),
            "fwd_port": r.get("fwd_port", ""),
            "protocol": r.get("proto", "tcp_udp"),
            "site_id": r.get("site_id", ""),
            "rule_id": r.get("_id"),
        }
        for r in rules
    ]


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
) -> dict[str, Any]:
    """Create a port forwarding rule on the gateway.

    Maps an external port+protocol to an internal IP+port. Before creating,
    verify the target device is reachable internally (see unifi-port-forwarding
    skill for the three-part requirement: forward + EXTERNAL→zone policy + listener).

    Args:
        ctx: MCP context
        name: Rule name (e.g. "NAS HTTPS")
        dst_port: External port or range (e.g. "5000" or "8000-8100")
        fwd_ip: Internal destination IP (e.g. "192.168.1.100")
        fwd_port: Internal destination port (e.g. "443")
        proto: Protocol: tcp, udp, tcp_udp, icmp, igmp, icmpv6
        enabled: Create enabled or disabled
        site: Site name

    Returns:
        Created rule summary
    """
    client = _get_client(ctx, device)
    data: dict[str, Any] = {
        "name": name,
        "dst_port": dst_port,
        "fwd_ip": fwd_ip,
        "fwd_port": fwd_port,
        "proto": proto,
        "enabled": enabled,
        "site_id": site,
        "rule_index": 0,
    }
    try:
        created = await client.create_port_forward(data, site)
    except Exception as e:
        return {"success": False, "message": f"Controller rejected rule: {e}"}

    return {
        "success": True,
        "id": created.get("_id"),
        "name": created.get("name"),
        "dst_port": created.get("dst_port"),
        "fwd_ip": created.get("fwd_ip"),
        "fwd_port": created.get("fwd_port"),
    }


async def delete_port_forward(
    ctx: Context,
    rule_id: str,
    confirm: bool = False,
    site: str = "default",
    device: str | None = None,
) -> dict[str, Any]:
    """Delete a port forwarding rule. Requires confirm=True.

    Args:
        ctx: MCP context
        rule_id: Port forward rule ID (from get_port_forwards)
        confirm: Must be True to actually delete
        site: Site name

    Returns:
        Deletion status
    """
    if not confirm:
        return {
            "success": False,
            "message": "Set confirm=true to delete this port forwarding rule.",
        }
    client = _get_client(ctx, device)
    rules = await client.get_port_forwards(site)
    target = next((r for r in rules if r.get("_id") == rule_id), None)
    if target is None:
        return {"success": False, "message": f"Port forward rule not found: {rule_id}"}
    await client.delete_port_forward(rule_id, site)
    return {"success": True, "deleted": target.get("name")}


# ---------------------------------------------------------------------------
# Zone-name inference from firewall policy rule names
# ---------------------------------------------------------------------------

# Known zone-name anchors: substrings that, when found in a rule name,
# identify a zone.  The last match wins (more specific patterns first).
_ZONE_ANCHORS: list[tuple[str, str]] = [
    # Services / infrastructure
    ("DNS Servers", "DNS Servers"),
    ("DNS Server", "DNS Servers"),
    ("SERVERS", "SERVERS"),
    ("Servers", "SERVERS"),
    ("INFRA", "INFRA_SPECIAL"),
    ("IPTV", "IPTV"),
    ("BELL", "BELL_TV"),
    ("Bell", "BELL_TV"),
    ("Microtik", "Microtik"),
    ("TMX", "TMX_NET"),
    # Zones that appear by zone-suffix in rule names
    ("Zone-701", "ZONE_701"),
    ("Zone-702", "ZONE_702"),
    ("Zone-703", "ZONE_703"),
    # Human / home
    ("Mike", "HOME"),
    ("Alicia", "HOME"),
    ("Mike-Desktop", "HOME"),
    ("Everyone", "HOME"),
    # Network-side / WAN
    ("External", "WAN"),
    ("WAN", "WAN"),
    ("Gateway", "Gateway"),
]


def infer_zone_names(
    policies: list[dict[str, Any]],
) -> dict[str, str]:
    """Infer human-readable zone names from firewall policy rule names.

    UniFi Network 10 uses opaque hex zone IDs; this function maps each
    unique zone_id to a human-friendly name by examining custom (non-predefined)
    and predefined policy names for readable anchors.

    Returns:
        Dict mapping zone_id → inferred human name
    """
    zone_scores: dict[str, dict[str, int]] = {}

    for p in policies:
        # Focus on custom rules first; fall back to predefined
        name = p.get("name", "") or ""
        for side in ("source", "destination"):
            zone_id = (p.get(side) or {}).get("zone_id")
            if not zone_id:
                continue
            if zone_id not in zone_scores:
                zone_scores[zone_id] = {}
            # Score each anchor
            for anchor, canonical in _ZONE_ANCHORS:
                if anchor in name:
                    zone_scores[zone_id][canonical] = zone_scores[zone_id].get(canonical, 0) + 1

    # Pick highest-scoring name per zone
    result: dict[str, str] = {}
    for zone_id, scores in zone_scores.items():
        if scores:
            result[zone_id] = max(scores, key=scores.get)
        else:
            result[zone_id] = f"Zone {zone_id[-4:]}"
    return result


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
        return {
            "success": False,
            "message": "Set confirm=true to delete. This disconnects all clients on that SSID.",
        }
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


async def create_firewall_rule(
    ctx: Context,
    name: str,
    action: str,
    protocol: str,
    dst_port: str | int | None = None,
    src_zone: str | None = None,
    dst_zone: str | None = None,
    src_port: str | int | None = None,
    logging: bool = False,
    enabled: bool = True,
    site: str = "default",
    device: str | None = None,
) -> dict[str, Any]:
    """Create a legacy firewall rule (UniFi Network <9 or traditional API).

    Mutating operation: applied immediately and persisted on the controller.
    For zone-based policies (Network 9+), prefer create_firewall_policy.
    Review existing rules with get_firewall_rules first.

    Args:
        name: Unique rule name
        action: Action — "accept", "drop", or "reject"
        protocol: Protocol — "tcp", "udp", "icmp", "all", or IANA number
        dst_port: Destination port or range (e.g., "80", "80-443")
        src_zone: Source zone ID (from get_firewall_policies)
        dst_zone: Destination zone ID
        src_port: Source port or range
        logging: Enable logging for matches
        enabled: Whether rule is active on creation. Defaults to True.
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.

    Returns:
        Created firewall rule configuration
    """
    client = _get_client(ctx, device)
    data = {
        "name": name,
        "action": action,
        "protocol": protocol,
        "logging": logging,
        "enabled": enabled,
    }
    if dst_port is not None:
        data["dst_port"] = str(dst_port)
    if src_zone is not None:
        data["src_firewallgroup_ids"] = [src_zone]
    if dst_zone is not None:
        data["dst_firewallgroup_ids"] = [dst_zone]
    if src_port is not None:
        data["src_port"] = str(src_port)

    created = await client.create_firewall_rule(data, site)
    return {
        "success": True,
        "rule": {
            "name": created.get("name"),
            "_id": created.get("_id"),
            "action": created.get("action"),
            "protocol": created.get("protocol"),
            "enabled": created.get("enabled", True),
        },
    }


async def update_firewall_rule(
    ctx: Context,
    rule_id: str,
    name: str | None = None,
    action: str | None = None,
    protocol: str | None = None,
    dst_port: str | int | None = None,
    src_zone: str | None = None,
    dst_zone: str | None = None,
    src_port: str | int | None = None,
    logging: bool | None = None,
    enabled: bool | None = None,
    site: str = "default",
    device: str | None = None,
) -> dict[str, Any]:
    """Update a legacy firewall rule. Only provided fields are changed.

    Mutating operation: applied immediately and persisted on the controller.
    Use get_firewall_rules to find the rule ID first.

    Args:
        rule_id: Firewall rule ID (from get_firewall_rules)
        name: New rule name
        action: Action — "accept", "drop", or "reject"
        protocol: Protocol — "tcp", "udp", "icmp", "all", or IANA number
        dst_port: Destination port or range
        src_zone: Source zone ID
        dst_zone: Destination zone ID
        src_port: Source port or range
        logging: Enable/disable logging
        enabled: Enable/disable the rule
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.

    Returns:
        Updated firewall rule configuration
    """
    client = _get_client(ctx, device)
    rules = await client.get_firewall_rules(site)
    target = next((r for r in rules if r.get("_id") == rule_id), None)
    if target is None:
        return {"success": False, "message": f"Rule not found: {rule_id}"}

    data = {}
    if name is not None:
        data["name"] = name
    if action is not None:
        data["action"] = action
    if protocol is not None:
        data["protocol"] = protocol
    if dst_port is not None:
        data["dst_port"] = str(dst_port)
    if src_zone is not None:
        data["src_firewallgroup_ids"] = [src_zone]
    if dst_zone is not None:
        data["dst_firewallgroup_ids"] = [dst_zone]
    if src_port is not None:
        data["src_port"] = str(src_port)
    if logging is not None:
        data["logging"] = logging
    if enabled is not None:
        data["enabled"] = enabled

    updated = await client.update_firewall_rule(rule_id, data, site)
    return {
        "success": True,
        "rule": {
            "name": updated.get("name"),
            "_id": updated.get("_id"),
            "action": updated.get("action"),
            "protocol": updated.get("protocol"),
            "enabled": updated.get("enabled", True),
        },
    }


async def delete_firewall_rule(
    ctx: Context,
    rule_id: str,
    confirm: bool = False,
    site: str = "default",
    device: str | None = None,
) -> dict[str, Any]:
    """Delete a legacy firewall rule. Requires confirm=True.

    Mutating operation: permanently removes the rule from the controller.

    Args:
        rule_id: Firewall rule ID (from get_firewall_rules)
        confirm: Must be True to actually delete
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.

    Returns:
        Deletion status
    """
    if not confirm:
        return {"success": False, "message": "Set confirm=true to delete this firewall rule."}
    client = _get_client(ctx, device)
    rules = await client.get_firewall_rules(site)
    target = next((r for r in rules if r.get("_id") == rule_id), None)
    if target is None:
        return {"success": False, "message": f"Rule not found: {rule_id}"}
    await client.delete_firewall_rule(rule_id, site)
    return {"success": True, "deleted": target.get("name")}


async def update_site_settings(
    ctx: Context,
    settings: dict[str, Any],
    site: str = "default",
    device: str | None = None,
) -> dict[str, Any]:
    """Update site settings.

    Mutating operation: changes are applied immediately and persisted.
    Settings are key-value pairs matching the UniFi site setting schema.
    Use get_site_settings first to see available settings and their current values.

    Args:
        settings: Dictionary of settings to update (e.g., {"auto_backup_enabled": true})
        site: Site to operate on. Defaults to "default".
        device: Optional device name to target a specific console; omit for default.

    Returns:
        Updated settings response
    """
    client = _get_client(ctx, device)
    result = await client.update_site_settings(settings, site)
    return {"success": True, "result": result}
