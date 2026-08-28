"""Capability-aware aggregate observation collectors."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from unifi_mcp.clients.network import is_device_online, is_wireless_client
from unifi_mcp.observability.models import (
    ClientCountMetrics,
    DeviceCountMetrics,
    Observation,
    ProtectHealthMetrics,
    SiteHealthMetrics,
    TrafficMetrics,
)


@dataclass(frozen=True)
class CollectionLimitation:
    source: str
    controller: str
    site: str
    error_code: str


@dataclass
class ObservationCollection:
    observations: list[Observation] = field(default_factory=list)
    limitations: list[CollectionLimitation] = field(default_factory=list)


class ObservationSource(Protocol):
    source: str
    controller: str
    site: str

    async def collect(self, observed_at: datetime) -> list[Observation]: ...


class NetworkObservationSource:
    source = "network"

    def __init__(self, client: Any, *, controller: str, site: str) -> None:
        self._client = client
        self.controller = controller
        self.site = site

    async def collect(self, observed_at: datetime) -> list[Observation]:
        health, devices, clients = await asyncio.gather(
            self._client.get_site_health(self.site),
            self._client.get_devices_basic(self.site),
            self._client.get_clients(self.site),
        )
        healthy = sum(item.get("status") == "ok" for item in health)
        online = sum(is_device_online(item) for item in devices)
        wireless = sum(is_wireless_client(item) for item in clients)
        rx_bytes = sum(max(0, float(item.get("rx_bytes", 0) or 0)) for item in clients)
        tx_bytes = sum(max(0, float(item.get("tx_bytes", 0) or 0)) for item in clients)
        wan = next((item for item in health if item.get("subsystem") == "wan"), None)
        scope = {
            "source": "network",
            "controller": self.controller,
            "site": self.site,
            "observed_at": observed_at,
        }
        return [
            Observation(
                **scope,
                kind="site_health",
                status="ok" if healthy == len(health) else "issues",
                metrics=SiteHealthMetrics(
                    subsystem_total=len(health),
                    healthy=healthy,
                    issues=len(health) - healthy,
                    wan_up=wan.get("status") == "ok" if wan else None,
                ),
            ),
            Observation(
                **scope,
                kind="device_counts",
                status="ok" if online == len(devices) else "issues",
                metrics=DeviceCountMetrics(
                    total=len(devices), online=online, offline=len(devices) - online
                ),
            ),
            Observation(
                **scope,
                kind="client_counts",
                status="ok",
                metrics=ClientCountMetrics(
                    total=len(clients), wired=len(clients) - wireless, wireless=wireless
                ),
            ),
            Observation(
                **scope,
                kind="traffic",
                status="ok",
                metrics=TrafficMetrics(rx_bytes=rx_bytes, tx_bytes=tx_bytes),
            ),
        ]


class ProtectObservationSource:
    source = "protect"
    site = ""

    def __init__(self, client: Any, *, controller: str) -> None:
        self._client = client
        self.controller = controller

    async def collect(self, observed_at: datetime) -> list[Observation]:
        cameras = await self._client.get_cameras()
        online = sum(
            bool(camera.get("isConnected"))
            or str(camera.get("state", "")).lower() in {"connected", "online"}
            for camera in cameras
        )
        return [
            Observation(
                source="protect",
                controller=self.controller,
                kind="protect_health",
                status="ok" if online == len(cameras) else "issues",
                observed_at=observed_at,
                metrics=ProtectHealthMetrics(
                    total=len(cameras), online=online, offline=len(cameras) - online
                ),
            )
        ]


class ObservationCollector:
    def __init__(self, sources: list[ObservationSource], *, max_concurrency: int = 4) -> None:
        self._sources = sources
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _collect_one(
        self, source: ObservationSource, observed_at: datetime
    ) -> ObservationCollection:
        async with self._semaphore:
            try:
                observations = await source.collect(observed_at)
            except Exception as exc:
                return ObservationCollection(
                    limitations=[
                        CollectionLimitation(
                            source=source.source,
                            controller=source.controller,
                            site=source.site,
                            error_code=type(exc).__name__,
                        )
                    ]
                )
        return ObservationCollection(observations=observations)

    async def collect(self, *, observed_at: datetime | None = None) -> ObservationCollection:
        timestamp = (observed_at or datetime.now(UTC)).astimezone(UTC)
        results = await asyncio.gather(
            *(self._collect_one(source, timestamp) for source in self._sources)
        )
        return ObservationCollection(
            observations=[item for result in results for item in result.observations],
            limitations=[item for result in results for item in result.limitations],
        )
