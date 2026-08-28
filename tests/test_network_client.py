"""Tests for the UniFi Network API client."""

import asyncio
import json

import httpx
import pytest
import respx

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient, is_device_online, is_wireless_client
from unifi_mcp.config import UniFiSettings
from unifi_mcp.exceptions import UniFiAPIError, UniFiConnectionError, UniFiNotFoundError


def make_ctx(devices_json: str | None = None, **kwargs) -> AppContext:
    kwargs.setdefault("devices_json", devices_json)
    settings = UniFiSettings(_env_file=None, **kwargs)
    return AppContext(
        client=httpx.AsyncClient(verify=False),
        settings=settings,
        cache={},
        auth=None,
    )


SITES = {"data": [{"id": "site-uuid-1", "name": "Default", "internalReference": "default"}]}
CONCURRENCY_TIMEOUT = 1

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
        ctx = make_ctx('[{"name":"nvr","url":"https://x","api_key":"k","services":["protect"]}]')
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
        ctx = make_ctx('[{"name":"gw","url":"https://x","api_key":"k","site":"office"}]')
        client = UniFiNetworkClient(ctx)
        assert client.site == "office"

    @respx.mock
    async def test_requests_use_targeted_device_url_and_key(self):
        ctx = make_ctx(
            '[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"},'
            '{"name":"nvr2","url":"https://10.0.0.2","api_key":"key-nvr",'
            '"services":["network"]}]'
        )
        route = respx.get("https://10.0.0.2/proxy/network/integration/v1/sites").respond(json=SITES)
        client = UniFiNetworkClient(ctx, device_name="nvr2")
        sites = await client.get_sites()
        assert len(sites) == 1
        assert route.calls.last.request.headers["X-API-KEY"] == "key-nvr"


class TestIntegrationAPI:
    def make_integration_client(self):
        ctx = make_ctx('[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]')
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


class TestNetworkWrites:
    @respx.mock
    async def test_separate_client_instances_share_read_cache(self):
        ctx = make_ctx('[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]')
        route = respx.get("https://10.0.0.1/proxy/network/integration/v1/test-resource").respond(
            json={"version": 1}
        )

        first = UniFiNetworkClient(ctx)
        second = UniFiNetworkClient(ctx)

        assert await first.get("/v1/test-resource") == {"version": 1}
        assert await second.get("/v1/test-resource") == {"version": 1}
        assert route.call_count == 1

    @respx.mock
    async def test_shared_cache_does_not_collide_between_devices(self):
        ctx = make_ctx(
            '[{"name":"gw-a","url":"https://10.0.0.1","api_key":"key-a"},'
            '{"name":"gw-b","url":"https://10.0.0.2","api_key":"key-b"}]'
        )
        route_a = respx.get("https://10.0.0.1/proxy/network/integration/v1/test-resource").respond(
            json={"device": "a"}
        )
        route_b = respx.get("https://10.0.0.2/proxy/network/integration/v1/test-resource").respond(
            json={"device": "b"}
        )

        assert await UniFiNetworkClient(ctx, "gw-a").get("/v1/test-resource") == {"device": "a"}
        assert await UniFiNetworkClient(ctx, "gw-b").get("/v1/test-resource") == {"device": "b"}
        assert route_a.call_count == 1
        assert route_b.call_count == 1

    @respx.mock
    async def test_get_networks_fresh_bypasses_cached_response(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        route = respx.get("https://10.0.0.1/proxy/network/api/s/default/rest/networkconf").mock(
            side_effect=[
                httpx.Response(200, json={"data": [{"_id": "old"}]}),
                httpx.Response(200, json={"data": [{"_id": "new"}]}),
            ]
        )
        client = UniFiNetworkClient(ctx)

        assert (await client.get_networks())[0]["_id"] == "old"
        assert (await client.get_networks())[0]["_id"] == "old"
        assert (await client.get_networks(fresh=True))[0]["_id"] == "new"
        assert route.call_count == 2

    @respx.mock
    async def test_fresh_network_read_replaces_cached_response(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        route = respx.get("https://10.0.0.1/proxy/network/api/s/default/rest/networkconf").mock(
            side_effect=[
                httpx.Response(200, json={"data": [{"_id": "old"}]}),
                httpx.Response(200, json={"data": [{"_id": "new"}]}),
            ]
        )
        client = UniFiNetworkClient(ctx)

        assert (await client.get_networks())[0]["_id"] == "old"
        assert (await client.get_networks(fresh=True))[0]["_id"] == "new"
        assert (await client.get_networks())[0]["_id"] == "new"
        assert route.call_count == 2

    @respx.mock
    async def test_failed_fresh_network_read_evicts_cached_response(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        route = respx.get("https://10.0.0.1/proxy/network/api/s/default/rest/networkconf").mock(
            side_effect=[
                httpx.Response(200, json={"data": [{"_id": "old"}]}),
                httpx.Response(503, json={"message": "temporarily unavailable"}),
                httpx.Response(200, json={"data": [{"_id": "new"}]}),
            ]
        )
        client = UniFiNetworkClient(ctx)

        assert (await client.get_networks())[0]["_id"] == "old"
        with pytest.raises(UniFiAPIError):
            await client.get_networks(fresh=True)
        assert (await client.get_networks())[0]["_id"] == "new"
        assert route.call_count == 3

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
    @respx.mock
    async def test_successful_mutation_invalidates_cached_get(self, method):
        ctx = make_ctx('[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]')
        get_route = respx.get("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=[
                httpx.Response(200, json={"version": 1}),
                httpx.Response(200, json={"version": 2}),
            ]
        )
        mutation_route = respx.route(
            method=method,
            url="https://10.0.0.1/proxy/network/integration/v1/test-resource",
        ).respond(200, json={"accepted": True})
        client = UniFiNetworkClient(ctx)

        assert await client.get("/v1/test-resource") == {"version": 1}
        assert await client.get("/v1/test-resource") == {"version": 1}
        await client.request(method, "/v1/test-resource", json={"change": True})
        assert await client.get("/v1/test-resource") == {"version": 2}

        assert get_route.call_count == 2
        assert mutation_route.call_count == 1

    @respx.mock
    async def test_failed_mutation_connection_invalidates_cached_get(self):
        ctx = make_ctx('[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]')
        get_route = respx.get("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=[
                httpx.Response(200, json={"version": 1}),
                httpx.Response(200, json={"version": 2}),
            ]
        )
        respx.put("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=httpx.ConnectError("connection failed")
        )
        client = UniFiNetworkClient(ctx)

        assert await client.get("/v1/test-resource") == {"version": 1}
        with pytest.raises(UniFiConnectionError):
            await client.put("/v1/test-resource", json={"change": True})
        assert await client.get("/v1/test-resource") == {"version": 2}
        assert get_route.call_count == 2

    @respx.mock
    async def test_rejected_mutation_invalidates_cached_get(self):
        ctx = make_ctx('[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]')
        get_route = respx.get("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=[
                httpx.Response(200, json={"version": 1}),
                httpx.Response(200, json={"version": 2}),
            ]
        )
        respx.put("https://10.0.0.1/proxy/network/integration/v1/test-resource").respond(
            409, json={"message": "rejected"}
        )
        client = UniFiNetworkClient(ctx)

        assert await client.get("/v1/test-resource") == {"version": 1}
        with pytest.raises(UniFiAPIError):
            await client.put("/v1/test-resource", json={"change": True})
        assert await client.get("/v1/test-resource") == {"version": 2}
        assert get_route.call_count == 2

    @respx.mock
    async def test_get_started_before_mutation_cannot_restore_stale_cache(self):
        ctx = make_ctx('[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]')
        get_started = asyncio.Event()
        release_get = asyncio.Event()

        async def get_response(request):
            if not get_started.is_set():
                get_started.set()
                await release_get.wait()
                return httpx.Response(200, json={"version": 1})
            return httpx.Response(200, json={"version": 2})

        get_route = respx.get("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=get_response
        )
        respx.put("https://10.0.0.1/proxy/network/integration/v1/test-resource").respond(
            200, json={"accepted": True}
        )
        client = UniFiNetworkClient(ctx)

        old_get = asyncio.create_task(client.get("/v1/test-resource"))
        await get_started.wait()
        await client.put("/v1/test-resource", json={"change": True})
        release_get.set()

        assert await old_get == {"version": 1}
        assert await client.get("/v1/test-resource") == {"version": 2}
        assert get_route.call_count == 2

    @respx.mock
    async def test_get_started_during_mutation_cannot_survive_final_invalidation(self):
        ctx = make_ctx('[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]')
        mutation_started = asyncio.Event()
        release_mutation = asyncio.Event()

        async def mutation_response(request):
            mutation_started.set()
            await release_mutation.wait()
            return httpx.Response(200, json={"accepted": True})

        get_route = respx.get("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=[
                httpx.Response(200, json={"version": 1}),
                httpx.Response(200, json={"version": 2}),
            ]
        )
        respx.put("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=mutation_response
        )
        client = UniFiNetworkClient(ctx)

        mutation = asyncio.create_task(client.put("/v1/test-resource", json={"change": True}))
        await mutation_started.wait()
        assert await client.get("/v1/test-resource") == {"version": 1}
        release_mutation.set()
        await mutation

        assert await client.get("/v1/test-resource") == {"version": 2}
        assert get_route.call_count == 2

    @respx.mock
    async def test_fresh_get_prevents_older_get_from_overwriting_new_cache(self):
        ctx = make_ctx('[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]')
        old_get_started = asyncio.Event()
        release_old_get = asyncio.Event()
        request_count = 0

        async def get_response(_request):
            nonlocal request_count
            request_count += 1
            if request_count == 1:
                old_get_started.set()
                await asyncio.wait_for(release_old_get.wait(), CONCURRENCY_TIMEOUT)
                return httpx.Response(200, json={"version": 1})
            return httpx.Response(200, json={"version": 2})

        get_route = respx.get("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=get_response
        )
        client = UniFiNetworkClient(ctx)

        old_get = asyncio.create_task(client.get("/v1/test-resource"))
        await asyncio.wait_for(old_get_started.wait(), CONCURRENCY_TIMEOUT)
        assert await client.get("/v1/test-resource", _no_cache=True) == {"version": 2}
        release_old_get.set()

        assert await asyncio.wait_for(old_get, CONCURRENCY_TIMEOUT) == {"version": 1}
        assert await client.get("/v1/test-resource") == {"version": 2}
        assert get_route.call_count == 2

    @pytest.mark.parametrize("_repeat", range(3))
    @respx.mock
    async def test_stale_fresh_get_cannot_overwrite_completed_mutation_epoch(self, _repeat):
        ctx = make_ctx('[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]')
        stale_fresh_started = asyncio.Event()
        release_stale_fresh = asyncio.Event()
        request_count = 0

        async def get_response(_request):
            nonlocal request_count
            request_count += 1
            if request_count == 1:
                stale_fresh_started.set()
                await asyncio.wait_for(release_stale_fresh.wait(), CONCURRENCY_TIMEOUT)
                return httpx.Response(200, json={"version": 1})
            return httpx.Response(200, json={"version": 2})

        get_route = respx.get("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=get_response
        )
        respx.put("https://10.0.0.1/proxy/network/integration/v1/test-resource").respond(
            200, json={"accepted": True}
        )
        client = UniFiNetworkClient(ctx)

        stale_fresh = asyncio.create_task(client.get("/v1/test-resource", _no_cache=True))
        await asyncio.wait_for(stale_fresh_started.wait(), CONCURRENCY_TIMEOUT)
        await asyncio.wait_for(
            client.put("/v1/test-resource", json={"change": True}),
            CONCURRENCY_TIMEOUT,
        )
        release_stale_fresh.set()

        assert await asyncio.wait_for(stale_fresh, CONCURRENCY_TIMEOUT) == {"version": 1}
        assert await client.get("/v1/test-resource") == {"version": 2}
        assert get_route.call_count == 2

    @pytest.mark.parametrize("_repeat", range(3))
    @respx.mock
    async def test_newer_fresh_get_wins_over_older_fresh_get(self, _repeat):
        ctx = make_ctx('[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]')
        older_fresh_started = asyncio.Event()
        release_older_fresh = asyncio.Event()
        request_count = 0

        async def get_response(_request):
            nonlocal request_count
            request_count += 1
            if request_count == 1:
                older_fresh_started.set()
                await asyncio.wait_for(release_older_fresh.wait(), CONCURRENCY_TIMEOUT)
                return httpx.Response(200, json={"version": 1})
            return httpx.Response(200, json={"version": 2})

        get_route = respx.get("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=get_response
        )
        client = UniFiNetworkClient(ctx)

        older_fresh = asyncio.create_task(client.get("/v1/test-resource", _no_cache=True))
        await asyncio.wait_for(older_fresh_started.wait(), CONCURRENCY_TIMEOUT)
        assert await asyncio.wait_for(
            client.get("/v1/test-resource", _no_cache=True),
            CONCURRENCY_TIMEOUT,
        ) == {"version": 2}
        release_older_fresh.set()

        assert await asyncio.wait_for(older_fresh, CONCURRENCY_TIMEOUT) == {"version": 1}
        assert await client.get("/v1/test-resource") == {"version": 2}
        assert get_route.call_count == 2

    @respx.mock
    async def test_get_overlapping_failed_mutation_cannot_cache_old_response(self):
        ctx = make_ctx('[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]')
        old_get_started = asyncio.Event()
        release_old_get = asyncio.Event()
        request_count = 0

        async def get_response(_request):
            nonlocal request_count
            request_count += 1
            if request_count == 1:
                old_get_started.set()
                await asyncio.wait_for(release_old_get.wait(), CONCURRENCY_TIMEOUT)
                return httpx.Response(200, json={"version": 1})
            return httpx.Response(200, json={"version": 2})

        get_route = respx.get("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=get_response
        )
        respx.put("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=httpx.ConnectError("connection failed")
        )
        client = UniFiNetworkClient(ctx)

        old_get = asyncio.create_task(client.get("/v1/test-resource"))
        await asyncio.wait_for(old_get_started.wait(), CONCURRENCY_TIMEOUT)
        with pytest.raises(UniFiConnectionError):
            await client.put("/v1/test-resource", json={"change": True})
        release_old_get.set()

        assert await asyncio.wait_for(old_get, CONCURRENCY_TIMEOUT) == {"version": 1}
        assert await client.get("/v1/test-resource") == {"version": 2}
        assert get_route.call_count == 2

    @respx.mock
    async def test_get_overlapping_cancelled_mutation_cannot_cache_old_response(self):
        ctx = make_ctx('[{"name":"gw","url":"https://10.0.0.1","api_key":"key-gw"}]')
        old_get_started = asyncio.Event()
        release_old_get = asyncio.Event()
        mutation_started = asyncio.Event()
        request_count = 0

        async def get_response(_request):
            nonlocal request_count
            request_count += 1
            if request_count == 1:
                old_get_started.set()
                await asyncio.wait_for(release_old_get.wait(), CONCURRENCY_TIMEOUT)
                return httpx.Response(200, json={"version": 1})
            return httpx.Response(200, json={"version": 2})

        async def mutation_response(_request):
            mutation_started.set()
            await asyncio.Event().wait()

        get_route = respx.get("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=get_response
        )
        respx.put("https://10.0.0.1/proxy/network/integration/v1/test-resource").mock(
            side_effect=mutation_response
        )
        client = UniFiNetworkClient(ctx)

        old_get = asyncio.create_task(client.get("/v1/test-resource"))
        await asyncio.wait_for(old_get_started.wait(), CONCURRENCY_TIMEOUT)
        mutation = asyncio.create_task(client.put("/v1/test-resource", json={"change": True}))
        await asyncio.wait_for(mutation_started.wait(), CONCURRENCY_TIMEOUT)
        mutation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(mutation, CONCURRENCY_TIMEOUT)
        release_old_get.set()

        assert await asyncio.wait_for(old_get, CONCURRENCY_TIMEOUT) == {"version": 1}
        assert await client.get("/v1/test-resource") == {"version": 2}
        assert get_route.call_count == 2

    @respx.mock
    async def test_get_overlapping_auth_retry_mutation_cannot_cache_old_response(self):
        ctx = _local_ctx()
        old_get_started = asyncio.Event()
        release_old_get = asyncio.Event()
        request_count = 0
        resource_url = "https://10.0.0.1/proxy/network/api/s/default/rest/test-resource"

        async def get_response(_request):
            nonlocal request_count
            request_count += 1
            if request_count == 1:
                old_get_started.set()
                await asyncio.wait_for(release_old_get.wait(), CONCURRENCY_TIMEOUT)
                return httpx.Response(200, json={"version": 1})
            return httpx.Response(200, json={"version": 2})

        get_route = respx.get(resource_url).mock(side_effect=get_response)
        mutation_route = respx.put(resource_url).mock(
            side_effect=[
                httpx.Response(401, json={"message": "expired"}),
                httpx.Response(200, json={"accepted": True}),
            ]
        )
        login_route = respx.post("https://10.0.0.1/api/auth/login").respond(200, json={})
        client = UniFiNetworkClient(ctx)
        endpoint = "/api/s/default/rest/test-resource"

        old_get = asyncio.create_task(client.get(endpoint))
        await asyncio.wait_for(old_get_started.wait(), CONCURRENCY_TIMEOUT)
        await client.put(endpoint, json={"change": True})
        release_old_get.set()

        assert await asyncio.wait_for(old_get, CONCURRENCY_TIMEOUT) == {"version": 1}
        assert await client.get(endpoint) == {"version": 2}
        assert get_route.call_count == 2
        assert mutation_route.call_count == 2
        assert login_route.call_count == 1

    @respx.mock
    async def test_create_network(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.post("https://10.0.0.1/proxy/network/api/s/default/rest/networkconf").respond(
            json={"meta": {"rc": "ok"}, "data": [{"_id": "net1", "name": "IoT", "vlan": 50}]}
        )
        client = UniFiNetworkClient(ctx)
        result = await client.create_network({"name": "IoT", "vlan_enabled": True, "vlan": 50})
        assert result["_id"] == "net1"
        assert result["vlan"] == 50

    @respx.mock
    async def test_update_network(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.put("https://10.0.0.1/proxy/network/api/s/default/rest/networkconf/net1").respond(
            json={"meta": {"rc": "ok"}, "data": [{"_id": "net1", "name": "IoT Renamed"}]}
        )
        client = UniFiNetworkClient(ctx)
        result = await client.update_network("net1", {"name": "IoT Renamed"})
        assert result["name"] == "IoT Renamed"

    @respx.mock
    async def test_delete_network(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.delete("https://10.0.0.1/proxy/network/api/s/default/rest/networkconf/net1").respond(
            json={"meta": {"rc": "ok"}}
        )
        client = UniFiNetworkClient(ctx)
        await client.delete_network("net1")


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
        respx.put(
            "https://10.0.0.1/proxy/network/v2/api/site/default/firewall-policies/pol1"
        ).respond(json={"_id": "pol1", "enabled": False})
        client = UniFiNetworkClient(ctx)
        result = await client.update_firewall_policy("pol1", {"enabled": False})
        assert result["enabled"] is False

    @respx.mock
    async def test_delete_firewall_policy(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.delete(
            "https://10.0.0.1/proxy/network/v2/api/site/default/firewall-policies/pol1"
        ).respond(json={"meta": {"rc": "ok"}})
        client = UniFiNetworkClient(ctx)
        await client.delete_firewall_policy("pol1")


PF_DATA = {
    "meta": {"rc": "ok"},
    "data": [
        {
            "_id": "pf1",
            "name": "NAS HTTPS",
            "enabled": True,
            "dst_port": "443",
            "fwd_ip": "192.168.1.100",
            "fwd_port": "443",
            "proto": "tcp",
            "site_id": "default",
        }
    ],
}


class TestPortForwardWrites:
    @respx.mock
    async def test_get_port_forwards(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.get("https://10.0.0.1/proxy/network/api/s/default/rest/portforward").respond(
            json=PF_DATA
        )
        client = UniFiNetworkClient(ctx)
        rules = await client.get_port_forwards()
        assert len(rules) == 1
        assert rules[0]["name"] == "NAS HTTPS"
        assert rules[0]["fwd_port"] == "443"

    @respx.mock
    async def test_create_port_forward(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.post("https://10.0.0.1/proxy/network/api/s/default/rest/portforward").respond(
            json={"meta": {"rc": "ok"}, "data": [{"_id": "pf2", "name": "NVR RTSP"}]}
        )
        client = UniFiNetworkClient(ctx)
        result = await client.create_port_forward({"name": "NVR RTSP", "dst_port": "554"})
        assert result["_id"] == "pf2"

    @respx.mock
    async def test_delete_port_forward(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.delete("https://10.0.0.1/proxy/network/api/s/default/rest/portforward/pf1").respond(
            json={"meta": {"rc": "ok"}}
        )
        client = UniFiNetworkClient(ctx)
        await client.delete_port_forward("pf1")

    @respx.mock
    async def test_empty_port_forwards(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.get("https://10.0.0.1/proxy/network/api/s/default/rest/portforward").respond(
            json={"meta": {"rc": "ok"}, "data": []}
        )
        client = UniFiNetworkClient(ctx)
        rules = await client.get_port_forwards()
        assert rules == []


WPA3_WLAN = {
    "data": [
        {
            "_id": "wpa3test",
            "name": "TestWPA3",
            "essid": "TestWPA3",
            "enabled": True,
            "security": "wpapsk",
            "wpa_mode": "wpa3",
            "wpa_enc": "ccmp",
            "wpa3_support": True,
            "wpa3_transition": True,
            "pmf_mode": "optional",
            "bss_transition": True,
        }
    ]
}


class TestWlanWPA3:
    @respx.mock
    async def test_get_wlans_includes_wpa3_fields(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.get("https://10.0.0.1/proxy/network/api/s/default/rest/wlanconf").respond(
            json=WPA3_WLAN
        )
        client = UniFiNetworkClient(ctx)
        wlans = await client.get_wlans()
        w = wlans[0]
        assert w["wpa3_support"] is True
        assert w["wpa3_transition"] is True
        assert w["pmf_mode"] == "optional"
        assert w["bss_transition"] is True


DEV_PORTS = {
    "meta": {"rc": "ok"},
    "data": [
        {
            "_id": "dev1",
            "mac": "e0:63:da:e1:87:fb",
            "port_table": [
                {"port_idx": 1, "name": "Port 1", "media": "GE", "up": True},
                {"port_idx": 2, "name": "Port 2", "media": "GE", "up": False},
            ],
        }
    ],
}


class TestDevicePortWrites:
    @respx.mock
    async def test_get_device_port_table_fresh_bypasses_cached_response(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        route = respx.get("https://10.0.0.1/proxy/network/api/s/default/stat/device").mock(
            side_effect=[
                httpx.Response(200, json=DEV_PORTS),
                httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "_id": "dev1",
                                "mac": "e0:63:da:e1:87:fb",
                                "port_table": [{"port_idx": 1, "name": "Fresh Port"}],
                            }
                        ]
                    },
                ),
            ]
        )
        client = UniFiNetworkClient(ctx)

        assert (await client.get_device_port_table("e0:63:da:e1:87:fb"))[0]["name"] == "Port 1"
        assert (await client.get_device_port_table("e0:63:da:e1:87:fb"))[0]["name"] == "Port 1"
        fresh = await client.get_device_port_table("e0:63:da:e1:87:fb", fresh=True)
        assert fresh[0]["name"] == "Fresh Port"
        assert route.call_count == 2

    @respx.mock
    async def test_update_device_ports_merges_full_writable_overrides(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        device = {
            "data": [
                {
                    "_id": "dev1",
                    "mac": "e0:63:da:e1:87:fb",
                    "port_table": [
                        {"port_idx": 1, "name": "Operational 1", "up": True, "speed": 1000},
                        {"port_idx": 2, "name": "Operational 2", "up": False, "speed": 0},
                    ],
                    "port_overrides": [
                        {"port_idx": 1, "name": "Existing", "poe_mode": "auto"},
                        {"port_idx": 2, "forward": "all"},
                    ],
                }
            ]
        }
        respx.get("https://10.0.0.1/proxy/network/api/s/default/stat/device").respond(json=device)
        put_route = respx.put(
            "https://10.0.0.1/proxy/network/api/s/default/rest/device/dev1"
        ).respond(json={"meta": {"rc": "ok"}})
        client = UniFiNetworkClient(ctx)
        await client.update_device_ports("e0:63:da:e1:87:fb", [{"port_idx": 1, "name": "Cameras"}])

        payload = json.loads(put_route.calls.last.request.content)
        assert payload == {
            "port_overrides": [
                {"port_idx": 1, "name": "Cameras", "poe_mode": "auto"},
                {"port_idx": 2, "forward": "all"},
            ]
        }
        assert "port_table" not in payload
        assert "up" not in str(payload)
        assert "speed" not in str(payload)

    @respx.mock
    async def test_update_device_ports_fetches_fresh_overrides(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        route = respx.get("https://10.0.0.1/proxy/network/api/s/default/stat/device").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "_id": "dev1",
                                "mac": "e0:63:da:e1:87:fb",
                                "port_table": [{"port_idx": 1}],
                                "port_overrides": [{"port_idx": 1, "name": "Old"}],
                            }
                        ]
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "_id": "dev1",
                                "mac": "e0:63:da:e1:87:fb",
                                "port_table": [{"port_idx": 1}, {"port_idx": 2}],
                                "port_overrides": [
                                    {"port_idx": 1, "name": "Current"},
                                    {"port_idx": 2, "forward": "all"},
                                ],
                            }
                        ]
                    },
                ),
            ]
        )
        put_route = respx.put(
            "https://10.0.0.1/proxy/network/api/s/default/rest/device/dev1"
        ).respond(json={"meta": {"rc": "ok"}})
        client = UniFiNetworkClient(ctx)

        await client.get_device("e0:63:da:e1:87:fb")
        await client.update_device_ports("e0:63:da:e1:87:fb", [{"port_idx": 1, "name": "Cameras"}])

        assert json.loads(put_route.calls.last.request.content) == {
            "port_overrides": [
                {"port_idx": 1, "name": "Cameras"},
                {"port_idx": 2, "forward": "all"},
            ]
        }
        assert route.call_count == 2

    @pytest.mark.parametrize(
        "device, changes, expected",
        [
            (
                {"mac": "e0:63:da:e1:87:fb", "port_table": [{"port_idx": 1}]},
                [{"port_idx": 1, "name": "Cameras"}],
                "stable ID",
            ),
            (
                {"_id": "dev1", "mac": "e0:63:da:e1:87:fb"},
                [{"port_idx": 1, "name": "Cameras"}],
                "port table",
            ),
            (
                {"_id": "dev1", "mac": "e0:63:da:e1:87:fb", "port_table": [{"port_idx": 1}]},
                [{"port_idx": 2, "name": "Cameras"}],
                "does not exist",
            ),
            (
                {"_id": "dev1", "mac": "e0:63:da:e1:87:fb", "port_table": [{"port_idx": 1}]},
                [{"port_idx": 1}],
                "No valid port changes",
            ),
        ],
    )
    @respx.mock
    async def test_update_device_ports_rejects_unsafe_device_state_without_put(
        self, device, changes, expected
    ):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.get("https://10.0.0.1/proxy/network/api/s/default/stat/device").respond(
            json={"data": [device]}
        )
        put_route = respx.put(url__regex=r".*/rest/device/.*").respond(json={})
        client = UniFiNetworkClient(ctx)

        with pytest.raises(UniFiAPIError, match=expected):
            await client.update_device_ports("e0:63:da:e1:87:fb", changes)

        assert put_route.called is False

    @pytest.mark.parametrize("operational_field", ["up", "speed", "media", "unknown"])
    @respx.mock
    async def test_update_device_ports_rejects_non_writable_keys_without_put(
        self, operational_field
    ):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.get("https://10.0.0.1/proxy/network/api/s/default/stat/device").respond(
            json={
                "data": [
                    {
                        "_id": "dev1",
                        "mac": "e0:63:da:e1:87:fb",
                        "port_table": [{"port_idx": 1}],
                        "port_overrides": [{"port_idx": 1, "name": "Existing"}],
                    }
                ]
            }
        )
        put_route = respx.put(url__regex=r".*/rest/device/.*").respond(json={})
        client = UniFiNetworkClient(ctx)

        with pytest.raises(UniFiAPIError, match="writable"):
            await client.update_device_ports(
                "e0:63:da:e1:87:fb",
                [{"port_idx": 1, operational_field: "unsafe"}],
            )

        assert put_route.called is False

    @pytest.mark.parametrize("duplicate_source", ["existing", "requested"])
    @respx.mock
    async def test_update_device_ports_rejects_duplicate_indexes_without_put(
        self, duplicate_source
    ):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        overrides = [{"port_idx": 1, "name": "Existing"}]
        changes = [{"port_idx": 1, "name": "Cameras"}]
        if duplicate_source == "existing":
            overrides.append({"port_idx": 1, "poe_mode": "auto"})
        else:
            changes.append({"port_idx": 1, "poe_mode": "auto"})
        respx.get("https://10.0.0.1/proxy/network/api/s/default/stat/device").respond(
            json={
                "data": [
                    {
                        "_id": "dev1",
                        "mac": "e0:63:da:e1:87:fb",
                        "port_table": [{"port_idx": 1}],
                        "port_overrides": overrides,
                    }
                ]
            }
        )
        put_route = respx.put(url__regex=r".*/rest/device/.*").respond(json={})
        client = UniFiNetworkClient(ctx)

        with pytest.raises(UniFiAPIError, match="duplicate.*port_idx"):
            await client.update_device_ports("e0:63:da:e1:87:fb", changes)

        assert put_route.called is False

    @respx.mock
    async def test_get_device_port_table(self):
        ctx = _local_ctx()
        respx.get("https://10.0.0.1/api/auth/login").respond(200, json={})
        respx.get("https://10.0.0.1/proxy/network/api/s/default/stat/device").respond(
            json=DEV_PORTS
        )
        client = UniFiNetworkClient(ctx)
        ports = await client.get_device_port_table("e0:63:da:e1:87:fb")
        assert len(ports) == 2
        assert ports[0]["port_idx"] == 1
