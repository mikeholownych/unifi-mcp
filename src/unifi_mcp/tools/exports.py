"""Portable snapshot and report MCP operations."""

from typing import Any

from mcp.server.mcpserver import Context

from unifi_mcp.clients.base import AppContext
from unifi_mcp.clients.network import UniFiNetworkClient
from unifi_mcp.clients.protect import UniFiProtectClient
from unifi_mcp.reports.csv import render_csv_report
from unifi_mcp.reports.html import render_html_report
from unifi_mcp.snapshots.codec import encode_snapshot, verify_snapshot_bytes
from unifi_mcp.snapshots.collector import (
    NetworkSnapshotSource,
    ProtectSnapshotSource,
    SnapshotCollector,
    SnapshotSource,
    UnsupportedSnapshotSource,
)
from unifi_mcp.snapshots.export import SnapshotExporter


def _app(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context


def _sources(app: AppContext) -> list[SnapshotSource]:
    sources: list[SnapshotSource] = []
    network_devices = app.settings.get_network_devices()
    if not network_devices and app.settings.mode == "local":
        client = UniFiNetworkClient(app)
        sources.append(
            NetworkSnapshotSource(
                client,
                device_name=app.settings.default_device_name,
                site=app.settings.site,
                mode="local_session",
            )
        )
    for device in network_devices:
        if app.settings.mode == "cloud":
            sources.append(
                UnsupportedSnapshotSource(
                    source="network",
                    device_name=device.name,
                    site=device.site,
                    mode="cloud",
                    summary="Portable Network configuration reads are unavailable in cloud mode",
                )
            )
        else:
            sources.append(
                NetworkSnapshotSource(
                    UniFiNetworkClient(app, device.name),
                    device_name=device.name,
                    site=device.site,
                    mode="local_session" if app.settings.mode == "local" else "integration_api",
                )
            )
    for device in app.settings.get_protect_devices():
        sources.append(
            ProtectSnapshotSource(
                UniFiProtectClient(app.client, device),
                device_name=device.name,
                mode="integration_api",
            )
        )
    return sources


async def get_snapshot_capabilities(ctx: Context) -> dict[str, Any]:
    app = _app(ctx)
    sources = _sources(app)
    return {
        "schema_version": 1,
        "export_directory_configured": True,
        "portable_snapshot": True,
        "report_formats": ["html", "csv"],
        "native_controller_backup": False,
        "native_restore": False,
        "sources": [
            {
                "source": source.source,
                "device_name": source.device_name,
                "site": source.site,
                "mode": source.mode,
            }
            for source in sources
        ],
    }


async def export_portable_snapshot(
    ctx: Context, filename: str, confirm: bool = False
) -> dict[str, Any]:
    if not confirm:
        return {
            "success": False,
            "message": "Snapshot export writes a local file and requires confirm=true.",
        }
    app = _app(ctx)
    document = await SnapshotCollector(_sources(app)).collect()
    encoded = encode_snapshot(document)
    sealed = verify_snapshot_bytes(encoded)
    result = await SnapshotExporter(app.settings.export_directory).write(filename, encoded)
    return {
        "success": True,
        "filename": result.path.name,
        "size_bytes": result.size_bytes,
        "schema_version": sealed.schema_version,
        "content_sha256": sealed.content_sha256,
        "source_count": len(sealed.content.sources),
        "limitations": [item.model_dump(mode="json") for item in sealed.content.limitations],
    }


async def verify_snapshot(ctx: Context, filename: str) -> dict[str, Any]:
    app = _app(ctx)
    data = await SnapshotExporter(app.settings.export_directory).read(filename)
    document = verify_snapshot_bytes(data)
    return {
        "valid": True,
        "filename": filename,
        "schema_version": document.schema_version,
        "content_sha256": document.content_sha256,
        "redaction_status": document.redaction_status,
    }


async def export_network_report(
    ctx: Context, filename: str, format: str, confirm: bool = False
) -> dict[str, Any]:
    if not confirm:
        return {
            "success": False,
            "message": "Report export writes a local file and requires confirm=true.",
        }
    if format not in {"html", "csv"}:
        raise ValueError("report format must be html or csv")
    if not filename.endswith(f".{format}"):
        raise ValueError(f"{format} reports require a .{format} filename")
    app = _app(ctx)
    document = await SnapshotCollector(_sources(app)).collect()
    data = render_html_report(document) if format == "html" else render_csv_report(document)
    result = await SnapshotExporter(app.settings.export_directory).write(filename, data)
    return {
        "success": True,
        "filename": result.path.name,
        "format": format,
        "size_bytes": result.size_bytes,
        "source_count": len(document.content.sources),
        "limitations": [item.model_dump(mode="json") for item in document.content.limitations],
    }
