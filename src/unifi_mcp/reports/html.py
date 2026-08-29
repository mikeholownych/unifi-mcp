"""Accessible standalone HTML snapshot report renderer."""

from html import escape

from unifi_mcp.snapshots.models import SnapshotDocument


def _cell(value: object | None) -> str:
    return escape("" if value is None else str(value), quote=True)


def render_html_report(document: SnapshotDocument) -> bytes:
    """Render a bounded standalone report from a strict snapshot document."""
    device_rows = "".join(
        "<tr>"
        f"<td>{_cell(item.service)}</td><td>{_cell(item.controller)}</td>"
        f"<td>{_cell(item.site)}</td><td>{_cell(item.name)}</td>"
        f"<td>{_cell(item.model)}</td><td>{_cell(item.state)}</td>"
        "</tr>"
        for item in document.content.devices
    )
    limitations = (
        "".join(
            f"<li><strong>{_cell(item.code)}</strong>: {_cell(item.summary)} "
            f"({_cell(item.device_name)})</li>"
            for item in document.content.limitations
        )
        or "<li>None reported</li>"
    )
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>UniFi Snapshot Report</title><style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#17202a}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd1d1;padding:.45rem;text-align:left}}
th{{background:#eef2f3}}.meta{{display:flex;gap:2rem;flex-wrap:wrap}}@media print{{body{{margin:0;max-width:none}}}}
</style></head><body><main><h1>UniFi Snapshot Report</h1>
<div class="meta"><p>Schema: {_cell(document.schema_version)}</p>
<p>Generated: {_cell(document.generated_at.isoformat())}</p>
<p>Redaction: {_cell(document.redaction_status)}</p></div>
<h2>Summary</h2><p>{len(document.content.devices)} devices, {len(document.content.networks)} networks, {len(document.content.wlans)} WLANs, {len(document.content.firewall)} firewall entries.</p>
<h2>Devices</h2><table><thead><tr><th>Service</th><th>Controller</th><th>Site</th><th>Name</th><th>Model</th><th>State</th></tr></thead>
<tbody>{device_rows}</tbody></table><h2>Data Limitations</h2><ul>{limitations}</ul>
</main></body></html>"""
    return html.encode("utf-8")
