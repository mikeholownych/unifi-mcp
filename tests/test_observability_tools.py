"""Tests for aggregate history MCP tool availability."""

from types import SimpleNamespace

from unifi_mcp.tools import observability as observability_tools


def context_for(app_context):
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app_context))


async def test_history_tools_report_unavailable_without_runtime(mock_ctx):
    ctx = context_for(mock_ctx)

    capture = await observability_tools.capture_observations_now(ctx)
    scopes = await observability_tools.list_observation_scopes(ctx)

    assert capture["available"] is False
    assert scopes["available"] is False
    assert "UNIFI_RUNTIME_ENABLED" in capture["reason"]
