"""Safety-contract tests for network mutation tools."""

import inspect
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient
from unifi_mcp.config import UniFiSettings
from unifi_mcp.exceptions import UniFiConnectionError, UniFiDeliveryUnknownError
from unifi_mcp.tools.network import clients as client_tools
from unifi_mcp.tools.network import devices, sites
from unifi_mcp.tools.network._verification import verify_eventually


class FakeMutationClient:
    """Stateful controller fake that separates mutation acceptance from persistence."""

    def __init__(self) -> None:
        self.ctx = SimpleNamespace(
            settings=SimpleNamespace(
                mutation_verify_attempts=5,
                mutation_verify_initial_delay=0,
                mutation_verify_max_delay=0,
            )
        )
        self.networks = [
            {
                "_id": "net-1",
                "name": "IoT",
                "purpose": "corporate",
                "vlan_enabled": True,
                "vlan": 50,
                "ip_subnet": "192.168.50.1/24",
                "dhcpd_enabled": True,
                "dhcpd_start": "192.168.50.10",
                "dhcpd_stop": "192.168.50.200",
                "dhcpd_leasetime": 86400,
                "enabled": True,
            }
        ]
        self.ports = [{"port_idx": 1, "name": "Port 1", "enabled": True}]
        self.persist_mutations = True
        self.return_created_id = True
        self.raise_on_readback = False
        self.mutation_accepted = False
        self.network_creates: list[dict] = []
        self.network_updates: list[dict] = []
        self.network_update_ids: list[str] = []
        self.network_deletes: list[str | None] = []
        self.port_updates: list[dict] = []
        self.network_reads: list[bool] = []
        self.port_reads: list[bool] = []
        self.stale_network_reads = 0
        self.stale_port_reads = 0
        self._networks_before_mutation: list[dict] = []
        self._ports_before_mutation: list[dict] = []

    def _readback(self) -> None:
        if self.mutation_accepted and self.raise_on_readback:
            raise RuntimeError("read-back unavailable")

    async def get_networks(self, site: str = "default", *, fresh: bool = False) -> list[dict]:
        self._readback()
        self.network_reads.append(fresh)
        if self.mutation_accepted and self.stale_network_reads:
            self.stale_network_reads -= 1
            return deepcopy(self._networks_before_mutation)
        return deepcopy(self.networks)

    async def create_network(self, data: dict, site: str = "default") -> dict:
        self._networks_before_mutation = deepcopy(self.networks)
        self.mutation_accepted = True
        self.network_creates.append(deepcopy(data))
        created = {**data}
        if self.return_created_id:
            created["_id"] = "net-created"
        if self.persist_mutations:
            self.networks.append(created)
        return deepcopy(created)

    async def update_network(self, network_id: str, data: dict, site: str = "default") -> dict:
        self._networks_before_mutation = deepcopy(self.networks)
        self.mutation_accepted = True
        self.network_updates.append(deepcopy(data))
        self.network_update_ids.append(network_id)
        if self.persist_mutations:
            for network in self.networks:
                if network.get("_id") == network_id:
                    network.update(data)
                    return deepcopy(network)
        return {"_id": network_id, **data}

    async def delete_network(self, network_id: str, site: str = "default") -> None:
        self._networks_before_mutation = deepcopy(self.networks)
        self.mutation_accepted = True
        self.network_deletes.append(network_id)
        if self.persist_mutations:
            self.networks = [n for n in self.networks if n.get("_id") != network_id]

    async def update_device_ports(
        self, mac: str, changes: list[dict], site: str = "default"
    ) -> dict:
        self._ports_before_mutation = deepcopy(self.ports)
        self.mutation_accepted = True
        self.port_updates.extend(deepcopy(changes))
        if self.persist_mutations:
            for change in changes:
                for port in self.ports:
                    if port.get("port_idx") == change.get("port_idx"):
                        port.update(change)
        return {}

    async def get_device_port_table(
        self, mac: str, site: str = "default", *, fresh: bool = False
    ) -> list[dict]:
        self._readback()
        self.port_reads.append(fresh)
        if self.mutation_accepted and self.stale_port_reads:
            self.stale_port_reads -= 1
            return deepcopy(self._ports_before_mutation)
        return deepcopy(self.ports)


def make_real_port_mutation_client() -> UniFiNetworkClient:
    settings = UniFiSettings(
        _env_file=None,
        mode="local",
        controller_url="https://10.0.0.1",
        username="admin",
        password="password",
    )
    context = AppContext(client=AsyncMock(), settings=settings, cache={}, auth=Mock())
    return UniFiNetworkClient(context)


@pytest.mark.parametrize(
    ("module", "tool", "arguments", "warning"),
    [
        (
            devices,
            devices.set_device_port,
            {"mac": "aa:bb:cc:dd:ee:ff", "port_idx": 1, "name": "Cameras"},
            "disrupt",
        ),
        (sites, sites.create_network, {"name": "Cameras"}, "disrupt"),
        (sites, sites.update_network, {"name": "IoT", "enabled": False}, "disrupt"),
    ],
)
async def test_mutation_requires_confirmation_before_client_resolution(
    module, tool, arguments, warning
):
    get_client = Mock(side_effect=AssertionError("client must not be resolved"))

    with patch.object(module, "_get_client", get_client):
        result = await tool(object(), **arguments)

    assert result["success"] is False
    assert "confirm=true" in result["message"]
    assert warning in result["message"].lower()
    get_client.assert_not_called()


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"dhcp_lease_time": 7200}, {"dhcpd_leasetime": 7200}),
        ({"dhcp_start": "192.168.50.20"}, {"dhcpd_start": "192.168.50.20"}),
        ({"dhcp_stop": "192.168.50.210"}, {"dhcpd_stop": "192.168.50.210"}),
        (
            {"dhcp_start": "", "dhcp_stop": ""},
            {"dhcpd_enabled": False, "dhcpd_start": "", "dhcpd_stop": ""},
        ),
        (
            {"dhcp_start": "192.168.50.20", "dhcp_stop": "192.168.50.210"},
            {
                "dhcpd_enabled": True,
                "dhcpd_start": "192.168.50.20",
                "dhcpd_stop": "192.168.50.210",
            },
        ),
    ],
)
async def test_update_network_dhcp_partial_updates_preserve_enable_state(kwargs, expected):
    client = FakeMutationClient()

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_network(object(), "IoT", confirm=True, **kwargs)

    assert result["success"] is True
    assert client.network_updates == [expected]


async def test_update_network_rejects_one_empty_dhcp_endpoint():
    client = FakeMutationClient()
    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_network(object(), "IoT", dhcp_start="", confirm=True)

    assert result["success"] is False
    assert "valid ip" in result["message"].lower()
    assert client.network_updates == []


async def test_update_network_rejects_dhcp_pool_when_effective_subnet_is_unknown():
    client = FakeMutationClient()
    client.networks[0].pop("ip_subnet")
    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_network(
            object(),
            "IoT",
            dhcp_start="192.168.50.10",
            dhcp_stop="192.168.50.20",
            confirm=True,
        )

    assert result["success"] is False
    assert "known effective subnet" in result["message"].lower()
    assert client.network_updates == []


async def test_update_network_rejects_subnet_that_strands_existing_dhcp_pool():
    client = FakeMutationClient()
    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_network(object(), "IoT", subnet="192.168.60.1/24", confirm=True)

    assert result["success"] is False
    assert "existing dhcp" in result["message"].lower()
    assert "new subnet" in result["message"].lower()
    assert client.network_updates == []


async def test_update_network_accepts_subnet_containing_existing_dhcp_pool():
    client = FakeMutationClient()
    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_network(
            object(), "IoT", subnet="192.168.50.254/24", confirm=True
        )

    assert result["success"] is True
    assert client.network_updates == [{"ip_subnet": "192.168.50.254/24"}]


async def test_set_device_port_confirms_and_returns_verified_observation():
    client = FakeMutationClient()

    with patch.object(devices, "_get_client", return_value=client):
        result = await devices.set_device_port(
            object(), "aa:bb:cc:dd:ee:ff", 1, name="Cameras", confirm=True
        )

    assert result["success"] is True
    assert result["changes"] == {"name": "Cameras"}
    assert client.port_reads == [True]


async def test_set_device_port_without_changes_does_not_mutate():
    client = FakeMutationClient()

    with patch.object(devices, "_get_client", return_value=client):
        result = await devices.set_device_port(object(), "aa:bb:cc:dd:ee:ff", 1, confirm=True)

    assert result["success"] is False
    assert "at least one" in result["message"].lower()
    assert client.port_updates == []


@pytest.mark.parametrize("native_network", ["", "   \t"])
async def test_set_device_port_rejects_blank_native_network_before_client_resolution(
    native_network,
):
    get_client = Mock(side_effect=AssertionError("client must not be resolved"))

    with patch.object(devices, "_get_client", get_client):
        result = await devices.set_device_port(
            object(),
            "aa:bb:cc:dd:ee:ff",
            1,
            native_network=native_network,
            confirm=True,
        )

    assert result["success"] is False
    assert "native_network" in result["message"]
    assert "nonblank" in result["message"]
    get_client.assert_not_called()


@pytest.mark.parametrize("failure", ["missing", "readback"])
async def test_set_device_port_rejects_unverified_mutation(failure):
    client = FakeMutationClient()
    client.persist_mutations = False
    client.raise_on_readback = failure == "readback"

    with patch.object(devices, "_get_client", return_value=client):
        result = await devices.set_device_port(
            object(), "aa:bb:cc:dd:ee:ff", 1, name="Cameras", confirm=True
        )

    assert result["success"] is False
    assert result["status"] == "accepted_unverified"
    assert result["accepted"] is True
    assert result["retry_safe"] is False
    if failure == "missing":
        assert result["requested"] == {"name": "Cameras"}
        assert result["observed"] == {"name": "Port 1"}


async def test_set_device_port_preflight_connection_failure_is_safe_to_retry():
    secret = "preflight-secret-token"
    client = make_real_port_mutation_client()
    client.get_device = AsyncMock(side_effect=UniFiConnectionError(secret))
    client.put = AsyncMock()

    with patch.object(devices, "_get_client", return_value=client):
        result = await devices.set_device_port(
            object(), "aa:bb:cc:dd:ee:ff", 1, name="Cameras", confirm=True
        )

    assert result["success"] is False
    assert result["status"] == "preflight_failed"
    assert result["accepted"] is False
    assert result["retry_safe"] is True
    assert "before dispatch" in result["message"].lower()
    assert secret not in str(result)
    client.get_device.assert_awaited_once_with("aa:bb:cc:dd:ee:ff", "default", fresh=True)
    client.put.assert_not_awaited()


async def test_set_device_port_put_connection_failure_has_unknown_delivery():
    secret = "put-secret-token"
    client = make_real_port_mutation_client()
    client.get_device = AsyncMock(
        return_value={
            "_id": "device-1",
            "port_table": [{"port_idx": 1}],
            "port_overrides": [],
        }
    )
    client.put = AsyncMock(side_effect=UniFiConnectionError(secret))

    with patch.object(devices, "_get_client", return_value=client):
        result = await devices.set_device_port(
            object(), "aa:bb:cc:dd:ee:ff", 1, name="Cameras", confirm=True
        )

    assert result["success"] is False
    assert result["status"] == "delivery_unknown"
    assert result["accepted"] is None
    assert result["retry_safe"] is False
    assert secret not in str(result)
    client.get_device.assert_awaited_once_with("aa:bb:cc:dd:ee:ff", "default", fresh=True)
    client.put.assert_awaited_once()


async def test_create_network_confirms_and_returns_verified_observation():
    client = FakeMutationClient()

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.create_network(object(), "Cameras", vlan=60, confirm=True)

    assert result == {
        "success": True,
        "name": "Cameras",
        "network_id": "net-created",
        "purpose": "corporate",
        "vlan": 60,
        "subnet": None,
    }
    assert client.network_creates == [
        {
            "name": "Cameras",
            "purpose": "corporate",
            "vlan_enabled": True,
            "vlan": 60,
            "dhcpd_enabled": False,
        }
    ]
    assert client.network_reads == [True]


@pytest.mark.parametrize(
    "dhcp",
    [
        {"dhcp_start": "192.168.60.10"},
        {"dhcp_stop": "192.168.60.200"},
        {"dhcp_lease_time": 7200},
    ],
)
async def test_create_network_rejects_partial_dhcp_without_api_call(dhcp):
    client = FakeMutationClient()

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.create_network(object(), "Cameras", vlan=60, confirm=True, **dhcp)

    assert result["success"] is False
    assert "dhcp_start" in result["message"]
    assert "dhcp_stop" in result["message"]
    assert client.network_creates == []
    assert client.mutation_accepted is False


async def test_create_network_without_returned_id_fails_verification():
    client = FakeMutationClient()
    client.return_created_id = False

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.create_network(object(), "Cameras", vlan=60, confirm=True)

    assert result["success"] is False
    assert result["status"] == "accepted_unverified"
    assert result["accepted"] is True
    assert result["retry_safe"] is False
    assert "stable id" in result["message"].lower()
    assert "duplicate" in result["message"].lower()
    assert result["requested"]["name"] == "Cameras"
    assert result["observed"] is None


async def test_create_network_same_name_with_different_id_fails_verification():
    client = FakeMutationClient()
    client.persist_mutations = False
    client.networks.append(
        {
            "_id": "different-network",
            "name": "Cameras",
            "purpose": "corporate",
            "vlan_enabled": True,
            "vlan": 60,
            "dhcpd_enabled": False,
        }
    )

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.create_network(object(), "Cameras", vlan=60, confirm=True)

    assert result["success"] is False
    assert result["status"] == "accepted_unverified"
    assert result["accepted"] is True
    assert result["retry_safe"] is False
    assert result["requested"]["name"] == "Cameras"
    assert result["observed"] is None


@pytest.mark.parametrize("failure", ["missing", "readback"])
async def test_create_network_rejects_unverified_mutation(failure):
    client = FakeMutationClient()
    client.persist_mutations = False
    client.raise_on_readback = failure == "readback"

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.create_network(object(), "Cameras", vlan=60, confirm=True)

    assert result["success"] is False
    assert result["status"] == "accepted_unverified"
    assert result["accepted"] is True
    assert result["retry_safe"] is False
    assert "duplicate" in result["message"].lower()
    if failure == "missing":
        assert result["requested"]["name"] == "Cameras"
        assert result["observed"] is None


async def test_update_network_confirms_and_returns_verified_normalized_values():
    client = FakeMutationClient()

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_network(
            object(), "IoT", name_new="Devices", enabled=False, confirm=True
        )

    assert result["success"] is True
    assert result["name"] == "Devices"
    assert result["network_id"] == "net-1"
    assert result["enabled"] is False
    assert client.network_reads == [True, True]


async def test_update_network_without_stable_id_does_not_mutate():
    client = FakeMutationClient()
    client.networks[0].pop("_id")

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_network(object(), "IoT", enabled=False, confirm=True)

    assert result["success"] is False
    assert "stable id" in result["message"].lower()
    assert client.network_updates == []


@pytest.mark.parametrize("failure", ["mismatch", "readback"])
async def test_update_network_rejects_unverified_mutation(failure):
    client = FakeMutationClient()
    client.persist_mutations = False
    client.raise_on_readback = failure == "readback"

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_network(object(), "IoT", enabled=False, confirm=True)

    assert result["success"] is False
    assert result["status"] == "accepted_unverified"
    assert result["accepted"] is True
    assert result["retry_safe"] is False
    if failure == "mismatch":
        assert result["requested"] == {"enabled": False}
        assert result["observed"] == {"enabled": True}


async def test_delete_network_succeeds_only_after_verified_absence():
    client = FakeMutationClient()

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.delete_network(object(), "IoT", confirm=True)

    assert result == {"success": True, "message": "Network 'IoT' deleted"}
    assert client.network_reads == [True, True]


@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_network_mutation_resolves_reused_name_from_fresh_state(operation):
    client = FakeMutationClient()
    stale = deepcopy(client.networks)
    client.networks[0]["_id"] = "net-2"

    async def get_networks(site="default", *, fresh=False):
        client._readback()
        client.network_reads.append(fresh)
        return deepcopy(client.networks if fresh else stale)

    client.get_networks = get_networks
    with patch.object(sites, "_get_client", return_value=client):
        if operation == "update":
            result = await sites.update_network(object(), "IoT", enabled=False, confirm=True)
        else:
            result = await sites.delete_network(object(), "IoT", confirm=True)

    assert result["success"] is True
    assert client.network_reads[0] is True
    if operation == "update":
        assert client.network_update_ids == ["net-2"]
    else:
        assert client.network_deletes == ["net-2"]


async def test_port_native_network_resolution_uses_fresh_state():
    client = FakeMutationClient()
    stale = deepcopy(client.networks)
    client.networks[0]["_id"] = "net-2"

    async def get_networks(site="default", *, fresh=False):
        client.network_reads.append(fresh)
        return deepcopy(client.networks if fresh else stale)

    client.get_networks = get_networks
    with patch.object(devices, "_get_client", return_value=client):
        result = await devices.set_device_port(
            object(),
            "aa:bb:cc:dd:ee:ff",
            1,
            native_network="IoT",
            confirm=True,
        )

    assert result["success"] is True
    assert client.network_reads == [True]
    assert client.port_updates == [
        {
            "port_idx": 1,
            "native_networkconf_id": "net-2",
            "setting_preference": "manual",
        }
    ]


async def test_wlan_mutation_resolves_name_from_fresh_state():
    class FakeWlanClient:
        def __init__(self):
            self.reads = []
            self.updated_id = None

        async def get_wlans(self, site="default", *, fresh=False):
            self.reads.append(fresh)
            return [{"_id": "wlan-2" if fresh else "wlan-1", "name": "Office"}]

        async def update_wlan(self, wlan_id, data, site="default"):
            self.updated_id = wlan_id
            return {"_id": wlan_id, "name": "Office", **data}

    client = FakeWlanClient()
    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_wlan(object(), "Office", enabled=False)

    assert result["success"] is True
    assert client.reads == [True]
    assert client.updated_id == "wlan-2"


async def test_reserve_client_ip_resolves_name_from_fresh_state():
    class FakeClientLookup:
        def __init__(self):
            self.reads = []
            self.updated_id = None

        async def get_all_clients(self, site="default", *, fresh=False):
            self.reads.append(fresh)
            client_id = "client-2" if fresh else "client-1"
            return [{"_id": client_id, "name": "Printer", "mac": "aa:bb", "ip": "10.0.0.2"}]

        async def set_client_fixed_ip(self, client_id, ip, site="default"):
            self.updated_id = client_id
            return {"fixed_ip": ip}

    client = FakeClientLookup()
    with patch.object(client_tools, "_get_client", return_value=client):
        result = await client_tools.reserve_client_ip(object(), "Printer")

    assert result["success"] is True
    assert client.reads == [True]
    assert client.updated_id == "client-2"


async def test_delete_network_without_stable_id_does_not_mutate():
    client = FakeMutationClient()
    client.networks[0].pop("_id")

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.delete_network(object(), "IoT", confirm=True)

    assert result["success"] is False
    assert "stable id" in result["message"].lower()
    assert client.network_deletes == []


@pytest.mark.parametrize("failure", ["still-present", "readback"])
async def test_delete_network_rejects_unverified_mutation(failure):
    client = FakeMutationClient()
    client.persist_mutations = False
    client.raise_on_readback = failure == "readback"

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.delete_network(object(), "IoT", confirm=True)

    assert result["success"] is False
    assert result["status"] == "accepted_unverified"
    assert result["accepted"] is True
    assert result["retry_safe"] is False
    if failure == "still-present":
        assert result["observed"]["network_id"] == "net-1"


@pytest.mark.parametrize("operation", ["create", "update", "delete", "port"])
async def test_mutation_verification_retries_stale_read_until_converged(operation):
    client = FakeMutationClient()
    if operation == "port":
        client.stale_port_reads = 1
        with (
            patch.object(devices, "_get_client", return_value=client),
            patch("asyncio.sleep") as sleep,
        ):
            result = await devices.set_device_port(
                object(), "aa:bb:cc:dd:ee:ff", 1, name="Cameras", confirm=True
            )
        assert client.port_reads == [True, True]
    else:
        client.stale_network_reads = 1
        with (
            patch.object(sites, "_get_client", return_value=client),
            patch("asyncio.sleep") as sleep,
        ):
            if operation == "create":
                result = await sites.create_network(object(), "Cameras", vlan=60, confirm=True)
            elif operation == "update":
                result = await sites.update_network(object(), "IoT", enabled=False, confirm=True)
            else:
                result = await sites.delete_network(object(), "IoT", confirm=True)
        assert client.network_reads[-2:] == [True, True]

    assert result["success"] is True
    sleep.assert_awaited_once()


async def test_verification_uses_exponential_capped_backoff_until_exhausted():
    reads = 0

    async def fetch():
        nonlocal reads
        reads += 1
        return "stale"

    with patch("unifi_mcp.tools.network._verification.asyncio.sleep") as sleep:
        result = await verify_eventually(
            fetch,
            lambda value: (False, value),
            operation="test mutation",
            logger=Mock(),
            attempts=5,
            initial_delay=0.5,
            max_delay=2.0,
        )

    assert result.matched is False
    assert reads == 5
    assert [call.args[0] for call in sleep.await_args_list] == [0.5, 1.0, 2.0, 2.0]


async def test_verification_converges_after_multiple_stale_reads():
    observations = iter(["stale-1", "stale-2", "fresh"])

    with patch("unifi_mcp.tools.network._verification.asyncio.sleep") as sleep:
        result = await verify_eventually(
            lambda: _next_async(observations),
            lambda value: (value == "fresh", value),
            operation="test mutation",
            logger=Mock(),
            attempts=5,
            initial_delay=0.25,
            max_delay=1.0,
        )

    assert result.matched is True
    assert result.observed == "fresh"
    assert [call.args[0] for call in sleep.await_args_list] == [0.25, 0.5]


async def _next_async(values):
    return next(values)


@pytest.mark.parametrize("tool", [sites.create_network, sites.update_network])
@pytest.mark.parametrize("endpoint", ["dhcp_start", "dhcp_stop"])
@pytest.mark.parametrize(
    ("address", "boundary"),
    [
        ("192.168.50.1", "gateway"),
        ("192.168.50.0", "network"),
        ("192.168.50.255", "broadcast"),
    ],
)
async def test_network_mutations_reject_reserved_dhcp_boundaries(tool, endpoint, address, boundary):
    client = FakeMutationClient()
    kwargs = {
        "name": "Cameras" if tool is sites.create_network else "IoT",
        "subnet": "192.168.50.1/24",
        "dhcp_start": "192.168.50.2",
        "dhcp_stop": "192.168.50.254",
        "confirm": True,
    }
    kwargs[endpoint] = address

    with patch.object(sites, "_get_client", return_value=client):
        result = await tool(object(), **kwargs)

    assert result["success"] is False
    assert boundary in result["message"].lower()
    assert result.get("accepted") is not True
    assert client.network_creates == []
    assert client.network_updates == []


@pytest.mark.parametrize("tool", [sites.create_network, sites.update_network])
async def test_network_mutations_accept_nearest_valid_dhcp_hosts(tool):
    client = FakeMutationClient()
    kwargs = {
        "name": "Cameras" if tool is sites.create_network else "IoT",
        "subnet": "192.168.50.1/24",
        "dhcp_start": "192.168.50.2",
        "dhcp_stop": "192.168.50.254",
        "confirm": True,
    }

    with patch.object(sites, "_get_client", return_value=client):
        result = await tool(object(), **kwargs)

    assert result["success"] is True


async def test_validation_and_controller_rejection_do_not_claim_acceptance():
    validation = await sites.create_network(object(), " ", confirm=True)
    client = FakeMutationClient()

    async def reject(*args, **kwargs):
        raise RuntimeError("controller rejection")

    client.update_network = reject
    with patch.object(sites, "_get_client", return_value=client):
        rejection = await sites.update_network(object(), "IoT", enabled=False, confirm=True)

    assert validation.get("accepted") is not True
    assert rejection.get("accepted") is not True
    assert validation.get("status") != "accepted_unverified"
    assert rejection.get("status") != "accepted_unverified"


@pytest.mark.parametrize("operation", ["create", "update", "delete", "port"])
async def test_mutation_connection_failure_reports_delivery_unknown_without_readback(operation):
    secret = "controller-token=top-secret"
    client = FakeMutationClient()

    async def delivery_unknown(*args, **kwargs):
        raise UniFiConnectionError(secret)

    if operation == "create":
        client.create_network = delivery_unknown
        module = sites
        call = sites.create_network(object(), "Cameras", vlan=60, confirm=True)
    elif operation == "update":
        client.update_network = delivery_unknown
        module = sites
        call = sites.update_network(object(), "IoT", enabled=False, confirm=True)
    elif operation == "delete":
        client.delete_network = delivery_unknown
        module = sites
        call = sites.delete_network(object(), "IoT", confirm=True)
    else:

        async def port_delivery_unknown(*args, **kwargs):
            raise UniFiDeliveryUnknownError(secret)

        client.update_device_ports = port_delivery_unknown
        module = devices
        call = devices.set_device_port(
            object(), "aa:bb:cc:dd:ee:ff", 1, name="Cameras", confirm=True
        )

    with patch.object(module, "_get_client", return_value=client):
        result = await call

    assert result["success"] is False
    assert result["status"] == "delivery_unknown"
    assert result["accepted"] is None
    assert result["retry_safe"] is False
    assert "controller outcome is unknown" in result["message"].lower()
    assert "inspect current state before retrying" in result["message"].lower()
    assert "rejected" not in result["message"].lower()
    assert secret not in str(result)
    assert client.port_reads == []
    assert client.network_reads == ([True] if operation in {"update", "delete"} else [])
    if operation == "create":
        assert "duplicate" in result["message"].lower()


async def test_update_network_verification_accepts_normalized_values():
    client = FakeMutationClient()

    async def normalized_update(network_id, data, site="default"):
        client.mutation_accepted = True
        client.network_updates.append(deepcopy(data))
        client.networks[0].update(
            {
                "name": "  Devices  ",
                "vlan_enabled": True,
                "vlan": "60",
                "ip_subnet": "2001:0db8:0000:0000:0000:0000:0000:0001/64",
                "dhcpd_start": "2001:0db8:0000:0000:0000:0000:0000:0010",
                "dhcpd_stop": "2001:0db8:0000:0000:0000:0000:0000:0200",
                "dhcpd_leasetime": "7200",
            }
        )

    client.update_network = normalized_update
    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_network(
            object(),
            "IoT",
            name_new="Devices",
            vlan=60,
            subnet="2001:db8::1/64",
            dhcp_start="2001:db8::10",
            dhcp_stop="2001:db8::200",
            dhcp_lease_time=7200,
            confirm=True,
        )

    assert result["success"] is True
    assert result["name"] == "Devices"
    assert result["vlan"] == 60
    assert result["dhcp_lease_time"] == 7200


async def test_update_network_vlan_disable_does_not_require_stale_vlan_value_to_clear():
    client = FakeMutationClient()

    async def disable_vlan(network_id, data, site="default"):
        client.mutation_accepted = True
        client.network_updates.append(deepcopy(data))
        client.networks[0]["vlan_enabled"] = False

    client.update_network = disable_vlan
    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_network(object(), "IoT", vlan=-1, confirm=True)

    assert result["success"] is True


async def test_update_network_verification_does_not_treat_integer_zero_as_false():
    client = FakeMutationClient()

    async def persist_integer_boolean(network_id, data, site="default"):
        client.mutation_accepted = True
        client.network_updates.append(deepcopy(data))
        client.networks[0]["enabled"] = 0

    client.update_network = persist_integer_boolean
    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_network(object(), "IoT", enabled=False, confirm=True)

    assert result["success"] is False
    assert result["category"] == "verification_failed"


@pytest.mark.parametrize(
    ("tool", "kwargs", "message"),
    [
        (sites.create_network, {"name": " "}, "name must be nonblank"),
        (sites.create_network, {"name": "x", "purpose": "vpn"}, "purpose must be"),
        (sites.create_network, {"name": "x", "vlan": 0}, "vlan must be between 1 and 4094"),
        (sites.create_network, {"name": "x", "vlan": 4095}, "vlan must be between 1 and 4094"),
        (sites.create_network, {"name": "x", "subnet": "not-cidr"}, "subnet must be"),
        (sites.create_network, {"name": "x", "dhcp_lease_time": 0}, "positive"),
        (
            sites.create_network,
            {
                "name": "x",
                "subnet": "192.168.1.1/24",
                "dhcp_start": "192.168.2.10",
                "dhcp_stop": "192.168.2.20",
            },
            "within the effective subnet",
        ),
        (
            sites.create_network,
            {"name": "x", "dhcp_start": "192.168.1.20", "dhcp_stop": "192.168.1.10"},
            "effective subnet",
        ),
        (
            sites.create_network,
            {
                "name": "x",
                "subnet": "192.168.1.1/24",
                "dhcp_start": "192.168.1.20",
                "dhcp_stop": "192.168.1.10",
            },
            "less than or equal",
        ),
        (
            sites.create_network,
            {
                "name": "x",
                "subnet": "192.168.1.1/24",
                "dhcp_start": "invalid",
                "dhcp_stop": "192.168.1.20",
            },
            "valid ip addresses",
        ),
        (sites.update_network, {"name": "x", "name_new": " "}, "name_new must be nonblank"),
        (sites.update_network, {"name": "x", "vlan": 0}, "vlan must be -1 or between"),
        (sites.update_network, {"name": "x", "dhcp_lease_time": -1}, "positive"),
    ],
)
async def test_network_validation_rejects_before_client_resolution(tool, kwargs, message):
    get_client = Mock(side_effect=AssertionError("client must not be resolved"))
    with patch.object(sites, "_get_client", get_client):
        result = await tool(object(), confirm=True, **kwargs)

    assert result["success"] is False
    assert message in result["message"].lower()
    get_client.assert_not_called()


@pytest.mark.parametrize(
    ("tool", "vlan"),
    [
        (sites.create_network, True),
        (sites.create_network, False),
        (sites.update_network, True),
        (sites.update_network, False),
    ],
)
async def test_network_vlan_rejects_boolean_before_client_resolution(tool, vlan):
    get_client = Mock(side_effect=AssertionError("client must not be resolved"))
    with patch.object(sites, "_get_client", get_client):
        result = await tool(object(), name="IoT", vlan=vlan, confirm=True)

    assert result["success"] is False
    assert "vlan must be an integer" in result["message"].lower()
    assert "bool" in result["message"].lower()
    get_client.assert_not_called()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mac": "not-a-mac", "port_idx": 1, "name": "x"}, "mac must be"),
        ({"mac": "aa:bb:cc:dd:ee:ff", "port_idx": 0, "name": "x"}, "positive"),
        ({"mac": "aa:bb:cc:dd:ee:ff", "port_idx": 1, "name": " "}, "name must be nonblank"),
        ({"mac": "aa:bb:cc:dd:ee:ff", "port_idx": 1, "poe_mode": "smart"}, "poe_mode must be"),
        ({"mac": "aa:bb:cc:dd:ee:ff", "port_idx": 1, "forward": "none"}, "forward must be"),
    ],
)
async def test_port_validation_rejects_before_client_resolution(kwargs, message):
    get_client = Mock(side_effect=AssertionError("client must not be resolved"))
    with patch.object(devices, "_get_client", get_client):
        result = await devices.set_device_port(object(), confirm=True, **kwargs)

    assert result["success"] is False
    assert message in result["message"].lower()
    get_client.assert_not_called()


@pytest.mark.parametrize("enabled", [0, 1, "true", "false"])
async def test_port_enabled_rejects_non_boolean_before_client_resolution(enabled):
    get_client = Mock(side_effect=AssertionError("client must not be resolved"))
    with patch.object(devices, "_get_client", get_client):
        result = await devices.set_device_port(
            object(),
            "aa:bb:cc:dd:ee:ff",
            1,
            enabled=enabled,
            confirm=True,
        )

    assert result["success"] is False
    assert "enabled must be a boolean" in result["message"].lower()
    get_client.assert_not_called()


@pytest.mark.parametrize("tool", [sites.update_network, sites.delete_network])
async def test_duplicate_network_name_requires_stable_id_without_mutation(tool):
    client = FakeMutationClient()
    duplicate = deepcopy(client.networks[0])
    duplicate["_id"] = "net-2"
    client.networks.append(duplicate)

    with patch.object(sites, "_get_client", return_value=client):
        result = await tool(
            object(),
            "iot",
            confirm=True,
            **({"enabled": False} if tool is sites.update_network else {}),
        )

    assert result["success"] is False
    assert "ambiguous" in result["message"].lower()
    assert "stable id" in result["message"].lower()
    assert client.network_updates == []
    assert client.network_deletes == []


async def test_exact_network_id_wins_over_duplicate_names():
    client = FakeMutationClient()
    duplicate = deepcopy(client.networks[0])
    duplicate["_id"] = "net-2"
    client.networks.append(duplicate)

    with patch.object(sites, "_get_client", return_value=client):
        result = await sites.update_network(object(), "net-1", enabled=False, confirm=True)

    assert result["success"] is True
    assert client.network_updates == [{"enabled": False}]


async def test_duplicate_native_network_name_requires_id_without_port_mutation():
    client = FakeMutationClient()
    client.networks.append({"_id": "net-2", "name": "IoT"})
    with patch.object(devices, "_get_client", return_value=client):
        result = await devices.set_device_port(
            object(),
            "aa:bb:cc:dd:ee:ff",
            1,
            native_network="iot",
            confirm=True,
        )

    assert result["success"] is False
    assert "ambiguous" in result["message"].lower()
    assert "stable id" in result["message"].lower()
    assert client.port_updates == []


@pytest.mark.parametrize("operation", ["network", "port", "verification"])
async def test_mutation_errors_are_redacted(operation):
    secret = "secret-body-at-10.0.0.1-for-net-1"
    client = FakeMutationClient()
    if operation == "network":

        async def reject(*args, **kwargs):
            raise RuntimeError(secret)

        client.update_network = reject
        tool = sites.update_network
        args = (object(), "IoT")
        kwargs = {"enabled": False, "confirm": True}
        module = sites
    elif operation == "port":

        async def reject(*args, **kwargs):
            raise RuntimeError(secret)

        client.update_device_ports = reject
        tool = devices.set_device_port
        args = (object(), "aa:bb:cc:dd:ee:ff", 1)
        kwargs = {"name": "Cameras", "confirm": True}
        module = devices
    else:
        client.raise_on_readback = True
        tool = sites.update_network
        args = (object(), "IoT")
        kwargs = {"enabled": False, "confirm": True}
        module = sites

    with patch.object(module, "_get_client", return_value=client):
        result = await tool(*args, **kwargs)

    assert result["success"] is False
    assert secret not in str(result)
    assert "check server logs" in result["message"].lower()


def test_confirm_parameters_follow_legacy_site_and_device_parameters():
    from unifi_mcp import server

    for tool in (
        sites.create_network,
        sites.update_network,
        sites.delete_network,
        devices.set_device_port,
        server.create_network,
        server.update_network,
        server.delete_network,
        server.set_device_port,
    ):
        parameters = list(inspect.signature(tool).parameters)
        assert parameters.index("site") < parameters.index("device") < parameters.index("confirm")
