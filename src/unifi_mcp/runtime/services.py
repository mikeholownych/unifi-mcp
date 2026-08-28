"""Composition root for optional event and automation runtime services."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, Field

from unifi_mcp.clients.network import UniFiNetworkClient
from unifi_mcp.clients.protect import UniFiProtectClient
from unifi_mcp.events.poller import EventPoller
from unifi_mcp.events.sources import EventSource, NetworkEventSource, ProtectEventSource
from unifi_mcp.observability.collectors import (
    NetworkObservationSource,
    ObservationCollector,
    ObservationSource,
    ProtectObservationSource,
)
from unifi_mcp.observability.prometheus import MetricsSnapshot, MetricsState
from unifi_mcp.runtime.events import EventRepository
from unifi_mcp.runtime.jobs import JobDefinition, JobRegistry
from unifi_mcp.runtime.observations import ObservationRepository
from unifi_mcp.runtime.scheduler import Scheduler
from unifi_mcp.runtime.store import RuntimeStore
from unifi_mcp.runtime.webhooks import WebhookService

if TYPE_CHECKING:
    from unifi_mcp.clients.base import AppContext


class PollEventsArguments(BaseModel):
    """Optional scope for a polling run."""

    source: str | None = None
    device_name: str | None = None


class RetryWebhookArguments(BaseModel):
    """Bounded webhook retry batch."""

    limit: int = Field(default=100, ge=1, le=1000)


class PruneRuntimeArguments(BaseModel):
    """The retention job intentionally accepts no arbitrary options."""


class CaptureObservationsArguments(BaseModel):
    """Optional aggregate observation source scope."""

    source: str | None = None
    controller: str | None = None


@dataclass(frozen=True)
class SourceCapability:
    source: str
    device_name: str
    site: str
    mode: str
    reason: str | None = None


@dataclass
class RuntimeServices:
    """Runtime components owned by the application lifespan."""

    store: RuntimeStore
    repository: EventRepository
    poller: EventPoller
    sources: list[EventSource]
    capabilities: list[SourceCapability]
    scheduler: Scheduler
    webhooks: WebhookService
    webhook_client: httpx.AsyncClient
    observation_repository: ObservationRepository
    observation_collector: ObservationCollector
    metrics_state: MetricsState
    configured_controller_count: int

    async def close(self) -> None:
        await self.webhook_client.aclose()

    async def refresh_metrics(self) -> MetricsSnapshot:
        async with self.store.transaction() as connection:
            result = await connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM events),
                    (SELECT COUNT(*) FROM schedules WHERE enabled = 1),
                    (SELECT COUNT(*) FROM webhook_deliveries WHERE status IN ('pending', 'retry')),
                    (SELECT COUNT(*) FROM observations),
                    (SELECT COUNT(DISTINCT controller) FROM observations)
                """
            )
            row = await result.fetchone()
        reachable = min(int(row[4]), self.configured_controller_count)
        snapshot = MetricsSnapshot(
            runtime_up=1,
            events_total=int(row[0]),
            schedules_enabled=int(row[1]),
            webhook_pending=int(row[2]),
            observations_total=int(row[3]),
            controllers_reachable=reachable,
            controllers_unreachable=max(0, self.configured_controller_count - reachable),
        )
        self.metrics_state.set(snapshot)
        return snapshot


async def build_runtime_services(
    ctx: AppContext, webhook_client: httpx.AsyncClient
) -> RuntimeServices:
    """Build services only after the optional runtime store has opened."""
    if ctx.runtime is None:
        raise ValueError("runtime persistence must be enabled")

    sources: list[EventSource] = []
    capabilities: list[SourceCapability] = []
    if ctx.settings.mode == "local":
        network_client = UniFiNetworkClient(ctx)
        device_name = (
            network_client.device.name
            if network_client.device
            else ctx.settings.default_device_name
        )
        sources.append(
            NetworkEventSource(network_client, device_name=device_name, site=network_client.site)
        )
        capabilities.append(
            SourceCapability("network", device_name, network_client.site, "polling")
        )
    else:
        for device in ctx.settings.get_network_devices():
            capabilities.append(
                SourceCapability(
                    "network",
                    device.name,
                    device.site,
                    "unsupported",
                    "Network event polling requires legacy local session authentication",
                )
            )

    for device in ctx.settings.get_protect_devices():
        if device.has_protect_credentials:
            sources.append(
                ProtectEventSource(
                    UniFiProtectClient(ctx.client, device),
                    device_name=device.name,
                )
            )
            capabilities.append(SourceCapability("protect", device.name, "", "polling"))
        else:
            capabilities.append(
                SourceCapability(
                    "protect",
                    device.name,
                    "",
                    "unsupported",
                    "Protect event polling requires local username and password credentials",
                )
            )

    repository = EventRepository(ctx.runtime)
    poller = EventPoller(
        repository,
        timeout_seconds=ctx.settings.request_timeout,
        jitter_seconds=ctx.settings.event_poll_jitter_seconds,
    )
    webhooks = WebhookService(
        ctx.runtime,
        webhook_client,
        allow_private=ctx.settings.webhook_allow_private,
        max_attempts=ctx.settings.webhook_max_attempts,
    )
    observation_sources: list[ObservationSource] = []
    for device in ctx.settings.get_network_devices():
        observation_sources.append(
            NetworkObservationSource(
                UniFiNetworkClient(ctx, device.name),
                controller=device.name,
                site=device.site,
            )
        )
    if not observation_sources and ctx.settings.mode == "local":
        observation_sources.append(
            NetworkObservationSource(
                UniFiNetworkClient(ctx),
                controller=ctx.settings.default_device_name,
                site=ctx.settings.site,
            )
        )
    for device in ctx.settings.get_protect_devices():
        observation_sources.append(
            ProtectObservationSource(UniFiProtectClient(ctx.client, device), controller=device.name)
        )
    observation_repository = ObservationRepository(ctx.runtime)
    observation_collector = ObservationCollector(observation_sources)
    configured_controller_count = max(1, len(ctx.settings.get_device_names()))
    metrics_state = MetricsState(
        MetricsSnapshot(
            runtime_up=1,
            events_total=0,
            schedules_enabled=0,
            webhook_pending=0,
            observations_total=0,
            controllers_reachable=0,
            controllers_unreachable=configured_controller_count,
        )
    )

    async def poll_events(arguments: PollEventsArguments) -> dict[str, Any]:
        selected = [
            source
            for source in sources
            if (arguments.source is None or source.source == arguments.source)
            and (arguments.device_name is None or source.device_name == arguments.device_name)
        ]
        summary = await poller.poll(selected)
        return {
            "inserted": summary.inserted,
            "duplicates": summary.duplicates,
            "failed_sources": summary.failed_sources,
            "sources": [asdict(outcome) for outcome in summary.sources],
        }

    async def retry_webhooks(arguments: RetryWebhookArguments) -> dict[str, Any]:
        results = await webhooks.deliver_due(limit=arguments.limit)
        return {
            "attempted": len(results),
            "delivered": sum(result.status == "delivered" for result in results),
            "failed": sum(result.status == "failed" for result in results),
        }

    async def capture_observations(arguments: CaptureObservationsArguments) -> dict[str, Any]:
        selected = [
            source
            for source in observation_sources
            if (arguments.source is None or source.source == arguments.source)
            and (arguments.controller is None or source.controller == arguments.controller)
        ]
        result = await ObservationCollector(selected).collect()
        inserted = await observation_repository.insert_batch(result.observations)
        await services.refresh_metrics()
        return {
            "inserted": inserted,
            "limitations": [asdict(item) for item in result.limitations],
        }

    async def prune_runtime(_arguments: PruneRuntimeArguments) -> dict[str, Any]:
        now = datetime.now(UTC)
        cutoffs = (
            now - timedelta(days=ctx.settings.event_retention_days),
            now - timedelta(days=ctx.settings.job_retention_days),
            now - timedelta(days=ctx.settings.webhook_delivery_retention_days),
            now - timedelta(days=ctx.settings.observation_retention_days),
        )
        async with ctx.runtime.transaction() as connection:
            deliveries = await connection.execute(
                "DELETE FROM webhook_deliveries WHERE status IN ('delivered', 'failed', 'dead_letter') AND updated_at < ?",
                (cutoffs[2].isoformat(),),
            )
            runs = await connection.execute(
                "DELETE FROM job_runs WHERE finished_at IS NOT NULL AND finished_at < ?",
                (cutoffs[1].isoformat(),),
            )
            events = await connection.execute(
                "DELETE FROM events WHERE occurred_at < ?",
                (cutoffs[0].isoformat(),),
            )
            observations = await connection.execute(
                "DELETE FROM observations WHERE observed_at < ?",
                (cutoffs[3].isoformat(),),
            )
        return {
            "events_deleted": events.rowcount,
            "job_runs_deleted": runs.rowcount,
            "deliveries_deleted": deliveries.rowcount,
            "observations_deleted": observations.rowcount,
        }

    registry = JobRegistry(
        [
            JobDefinition("poll_events", PollEventsArguments, poll_events),
            JobDefinition("retry_webhook_deliveries", RetryWebhookArguments, retry_webhooks, True),
            JobDefinition("prune_runtime_data", PruneRuntimeArguments, prune_runtime),
            JobDefinition(
                "capture_observations", CaptureObservationsArguments, capture_observations
            ),
        ]
    )
    scheduler = Scheduler(
        ctx.runtime,
        registry,
        job_timeout_seconds=ctx.settings.automation_job_timeout_seconds,
        stale_run_seconds=ctx.settings.automation_stale_run_seconds,
        max_job_attempts=ctx.settings.automation_job_max_attempts,
        retry_initial_delay_seconds=ctx.settings.automation_retry_initial_delay_seconds,
    )
    services = RuntimeServices(
        store=ctx.runtime,
        repository=repository,
        poller=poller,
        sources=sources,
        capabilities=capabilities,
        scheduler=scheduler,
        webhooks=webhooks,
        webhook_client=webhook_client,
        observation_repository=observation_repository,
        observation_collector=observation_collector,
        metrics_state=metrics_state,
        configured_controller_count=configured_controller_count,
    )
    return services
