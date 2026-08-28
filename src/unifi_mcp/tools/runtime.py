"""MCP-facing event and automation runtime management."""

from dataclasses import asdict
from typing import Any

from mcp.server.mcpserver import Context

from unifi_mcp.clients.base import AppContext
from unifi_mcp.runtime.services import RuntimeServices


def _app(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context


def _services(ctx: Context) -> RuntimeServices | None:
    return _app(ctx).runtime_services


def _unavailable() -> dict[str, Any]:
    return {
        "available": False,
        "reason": "Runtime persistence is disabled; set UNIFI_RUNTIME_ENABLED=true",
    }


async def list_runtime_events(ctx: Context, limit: int = 100) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    events = await services.repository.list_events(limit=limit)
    return {
        "available": True,
        "events": [event.model_dump(mode="json") for event in events],
    }


async def get_event_polling_status(ctx: Context) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    return {
        "available": True,
        "background_enabled": _app(ctx).settings.automation_enabled,
        "sources": [asdict(capability) for capability in services.capabilities],
    }


async def poll_events_now(
    ctx: Context,
    source: str | None = None,
    device_name: str | None = None,
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    selected = [
        event_source
        for event_source in services.sources
        if (source is None or event_source.source == source)
        and (device_name is None or event_source.device_name == device_name)
    ]
    summary = await services.poller.poll(selected)
    return {
        "available": True,
        "inserted": summary.inserted,
        "duplicates": summary.duplicates,
        "failed_sources": summary.failed_sources,
        "sources": [asdict(outcome) for outcome in summary.sources],
    }


async def list_schedules(ctx: Context) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    schedules = await services.scheduler.list_schedules()
    return {
        "available": True,
        "background_enabled": _app(ctx).settings.automation_enabled,
        "schedules": [schedule.model_dump(mode="json") for schedule in schedules],
    }


async def create_interval_schedule(
    ctx: Context,
    name: str,
    job_name: str,
    interval_seconds: int,
    arguments: dict[str, Any] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    if not confirm:
        return {
            "success": False,
            "message": "Schedule creation requires confirm=true because it enables recurring work.",
        }
    schedule = await services.scheduler.create_interval_schedule(
        name=name,
        job_name=job_name,
        interval_seconds=interval_seconds,
        arguments=arguments or {},
    )
    return {
        "success": True,
        "background_enabled": _app(ctx).settings.automation_enabled,
        "schedule": schedule.model_dump(mode="json"),
    }


async def set_schedule_enabled(
    ctx: Context, schedule_id: str, enabled: bool, confirm: bool = False
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    if not confirm:
        return {"success": False, "message": "Schedule changes require confirm=true."}
    updated = await services.scheduler.set_schedule_enabled(schedule_id, enabled)
    return {"success": updated, "schedule_id": schedule_id, "enabled": enabled}


async def delete_schedule(ctx: Context, schedule_id: str, confirm: bool = False) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    if not confirm:
        return {"success": False, "message": "Schedule deletion requires confirm=true."}
    deleted = await services.scheduler.delete_schedule(schedule_id)
    return {"success": deleted, "schedule_id": schedule_id}


async def run_schedule_now(ctx: Context, schedule_id: str, confirm: bool = False) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    if not confirm:
        return {"success": False, "message": "Running a schedule requires confirm=true."}
    run = await services.scheduler.run_schedule_now(schedule_id)
    return {"success": run.status == "succeeded", "run": run.model_dump(mode="json")}


async def list_job_runs(ctx: Context, limit: int = 100) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    runs = await services.scheduler.list_job_runs(limit=limit)
    return {"available": True, "runs": [run.model_dump(mode="json") for run in runs]}


async def list_webhook_destinations(ctx: Context) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    destinations = await services.webhooks.list_destinations()
    return {
        "available": True,
        "destinations": [destination.model_dump(mode="json") for destination in destinations],
    }


async def create_webhook_destination(
    ctx: Context,
    name: str,
    url: str,
    secret_env_name: str | None = None,
    categories: list[str] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    if not confirm:
        return {
            "success": False,
            "message": "Webhook creation requires confirm=true because it enables outbound data.",
        }
    destination = await services.webhooks.create_destination(
        name=name,
        url=url,
        secret_env_name=secret_env_name,
        categories=categories or [],
    )
    return {"success": True, "destination": destination.model_dump(mode="json")}


async def set_webhook_destination_enabled(
    ctx: Context, destination_id: str, enabled: bool, confirm: bool = False
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    if not confirm:
        return {"success": False, "message": "Webhook changes require confirm=true."}
    updated = await services.webhooks.set_destination_enabled(destination_id, enabled)
    return {"success": updated, "destination_id": destination_id, "enabled": enabled}


async def delete_webhook_destination(
    ctx: Context, destination_id: str, confirm: bool = False
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    if not confirm:
        return {"success": False, "message": "Webhook deletion requires confirm=true."}
    deleted = await services.webhooks.delete_destination(destination_id)
    return {"success": deleted, "destination_id": destination_id}


async def test_webhook_destination(
    ctx: Context, destination_id: str, confirm: bool = False
) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    if not confirm:
        return {
            "success": False,
            "message": "Testing a webhook sends outbound data and requires confirm=true.",
        }
    result = await services.webhooks.test_destination(destination_id)
    return {"success": result.status == "succeeded", "result": result.model_dump(mode="json")}


async def list_webhook_deliveries(ctx: Context, limit: int = 100) -> dict[str, Any]:
    services = _services(ctx)
    if services is None:
        return _unavailable()
    deliveries = await services.webhooks.list_deliveries(limit=limit)
    return {
        "available": True,
        "deliveries": [delivery.model_dump(mode="json") for delivery in deliveries],
    }
