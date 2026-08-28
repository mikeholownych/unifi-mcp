"""Tests for snapshot-backed HTML and CSV reports."""

from datetime import UTC, datetime

from unifi_mcp.reports.csv import render_csv_report
from unifi_mcp.reports.html import render_html_report
from unifi_mcp.snapshots.models import DeviceSnapshot, SnapshotContent, SnapshotDocument


def test_report_renderers_escape_html_and_neutralize_csv_formulas():
    document = SnapshotDocument(
        generated_at=datetime(2026, 8, 28, 12, tzinfo=UTC),
        content=SnapshotContent(
            devices=[
                DeviceSnapshot(
                    id="device-1",
                    name='=HYPERLINK("https://evil.test")<script>',
                    service="network",
                )
            ]
        ),
    )

    html = render_html_report(document).decode()
    csv = render_csv_report(document).decode()

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "secrets_excluded" in html
    assert "'=HYPERLINK" in csv
    assert "schema_version,generated_at,redaction_status" in csv
