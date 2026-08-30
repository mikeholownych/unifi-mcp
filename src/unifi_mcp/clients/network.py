"""UniFi Network API client."""

import logging
from typing import Any

from unifi_mcp.clients.base import AppContext, UniFiHTTPClient
from unifi_mcp.exceptions import (
    UniFiAPIError,
    UniFiConnectionError,
    UniFiDeliveryUnknownError,
    UniFiNotFoundError,
)

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
                raise ValueError(
                    f"Device '{device_name}' does not have the network service enabled"
                )
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
            return [
                {
                    "subsystem": "network",
                    "status": status,
                    "devices_online": online,
                    "devices_offline": offline,
                    "num_adopted": len(devices),
                    "note": "Limited health data available via Integration API",
                }
            ]

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

    async def update_site_settings(
        self, data: dict[str, Any], site: str | None = None
    ) -> dict[str, Any]:
        """Update site settings.

        Args:
            data: Settings to update (key-value pairs matching UniFi setting schema)
            site: Site name

        Returns:
            Updated settings response
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("site settings update")

        endpoint = self._site_endpoint("rest/setting", site)
        response = await self.put(endpoint, json=data)
        return response

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

    async def get_devices(
        self, site: str | None = None, *, fresh: bool = False
    ) -> list[dict[str, Any]]:
        """Get all devices (APs, switches, routers, etc.).

        Args:
            site: Site name
            fresh: Bypass the read cache

        Returns:
            List of device information dictionaries
        """
        if self.is_integration_api:
            # Integration API uses site-specific endpoint
            endpoint = await self._integration_site_endpoint("devices", site)
            response = await self.get(endpoint, _no_cache=fresh)
            return self._extract_list_data(response)

        if self.is_cloud:
            # Cloud API endpoint
            response = await self.get("/v1/devices", _no_cache=fresh)
            return self._extract_list_data(response)

        # Traditional local API
        endpoint = self._site_endpoint("stat/device", site)
        response = await self.get(endpoint, _no_cache=fresh)
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

    async def get_device(
        self, mac: str, site: str | None = None, *, fresh: bool = False
    ) -> dict[str, Any]:
        """Get details for a specific device.

        Args:
            mac: Device MAC address
            site: Site name
            fresh: Bypass the read cache

        Returns:
            Device information dictionary

        Raises:
            UniFiNotFoundError: If device not found
        """
        devices = await self.get_devices(site, fresh=fresh)

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

    async def update_device_ports(
        self, mac: str, ports: list[dict[str, Any]], site: str | None = None
    ) -> dict[str, Any]:
        """Update one or more switch ports on a device.

        Each entry in ``ports`` must include ``port_idx`` plus at least one
        writable field. Requested changes are merged into the device's complete
        ``port_overrides`` collection; operational ``port_table`` fields are
        used only to validate that each requested index exists.

        Args:
            mac: Device MAC address
            ports: List of port objects with port_idx and changed fields
            site: Site name

        Returns:
            Updated device record
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("switch port configuration")

        writable_fields = {
            "port_idx",
            "name",
            "native_networkconf_id",
            "poe_mode",
            "forward",
            "enabled",
            "setting_preference",
        }
        if any(set(change) - writable_fields for change in ports):
            raise UniFiAPIError("Port update contains fields outside the writable allowlist")

        device = await self.get_device(mac, site, fresh=True)
        device_id = device.get("_id") or device.get("id")
        if not device_id:
            raise UniFiAPIError("Device has no stable ID; refusing port update")

        current_ports = device.get("port_table")
        if not isinstance(current_ports, list) or not current_ports:
            raise UniFiAPIError("Device has no current port table; refusing port update")
        valid_indexes = {port.get("port_idx") for port in current_ports}

        current_overrides = device.get("port_overrides", [])
        if not isinstance(current_overrides, list):
            raise UniFiAPIError("Device port overrides are not a writable collection")
        override_indexes = [
            override.get("port_idx")
            for override in current_overrides
            if override.get("port_idx") is not None
        ]
        if len(override_indexes) != len(set(override_indexes)):
            raise UniFiAPIError("Existing port overrides contain duplicate port_idx values")
        requested_indexes = [change.get("port_idx") for change in ports]
        if len(requested_indexes) != len(set(requested_indexes)):
            raise UniFiAPIError("Requested port changes contain duplicate port_idx values")
        updated_overrides = [dict(override) for override in current_overrides]
        override_positions = {
            override.get("port_idx"): position
            for position, override in enumerate(updated_overrides)
            if override.get("port_idx") is not None
        }
        valid_changes = 0
        for change in ports:
            port_idx = change.get("port_idx")
            if port_idx not in valid_indexes:
                raise UniFiAPIError(f"Requested port index {port_idx!r} does not exist")
            writable_change = {key: value for key, value in change.items() if key != "port_idx"}
            if not writable_change:
                continue
            valid_changes += 1
            if port_idx in override_positions:
                updated_overrides[override_positions[port_idx]].update(writable_change)
            else:
                override_positions[port_idx] = len(updated_overrides)
                updated_overrides.append({"port_idx": port_idx, **writable_change})

        if not valid_changes:
            raise UniFiAPIError("No valid port changes to update")

        endpoint = self._site_endpoint(f"rest/device/{device_id}", site)
        try:
            response = await self.put(endpoint, json={"port_overrides": updated_overrides})
        except UniFiConnectionError:
            raise UniFiDeliveryUnknownError(
                "Switch port update delivery could not be determined"
            ) from None
        return response

    async def get_device_port_table(
        self, mac: str, site: str | None = None, *, fresh: bool = False
    ) -> list[dict[str, Any]]:
        """Get the raw port_table for a device.

        Returns the unmodified port_table entries (port_idx, name, media,
        forward, native_networkconf_id, excluded_networkconf_ids, poe fields,
        speed, up, etc.) for a switch or gateway.

        Args:
            mac: Device MAC address
            site: Site name
            fresh: Bypass the read cache

        Returns:
            List of port entries
        """
        device = await self.get_device(mac, site, fresh=fresh)
        return device.get("port_table", [])

    # =========================================================================
    # Client Management
    # =========================================================================

    async def get_clients(
        self, site: str | None = None, *, fresh: bool = False
    ) -> list[dict[str, Any]]:
        """Get all connected clients.

        Args:
            site: Site name
            fresh: Bypass the read cache

        Returns:
            List of connected client information
        """
        if self.is_integration_api:
            # Integration API uses site-specific endpoint
            endpoint = await self._integration_site_endpoint("clients", site)
            response = await self.get(endpoint, _no_cache=fresh)
            return self._extract_list_data(response)

        if self.is_cloud:
            # Cloud API endpoint
            response = await self.get("/v1/clients", _no_cache=fresh)
            return self._extract_list_data(response)

        # Traditional local API
        endpoint = self._site_endpoint("stat/sta", site)
        response = await self.get(endpoint, _no_cache=fresh)
        return response.get("data", [])

    async def get_all_clients(
        self, site: str | None = None, *, fresh: bool = False
    ) -> list[dict[str, Any]]:
        """Get all known clients (including offline).

        Args:
            site: Site name
            fresh: Bypass the read cache

        Returns:
            List of all known clients
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("known (offline) clients list")
        endpoint = self._site_endpoint("stat/alluser", site)
        response = await self.get(endpoint, _no_cache=fresh)
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
            client_mac = client.get("mac", "").lower().replace(":", "").replace("-", "")
            if client_mac == mac_normalized:
                return client

        # Then check all known clients (session-auth mode only)
        try:
            all_clients = await self.get_all_clients(site)
        except UniFiAPIError:
            all_clients = []
        for client in all_clients:
            client_mac = client.get("mac", "").lower().replace(":", "").replace("-", "")
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

    async def set_client_fixed_ip(
        self,
        client_id: str,
        fixed_ip: str | None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Set or clear a DHCP reservation (fixed IP) for a client.

        Args:
            client_id: Client record ID (from stat/alluser / rest/user)
            fixed_ip: IP address to reserve; None clears the reservation
            site: Site name

        Returns:
            Updated client record
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("DHCP reservations")

        endpoint = self._site_endpoint(f"rest/user/{client_id}", site)
        data: dict[str, Any] = (
            {"use_fixedip": True, "fixed_ip": fixed_ip} if fixed_ip else {"use_fixedip": False}
        )
        response = await self.put(endpoint, json=data)
        updated = (response.get("data") or [{}])[0]
        if updated:
            return updated
        # Some controller versions return an empty array on no-op PUTs;
        # fall back to reading the record back for verification.
        record = await self.get(endpoint)
        return (record.get("data") or [{}])[0]

    # =========================================================================
    # Statistics & Events
    # =========================================================================

    async def get_events(self, limit: int = 100, site: str | None = None) -> list[dict[str, Any]]:
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

    async def get_client_dpi_stats(self, mac: str, site: str | None = None) -> list[dict[str, Any]]:
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

    async def get_networks(
        self, site: str | None = None, *, fresh: bool = False
    ) -> list[dict[str, Any]]:
        """Get network/VLAN configurations.

        Args:
            site: Site name
            fresh: Bypass the read cache

        Returns:
            List of network configuration dictionaries
        """
        if self.is_integration_api:
            # Integration API uses site-specific endpoint
            endpoint = await self._integration_site_endpoint("networks", site)
            response = await self.get(endpoint, _no_cache=fresh)
            return self._extract_list_data(response)

        if self.is_cloud:
            self._require_traditional_api("network configurations")

        endpoint = self._site_endpoint("rest/networkconf", site)
        response = await self.get(endpoint, _no_cache=fresh)
        return response.get("data", [])

    async def get_wlans(
        self, site: str | None = None, *, fresh: bool = False
    ) -> list[dict[str, Any]]:
        """Get wireless network configurations.

        Args:
            site: Site name
            fresh: Bypass the read cache

        Returns:
            List of WLAN configuration dictionaries
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("wireless network (SSID) configurations")

        endpoint = self._site_endpoint("rest/wlanconf", site)
        response = await self.get(endpoint, _no_cache=fresh)
        return response.get("data", [])

    async def create_network(self, data: dict[str, Any], site: str | None = None) -> dict[str, Any]:
        """Create a network/VLAN configuration.

        Args:
            data: Network configuration (name, purpose, vlan_enabled, vlan, ip_subnet, etc.)
            site: Site name

        Returns:
            Created network configuration
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("network (VLAN) creation")

        endpoint = self._site_endpoint("rest/networkconf", site)
        response = await self.post(endpoint, json=data)
        return (response.get("data") or [{}])[0]

    async def update_network(
        self, network_id: str, data: dict[str, Any], site: str | None = None
    ) -> dict[str, Any]:
        """Update a network/VLAN configuration.

        Args:
            network_id: Network ID
            data: Fields to update
            site: Site name

        Returns:
            Updated network configuration
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("network (VLAN) updates")

        endpoint = self._site_endpoint(f"rest/networkconf/{network_id}", site)
        response = await self.put(endpoint, json=data)
        return (response.get("data") or [{}])[0]

    async def delete_network(self, network_id: str, site: str | None = None) -> None:
        """Delete a network/VLAN configuration.

        Args:
            network_id: Network ID
            site: Site name
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("network (VLAN) deletion")

        endpoint = self._site_endpoint(f"rest/networkconf/{network_id}", site)
        await self.delete(endpoint)

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

    async def create_firewall_rule(
        self, data: dict[str, Any], site: str | None = None
    ) -> dict[str, Any]:
        """Create a legacy firewall rule (UniFi Network <9 or traditional API).

        Args:
            data: Rule configuration (name, action, protocol, port, etc.)
            site: Site name

        Returns:
            Created firewall rule configuration
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("firewall rule creation")

        endpoint = self._site_endpoint("rest/firewallrule", site)
        response = await self.post(endpoint, json=data)
        return (response.get("data") or [{}])[0]

    async def update_firewall_rule(
        self, rule_id: str, data: dict[str, Any], site: str | None = None
    ) -> dict[str, Any]:
        """Update a legacy firewall rule.

        Args:
            rule_id: Firewall rule ID
            data: Fields to update
            site: Site name

        Returns:
            Updated firewall rule configuration
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("firewall rule updates")

        endpoint = self._site_endpoint(f"rest/firewallrule/{rule_id}", site)
        response = await self.put(endpoint, json=data)
        return (response.get("data") or [{}])[0]

    async def delete_firewall_rule(self, rule_id: str, site: str | None = None) -> None:
        """Delete a legacy firewall rule.

        Args:
            rule_id: Firewall rule ID
            site: Site name
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("firewall rule deletion")

        endpoint = self._site_endpoint(f"rest/firewallrule/{rule_id}", site)
        await self.delete(endpoint)

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

    async def create_wlan(self, data: dict[str, Any], site: str | None = None) -> dict[str, Any]:
        """Create a wireless network (SSID).

        Args:
            data: WLAN configuration (name, x_passphrase, security, etc.)
            site: Site name

        Returns:
            Created WLAN configuration
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("wireless network creation")

        endpoint = self._site_endpoint("rest/wlanconf", site)
        response = await self.post(endpoint, json=data)
        return (response.get("data") or [{}])[0]

    async def update_wlan(
        self, wlan_id: str, data: dict[str, Any], site: str | None = None
    ) -> dict[str, Any]:
        """Update a wireless network (SSID).

        Args:
            wlan_id: WLAN ID
            data: Fields to update
            site: Site name

        Returns:
            Updated WLAN configuration
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("wireless network updates")

        endpoint = self._site_endpoint(f"rest/wlanconf/{wlan_id}", site)
        response = await self.put(endpoint, json=data)
        return (response.get("data") or [{}])[0]

    async def delete_wlan(self, wlan_id: str, site: str | None = None) -> None:
        """Delete a wireless network (SSID).

        Args:
            wlan_id: WLAN ID
            site: Site name
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("wireless network deletion")

        endpoint = self._site_endpoint(f"rest/wlanconf/{wlan_id}", site)
        await self.delete(endpoint)

    async def create_firewall_policy(
        self, policy: dict[str, Any], site: str | None = None
    ) -> dict[str, Any]:
        """Create a zone-based firewall policy (UniFi Network 9+).

        Args:
            policy: Policy object matching the v2 firewall-policies schema
            site: Site name

        Returns:
            Created policy
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("firewall policy creation")

        site_name = site or self.site
        endpoint = f"/v2/api/site/{site_name}/firewall-policies"
        return await self.post(endpoint, json=policy)

    async def update_firewall_policy(
        self, policy_id: str, data: dict[str, Any], site: str | None = None
    ) -> dict[str, Any]:
        """Update a zone-based firewall policy.

        Args:
            policy_id: Policy ID
            data: Fields to update
            site: Site name

        Returns:
            Updated policy
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("firewall policy updates")

        site_name = site or self.site
        endpoint = f"/v2/api/site/{site_name}/firewall-policies/{policy_id}"
        return await self.put(endpoint, json=data)

    async def delete_firewall_policy(self, policy_id: str, site: str | None = None) -> None:
        """Delete a zone-based firewall policy.

        Args:
            policy_id: Policy ID
            site: Site name
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("firewall policy deletion")

        site_name = site or self.site
        endpoint = f"/v2/api/site/{site_name}/firewall-policies/{policy_id}"
        await self.delete(endpoint)

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

    # =========================================================================
    # Port Forwarding
    # =========================================================================

    async def get_port_forwards(self, site: str | None = None) -> list[dict[str, Any]]:
        """Get all port forwarding rules.

        Returns the configured port forwards. Each rule maps an external
        port+protocol on the gateway to an internal IP+port.

        Args:
            site: Site name

        Returns:
            List of port forward rule dictionaries
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("port forwarding rules")

        endpoint = self._site_endpoint("rest/portforward", site)
        response = await self.get(endpoint)
        return response.get("data", [])

    async def create_port_forward(
        self, data: dict[str, Any], site: str | None = None
    ) -> dict[str, Any]:
        """Create a port forwarding rule.

        Args:
            data: Port forward configuration object
            site: Site name

        Returns:
            Created port forward rule
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("port forwarding rule creation")

        endpoint = self._site_endpoint("rest/portforward", site)
        response = await self.post(endpoint, json=data)
        return (response.get("data") or [{}])[0]

    async def delete_port_forward(self, rule_id: str, site: str | None = None) -> None:
        """Delete a port forwarding rule.

        Args:
            rule_id: Port forward rule ID
            site: Site name
        """
        if self.is_integration_api or self.is_cloud:
            self._require_traditional_api("port forwarding rule deletion")

        endpoint = self._site_endpoint(f"rest/portforward/{rule_id}", site)
        await self.delete(endpoint)
