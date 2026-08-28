"""Tests for capability-based polling adapters."""

from unittest.mock import AsyncMock

from unifi_mcp.events.sources import NetworkEventSource, ProtectEventSource


async def test_network_source_polls_bounded_recent_window():
    client = AsyncMock()
    client.get_events.return_value = [
        {"_id": "network-1", "time": 1787918400000, "key": "EVT_AP_Connected"}
    ]
    source = NetworkEventSource(client, device_name="gateway", site="default")

    batch = await source.poll({"watermark_ms": 1787918300000})

    client.get_events.assert_awaited_once_with(3000, "default")
    assert batch.capability == "polling"
    assert [event.source_key for event in batch.events] == ["network-1"]
    assert batch.cursor == {"watermark_ms": 1787918400000}


async def test_protect_source_uses_cursor_overlap_window():
    client = AsyncMock()
    client.get_events.return_value = [
        {"id": "protect-1", "start": 1787918400000, "type": "motion", "camera": "cam-1"}
    ]
    source = ProtectEventSource(
        client,
        device_name="console",
        overlap_ms=5000,
        now_ms=lambda: 1787918500000,
    )

    batch = await source.poll({"watermark_ms": 1787918390000})

    client.get_events.assert_awaited_once_with(
        start=1787918385000,
        end=1787918500000,
        limit=1000,
    )
    assert [event.source_key for event in batch.events] == ["protect-1"]
    assert batch.cursor == {"watermark_ms": 1787918400000}
