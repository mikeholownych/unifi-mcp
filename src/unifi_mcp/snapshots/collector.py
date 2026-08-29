"""Capability-aware collection into the portable snapshot schema."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from unifi_mcp.snapshots.models import (
    DeviceSnapshot,
    FirewallSnapshot,
    NetworkSnapshot,
    SnapshotContent,
    SnapshotDocument,
    SnapshotLimitation,
    SourceScope,
    WlanSnapshot,
)


@dataclass
class SnapshotFragment:
    devices: list[DeviceSnapshot] = field(default_factory=list)
    networks: list[NetworkSnapshot] = field(default_factory=list)
    wlans: list[WlanSnapshot] = field(default_factory=list)
    firewall: list[FirewallSnapshot] = field(default_factory=list)
    limitations: list[SnapshotLimitation] = field(default_factory=list)
    status: str = "complete"


class SnapshotSource(Protocol):
    source: str
    device_name: str
    site: str
    mode: str

    async def collect(self) -> SnapshotFragment: ...


class NetworkSnapshotSource:
    source = "network"

    def __init__(self, client: Any, *, device_name: str, site: str, mode: str = "api") -> None:
        self._client = client
        self.device_name = device_name
        self.site = site
        self.mode = mode

    async def collect(self) -> SnapshotFragment:
        results = await asyncio.gather(
            self._client.get_devices_basic(self.site),
            self._client.get_networks(self.site, fresh=True),
            self._client.get_wlans(self.site, fresh=True),
            self._client.get_firewall_rules(self.site),
            self._client.get_firewall_policies(self.site),
            return_exceptions=True,
        )
        limitations = []
        values: list[list[dict[str, Any]]] = []
        for area, result in zip(
            ("devices", "networks", "wlans", "firewall_rules", "firewall_policies"),
            results,
            strict=True,
        ):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                limitations.append(
                    SnapshotLimitation(
                        source="network",
                        device_name=self.device_name,
                        site=self.site,
                        code=type(result).__name__,
                        summary=f"{area} collection unavailable",
                    )
                )
                values.append([])
            else:
                values.append(result)
        devices_raw, networks_raw, wlans_raw, rules_raw, policies_raw = values
        devices = [
            DeviceSnapshot(
                id=str(item.get("id") or item.get("_id") or item.get("mac")),
                name=str(item.get("name") or item.get("hostname") or item.get("mac")),
                service="network",
                controller=self.device_name,
                site=self.site,
                kind=item.get("type"),
                model=item.get("model"),
                state=str(item["state"]) if item.get("state") is not None else None,
            )
            for item in devices_raw
            if item.get("id") or item.get("_id") or item.get("mac")
        ]
        networks = [
            NetworkSnapshot(
                id=str(item.get("id") or item.get("_id")),
                name=str(item.get("name") or item.get("id") or item.get("_id")),
                controller=self.device_name,
                site=self.site,
                purpose=item.get("purpose"),
                subnet=item.get("subnet") or item.get("ip_subnet"),
                vlan=item.get("vlan") or item.get("vlan_id"),
            )
            for item in networks_raw
            if item.get("id") or item.get("_id")
        ]
        wlans = [
            WlanSnapshot(
                id=str(item.get("id") or item.get("_id")),
                name=str(item.get("name") or item.get("id") or item.get("_id")),
                controller=self.device_name,
                site=self.site,
                enabled=bool(item.get("enabled", True)),
                security=item.get("security") or item.get("security_protocol"),
                hidden=bool(item.get("hide_ssid", False)),
            )
            for item in wlans_raw
            if item.get("id") or item.get("_id")
        ]
        firewall = [
            FirewallSnapshot(
                id=str(item.get("id") or item.get("_id")),
                name=str(item.get("name") or item.get("id") or item.get("_id")),
                controller=self.device_name,
                site=self.site,
                kind=kind,
                action=item.get("action"),
                enabled=bool(item.get("enabled", True)),
            )
            for kind, items in (("rule", rules_raw), ("policy", policies_raw))
            for item in items
            if item.get("id") or item.get("_id")
        ]
        return SnapshotFragment(
            devices=devices,
            networks=networks,
            wlans=wlans,
            firewall=firewall,
            limitations=limitations,
            status="partial" if limitations else "complete",
        )


class ProtectSnapshotSource:
    source = "protect"
    site = ""

    def __init__(self, client: Any, *, device_name: str, mode: str = "api") -> None:
        self._client = client
        self.device_name = device_name
        self.mode = mode

    async def collect(self) -> SnapshotFragment:
        cameras = await self._client.get_cameras()
        return SnapshotFragment(
            devices=[
                DeviceSnapshot(
                    id=str(item.get("id") or item.get("_id")),
                    name=str(item.get("name") or item.get("id") or item.get("_id")),
                    service="protect",
                    controller=self.device_name,
                    kind="camera",
                    model=item.get("type") or item.get("modelKey"),
                    state=str(item["state"]) if item.get("state") is not None else None,
                )
                for item in cameras
                if item.get("id") or item.get("_id")
            ]
        )


class UnsupportedSnapshotSource:
    """Represent a configured service whose required read API is unavailable."""

    def __init__(
        self, *, source: str, device_name: str, site: str, mode: str, summary: str
    ) -> None:
        self.source = source
        self.device_name = device_name
        self.site = site
        self.mode = mode
        self._summary = summary

    async def collect(self) -> SnapshotFragment:
        return SnapshotFragment(
            status="unsupported",
            limitations=[
                SnapshotLimitation(
                    source=self.source,
                    device_name=self.device_name,
                    site=self.site,
                    code="capability_unavailable",
                    summary=self._summary,
                )
            ],
        )


class SnapshotCollector:
    def __init__(self, sources: list[SnapshotSource], *, max_concurrency: int = 4) -> None:
        self._sources = sources
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _collect_source(
        self, source: SnapshotSource
    ) -> tuple[SourceScope, SnapshotFragment, SnapshotLimitation | None]:
        async with self._semaphore:
            try:
                fragment = await source.collect()
            except Exception as exc:
                return (
                    SourceScope(
                        source=source.source,
                        device_name=source.device_name,
                        site=source.site,
                        mode=source.mode,
                        status="failed",
                    ),
                    SnapshotFragment(),
                    SnapshotLimitation(
                        source=source.source,
                        device_name=source.device_name,
                        site=source.site,
                        code=type(exc).__name__,
                        summary="Source collection failed",
                    ),
                )
        return (
            SourceScope(
                source=source.source,
                device_name=source.device_name,
                site=source.site,
                mode=source.mode,
                status=fragment.status,
            ),
            fragment,
            None,
        )

    async def collect(self, *, generated_at: datetime | None = None) -> SnapshotDocument:
        results = await asyncio.gather(*(self._collect_source(source) for source in self._sources))
        return SnapshotDocument(
            generated_at=generated_at or datetime.now(UTC),
            content=SnapshotContent(
                sources=[result[0] for result in results],
                # Source-local limitations preserve successful sibling endpoints.
                limitations=[
                    *[result[2] for result in results if result[2] is not None],
                    *[
                        limitation
                        for _, fragment, _ in results
                        for limitation in fragment.limitations
                    ],
                ],
                devices=[item for _, fragment, _ in results for item in fragment.devices],
                networks=[item for _, fragment, _ in results for item in fragment.networks],
                wlans=[item for _, fragment, _ in results for item in fragment.wlans],
                firewall=[item for _, fragment, _ in results for item in fragment.firewall],
            ),
        )
