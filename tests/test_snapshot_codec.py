"""Tests for canonical snapshot encoding and verification."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from unifi_mcp.snapshots.codec import encode_snapshot, verify_snapshot_bytes
from unifi_mcp.snapshots.models import DeviceSnapshot, SnapshotContent, SnapshotDocument


def document(generated_at: datetime, device_ids: list[str]) -> SnapshotDocument:
    return SnapshotDocument(
        generated_at=generated_at,
        content=SnapshotContent(
            devices=[
                DeviceSnapshot(id=device_id, name=device_id, service="network")
                for device_id in device_ids
            ]
        ),
    )


def test_checksum_ignores_declared_volatile_time_and_input_order():
    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    first = json.loads(encode_snapshot(document(now, ["b", "a"])))
    second = json.loads(encode_snapshot(document(now + timedelta(minutes=1), ["a", "b"])))

    assert first["content_sha256"] == second["content_sha256"]
    assert first["generated_at"] != second["generated_at"]


def test_verification_rejects_modified_content():
    encoded = encode_snapshot(document(datetime(2026, 8, 28, 12, tzinfo=UTC), ["device-a"]))
    payload = json.loads(encoded)
    payload["content"]["devices"][0]["name"] = "tampered"

    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_snapshot_bytes(json.dumps(payload).encode())
