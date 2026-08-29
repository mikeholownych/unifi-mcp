"""Tests for strict, deterministic portable snapshot models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from unifi_mcp.snapshots.models import DeviceSnapshot, SnapshotContent, SnapshotDocument


def test_snapshot_document_sorts_stable_collections():
    document = SnapshotDocument(
        generated_at=datetime(2026, 8, 28, 12, tzinfo=UTC),
        content=SnapshotContent(
            devices=[
                DeviceSnapshot(id="device-b", name="B", service="network"),
                DeviceSnapshot(id="device-a", name="A", service="network"),
            ]
        ),
    )

    assert [device.id for device in document.content.devices] == ["device-a", "device-b"]
    assert document.schema_version == 1
    assert document.redaction_status == "secrets_excluded"


def test_snapshot_document_rejects_naive_time_and_unknown_secret_fields():
    with pytest.raises(ValidationError, match="timezone"):
        SnapshotDocument(generated_at=datetime(2026, 8, 28, 12), content=SnapshotContent())

    with pytest.raises(ValidationError, match="password"):
        DeviceSnapshot(
            id="device-a",
            name="A",
            service="network",
            password="must-not-persist",
        )
