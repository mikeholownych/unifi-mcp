"""Tests for MCP-facing runtime management safety gates."""

from types import SimpleNamespace

from unifi_mcp.tools import runtime as runtime_tools


def context_for(app_context):
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app_context))


async def test_runtime_tools_report_unavailable_when_persistence_is_disabled(mock_ctx):
    result = await runtime_tools.list_runtime_events(context_for(mock_ctx))

    assert result == {
        "available": False,
        "reason": "Runtime persistence is disabled; set UNIFI_RUNTIME_ENABLED=true",
    }


async def test_schedule_and_webhook_mutations_require_confirmation(mock_ctx):
    mock_ctx.runtime_services = SimpleNamespace()
    ctx = context_for(mock_ctx)

    schedule = await runtime_tools.create_interval_schedule(
        ctx,
        name="poll",
        job_name="poll_events",
        interval_seconds=60,
    )
    webhook = await runtime_tools.create_webhook_destination(
        ctx,
        name="automation",
        url="https://hooks.example.test/events",
    )

    assert schedule["success"] is False
    assert "confirm=true" in schedule["message"]
    assert webhook["success"] is False
    assert "confirm=true" in webhook["message"]
