"""Tests for capability-aware, secret-free snapshot collection."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from unifi_mcp.snapshots.collector import (
    NetworkSnapshotSource,
    ProtectSnapshotSource,
    SnapshotCollector,
)


async def test_collection_keeps_successes_and_records_redacted_source_failure():
    network = AsyncMock()
    network.get_devices_basic.return_value = [
        {"mac": "aa:bb", "name": "Gateway", "model": "UDM", "state": 1, "api_key": "x"}
    ]
    network.get_networks.return_value = [
        {"_id": "net-1", "name": "LAN", "ip_subnet": "192.0.2.1/24", "purpose": "corporate"}
    ]
    network.get_wlans.return_value = [
        {
            "_id": "wlan-1",
            "name": "Office",
            "enabled": True,
            "security": "wpapsk",
            "x_passphrase": "must-not-persist",
        }
    ]
    network.get_firewall_rules.return_value = []
    network.get_firewall_policies.return_value = []
    protect = AsyncMock()
    protect.get_cameras.side_effect = RuntimeError("password=must-not-leak")
    collector = SnapshotCollector(
        [
            NetworkSnapshotSource(network, device_name="gateway", site="default"),
            ProtectSnapshotSource(protect, device_name="nvr"),
        ]
    )

    document = await collector.collect(generated_at=datetime(2026, 8, 28, 12, tzinfo=UTC))
    rendered = document.model_dump_json()

    assert [device.id for device in document.content.devices] == ["aa:bb"]
    assert [network.id for network in document.content.networks] == ["net-1"]
    assert [wlan.id for wlan in document.content.wlans] == ["wlan-1"]
    assert [source.status for source in document.content.sources] == ["complete", "failed"]
    assert document.content.limitations[0].code == "RuntimeError"
    assert "must-not-leak" not in rendered
    assert "must-not-persist" not in rendered
