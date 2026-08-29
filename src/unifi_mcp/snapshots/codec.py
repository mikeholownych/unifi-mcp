"""Canonical JSON encoding and checksum verification for snapshots."""

import hashlib
import hmac
import json
from typing import Any

from pydantic import ValidationError

from unifi_mcp.snapshots.models import SnapshotDocument

MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _checksum(document: SnapshotDocument) -> str:
    stable = document.model_dump(
        mode="json",
        exclude={"generated_at", "content_sha256"},
    )
    return hashlib.sha256(_canonical(stable)).hexdigest()


def encode_snapshot(document: SnapshotDocument) -> bytes:
    """Return a canonical document carrying its stable content checksum."""
    sealed = document.model_copy(update={"content_sha256": _checksum(document)})
    return _canonical(sealed.model_dump(mode="json")) + b"\n"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"snapshot JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def verify_snapshot_bytes(data: bytes) -> SnapshotDocument:
    """Parse and verify one bounded snapshot document."""
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot exceeds the maximum supported size")
    try:
        payload = json.loads(data, object_pairs_hook=_reject_duplicate_keys)
        document = SnapshotDocument.model_validate(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
        raise ValueError("snapshot is not valid schema-versioned JSON") from exc
    if document.content_sha256 is None:
        raise ValueError("snapshot checksum is missing")
    expected = _checksum(document)
    if not hmac.compare_digest(document.content_sha256, expected):
        raise ValueError("snapshot checksum mismatch")
    return document
