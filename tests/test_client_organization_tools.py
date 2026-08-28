"""MCP behavior for local client organization."""

from types import SimpleNamespace

import pytest

from unifi_mcp.runtime.client_organization import ClientOrganizationRepository, stable_client_key
from unifi_mcp.runtime.store import RuntimeStore
from unifi_mcp.tools import client_organization as tools


def context_for(app):
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app))


class FakeNetworkClient:
    def __init__(self, clients):
        self.clients = clients
        self.device = SimpleNamespace(name="gateway")
        self.site = "default"

    async def get_all_clients(self, _site):
        return self.clients


@pytest.fixture
async def app(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    try:
        yield SimpleNamespace(
            runtime_services=SimpleNamespace(
                client_organization=ClientOrganizationRepository(store)
            ),
            settings=SimpleNamespace(default_device_name="default"),
        )
    finally:
        await store.close()


async def test_mutation_requires_confirmation_without_controller_read(app, monkeypatch):
    called = False

    def network_client(*_args):
        nonlocal called
        called = True
        return FakeNetworkClient([])

    monkeypatch.setattr(tools, "_network_client", network_client)
    result = await tools.set_client_tags(context_for(app), "camera", ["iot"])

    assert result["confirmed"] is False
    assert called is False


async def test_ambiguous_name_is_rejected_without_persistence(app, monkeypatch):
    client = FakeNetworkClient(
        [
            {"mac": "00:00:00:00:00:01", "name": "camera"},
            {"mac": "00:00:00:00:00:02", "hostname": "CAMERA"},
        ]
    )
    monkeypatch.setattr(tools, "_network_client", lambda *_args: client)

    with pytest.raises(ValueError, match="ambiguous"):
        await tools.set_client_tags(context_for(app), "camera", ["iot"], confirm=True)

    assert (
        await app.runtime_services.client_organization.list_client_keys(
            controller="gateway", site="default", tag="iot"
        )
        == []
    )


async def test_tags_survive_client_rename(app, monkeypatch):
    client = FakeNetworkClient([{"mac": "aa:bb:cc:dd:ee:ff", "name": "Old Name"}])
    monkeypatch.setattr(tools, "_network_client", lambda *_args: client)
    ctx = context_for(app)

    await tools.set_client_tags(ctx, "Old Name", ["trusted"], confirm=True)
    client.clients = [{"mac": "aa:bb:cc:dd:ee:ff", "name": "New Name"}]
    result = await tools.get_client_organization(ctx, "New Name")

    assert result["client"]["name"] == "New Name"
    assert result["organization"]["client_key"] == stable_client_key(
        "gateway", "default", "aa:bb:cc:dd:ee:ff"
    )
    assert result["organization"]["tags"] == ["trusted"]


async def test_tools_report_unavailable_without_runtime(mock_ctx):
    result = await tools.get_client_organization(context_for(mock_ctx), "aa:bb:cc:dd:ee:ff")

    assert result["available"] is False
    assert "UNIFI_RUNTIME_ENABLED" in result["reason"]
