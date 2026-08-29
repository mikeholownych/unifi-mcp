"""Tests for isolated multi-source event polling."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from unifi_mcp.events.models import NormalizedEvent
from unifi_mcp.events.poller import EventPoller
from unifi_mcp.events.sources import PollBatch
from unifi_mcp.runtime import RuntimeStore
from unifi_mcp.runtime.events import EventRepository


async def test_poller_persists_success_without_advancing_failed_source(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    repository = EventRepository(store)
    successful = SimpleNamespace(
        source="network",
        device_name="gateway",
        site="default",
        poll=AsyncMock(
            return_value=PollBatch(
                events=[
                    NormalizedEvent(
                        source="network",
                        source_key="event-1",
                        device_name="gateway",
                        site="default",
                        category="network.connected",
                        severity="info",
                        occurred_at=datetime(2026, 8, 28, 12, tzinfo=UTC),
                        summary="Connected",
                    )
                ],
                cursor={"watermark_ms": 100},
            )
        ),
    )
    failed = SimpleNamespace(
        source="protect",
        device_name="console",
        site="",
        poll=AsyncMock(side_effect=RuntimeError("password=must-not-leak")),
    )
    sleep = AsyncMock()

    try:
        summary = await EventPoller(
            repository,
            timeout_seconds=1,
            jitter_seconds=0.5,
            sleep=sleep,
            jitter=lambda _minimum, _maximum: 0.25,
        ).poll([successful, failed])
        network_cursor = await repository.get_cursor("network", "gateway", "default")
        protect_cursor = await repository.get_cursor("protect", "console", "")
    finally:
        await store.close()

    assert summary.inserted == 1
    assert summary.failed_sources == 1
    assert [outcome.status for outcome in summary.sources] == ["ok", "error"]
    assert summary.sources[1].error_code == "RuntimeError"
    assert "must-not-leak" not in repr(summary)
    assert network_cursor == {"watermark_ms": 100}
    assert protect_cursor is None
    assert [call.args for call in sleep.await_args_list] == [(0.25,), (0.25,)]
