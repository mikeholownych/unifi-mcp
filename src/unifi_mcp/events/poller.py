"""Bounded, failure-isolated event polling orchestration."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from unifi_mcp.events.sources import EventSource
from unifi_mcp.runtime.events import EventRepository


@dataclass(frozen=True)
class SourcePollOutcome:
    """Redacted result for one configured source."""

    source: str
    device_name: str
    site: str
    status: Literal["ok", "error", "timeout"]
    inserted: int = 0
    duplicates: int = 0
    error_code: str | None = None


@dataclass(frozen=True)
class PollSummary:
    """Aggregate polling result."""

    sources: list[SourcePollOutcome]

    @property
    def inserted(self) -> int:
        return sum(source.inserted for source in self.sources)

    @property
    def duplicates(self) -> int:
        return sum(source.duplicates for source in self.sources)

    @property
    def failed_sources(self) -> int:
        return sum(source.status != "ok" for source in self.sources)


class EventPoller:
    """Poll event sources concurrently while committing each source independently."""

    def __init__(
        self,
        repository: EventRepository,
        *,
        timeout_seconds: float = 30,
        max_concurrency: int = 4,
        jitter_seconds: float = 0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._repository = repository
        self._timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._jitter_seconds = max(0, jitter_seconds)
        self._sleep = sleep
        self._jitter = jitter

    async def _poll_source(self, source: EventSource) -> SourcePollOutcome:
        async with self._semaphore:
            try:
                if self._jitter_seconds:
                    await self._sleep(self._jitter(0, self._jitter_seconds))
                cursor = await self._repository.get_cursor(
                    source.source, source.device_name, source.site
                )
                async with asyncio.timeout(self._timeout_seconds):
                    batch = await source.poll(cursor)
                result = await self._repository.insert_batch(
                    batch.events,
                    source=source.source,
                    device_name=source.device_name,
                    site=source.site,
                    cursor=batch.cursor,
                )
            except TimeoutError:
                return SourcePollOutcome(
                    source=source.source,
                    device_name=source.device_name,
                    site=source.site,
                    status="timeout",
                    error_code="TimeoutError",
                )
            except Exception as exc:
                return SourcePollOutcome(
                    source=source.source,
                    device_name=source.device_name,
                    site=source.site,
                    status="error",
                    error_code=type(exc).__name__,
                )

        return SourcePollOutcome(
            source=source.source,
            device_name=source.device_name,
            site=source.site,
            status="ok",
            inserted=result.inserted,
            duplicates=result.duplicates,
        )

    async def poll(self, sources: list[EventSource]) -> PollSummary:
        """Poll all configured sources, preserving source result order."""
        outcomes = await asyncio.gather(*(self._poll_source(source) for source in sources))
        return PollSummary(sources=list(outcomes))
