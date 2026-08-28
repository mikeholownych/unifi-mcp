"""Bounded read-after-write verification for safety-critical mutations."""

import asyncio
import ipaddress
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")

_BOOLEAN_FIELDS = {"enabled", "vlan_enabled", "dhcpd_enabled"}
_INTEGER_FIELDS = {"port_idx", "vlan", "dhcpd_leasetime"}
_ADDRESS_FIELDS = {"dhcpd_start", "dhcpd_stop"}
_CIDR_FIELDS = {"ip_subnet"}


@dataclass(frozen=True)
class VerificationResult:
    """Final outcome from bounded verification attempts."""

    matched: bool
    observed: Any
    error_type: str | None = None


def normalize_field(field: str, value: Any) -> Any:
    """Normalize controller values without coercing unsafe boolean forms."""
    if value is None:
        return None
    if field in _BOOLEAN_FIELDS:
        return value if isinstance(value, bool) else value
    if field in _INTEGER_FIELDS and not isinstance(value, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if field in _ADDRESS_FIELDS:
        try:
            return str(ipaddress.ip_address(str(value).strip()))
        except ValueError:
            return str(value).strip()
    if field in _CIDR_FIELDS:
        try:
            return str(ipaddress.ip_interface(str(value).strip()))
        except ValueError:
            return str(value).strip()
    if isinstance(value, str):
        return value.strip()
    return value


def requested_observation(
    record: dict[str, Any] | None, requested: dict[str, Any]
) -> tuple[bool, dict[str, Any] | None]:
    """Compare requested fields and return normalized observed values."""
    if record is None:
        return False, None

    fields = [field for field in requested if field != "setting_preference"]
    if requested.get("vlan_enabled") is False:
        fields = [field for field in fields if field != "vlan"]
    observed = {field: normalize_field(field, record.get(field)) for field in fields}
    expected = {field: normalize_field(field, requested[field]) for field in fields}
    matched = all(
        (isinstance(expected[field], bool) and observed[field] is expected[field])
        or (not isinstance(expected[field], bool) and observed[field] == expected[field])
        for field in fields
    )
    return matched, observed


async def verify_eventually(
    fetch: Callable[[], Awaitable[T]],
    evaluate: Callable[[T], tuple[bool, Any]],
    *,
    operation: str,
    logger: logging.Logger,
    attempts: int,
    initial_delay: float,
    max_delay: float,
) -> VerificationResult:
    """Fetch fresh state with bounded exponential backoff."""
    observed: Any = None
    final_error_type: str | None = None
    for attempt in range(attempts):
        try:
            matched, observed = evaluate(await fetch())
            final_error_type = None
            if matched:
                return VerificationResult(True, observed)
        except Exception as exc:
            final_error_type = type(exc).__name__
            logger.warning("Verification read failed for %s (%s)", operation, final_error_type)
        if attempt + 1 < attempts:
            await asyncio.sleep(min(initial_delay * (2**attempt), max_delay))
    return VerificationResult(False, observed, final_error_type)


def accepted_unverified(
    requested: dict[str, Any],
    observed: Any,
    *,
    message: str | None = None,
) -> dict[str, Any]:
    """Return a stable, redaction-safe result for an accepted mutation."""
    return {
        "success": False,
        "status": "accepted_unverified",
        "accepted": True,
        "retry_safe": False,
        "message": message
        or (
            "Controller accepted the mutation, but verification did not converge. "
            "Retrying is unsafe and may duplicate or conflict with the accepted change; "
            "check server logs and controller state."
        ),
        "requested": requested,
        "observed": observed,
        "category": "verification_failed",
    }


def delivery_unknown(operation: str, *, duplicate_risk: bool = False) -> dict[str, Any]:
    """Return a stable result when mutation delivery cannot be determined."""
    message = (
        f"Connection failed during {operation}; the controller outcome is unknown. "
        "Inspect current state before retrying because a retry may duplicate or conflict "
        "with a delivered change."
    )
    if duplicate_risk:
        message += " In particular, retrying may create a duplicate network."
    return {
        "success": False,
        "status": "delivery_unknown",
        "accepted": None,
        "retry_safe": False,
        "message": message,
        "category": "transport_uncertain",
    }


def preflight_failed(operation: str) -> dict[str, Any]:
    """Return a stable result when a mutation fails before dispatch."""
    return {
        "success": False,
        "status": "preflight_failed",
        "accepted": False,
        "retry_safe": True,
        "message": (
            f"{operation.capitalize()} preflight failed before dispatch; no mutation request "
            "was sent. Retry is safe after controller connectivity is restored."
        ),
        "category": "transport_preflight",
    }
