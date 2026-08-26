"""UniFi Network API client."""

import logging
from typing import Any

from unifi_mcp.clients.base import AppContext, UniFiHTTPClient
from unifi_mcp.exceptions import UniFiAPIError, UniFiNotFoundError

logger = logging.getLogger(__name__)


def is_device_online(device: dict[str, Any]) -> bool:
    """Check device online state across API formats.

    Integration API uses "ONLINE"/"OFFLINE" strings while the
    traditional controller API uses 1/0 integers.

    Args:
        device: Device dictionary from either API

    Returns:
        True if the device is online
    """
    state = device.get("state")
    if isinstance(state, str):
        return state.upper() == "ONLINE"
    return state == 1


def is_wireless_client(client: dict[str, Any]) -> bool:
    """Determine if a client is wireless across API formats.

    Integration API uses ``type: WIRELESS`` while the traditional
    controller API uses ``is_wired`` booleans.
    """
    client_type = client.get("type")
    if client_type:
        return str(client_type).upper() == "WIRELESS"
    if "is_wired" in client:
        return not client["is_wired"]
    return False


class UniFiNetworkClient(UniFiHTTPClient):
    """Client for UniFi Network Controller API.

    Provides methods for managing devices, clients, sites, and statistics.
    Supports multiple modes:
    - integration: UniFi OS Integration API with per-device API key
      (default when a device config with an api_key is resolved)
    - local: Session-based auth with traditional API endpoints
    - cloud: Ubiquiti Cloud API (api.ui.com)
    """

    def __init__(self, ctx: AppContext, device_name: str | None = None):
        """Initialize the Network API client.

        Args:
            ctx: Application context with shared resources
            device_name: Optional friendly name of a configured device to
                target. If None, the first network-enabled device is used.

        Raises:
            ValueError: If the named device doesn't exist or has no Network service
        """
        if device_name is not None:
            device = ctx.settings.get_device(device_name)
            if device is None:
                available = ", ".join(ctx.settings.get_device_names()) or "none"
                raise ValueError(
                    f"UniFi device '{device_name}' not found. Configured devices: {available}"
                )
            if not device.has_network:
                raise ValueError(f"Device '{device_name}' does not have the network service enabled")
        else:
            net_devices = ctx.settings.get_network_devices()
            device = net_devices[0] if net_devices else None

        super().__init__(ctx, device=device)

        self.force_session_mode = ctx.settings.mode == "local"
        self.site = device.site if device else ctx.settings.site
        self.is_cloud = ctx.settings.mode == "cloud" and device is None
        self.is_integration_api = device is not None and not self.force_session_mode
        self._site_id_cache: dict[str, str] = {}

    def _require_traditional_api(self, feature: str) -> None:
        """Raise an informative error for features unavailable via Integration/Cloud APIs.

        Args:
            feature: Human-readable feature name for the error message

        Raises:
            UniFiAPIError: Always, describing how to enable the feature
        """
        raise UniFiAPIError(
            f"'{feature}' is not available via the Integration API. "
            "Use legacy session auth (UNIFI_MODE=local with UNIFI_USERNAME/"
            "UNIFI_PASSWORD) to access this feature."
        )

    async def _get_site_id(self, site_name: str | None = None) -> str:
        """Get the site UUID for the Integration API.

        The Integration API uses site UUIDs instead of site names.

        Args:
            site_name: Site name (defaults to configured site)

        Returns:
            Site UUID

        Raises:
            UniFiNotFoundError: If site not found
        """
        site_name = site_name or self.site

        # Check cache first
        if site_name in self._site_id_cache:
            return self._site_id_cache[site_name]

        # Fetch sites and find matching one
        sites = await self.get_sites()
        for site in sites:
            # Integration API uses 'internalReference' for site name
            internal_ref = site.get("internalReference", site.get("name", ""))
            name = site.get("name", "")
            site_id = site.get("id") or site.get("_id", "")

            if site_name.lower() in (internal_ref.lower(), name.lower()):
                self._site_id_cache[site_name] = site_id
                return site_id

        raise UniFiNotFoundError("Site", site_name)

    def _site_endpoint(self, path: str, site: str | None = None) -> str:
        """Build a site-specific endpoint path for traditional API.

        Args:
            path: API path after /api/s/{site}/
            site: Site name (defaults to configured site)

        Returns:
            Full endpoint path
        """
        site = site or self.site
        return f"/api/s/{site}/{path}"

    async def _integration_site_endpoint(self, path: str, site: str | None = None) -> str:
        """Build a site-specific endpoint for Integration API.

        Args:
            path: Path after /v1/sites/{site_id}/
            site: Site name (defaults to configured site)

        Returns:
            Full endpoint path with site UUID
        """
        site_id = await self._get_site_id(site)
        return f"/v1/sites/{site_id}/{path}"

    def _extract_list_data(self, response: dict | list) -> list[dict[str, Any]]:
        """Extract list data from API response.

        Integration/Cloud APIs return paginated responses with 'data' field.

        Args:
            response: API response

        Returns:
            List of data items
        """
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            return response.get("data", [])
        return []

    # =========================================================================
    # Site Management
    # =========================================================================

    async def get_sites(self) -> list[dict[str, Any]]:
        """Get all sites accessible to the current user.

        Returns:
            List of site information dictionaries
        """
        if self.is_cloud or self.is_integration_api:
            # Cloud and Integration API use /v1/sites
            response = await self.get("/v1/sites")
            # These APIs return data directly or in simpler format
            if isinstance(response, list):
                return response
            return response.get("data", response) if isinstance(response, dict) else []

        response = await self.get("/api/self/sites")
        return response.get("data", [])

    async def get_site_health(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get health status for a site.

        Args:
            site: Site name (defaults to configured site)

        Returns:
            List of health status entries by subsystem
        """
        if self.is_integration_api or self.is_cloud:
            # Integration/Cloud APIs don't expose the health endpoint;
            # construct basic health from devices
            devices = await self.get_devices(site)
            online = sum(1 for d in devices if is_device_online(d))
            offline = len(devices) - online
            status = "ok" if offline == 0 else "degraded"
            return [{
                "subsystem": "network",
                "status": status,
                "devices_online": online,
                "devices_offline": offline,
                "num_adopted": len(devices),
                "note": "Limited health data available via Integration API",
            }]

        endpoint = self._site_endpoint("stat/health", site)
        response = await self.get(endpoint)
        return response.get("data", [])

    async def get_site_settings(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get site settings.

        Args:
            site: Site name

        Returns:
            List of settings objects
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("site settings")
        endpoint = self._site_endpoint("rest/setting", site)
        response = await self.get(endpoint)
        return response.get("data", [])

    async def get_sysinfo(self, site: str | None = None) -> dict[str, Any]:
        """Get system information for the site.

        Args:
            site: Site name

        Returns:
            System information dictionary
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("controller system info")
        endpoint = self._site_endpoint("stat/sysinfo", site)
        response = await self.get(endpoint)
        data = response.get("data", [])
        return data[0] if data else {}

    # =========================================================================
    # Device Management
    # =========================================================================

    async def get_devices(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get all devices (APs, switches, routers, etc.).

        Args:
            site: Site name

        Returns:
            List of device information dictionaries
        """
        if self.is_integration_api:
            # Integration API uses site-specific endpoint
            endpoint = await self._integration_site_endpoint("devices", site)
            response = await self.get(endpoint)
            return self._extract_list_data(response)

        if self.is_cloud:
            # Cloud API endpoint
            response = await self.get("/v1/devices")
            return self._extract_list_data(response)

        # Traditional local API
        endpoint = self._site_endpoint("stat/device", site)
        response = await self.get(endpoint)
        return response.get("data", [])

    async def get_devices_basic(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get basic device information (faster, less data).

        Args:
            site: Site name

        Returns:
            List of basic device info (mac, type, state, adopted, disabled)
        """
        if self.is_integration_api or self.is_cloud:
            # No dedicated basic endpoint on these APIs; slim down full results
            devices = await self.get_devices(site)
            return [
                {
                    "name": d.get("name", ""),
                    "mac": d.get("mac") or d.get("macAddress", ""),
                    "state": d.get("state"),
                    "adopted": d.get("adopted", True),
                }
                for d in devices
            ]

        endpoint = self._site_endpoint("stat/device-basic", site)
        response = await self.get(endpoint)
        return response.get("data", [])

    async def get_device(self, mac: str, site: str | None = None) -> dict[str, Any]:
        """Get details for a specific device.

        Args:
            mac: Device MAC address
            site: Site name

        Returns:
            Device information dictionary

        Raises:
            UniFiNotFoundError: If device not found
        """
        devices = await self.get_devices(site)

        mac_normalized = mac.lower().replace(":", "").replace("-", "")

        for device in devices:
            raw_mac = device.get("mac") or device.get("macAddress") or ""
            device_mac = raw_mac.lower().replace(":", "").replace("-", "")
            if device_mac == mac_normalized:
                return device

        raise UniFiNotFoundError("Device", mac)

    async def restart_device(self, mac: str, site: str | None = None) -> dict[str, Any]:
        """Restart a device.

        Args:
            mac: Device MAC address
            site: Site name

        Returns:
            Command result
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("device restart")
        endpoint = self._site_endpoint("cmd/devmgr", site)
        payload = {"cmd": "restart", "mac": mac.lower()}
        response = await self.post(endpoint, json=payload)
        return response

    async def locate_device(
        self, mac: str, enabled: bool = True, site: str | None = None
    ) -> dict[str, Any]:
        """Enable or disable device LED blinking for location.

        Args:
            mac: Device MAC address
            enabled: True to start blinking, False to stop
            site: Site name

        Returns:
            Command result
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("device locate (LED blink)")
        endpoint = self._site_endpoint("cmd/devmgr", site)
        cmd = "set-locate" if enabled else "unset-locate"
        payload = {"cmd": cmd, "mac": mac.lower()}
        response = await self.post(endpoint, json=payload)
        return response

    async def upgrade_device(self, mac: str, site: str | None = None) -> dict[str, Any]:
        """Upgrade device firmware.

        Args:
            mac: Device MAC address
            site: Site name

        Returns:
            Command result
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("device firmware upgrade")
        endpoint = self._site_endpoint("cmd/devmgr", site)
        payload = {"cmd": "upgrade", "mac": mac.lower()}
        response = await self.post(endpoint, json=payload)
        return response

    async def provision_device(self, mac: str, site: str | None = None) -> dict[str, Any]:
        """Force provision a device.

        Args:
            mac: Device MAC address
            site: Site name

        Returns:
            Command result
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("device provisioning")
        endpoint = self._site_endpoint("cmd/devmgr", site)
        payload = {"cmd": "force-provision", "mac": mac.lower()}
        response = await self.post(endpoint, json=payload)
        return response

    # =========================================================================
    # Client Management
    # =========================================================================

    async def get_clients(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get all connected clients.

        Args:
            site: Site name

        Returns:
            List of connected client information
        """
        if self.is_integration_api:
            # Integration API uses site-specific endpoint
            endpoint = await self._integration_site_endpoint("clients", site)
            response = await self.get(endpoint)
            return self._extract_list_data(response)

        if self.is_cloud:
            # Cloud API endpoint
            response = await self.get("/v1/clients")
            return self._extract_list_data(response)

        # Traditional local API
        endpoint = self._site_endpoint("stat/sta", site)
        response = await self.get(endpoint)
        return response.get("data", [])

    async def get_all_clients(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get all known clients (including offline).

        Args:
            site: Site name

        Returns:
            List of all known clients
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("known (offline) clients list")
        endpoint = self._site_endpoint("stat/alluser", site)
        response = await self.get(endpoint)
        return response.get("data", [])

    async def get_client(self, mac: str, site: str | None = None) -> dict[str, Any]:
        """Get details for a specific client.

        Args:
            mac: Client MAC address
            site: Site name

        Returns:
            Client information dictionary

        Raises:
            UniFiNotFoundError: If client not found
        """
        # First check connected clients
        clients = await self.get_clients(site)

        mac_normalized = mac.lower().replace(":", "").replace("-", "")

        for client in clients:
            client_mac = (
                client.get("mac", "").lower().replace(":", "").replace("-", "")
            )
            if client_mac == mac_normalized:
                return client

        # Then check all known clients (session-auth mode only)
        try:
            all_clients = await self.get_all_clients(site)
        except UniFiAPIError:
            all_clients = []
        for client in all_clients:
            client_mac = (
                client.get("mac", "").lower().replace(":", "").replace("-", "")
            )
            if client_mac == mac_normalized:
                return client

        raise UniFiNotFoundError("Client", mac)

    async def block_client(self, mac: str, site: str | None = None) -> dict[str, Any]:
        """Block a client from the network.

        Args:
            mac: Client MAC address
            site: Site name

        Returns:
            Command result
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("client blocking")
        endpoint = self._site_endpoint("cmd/stamgr", site)
        payload = {"cmd": "block-sta", "mac": mac.lower()}
        response = await self.post(endpoint, json=payload)
        return response

    async def unblock_client(self, mac: str, site: str | None = None) -> dict[str, Any]:
        """Unblock a previously blocked client.

        Args:
            mac: Client MAC address
            site: Site name

        Returns:
            Command result
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("client unblocking")
        endpoint = self._site_endpoint("cmd/stamgr", site)
        payload = {"cmd": "unblock-sta", "mac": mac.lower()}
        response = await self.post(endpoint, json=payload)
        return response

    async def kick_client(self, mac: str, site: str | None = None) -> dict[str, Any]:
        """Disconnect a client (they can reconnect).

        Args:
            mac: Client MAC address
            site: Site name

        Returns:
            Command result
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("client kick/disconnect")
        endpoint = self._site_endpoint("cmd/stamgr", site)
        payload = {"cmd": "kick-sta", "mac": mac.lower()}
        response = await self.post(endpoint, json=payload)
        return response

    async def forget_client(self, mac: str, site: str | None = None) -> dict[str, Any]:
        """Remove a client from the known clients list.

        Args:
            mac: Client MAC address
            site: Site name

        Returns:
            Command result
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("client removal")
        endpoint = self._site_endpoint("cmd/stamgr", site)
        payload = {"cmd": "forget-sta", "mac": mac.lower()}
        response = await self.post(endpoint, json=payload)
        return response

    # =========================================================================
    # Statistics & Events
    # =========================================================================

    async def get_events(
        self, limit: int = 100, site: str | None = None
    ) -> list[dict[str, Any]]:
        """Get recent events.

        Args:
            limit: Maximum number of events to return (max 3000)
            site: Site name

        Returns:
            List of event dictionaries
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("network events")

        endpoint = self._site_endpoint("stat/event", site)
        params = {"_limit": min(limit, 3000)}
        try:
            response = await self.get(endpoint, params=params)
        except UniFiAPIError as e:
            if e.status_code == 404:
                # Endpoint removed on newer Network versions (10+)
                logger.warning("stat/event not available on this controller version")
                return []
            raise
        return response.get("data", [])

    async def get_alarms(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get active alarms.

        Args:
            site: Site name

        Returns:
            List of alarm dictionaries
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("alarms")

        endpoint = self._site_endpoint("stat/alarm", site)
        try:
            response = await self.get(endpoint)
        except UniFiAPIError as e:
            if e.status_code == 404:
                # Endpoint removed on newer Network versions (10+)
                logger.warning("stat/alarm not available on this controller version")
                return []
            raise
        return response.get("data", [])

    async def archive_alarms(self, site: str | None = None) -> dict[str, Any]:
        """Archive all alarms.

        Args:
            site: Site name

        Returns:
            Command result
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("alarm archiving")
        endpoint = self._site_endpoint("cmd/evtmgr", site)
        payload = {"cmd": "archive-all-alarms"}
        response = await self.post(endpoint, json=payload)
        return response

    async def get_dpi_stats(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get Deep Packet Inspection statistics.

        Args:
            site: Site name

        Returns:
            List of DPI statistics by application/category
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("DPI statistics")

        endpoint = self._site_endpoint("stat/sitedpi", site)
        payload = {"type": "by_app"}
        response = await self.post(endpoint, json=payload)
        return response.get("data", [])

    async def get_client_dpi_stats(
        self, mac: str, site: str | None = None
    ) -> list[dict[str, Any]]:
        """Get DPI statistics for a specific client.

        Args:
            mac: Client MAC address
            site: Site name

        Returns:
            List of DPI statistics for the client
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("per-client DPI statistics")

        endpoint = self._site_endpoint("stat/stadpi", site)
        payload = {"type": "by_app", "macs": [mac.lower()]}
        response = await self.post(endpoint, json=payload)
        return response.get("data", [])

    # =========================================================================
    # Speed Test
    # =========================================================================

    async def run_speed_test(self, site: str | None = None) -> dict[str, Any]:
        """Start a WAN speed test.

        Args:
            site: Site name

        Returns:
            Command result with test initiation status
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("speed tests")
        endpoint = self._site_endpoint("cmd/devmgr", site)
        payload = {"cmd": "speedtest"}
        response = await self.post(endpoint, json=payload)
        return response

    async def get_speed_test_status(self, site: str | None = None) -> dict[str, Any]:
        """Get speed test status and results.

        Args:
            site: Site name

        Returns:
            Speed test status and results
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("speed test status")
        endpoint = self._site_endpoint("cmd/devmgr", site)
        payload = {"cmd": "speedtest-status"}
        response = await self.post(endpoint, json=payload)
        return response

    # =========================================================================
    # Network Configuration
    # =========================================================================

    async def get_networks(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get network/VLAN configurations.

        Args:
            site: Site name

        Returns:
            List of network configuration dictionaries
        """
        if self.is_integration_api:
            # Integration API uses site-specific endpoint
            endpoint = await self._integration_site_endpoint("networks", site)
            response = await self.get(endpoint)
            return self._extract_list_data(response)

        if self.is_cloud:
            self._require_traditional_api("network configurations")

        endpoint = self._site_endpoint("rest/networkconf", site)
        response = await self.get(endpoint)
        return response.get("data", [])

    async def get_wlans(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get wireless network configurations.

        Args:
            site: Site name

        Returns:
            List of WLAN configuration dictionaries
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("wireless network (SSID) configurations")

        endpoint = self._site_endpoint("rest/wlanconf", site)
        response = await self.get(endpoint)
        return response.get("data", [])

    async def get_port_profiles(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get switch port profiles.

        Args:
            site: Site name

        Returns:
            List of port profile configurations
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("switch port profiles")

        endpoint = self._site_endpoint("rest/portconf", site)
        response = await self.get(endpoint)
        return response.get("data", [])

    async def get_firewall_rules(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get firewall rules.

        Args:
            site: Site name

        Returns:
            List of firewall rule configurations
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("firewall rules")

        endpoint = self._site_endpoint("rest/firewallrule", site)
        response = await self.get(endpoint)
        return response.get("data", [])

    async def get_firewall_policies(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get zone-based firewall policies (UniFi Network 9+).

        Modern UniFi OS controllers use zone-based firewall policies instead
        of legacy firewall rules. Zone IDs can be correlated with networks
        via the UniFi UI; policies are evaluated by index order.

        Args:
            site: Site name

        Returns:
            List of zone-based firewall policy configurations
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("zone-based firewall policies")

        site_name = site or self.site
        endpoint = f"/v2/api/site/{site_name}/firewall-policies"
        return await self.get(endpoint)

    async def get_routing(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get routing table.

        Args:
            site: Site name

        Returns:
            List of routes
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("routing table")

        endpoint = self._site_endpoint("stat/routing", site)
        response = await self.get(endpoint)
        return response.get("data", [])
