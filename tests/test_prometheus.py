"""Tests for optional low-cardinality Prometheus rendering and serving."""

import httpx
import pytest

pytest.importorskip("prometheus_client")

from unifi_mcp.observability.prometheus import MetricsServer, MetricsSnapshot, render_prometheus


def test_prometheus_output_has_fixed_metrics_without_identity_labels():
    output = render_prometheus(
        MetricsSnapshot(
            runtime_up=1,
            events_total=12,
            schedules_enabled=2,
            webhook_pending=3,
            observations_total=20,
            controllers_reachable=1,
            controllers_unreachable=1,
        )
    ).decode()

    assert "unifi_mcp_events_total 12.0" in output
    assert "unifi_mcp_observations_total 20.0" in output
    assert "controller=" not in output
    for sensitive in ("aa:bb:cc:dd:ee:ff", "192.0.2.10", "Secret SSID"):
        assert sensitive not in output


async def test_metrics_server_requires_bearer_and_releases_listener():
    snapshot = MetricsSnapshot(
        runtime_up=1,
        events_total=0,
        schedules_enabled=0,
        webhook_pending=0,
        observations_total=0,
        controllers_reachable=0,
        controllers_unreachable=0,
    )
    server = MetricsServer(
        "127.0.0.1",
        0,
        lambda: snapshot,
        bearer_token_provider=lambda: "test-token",
    )
    server.start()

    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            unauthorized = await client.get(f"http://127.0.0.1:{server.port}/metrics")
            authorized = await client.get(
                f"http://127.0.0.1:{server.port}/metrics",
                headers={"Authorization": "Bearer test-token"},
            )
    finally:
        await server.close()

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert "unifi_mcp_runtime_up 1.0" in authorized.text
