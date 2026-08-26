"""Tests for the UniFi Network API client."""

import httpx
import pytest
import respx

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient, is_device_online, is_wireless_client
from unifi_mcp.config import UniFiSettings
from unifi_mcp.exceptions import UniFiAPIError, UniFiNotFoundError


def make_ctx(devices_json: str | None = None, **kwargs) -> AppContext:
    kwargs.setdefault("devices_json", devices_json)
    settings = UniFiSettings(_env_file=None, **kwargs)
    return AppContext(
        client=httpx.AsyncClient(verify=False),
        settings=settings,
        cache={},
        auth=None,
    )


SITES = {
    "data": [
        {"id": "site-uuid-1", "name": "Default", "internalReference": "default"}
    ]
}

DEVICES = {
    "data": [
        {
            "id": "dev1",
            "name": "U6-LR",
            "macAddress": "AA:BB:CC:DD:EE:FF",
            "model": "U6-LR",
            "features": ["accessPoint"],
            "state": "ONLINE",
            "firmwareVersion": "7.1.60",
            "firmwareUpdatable": True,
        }
    ]
}


class TestDeviceTargeting:
    async def test_unknown_device_raises(self):
        ctx = make_ctx('[{"name":"gw","url":"https://x","api_key":"k"}]')
        with pytest.raises(ValueError, match="not found"):
            UniFiNetworkClient(ctx, device_name="missing")

    async def test_device_without_network_raises(self):
        ctx = make_ctx(
            '[{"name":"nvr","url":"https://x","api_key":"k","services":["protect"]}]'
        )
        with pytest.raises(ValueError, match="network service"):
            UniFiNetworkClient(ctx, device_name="nvr")

    def test_defaults_to_first_network_device(self):
        ctx = make_ctx(
            '[{"name":"gw","url":"https://x","api_key":"k"},'
            '{"name":"other","url":"https://y","api_key":"j"}]'
        )
        client = UniFiNetworkClient(ctx)
        assert client.device.name == "gw"
        assert client.site == "default"

    def test_per_device_site(self):
        ctx = make_ctx(
            '[{"name":"gw","url":"https://x","api_key":"k","site":"office"}]'
        )
        client = UniFiNetworkClient(ctx)
        assert client.site == "office"

    @respx.mock
    async def test_requests_use_targeted_device_url_and_key(self):
        ctx = make_ctx(
            '[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"},'
            '{"name":"nvr2","url":"https://10.0.0.2","api_key":"key-nvr",'
            '"services":["network"]}]'
        )
        route = respx.get("https://10.0.0.2/proxy/network/integration/v1/sites").respond(
            json=SITES
        )
        client = UniFiNetworkClient(ctx, device_name="nvr2")
        sites = await client.get_sites()
        assert len(sites) == 1
        assert route.calls.last.request.headers["X-API-KEY"] == "key-nvr"


class TestIntegrationAPI:
    def make_integration_client(self):
        ctx = make_ctx(
            '[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]'
        )
        client = UniFiNetworkClient(ctx)
        assert client.is_integration_api is True
        return client

    @respx.mock
    async def test_get_devices_endpoint_and_extraction(self):
        client = self.make_integration_client()
        respx.get("https://10.0.0.1/proxy/network/integration/v1/sites").respond(json=SITES)
        device_route = respx.get(
            "https://10.0.0.1/proxy/network/integration/v1/sites/site-uuid-1/devices"
        ).respond(json=DEVICES)

        devices = await client.get_devices()

        assert len(devices) == 1
        assert device_route.called

    @respx.mock
    async def test_site_id_cached_after_first_lookup(self):
        client = self.make_integration_client()
        sites_route = respx.get("https://10.0.0.1/proxy/network/integration/v1/sites").respond(
            json=SITES
        )

        await client._integration_site_endpoint("devices")
        await client._integration_site_endpoint("clients")
        await client._integration_site_endpoint("networks")

        assert sites_route.call_count == 1  # subsequent lookups served from cache

    @respx.mock
    async def test_get_device_by_mac_any_format(self):
        client = self.make_integration_client()
        respx.get("https://10.0.0.1/proxy/network/integration/v1/sites").respond(json=SITES)
        respx.get(
            "https://10.0.0.1/proxy/network/integration/v1/sites/site-uuid-1/devices"
        ).respond(json=DEVICES)

        for mac in ("AA:BB:CC:DD:EE:FF", "aabbccddeeff", "aa-bb-cc-dd-ee-ff"):
            device = await client.get_device(mac)
            assert device["id"] == "dev1"

        with pytest.raises(UniFiNotFoundError):
            await client.get_device("11:22:33:44:55:66")

    @respx.mock
    async def test_unsupported_action_gives_clear_error(self):
        client = self.make_integration_client()
        with pytest.raises(UniFiAPIError, match="not available via the Integration API"):
            await client.restart_device("aa:bb:cc:dd:ee:ff")

    @respx.mock
    async def test_get_devices_basic_fallback(self):
        client = self.make_integration_client()
        respx.get("https://10.0.0.1/proxy/network/integration/v1/sites").respond(json=SITES)
        respx.get(
            "https://10.0.0.1/proxy/network/integration/v1/sites/site-uuid-1/devices"
        ).respond(json=DEVICES)

        basic = await client.get_devices_basic()
        assert basic[0]["mac"] == "AA:BB:CC:DD:EE:FF"
        assert basic[0]["state"] == "ONLINE"


class TestFormatHelpers:
    def test_is_device_online_both_formats(self):
        assert is_device_online({"state": 1}) is True
        assert is_device_online({"state": 0}) is False
        assert is_device_online({"state": "ONLINE"}) is True
        assert is_device_online({"state": "offline"}) is False

    def test_is_wireless_client_both_formats(self):
        assert is_wireless_client({"is_wired": False}) is True
        assert is_wireless_client({"is_wired": True}) is False
        assert is_wireless_client({"type": "WIRELESS"}) is True
        assert is_wireless_client({"type": "WIRED"}) is False
        assert is_wireless_client({}) is False


def _local_ctx() -> AppContext:
    settings = UniFiSettings(
        _env_file=None,
        mode="local",
        controller_url="https://10.0.0.1",
        username="admin",
        password="pw",
    )
    from unifi_mcp.auth.local import UniFiLocalAuth

    ctx = AppContext(client=httpx.AsyncClient(verify=False), settings=settings, cache={}, auth=None)
    ctx.auth = UniFiLocalAuth(ctx.client, settings)
    return ctx


class TestWlanWrites:
    @respx.mock
    async def test_update_wlan(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.put("https://10.0.0.1/proxy/network/api/s/default/rest/wlanconf/wlan123").respond(
            json={"meta": {"rc": "ok"}, "data": [{"_id": "wlan123", "enabled": False}]}
        )
        client = UniFiNetworkClient(ctx)
        result = await client.update_wlan("wlan123", {"enabled": False})
        assert result["enabled"] is False

    @respx.mock
    async def test_create_wlan(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.post("https://10.0.0.1/proxy/network/api/s/default/rest/wlanconf").respond(
            json={"meta": {"rc": "ok"}, "data": [{"_id": "new1", "name": "NewSSID"}]}
        )
        client = UniFiNetworkClient(ctx)
        result = await client.create_wlan({"name": "NewSSID", "security": "wpapsk"})
        assert result["_id"] == "new1"

    @respx.mock
    async def test_delete_wlan(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.delete("https://10.0.0.1/proxy/network/api/s/default/rest/wlanconf/new1").respond(
            json={"meta": {"rc": "ok"}}
        )
        client = UniFiNetworkClient(ctx)
        await client.delete_wlan("new1")


class TestFirewallPolicyWrites:
    @respx.mock
    async def test_create_firewall_policy(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.post("https://10.0.0.1/proxy/network/v2/api/site/default/firewall-policies").respond(
            json={"_id": "pol1", "name": "Test Rule"}
        )
        client = UniFiNetworkClient(ctx)
        result = await client.create_firewall_policy({"name": "Test Rule", "action": "ALLOW"})
        assert result["_id"] == "pol1"

    @respx.mock
    async def test_update_firewall_policy(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.put("https://10.0.0.1/proxy/network/v2/api/site/default/firewall-policies/pol1").respond(
            json={"_id": "pol1", "enabled": False}
        )
        client = UniFiNetworkClient(ctx)
        result = await client.update_firewall_policy("pol1", {"enabled": False})
        assert result["enabled"] is False

    @respx.mock
    async def test_delete_firewall_policy(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.delete("https://10.0.0.1/proxy/network/v2/api/site/default/firewall-policies/pol1").respond(
            json={"meta": {"rc": "ok"}}
        )
        client = UniFiNetworkClient(ctx)
        await client.delete_firewall_policy("pol1")
