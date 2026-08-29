"""Durable deterministic QoS policy plan tests."""

from datetime import UTC, datetime, timedelta

import pytest

from unifi_mcp.runtime.client_organization import stable_client_key
from unifi_mcp.runtime.qos import QoSPlanRepository
from unifi_mcp.runtime.store import RuntimeStore


@pytest.fixture
async def repository(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    try:
        yield QoSPlanRepository(store)
    finally:
        await store.close()


async def test_plan_target_snapshot_is_sorted_deduplicated_and_durable(repository):
    plan = await repository.create(
        controller="gateway",
        site="default",
        selector_type="tag",
        selector_value="iot",
        download_kbps=10_000,
        upload_kbps=2_000,
        client_keys=["ff:00:00:00:00:02", "ff:00:00:00:00:01", "ff:00:00:00:00:02"],
    )
    restored = await repository.get(plan["token"])

    assert restored == plan
    assert "ff:00:00:00:00" not in repr(restored)
    expected = sorted(
        [
            stable_client_key("gateway", "default", "ff:00:00:00:00:01"),
            stable_client_key("gateway", "default", "ff:00:00:00:00:02"),
        ]
    )
    assert restored["targets"] == [
        {"client_key": client_key, "position": position, "status": "pending"}
        for position, client_key in enumerate(expected)
    ]


async def test_identical_preview_has_deterministic_target_hash_but_unique_token(repository):
    arguments = {
        "controller": "gateway",
        "site": "default",
        "selector_type": "client",
        "selector_value": "aa:bb:cc:dd:ee:ff",
        "download_kbps": 1000,
        "upload_kbps": 500,
        "client_keys": ["aa:bb:cc:dd:ee:ff"],
    }
    first = await repository.create(**arguments)
    second = await repository.create(**arguments)

    assert first["token"] != second["token"]
    assert first["targets_hash"] == second["targets_hash"]
    assert first["selector_value"].startswith("sha256:")


async def test_expired_plan_cannot_be_loaded_for_apply(repository):
    plan = await repository.create(
        controller="gateway",
        site="default",
        selector_type="client",
        selector_value="aa:bb:cc:dd:ee:ff",
        download_kbps=1000,
        upload_kbps=500,
        client_keys=["aa:bb:cc:dd:ee:ff"],
        now=datetime.now(UTC) - timedelta(hours=2),
    )

    with pytest.raises(ValueError, match="expired"):
        await repository.get_for_apply(plan["token"])
