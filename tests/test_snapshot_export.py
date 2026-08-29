"""Tests for confined atomic snapshot/report exports."""

import stat

import pytest

from unifi_mcp.snapshots.export import SnapshotExporter


async def test_export_is_atomic_private_and_confined(tmp_path):
    exporter = SnapshotExporter(tmp_path / "exports")

    result = await exporter.write("network.snapshot.json", b'{"safe":true}\n')

    assert result.path == tmp_path / "exports" / "network.snapshot.json"
    assert result.path.read_bytes() == b'{"safe":true}\n'
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o600
    assert result.size_bytes == 14
    assert await exporter.read("network.snapshot.json") == b'{"safe":true}\n'

    with pytest.raises(ValueError, match="plain filename"):
        await exporter.write("../escape.json", b"unsafe")


async def test_export_rejects_unsupported_extension_and_existing_symlink(tmp_path):
    export_root = tmp_path / "exports"
    export_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("unchanged")
    (export_root / "linked.json").symlink_to(outside)
    exporter = SnapshotExporter(export_root)

    with pytest.raises(ValueError, match="extension"):
        await exporter.write("snapshot.exe", b"unsafe")
    with pytest.raises(ValueError, match="symlink"):
        await exporter.write("linked.json", b"unsafe")
    with pytest.raises(ValueError, match="symlink"):
        await exporter.read("linked.json")

    assert outside.read_text() == "unchanged"
