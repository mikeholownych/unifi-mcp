"""Tests for normalized event persistence."""

from datetime import UTC, datetime

from unifi_mcp.events.models import NormalizedEvent
from unifi_mcp.events.normalize import normalize_network_event, normalize_protect_event
from unifi_mcp.runtime import RuntimeStore
from unifi_mcp.runtime.events import EventRepository


async def test_insert_batch_deduplicates_and_advances_cursor(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    repository = EventRepository(store)
    event = NormalizedEvent(
        source="network",
        source_key="controller-event-1",
        device_name="gateway",
        site="default",
        category="client.connected",
        severity="info",
        occurred_at=datetime(2026, 8, 28, 12, tzinfo=UTC),
        summary="Client connected",
        subject_type="client",
        subject_id="client-1",
        details={"ssid": "Office"},
    )

    try:
        first = await repository.insert_batch(
            [event],
            source="network",
            device_name="gateway",
            site="default",
            cursor={"time": 100},
        )
        second = await repository.insert_batch(
            [event],
            source="network",
            device_name="gateway",
            site="default",
            cursor={"time": 200},
        )
        cursor = await repository.get_cursor("network", "gateway", "default")
        persisted = await repository.list_events(limit=10)
    finally:
        await store.close()

    assert first.inserted == 1
    assert first.duplicates == 0
    assert second.inserted == 0
    assert second.duplicates == 1
    assert cursor == {"time": 200}
    assert len(persisted) == 1
    assert persisted[0].source_key == "controller-event-1"
    assert persisted[0].details == {"ssid": "Office"}


async def test_source_keys_are_scoped_to_controller(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    repository = EventRepository(store)

    def event(device_name: str) -> NormalizedEvent:
        return NormalizedEvent(
            source="protect",
            source_key="controller-local-id",
            device_name=device_name,
            category="protect.motion",
            severity="info",
            occurred_at=datetime(2026, 8, 28, 12, tzinfo=UTC),
            summary="Motion",
        )

    try:
        first = await repository.insert_batch(
            [event("office")], source="protect", device_name="office", cursor={}
        )
        second = await repository.insert_batch(
            [event("warehouse")], source="protect", device_name="warehouse", cursor={}
        )
    finally:
        await store.close()

    assert first.inserted == 1
    assert second.inserted == 1


def test_network_normalization_uses_stable_fallback_key_and_redacts_secrets():
    raw = {
        "time": 1787918400000,
        "key": "EVT_WU_Connected",
        "msg": "Client joined password=hunter2",
        "hostname": "laptop",
        "ssid": "Office",
        "metadata": {"api_key": "must-not-persist"},
    }

    first = normalize_network_event(raw, device_name="gateway", site="default")
    second = normalize_network_event(
        dict(reversed(raw.items())), device_name="gateway", site="default"
    )

    assert first.source_key == second.source_key
    assert first.category == "network.evt_wu_connected"
    assert first.summary == "Client joined password=[REDACTED]"
    assert first.details == {"hostname": "laptop", "ssid": "Office"}


def test_protect_normalization_preserves_detection_metadata_only():
    event = normalize_protect_event(
        {
            "id": "protect-event-1",
            "type": "smartDetect",
            "start": 1787918400000,
            "camera": "camera-1",
            "smartDetectTypes": ["person"],
            "score": 87,
            "cookie": "must-not-persist",
        },
        device_name="console",
    )

    assert event.source_key == "protect-event-1"
    assert event.category == "protect.smart_detection"
    assert event.subject_type == "camera"
    assert event.subject_id == "camera-1"
    assert event.details == {"smart_detect_types": ["person"], "score": 87}
