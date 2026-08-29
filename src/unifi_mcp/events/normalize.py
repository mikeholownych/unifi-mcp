"""Normalize controller payloads into a bounded, redacted event envelope."""

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from unifi_mcp.events.models import NormalizedEvent

_SECRET_FRAGMENT = re.compile(
    r"\b(password|token|api[_-]?key|authorization|cookie)\s*[:=]\s*\S+",
    flags=re.IGNORECASE,
)


def _redact_summary(value: object, fallback: str) -> str:
    summary = str(value or fallback)[:1000]
    return _SECRET_FRAGMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", summary)


def _timestamp(value: object) -> datetime:
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=UTC)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(UTC)
    raise ValueError("event timestamp must be epoch seconds, epoch milliseconds, or ISO-8601")


def _fallback_key(parts: list[object]) -> str:
    encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def normalize_network_event(raw: dict[str, Any], *, device_name: str, site: str) -> NormalizedEvent:
    """Normalize one UniFi Network event using only persisted allowlisted fields."""
    event_key = str(raw.get("key") or "unknown")
    source_key = str(raw.get("_id") or raw.get("id") or "")
    if not source_key:
        source_key = _fallback_key(
            [
                device_name,
                site,
                raw.get("time") or raw.get("datetime"),
                event_key,
                raw.get("hostname"),
                raw.get("client"),
                raw.get("ap") or raw.get("gw") or raw.get("sw"),
            ]
        )

    details = {
        key: raw[key]
        for key in ("hostname", "ssid", "ap_name", "channel", "subsystem", "archived")
        if raw.get(key) is not None
    }
    lowered = f"{event_key} {raw.get('msg', '')}".lower()
    severity = "warning" if any(word in lowered for word in ("alarm", "down", "fail")) else "info"

    return NormalizedEvent(
        source="network",
        source_key=source_key,
        device_name=device_name,
        site=site,
        category=f"network.{event_key.lower()}",
        severity=severity,
        occurred_at=_timestamp(raw.get("time") or raw.get("datetime")),
        summary=_redact_summary(raw.get("msg"), event_key),
        subject_type="client" if raw.get("client") or raw.get("hostname") else None,
        subject_id=raw.get("client") or raw.get("hostname"),
        details=details,
    )


def normalize_protect_event(raw: dict[str, Any], *, device_name: str) -> NormalizedEvent:
    """Normalize one UniFi Protect event using only persisted allowlisted fields."""
    event_type = str(raw.get("type") or "unknown")
    category_type = {
        "smartdetect": "smart_detection",
        "motion": "motion",
        "ring": "ring",
    }.get(event_type.lower(), event_type.lower())
    source_key = str(raw.get("id") or raw.get("_id") or "")
    if not source_key:
        source_key = _fallback_key(
            [device_name, raw.get("start") or raw.get("timestamp"), event_type, raw.get("camera")]
        )

    details: dict[str, Any] = {}
    if raw.get("smartDetectTypes") is not None:
        details["smart_detect_types"] = raw["smartDetectTypes"]
    if raw.get("score") is not None:
        details["score"] = raw["score"]

    camera = raw.get("camera")
    return NormalizedEvent(
        source="protect",
        source_key=source_key,
        device_name=device_name,
        category=f"protect.{category_type}",
        severity="info",
        occurred_at=_timestamp(raw.get("start") or raw.get("timestamp")),
        summary=_redact_summary(raw.get("description"), f"Protect {event_type} event"),
        subject_type="camera" if camera else None,
        subject_id=str(camera) if camera else None,
        details=details,
    )
