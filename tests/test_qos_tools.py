"""Capability-gated QoS MCP tool tests."""

from types import SimpleNamespace

import pytest

from unifi_mcp.runtime.client_organization import ClientOrganizationRepository, stable_client_key
from unifi_mcp.runtime.qos import QoSPlanRepository
from unifi_mcp.runtime.store import RuntimeStore
from unifi_mcp.tools import qos as tools


def context_for(app):
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app))


class FakeNetworkClient:
    def __init__(self, clients=None):
        self.clients = clients or []
        self.device = SimpleNamespace(name="gateway")
        self.site = "default"
        self.mutation_calls = 0

    async def get_all_clients(self, _site):
        return self.clients


@pytest.fixture
async def app(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    try:
        yield SimpleNamespace(
            runtime_services=SimpleNamespace(
                client_organization=ClientOrganizationRepository(store),
                qos_plans=QoSPlanRepository(store),
            ),
            settings=SimpleNamespace(default_device_name="default", mode="local"),
        )
    finally:
        await store.close()


async def test_capabilities_explain_unsupported_controller_qos(mock_ctx):
    result = await tools.get_client_qos_capabilities(context_for(mock_ctx))

    assert result["supported"] is False
    assert result["mutation_available"] is False
    assert "validated" in result["guidance"]


async def test_tag_plan_persists_deterministic_current_target_set(app, monkeypatch):
    client = FakeNetworkClient()
    monkeypatch.setattr(tools, "_network_client", lambda *_args: client)
    repository = app.runtime_services.client_organization
    await repository.replace_tags(
        controller="gateway", site="default", client_key="ff:00:00:00:00:02", tags=["iot"]
    )
    await repository.replace_tags(
        controller="gateway", site="default", client_key="ff:00:00:00:00:01", tags=["iot"]
    )

    result = await tools.plan_client_qos_policy(
        context_for(app),
        selector_type="tag",
        selector_value="iot",
        download_kbps=10_000,
        upload_kbps=2_000,
    )

    assert result["supported"] is False
    assert [target["client_key"] for target in result["plan"]["targets"]] == sorted(
        [
            stable_client_key("gateway", "default", "ff:00:00:00:00:01"),
            stable_client_key("gateway", "default", "ff:00:00:00:00:02"),
        ]
    )
    assert await app.runtime_services.qos_plans.get(result["plan"]["token"])


async def test_unsupported_apply_makes_no_mutation_attempt(app, monkeypatch):
    client = FakeNetworkClient()
    monkeypatch.setattr(tools, "_network_client", lambda *_args: client)
    plan = await app.runtime_services.qos_plans.create(
        controller="gateway",
        site="default",
        selector_type="client",
        selector_value="aa:bb:cc:dd:ee:ff",
        download_kbps=1000,
        upload_kbps=500,
        client_keys=["aa:bb:cc:dd:ee:ff"],
    )

    result = await tools.apply_client_qos_policy(context_for(app), plan["token"], confirm=True)

    assert result["success"] is False
    assert result["supported"] is False
    assert result["mutation_attempted"] is False
    assert client.mutation_calls == 0


async def test_plan_requires_runtime(mock_ctx):
    result = await tools.plan_client_qos_policy(
        context_for(mock_ctx), "client", "aa:bb:cc:dd:ee:ff", 1000, 500
    )

    assert result["available"] is False
