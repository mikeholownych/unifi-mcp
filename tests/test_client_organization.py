"""Local client tag and group repository tests."""

import sqlite3

import pytest

from unifi_mcp.runtime.client_organization import ClientOrganizationRepository, stable_client_key
from unifi_mcp.runtime.store import RuntimeStore


@pytest.fixture
async def repository(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    try:
        yield ClientOrganizationRepository(store)
    finally:
        await store.close()


async def test_tags_use_normalized_stable_identity_and_replace_atomically(repository):
    await repository.replace_tags(
        controller="gateway", site="default", client_key="AA-BB-CC-DD-EE-FF", tags=["iot", "VIP"]
    )
    result = await repository.replace_tags(
        controller="gateway", site="default", client_key="aabbccddeeff", tags=["trusted"]
    )

    assert result == {
        "controller": "gateway",
        "site": "default",
        "client_key": stable_client_key("gateway", "default", "aa:bb:cc:dd:ee:ff"),
        "tags": ["trusted"],
        "group": None,
    }
    assert "aa:bb:cc:dd:ee:ff" not in repr(result)


async def test_client_has_at_most_one_group_and_group_delete_cascades(repository):
    await repository.create_group(controller="gateway", site="default", name="Cameras")
    await repository.create_group(controller="gateway", site="default", name="Guests")
    await repository.assign_group(
        controller="gateway", site="default", client_key="aa:bb:cc:dd:ee:ff", name="Cameras"
    )
    result = await repository.assign_group(
        controller="gateway", site="default", client_key="aa:bb:cc:dd:ee:ff", name="Guests"
    )

    assert result["group"]["name"] == "Guests"
    assert (
        await repository.list_client_keys(controller="gateway", site="default", group="Cameras")
        == []
    )
    assert await repository.list_client_keys(
        controller="gateway", site="default", group="Guests"
    ) == [stable_client_key("gateway", "default", "aa:bb:cc:dd:ee:ff")]

    assert await repository.delete_group(controller="gateway", site="default", name="Guests")
    assert (
        await repository.get_client(
            controller="gateway", site="default", client_key="aa:bb:cc:dd:ee:ff"
        )
    )["group"] is None


async def test_queries_are_scoped_and_deterministic(repository):
    await repository.replace_tags(
        controller="gateway", site="default", client_key="ff:00:00:00:00:02", tags=["iot"]
    )
    await repository.replace_tags(
        controller="gateway", site="default", client_key="ff:00:00:00:00:01", tags=["iot"]
    )
    await repository.replace_tags(
        controller="other", site="default", client_key="00:00:00:00:00:01", tags=["iot"]
    )

    assert await repository.list_client_keys(
        controller="gateway", site="default", tag="IOT"
    ) == sorted(
        [
            stable_client_key("gateway", "default", "ff:00:00:00:00:01"),
            stable_client_key("gateway", "default", "ff:00:00:00:00:02"),
        ]
    )


@pytest.mark.parametrize("client_key", ["", "not-a-mac", "aa:bb:cc:dd:ee"])
async def test_invalid_client_identity_is_rejected_without_writes(repository, client_key):
    with pytest.raises(ValueError, match="MAC"):
        await repository.replace_tags(
            controller="gateway", site="default", client_key=client_key, tags=["iot"]
        )

    assert await repository.list_client_keys(controller="gateway", site="default", tag="iot") == []


async def test_raw_mac_never_enters_persistence(tmp_path):
    database_path = tmp_path / "runtime.db"
    store = RuntimeStore(database_path)
    await store.open()
    repository = ClientOrganizationRepository(store)
    await repository.replace_tags(
        controller="gateway", site="default", client_key="aa:bb:cc:dd:ee:ff", tags=["iot"]
    )
    await store.close()

    with sqlite3.connect(database_path) as connection:
        database_dump = "\n".join(connection.iterdump())

    assert "aa:bb:cc:dd:ee:ff" not in database_dump.lower()
    assert "aabbccddeeff" not in database_dump.lower()
