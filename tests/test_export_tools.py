"""Tests for snapshot/report MCP tool safety gates."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from unifi_mcp.snapshots.collector import SnapshotFragment
from unifi_mcp.tools import exports as export_tools


def context_for(app_context):
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app_context))


async def test_export_mutations_require_confirmation(mock_ctx):
    ctx = context_for(mock_ctx)

    snapshot = await export_tools.export_portable_snapshot(ctx, "network.json")
    report = await export_tools.export_network_report(ctx, "network.html", "html")

    assert snapshot["success"] is False
    assert "confirm=true" in snapshot["message"]
    assert report["success"] is False
    assert "confirm=true" in report["message"]


async def test_exported_snapshot_can_be_verified(mock_ctx, tmp_path):
    mock_ctx.settings.export_dir = tmp_path / "exports"
    source = SimpleNamespace(
        source="network",
        device_name="gateway",
        site="default",
        mode="test",
        collect=AsyncMock(return_value=SnapshotFragment()),
    )
    ctx = context_for(mock_ctx)

    with patch("unifi_mcp.tools.exports._sources", return_value=[source]):
        exported = await export_tools.export_portable_snapshot(
            ctx, "network.snapshot.json", confirm=True
        )
        verified = await export_tools.verify_snapshot(ctx, "network.snapshot.json")

    assert exported["success"] is True
    assert verified["valid"] is True
    assert verified["content_sha256"] == exported["content_sha256"]
