"""AI-friendly network analysis and insight tools for UniFi Network."""

from typing import Any

from mcp.server.fastmcp import Context

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient, is_device_online, is_wireless_client
from unifi_mcp.exceptions import UniFiAPIError


def _get_client(ctx: Context, device: str | None = None) -> UniFiNetworkClient:
    """Get the UniFi Network client from context, optionally targeting a device."""
    app_ctx: AppContext = ctx.request_context.lifespan_context
    return UniFiNetworkClient(app_ctx, device_name=device)


async def _fetch_optional(coro) -> tuple[Any, str | None]:
    """Fetch data that may be unavailable on some API modes.

    Returns:
        Tuple of (data, limitation_note). limitation_note is None on success.
    """
    try:
        return await coro, None
    except UniFiAPIError as e:
        return [], f"unavailable: {e}"


async def analyze_network_issues(ctx: Context, site: str = "default", device: str | None = None) -> dict[str, Any]:
    """Analyze the network for potential issues and return a structured report.

    Aggregates device health, client connection issues, interference,
    firmware status, and recent alarms into an AI-friendly summary.

    Args:
        ctx: MCP context
        site: Site name
        device: Optional device name to target

    Returns:
        Comprehensive issue analysis with categorized problems and
        severity levels.
    """
    client = _get_client(ctx, device)

    # Gather data (some sources are unavailable via Integration API)
    devices = await client.get_devices(site)
    clients = await client.get_clients(site)
    health = await client.get_site_health(site)
    alarms, alarms_limit = await _fetch_optional(client.get_alarms(site))
    events, events_limit = await _fetch_optional(client.get_events(100, site))

    limitations = [
        note for note in (alarms_limit, events_limit) if note is not None
    ]

    issues = []
    warnings = []
    info = []

    # === Device Analysis ===

    # Check for offline devices
    offline_devices = [d for d in devices if not is_device_online(d) and d.get("adopted", True)]
    if offline_devices:
        issues.append({
            "category": "devices",
            "severity": "critical",
            "issue": f"{len(offline_devices)} device(s) are offline",
            "details": [{"name": d.get("name"), "mac": d.get("mac")} for d in offline_devices],
            "recommendation": "Check power and network connectivity for offline devices",
        })

    # Check for devices needing updates (Integration API uses firmwareUpdatable)
    upgradable = [d for d in devices if d.get("upgradable") or d.get("firmwareUpdatable")]
    if upgradable:
        warnings.append({
            "category": "firmware",
            "severity": "warning",
            "issue": f"{len(upgradable)} device(s) have firmware updates available",
            "details": [{"name": d.get("name"), "version": d.get("version")} for d in upgradable],
            "recommendation": "Schedule firmware updates to get latest features and security patches",
        })

    # Check for high CPU/memory usage
    for device in devices:
        sys_stats = device.get("system-stats", {})
        cpu = sys_stats.get("cpu")
        mem = sys_stats.get("mem")

        if cpu and float(cpu) > 80:
            warnings.append({
                "category": "performance",
                "severity": "warning",
                "issue": f"High CPU usage on {device.get('name')}",
                "details": {"device": device.get("name"), "cpu_percent": cpu},
                "recommendation": "Investigate load sources or consider hardware upgrade",
            })

        if mem and float(mem) > 85:
            warnings.append({
                "category": "performance",
                "severity": "warning",
                "issue": f"High memory usage on {device.get('name')}",
                "details": {"device": device.get("name"), "memory_percent": mem},
                "recommendation": "Restart device if memory leak suspected",
            })

    # === Wireless Analysis ===

    # Check for poor client signals
    poor_signal_clients = []
    for c in clients:
        if not c.get("is_wired"):
            rssi = c.get("rssi")
            signal = c.get("signal")
            if rssi and rssi < -75:
                poor_signal_clients.append({
                    "name": c.get("name") or c.get("hostname") or c.get("mac"),
                    "rssi": rssi,
                    "signal": signal,
                    "ap": c.get("ap_name"),
                })

    if poor_signal_clients:
        warnings.append({
            "category": "wireless",
            "severity": "warning",
            "issue": f"{len(poor_signal_clients)} client(s) have poor signal strength",
            "details": poor_signal_clients[:10],  # Top 10
            "recommendation": "Consider adding APs or adjusting AP placement for better coverage",
        })

    # Check for channel congestion (APs on same channel)
    channel_usage = {}
    for device in devices:
        if device.get("type") == "uap":
            for radio in device.get("radio_table", []):
                channel = radio.get("channel")
                if channel:
                    if channel not in channel_usage:
                        channel_usage[channel] = []
                    channel_usage[channel].append(device.get("name"))

    congested_channels = {ch: aps for ch, aps in channel_usage.items() if len(aps) > 1}
    if congested_channels:
        info.append({
            "category": "wireless",
            "severity": "info",
            "issue": "Multiple APs sharing same channel",
            "details": congested_channels,
            "recommendation": "Enable auto-channel or manually distribute channels to reduce interference",
        })

    # === WAN Analysis ===

    for subsystem in health:
        if subsystem.get("subsystem") == "wan":
            if subsystem.get("status") != "ok":
                issues.append({
                    "category": "wan",
                    "severity": "critical",
                    "issue": f"WAN connectivity issue: {subsystem.get('status')}",
                    "details": {
                        "wan_ip": subsystem.get("wan_ip"),
                        "status": subsystem.get("status"),
                    },
                    "recommendation": "Check ISP connection and gateway device",
                })

            # Check latency
            latency = subsystem.get("latency")
            if latency and latency > 50:
                warnings.append({
                    "category": "wan",
                    "severity": "warning",
                    "issue": f"High WAN latency: {latency}ms",
                    "details": {"latency_ms": latency},
                    "recommendation": "Contact ISP if consistently high latency",
                })

    # === Alarm Analysis ===

    if alarms:
        unarchived = [a for a in alarms if not a.get("archived")]
        if unarchived:
            issues.append({
                "category": "alarms",
                "severity": "warning",
                "issue": f"{len(unarchived)} active alarm(s)",
                "details": [{"key": a.get("key"), "msg": a.get("msg")} for a in unarchived[:5]],
                "recommendation": "Review and address active alarms",
            })

    return {
        "site": site,
        "summary": {
            "critical_issues": len(issues),
            "warnings": len(warnings),
            "informational": len(info),
            "overall_status": "critical" if issues else ("warning" if warnings else "healthy"),
        },
        "data_limitations": limitations,
        "issues": issues,
        "warnings": warnings,
        "info": info,
    }


async def get_optimization_recommendations(
    ctx: Context, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    """Analyze network configuration and provide optimization recommendations.

    Checks channel selection, TX power, VLAN efficiency, port configurations,
    and bandwidth utilization patterns.

    Args:
        ctx: MCP context
        site: Site name
        device: Optional device name to target

    Returns:
        Optimization recommendations organized by category.
    """
    client = _get_client(ctx, device)

    devices = await client.get_devices(site)
    wlans, wlans_limit = await _fetch_optional(client.get_wlans(site))
    networks = await client.get_networks(site)

    limitations = [note for note in (wlans_limit,) if note is not None]

    recommendations = []

    # === Wireless Optimizations ===

    # Check for APs with auto settings disabled
    for device in devices:
        if device.get("type") == "uap":
            for radio in device.get("radio_table", []):
                if radio.get("channel") and radio.get("channel") != "auto":
                    recommendations.append({
                        "category": "wireless",
                        "priority": "medium",
                        "recommendation": f"Consider enabling auto-channel on {device.get('name')} ({radio.get('name')})",
                        "reason": "Auto-channel helps avoid interference automatically",
                        "current": f"Fixed channel: {radio.get('channel')}",
                    })

    # Check for SSIDs on 2.4GHz only
    for device in devices:
        if device.get("type") == "uap":
            vap_table = device.get("vap_table", [])
            ssids_2g = set()
            ssids_5g = set()
            for vap in vap_table:
                if vap.get("radio") == "ng":
                    ssids_2g.add(vap.get("essid"))
                elif vap.get("radio") in ["na", "6e"]:
                    ssids_5g.add(vap.get("essid"))

            only_2g = ssids_2g - ssids_5g
            if only_2g:
                recommendations.append({
                    "category": "wireless",
                    "priority": "low",
                    "recommendation": f"Enable 5GHz for SSIDs: {', '.join(only_2g)}",
                    "reason": "5GHz offers higher speeds and less interference",
                })

    # Check band steering
    for wlan in wlans:
        if wlan.get("enabled") and not wlan.get("is_guest") and wlan.get("band_steering") == "off":
                recommendations.append({
                    "category": "wireless",
                    "priority": "low",
                    "recommendation": f"Enable band steering for '{wlan.get('name')}'",
                    "reason": "Helps clients connect to optimal band automatically",
                })

    # === Network Optimizations ===

    # Check for networks without VLANs
    flat_networks = [n for n in networks if not n.get("vlan_enabled") and n.get("purpose") != "wan"]
    if len(flat_networks) > 1:
        recommendations.append({
            "category": "security",
            "priority": "medium",
            "recommendation": "Consider using VLANs to segment network traffic",
            "reason": "VLANs improve security and reduce broadcast domains",
            "current": f"{len(flat_networks)} networks without VLAN segmentation",
        })

    # Check for guest network isolation
    for wlan in wlans:
        if wlan.get("is_guest") and wlan.get("enabled"):
            # Guest networks should typically have isolation
            recommendations.append({
                "category": "security",
                "priority": "high",
                "recommendation": f"Verify guest network '{wlan.get('name')}' has client isolation enabled",
                "reason": "Prevents guest devices from communicating with each other",
            })

    # === Performance Optimizations ===

    # Check for devices with many clients
    for device in devices:
        if device.get("type") == "uap":
            num_sta = device.get("num_sta", 0)
            if num_sta > 30:
                recommendations.append({
                    "category": "performance",
                    "priority": "medium",
                    "recommendation": f"Consider adding APs near {device.get('name')}",
                    "reason": f"AP has {num_sta} clients which may impact performance",
                    "current": f"{num_sta} connected clients",
                })

    return {
        "site": site,
        "total_recommendations": len(recommendations),
        "data_limitations": limitations,
        "recommendations": recommendations,
        "categories": {
            "wireless": [r for r in recommendations if r["category"] == "wireless"],
            "security": [r for r in recommendations if r["category"] == "security"],
            "performance": [r for r in recommendations if r["category"] == "performance"],
        },
    }


async def get_client_experience_report(
    ctx: Context, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    """Generate a client experience report with connection quality metrics.

    Includes signal strength distribution, roaming stats, failed connections,
    and problematic clients.

    Args:
        ctx: MCP context
        site: Site name
        device: Optional device name to target

    Returns:
        Client experience analysis with quality metrics and problem areas.
    """
    client = _get_client(ctx, device)

    clients = await client.get_clients(site)
    events, events_limit = await _fetch_optional(client.get_events(500, site))

    limitations = [note for note in (events_limit,) if note is not None]

    # Analyze wireless clients
    wireless_clients = [c for c in clients if is_wireless_client(c)]

    # Signal strength distribution
    signal_dist = {
        "excellent": [],  # > -50 dBm
        "good": [],       # -50 to -60 dBm
        "fair": [],       # -60 to -70 dBm
        "poor": [],       # -70 to -80 dBm
        "very_poor": [],  # < -80 dBm
    }

    for c in wireless_clients:
        rssi = c.get("rssi")
        name = c.get("name") or c.get("hostname") or c.get("mac")

        if rssi:
            if rssi > -50:
                signal_dist["excellent"].append({"name": name, "rssi": rssi})
            elif rssi > -60:
                signal_dist["good"].append({"name": name, "rssi": rssi})
            elif rssi > -70:
                signal_dist["fair"].append({"name": name, "rssi": rssi})
            elif rssi > -80:
                signal_dist["poor"].append({"name": name, "rssi": rssi})
            else:
                signal_dist["very_poor"].append({"name": name, "rssi": rssi})

    # Satisfaction scores
    satisfaction_scores = []
    for c in clients:
        sat = c.get("satisfaction")
        if sat is not None:
            satisfaction_scores.append(sat)

    avg_satisfaction = sum(satisfaction_scores) / len(satisfaction_scores) if satisfaction_scores else None

    # Analyze connection events
    connection_issues = []
    roaming_events = []

    for event in events:
        key = event.get("key", "")

        if "EVT_WU_Disconnected" in key or "EVT_WC_Disconnected" in key:
            connection_issues.append({
                "type": "disconnect",
                "client": event.get("hostname") or event.get("client"),
                "ap": event.get("ap_name"),
                "time": event.get("datetime"),
            })

        if "EVT_WU_Roam" in key:
            roaming_events.append({
                "client": event.get("hostname") or event.get("client"),
                "from_ap": event.get("ap_from"),
                "to_ap": event.get("ap_name"),
                "time": event.get("datetime"),
            })

    # Identify problem clients (high retry rate or low satisfaction)
    problem_clients = []
    for c in wireless_clients:
        issues = []

        if c.get("satisfaction") and c.get("satisfaction") < 70:
            issues.append(f"Low satisfaction: {c.get('satisfaction')}%")

        if c.get("tx_retries", 0) > 100:
            issues.append(f"High TX retries: {c.get('tx_retries')}")

        if c.get("rssi") and c.get("rssi") < -75:
            issues.append(f"Weak signal: {c.get('rssi')} dBm")

        if issues:
            problem_clients.append({
                "name": c.get("name") or c.get("hostname") or c.get("mac"),
                "mac": c.get("mac"),
                "issues": issues,
                "ap": c.get("ap_name"),
            })

    return {
        "site": site,
        "summary": {
            "total_wireless_clients": len(wireless_clients),
            "average_satisfaction": round(avg_satisfaction, 1) if avg_satisfaction else None,
            "problem_clients_count": len(problem_clients),
        },
        "data_limitations": limitations,
        "signal_distribution": {
            "excellent": len(signal_dist["excellent"]),
            "good": len(signal_dist["good"]),
            "fair": len(signal_dist["fair"]),
            "poor": len(signal_dist["poor"]),
            "very_poor": len(signal_dist["very_poor"]),
        },
        "problem_clients": problem_clients[:10],
        "recent_disconnections": connection_issues[:20],
        "recent_roaming": roaming_events[:20],
    }


async def get_device_health_summary(
    ctx: Context, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    """Summarize device health across all APs, switches, and routers.

    Includes uptime, load, memory, temperature, firmware versions,
    and devices needing attention.

    Args:
        ctx: MCP context
        site: Site name
        device: Optional device name to target

    Returns:
        Device health summary organized by device type.
    """
    client = _get_client(ctx, device)
    devices = await client.get_devices(site)

    # Helper to determine device type from model or features
    def get_device_type(d: dict) -> str:
        dev_type = d.get("type", "")
        if dev_type:
            return dev_type

        # Integration API uses 'features' array
        features = d.get("features", [])
        if "accessPoint" in features:
            return "uap"
        if "switching" in features:
            return "usw"
        if "gateway" in features or "routing" in features:
            return "ugw"

        # Check model name as fallback
        model = d.get("model", "").lower()
        if "ap" in model or "nano" in model or "flex" in model:
            return "uap"
        if "sw" in model or "switch" in model or "us-" in model:
            return "usw"
        if "udm" in model or "dream" in model:
            return "udm"
        if "ug" in model or "gateway" in model or "ucg" in model:
            return "ugw"

        return "other"

    # Categorize devices
    device_types = {
        "uap": {"name": "Access Points", "devices": []},
        "usw": {"name": "Switches", "devices": []},
        "ugw": {"name": "Gateways", "devices": []},
        "udm": {"name": "Dream Machines", "devices": []},
        "uxg": {"name": "Next-Gen Gateways", "devices": []},
    }

    needs_attention = []

    for device in devices:
        dev_type = get_device_type(device)
        sys_stats = device.get("system-stats", {})

        # Handle both API formats for version
        version = device.get("version") or device.get("firmwareVersion", "")

        health_info = {
            "name": device.get("name", "Unknown"),
            "mac": device.get("mac") or device.get("macAddress", ""),
            "model": device.get("model", ""),
            "version": version,
            "state": "online" if is_device_online(device) else "offline",
            "uptime_days": round(device.get("uptime", 0) / 86400, 1),
            "cpu_percent": sys_stats.get("cpu"),
            "memory_percent": sys_stats.get("mem"),
            "temperatures": device.get("temperatures", []),
            "upgradable": device.get("upgradable") or device.get("firmwareUpdatable", False),
            "clients": device.get("num_sta", 0),
        }

        # Add to category
        if dev_type in device_types:
            device_types[dev_type]["devices"].append(health_info)
        else:
            if "other" not in device_types:
                device_types["other"] = {"name": "Other Devices", "devices": []}
            device_types["other"]["devices"].append(health_info)

        # Check if needs attention
        attention_reasons = []

        if not is_device_online(device):
            attention_reasons.append("offline")

        if device.get("upgradable") or device.get("firmwareUpdatable"):
            attention_reasons.append("firmware update available")

        cpu = sys_stats.get("cpu")
        if cpu and float(cpu) > 80:
            attention_reasons.append(f"high CPU ({cpu}%)")

        mem = sys_stats.get("mem")
        if mem and float(mem) > 85:
            attention_reasons.append(f"high memory ({mem}%)")

        if attention_reasons:
            needs_attention.append({
                "name": device.get("name"),
                "mac": device.get("mac") or device.get("macAddress"),
                "reasons": attention_reasons,
            })

    # Filter out empty categories
    device_types = {k: v for k, v in device_types.items() if v["devices"]}

    return {
        "site": site,
        "total_devices": len(devices),
        "devices_needing_attention": len(needs_attention),
        "by_type": device_types,
        "needs_attention": needs_attention,
    }


async def get_traffic_analysis(
    ctx: Context, hours: int = 24, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    """Analyze traffic patterns over the specified time period.

    Includes top talkers, application breakdown (DPI), bandwidth trends,
    and unusual activity.

    Args:
        ctx: MCP context
        hours: Time period in hours to analyze
        site: Site name
        device: Optional device name to target

    Returns:
        Traffic analysis with patterns and top consumers.
    """
    client = _get_client(ctx, device)

    clients = await client.get_clients(site)
    dpi_stats, dpi_limit = await _fetch_optional(client.get_dpi_stats(site))

    limitations = [note for note in (dpi_limit,) if note is not None]

    # Top clients by traffic
    client_traffic = []
    for c in clients:
        tx = c.get("tx_bytes", 0)
        rx = c.get("rx_bytes", 0)
        total = tx + rx

        if total > 0:
            client_traffic.append({
                "name": c.get("name") or c.get("hostname") or c.get("mac"),
                "mac": c.get("mac"),
                "tx_bytes": tx,
                "rx_bytes": rx,
                "total_bytes": total,
                "tx_mb": round(tx / 1024 / 1024, 2),
                "rx_mb": round(rx / 1024 / 1024, 2),
            })

    # Sort by total traffic
    client_traffic.sort(key=lambda x: x["total_bytes"], reverse=True)

    # Application breakdown from DPI
    app_traffic = []
    for item in dpi_stats:
        tx = item.get("tx_bytes", 0)
        rx = item.get("rx_bytes", 0)
        total = tx + rx

        if total > 0:
            app_traffic.append({
                "category": item.get("cat_name", "Unknown"),
                "application": item.get("app_name", "Unknown"),
                "tx_bytes": tx,
                "rx_bytes": rx,
                "total_bytes": total,
                "total_mb": round(total / 1024 / 1024, 2),
            })

    app_traffic.sort(key=lambda x: x["total_bytes"], reverse=True)

    # Calculate totals
    total_tx = sum(c.get("tx_bytes", 0) for c in clients)
    total_rx = sum(c.get("rx_bytes", 0) for c in clients)

    return {
        "site": site,
        "period_hours": hours,
        "totals": {
            "tx_bytes": total_tx,
            "rx_bytes": total_rx,
            "tx_gb": round(total_tx / 1024 / 1024 / 1024, 2),
            "rx_gb": round(total_rx / 1024 / 1024 / 1024, 2),
        },
        "top_clients": client_traffic[:10],
        "top_applications": app_traffic[:15],
        "data_limitations": limitations,
    }


async def troubleshoot_client(
    ctx: Context, mac: str, site: str = "default", device: str | None = None
) -> dict[str, Any]:
    """Deep-dive troubleshooting for a specific client.

    Includes connection history, signal quality, AP associations,
    roaming events, and potential issues.

    Args:
        ctx: MCP context
        mac: Client MAC address
        site: Site name
        device: Optional device name to target

    Returns:
        Comprehensive troubleshooting information for the client.
    """
    client = _get_client(ctx, device)

    # Get client details
    client_data = await client.get_client(mac, site)
    events, events_limit = await _fetch_optional(client.get_events(200, site))

    limitations = [note for note in (events_limit,) if note is not None]

    is_wired = client_data.get("is_wired", False)

    # Build troubleshooting report
    report = {
        "client": {
            "name": client_data.get("name") or client_data.get("hostname") or mac,
            "mac": mac,
            "ip": client_data.get("ip"),
            "connection_type": "wired" if is_wired else "wireless",
            "connected": client_data.get("is_online", True),
            "uptime_seconds": client_data.get("uptime", 0),
        },
        "issues_detected": [],
        "recommendations": [],
    }

    # Wireless-specific analysis
    if not is_wired:
        rssi = client_data.get("rssi")
        signal = client_data.get("signal")
        satisfaction = client_data.get("satisfaction")
        tx_retries = client_data.get("tx_retries", 0)
        noise = client_data.get("noise")

        report["wireless"] = {
            "ap_name": client_data.get("ap_name"),
            "ap_mac": client_data.get("ap_mac"),
            "ssid": client_data.get("essid"),
            "channel": client_data.get("channel"),
            "radio": client_data.get("radio"),
            "rssi": rssi,
            "signal": signal,
            "noise": noise,
            "snr": (rssi - noise) if (rssi and noise) else None,
            "tx_rate": client_data.get("tx_rate"),
            "rx_rate": client_data.get("rx_rate"),
            "satisfaction": satisfaction,
            "tx_retries": tx_retries,
            "roam_count": client_data.get("roam_count", 0),
        }

        # Check for issues
        if rssi and rssi < -75:
            report["issues_detected"].append({
                "issue": "Weak signal strength",
                "details": f"RSSI: {rssi} dBm (should be > -70 dBm)",
                "severity": "warning",
            })
            report["recommendations"].append("Move client closer to AP or add additional AP")

        if satisfaction and satisfaction < 70:
            report["issues_detected"].append({
                "issue": "Low satisfaction score",
                "details": f"Satisfaction: {satisfaction}% (should be > 80%)",
                "severity": "warning",
            })

        if tx_retries > 100:
            report["issues_detected"].append({
                "issue": "High transmission retries",
                "details": f"TX retries: {tx_retries} (indicates interference or weak signal)",
                "severity": "warning",
            })
            report["recommendations"].append("Check for interference sources or adjust channel")

    # Analyze recent events for this client
    client_events = []
    mac_lower = mac.lower().replace(":", "").replace("-", "")

    for event in events:
        event_client = event.get("client", "").lower().replace(":", "")
        if event_client == mac_lower:
            client_events.append({
                "time": event.get("datetime"),
                "type": event.get("key"),
                "message": event.get("msg"),
                "ap": event.get("ap_name"),
            })

    report["recent_events"] = client_events[:20]

    # Count event types
    disconnect_count = sum(1 for e in client_events if "Disconnected" in e.get("type", ""))
    roam_count = sum(1 for e in client_events if "Roam" in e.get("type", ""))

    if disconnect_count > 5:
        report["issues_detected"].append({
            "issue": "Frequent disconnections",
            "details": f"{disconnect_count} disconnection events in recent history",
            "severity": "error",
        })
        report["recommendations"].append("Check for interference, verify DHCP settings, or update client drivers")

    if roam_count > 10:
        report["issues_detected"].append({
            "issue": "Excessive roaming",
            "details": f"{roam_count} roaming events (may indicate coverage issues)",
            "severity": "warning",
        })
        report["recommendations"].append("Adjust AP power levels or add additional coverage")

    # Overall assessment
    if not report["issues_detected"]:
        report["assessment"] = "Client appears healthy with no detected issues"
    else:
        report["assessment"] = f"Found {len(report['issues_detected'])} potential issue(s) requiring attention"

    report["data_limitations"] = limitations

    return report


async def get_all_sites_health(ctx: Context, device: str | None = None) -> dict[str, Any]:
    """Get a health overview across all sites on the controller.

    Args:
        ctx: MCP context
        device: Optional device name to target

    Returns:
        Per-site health summary with subsystem statuses.
    """
    client = _get_client(ctx, device)
    try:
        sites = await client.get_sites()
    except Exception as e:
        return {"sites": [], "error": f"Could not list sites: {e}"}

    overview = []
    for s in sites:
        site_name = s.get("name") or s.get("internalReference") or "unknown"
        entry: dict[str, Any] = {"site": site_name, "description": s.get("desc", "")}
        try:
            health = await client.get_site_health(site_name)
            subsystems = {}
            issues = []
            for sub in health:
                name = sub.get("subsystem", "unknown")
                status = sub.get("status", "unknown")
                subsystems[name] = {
                    "status": status,
                    "num_adopted": sub.get("num_adopted"),
                    "num_sta": sub.get("num_sta"),
                }
                if status != "ok":
                    issues.append({"subsystem": name, "status": status})
            entry["subsystems"] = subsystems
            entry["issues"] = issues
            entry["overall_status"] = "healthy" if not issues else "issues_detected"
        except Exception as e:
            entry["overall_status"] = "unavailable"
            entry["error"] = str(e)[:200]
        overview.append(entry)

    return {
        "total_sites": len(overview),
        "healthy": sum(1 for o in overview if o.get("overall_status") == "healthy"),
        "sites": overview,
    }
