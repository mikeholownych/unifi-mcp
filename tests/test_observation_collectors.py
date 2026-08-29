"""Tests for aggregate-only observation collectors."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from unifi_mcp.observability.collectors import (
    NetworkObservationSource,
    ObservationCollector,
    ProtectObservationSource,
)


async def test_collectors_keep_aggregates_and_redact_source_failures():
    network = AsyncMock()
    network.get_site_health.return_value = [
        {"subsystem": "wan", "status": "ok", "wan_ip": "192.0.2.10"},
        {"subsystem": "wlan", "status": "warning", "ssid": "Secret SSID"},
    ]
    network.get_devices_basic.return_value = [
        {"state": 1, "mac": "aa:bb", "name": "Private Gateway"},
        {"state": 0, "mac": "cc:dd"},
    ]
    network.get_clients.return_value = [
        {"is_wired": True, "rx_bytes": 100, "tx_bytes": 50, "hostname": "private"},
        {"is_wired": False, "rx_bytes": 20, "tx_bytes": 10, "ssid": "Secret SSID"},
    ]
    protect = AsyncMock()
    protect.get_cameras.side_effect = RuntimeError("password=must-not-leak")
    collector = ObservationCollector(
        [
            NetworkObservationSource(network, controller="gateway", site="default"),
            ProtectObservationSource(protect, controller="nvr"),
        ]
    )

    result = await collector.collect(observed_at=datetime(2026, 8, 28, 12, tzinfo=UTC))
    rendered = "\n".join(observation.model_dump_json() for observation in result.observations)

    assert [observation.kind for observation in result.observations] == [
        "site_health",
        "device_counts",
        "client_counts",
        "traffic",
    ]
    assert result.observations[1].metrics.model_dump() == {"total": 2, "online": 1, "offline": 1}
    assert result.limitations[0].error_code == "RuntimeError"
    for sensitive in ("aa:bb", "cc:dd", "192.0.2.10", "Secret SSID", "private", "must-not-leak"):
        assert sensitive not in rendered
