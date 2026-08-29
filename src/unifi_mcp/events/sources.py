"""Capability-based polling adapters for UniFi event APIs."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from unifi_mcp.events.models import NormalizedEvent
from unifi_mcp.events.normalize import normalize_network_event, normalize_protect_event


@dataclass(frozen=True)
class PollBatch:
    """One complete page from an event source."""

    events: list[NormalizedEvent]
    cursor: dict[str, object]
    capability: Literal["polling", "native_push"] = "polling"


class EventSource(Protocol):
    """A configured source that can produce normalized events."""

    source: str
    device_name: str
    site: str

    async def poll(self, cursor: dict[str, object] | None) -> PollBatch: ...


def _cursor_for(
    events: list[NormalizedEvent], previous: dict[str, object] | None
) -> dict[str, object]:
    if not events:
        return dict(previous or {})
    watermark_ms = max(round(event.occurred_at.timestamp() * 1000) for event in events)
    return {"watermark_ms": watermark_ms}


class NetworkEventSource:
    """Poll the bounded recent-event window exposed by traditional Network APIs."""

    source = "network"

    def __init__(self, client: Any, *, device_name: str, site: str) -> None:
        self._client = client
        self.device_name = device_name
        self.site = site

    async def poll(self, cursor: dict[str, object] | None) -> PollBatch:
        raw_events = await self._client.get_events(3000, self.site)
        if len(raw_events) >= 3000:
            raise RuntimeError(
                "Network event window reached its 3000-event limit; refusing to advance the cursor"
            )
        events = [
            normalize_network_event(raw, device_name=self.device_name, site=self.site)
            for raw in raw_events
        ]
        return PollBatch(events=events, cursor=_cursor_for(events, cursor))


class ProtectEventSource:
    """Poll Protect events incrementally with a deduplication overlap window."""

    source = "protect"
    site = ""

    def __init__(
        self,
        client: Any,
        *,
        device_name: str,
        overlap_ms: int = 60_000,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client = client
        self.device_name = device_name
        self._overlap_ms = overlap_ms
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))

    async def poll(self, cursor: dict[str, object] | None) -> PollBatch:
        end = self._now_ms()
        previous = (cursor or {}).get("watermark_ms")
        start = int(previous) - self._overlap_ms if previous is not None else end - 86_400_000
        raw_events = await self._client.get_events(start=start, end=end, limit=1000)
        if len(raw_events) >= 1000:
            raise RuntimeError(
                "Protect event window reached its 1000-event limit; refusing to advance the cursor"
            )
        events = [normalize_protect_event(raw, device_name=self.device_name) for raw in raw_events]
        return PollBatch(events=events, cursor=_cursor_for(events, cursor))
