"""MCP tools for aggregate observation history and trends."""

from dataclasses import asdict
from datetime import datetime
from typing import Any

from mcp.server.mcpserver import Context

from unifi_mcp.clients.base import AppContext
from unifi_mcp.runtime.services import RuntimeServices


def _services(ctx: Context) -> RuntimeServices | None:
    app: AppContext = ctx.request_context.lifespan_context
    return app.runtime_services


def _unavailable() -> dict[str, Any]:
    return {
        "available": False,
        "reason": "Observation history requires UNIFI_RUNTIME_ENABLED=true",
    }


def _timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamps must use ISO-8601 with a timezone") from exc


async def capture_observations_now(ctx: Context) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    result = await services.observation_collector.collect()
    inserted = await services.observation_repository.insert_batch(result.observations)
    await services.refresh_metrics()
    return {
        "available": True,
        "inserted": inserted,
        "limitations": [asdict(item) for item in result.limitations],
    }


async def query_observation_trends(
    ctx: Context,
    kind: str,
    metric: str,
    start: str,
    end: str,
    bucket_seconds: int = 300,
    source: str | None = None,
    controller: str | None = None,
    site: str | None = None,
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    buckets = await services.observation_repository.query_trend(
        kind=kind,
        metric=metric,
        start=_timestamp(start),
        end=_timestamp(end),
        bucket_seconds=bucket_seconds,
        source=source,
        controller=controller,
        site=site,
    )
    return {
        "available": True,
        "kind": kind,
        "metric": metric,
        "buckets": [bucket.model_dump(mode="json") for bucket in buckets],
    }


async def list_observation_scopes(ctx: Context) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    return {"available": True, "scopes": await services.observation_repository.list_scopes()}


async def get_observation_retention_status(ctx: Context) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    status = await services.observation_repository.retention_status()
    return {"available": True, **status}
