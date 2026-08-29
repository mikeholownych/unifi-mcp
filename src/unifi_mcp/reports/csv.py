"""RFC 4180-style CSV snapshot report renderer."""

import csv
import io

from unifi_mcp.snapshots.models import SnapshotDocument


def _safe(value: object | None) -> str:
    rendered = "" if value is None else str(value)
    if rendered.startswith(("=", "+", "-", "@")):
        return "'" + rendered
    return rendered


def render_csv_report(document: SnapshotDocument) -> bytes:
    """Render fixed-contract CSV rows with spreadsheet formulas neutralized."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["schema_version", "generated_at", "redaction_status"])
    writer.writerow(
        [document.schema_version, document.generated_at.isoformat(), document.redaction_status]
    )
    writer.writerow([])
    writer.writerow(["record_type", "service", "controller", "site", "id", "name", "state"])
    for item in document.content.devices:
        writer.writerow(
            [
                "device",
                _safe(item.service),
                _safe(item.controller),
                _safe(item.site),
                _safe(item.id),
                _safe(item.name),
                _safe(item.state),
            ]
        )
    for item in document.content.networks:
        writer.writerow(
            [
                "network",
                "network",
                _safe(item.controller),
                _safe(item.site),
                _safe(item.id),
                _safe(item.name),
                "",
            ]
        )
    for item in document.content.wlans:
        writer.writerow(
            [
                "wlan",
                "network",
                _safe(item.controller),
                _safe(item.site),
                _safe(item.id),
                _safe(item.name),
                "enabled" if item.enabled else "disabled",
            ]
        )
    return output.getvalue().encode("utf-8")
