"""Secure, retryable outbound event webhook delivery."""

import hashlib
import hmac
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel

from unifi_mcp.runtime.store import RuntimeStore
from unifi_mcp.security.destinations import Resolver, resolve_hostname, validate_webhook_url

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


class WebhookDestination(BaseModel):
    """Persisted non-secret webhook configuration."""

    id: str
    name: str
    url: str
    secret_env_name: str | None
    categories: list[str]
    enabled: bool


class DeliveryResult(BaseModel):
    """Redacted outcome of one delivery attempt."""

    delivery_id: str
    status: Literal["delivered", "retry", "failed"]
    http_status: int | None = None
    error_code: str | None = None


class StoredDelivery(BaseModel):
    """Redacted delivery state exposed to management tools."""

    id: str
    event_id: str
    destination_id: str
    status: str
    attempt_count: int
    next_attempt_at: datetime
    http_status: int | None
    error_code: str | None


class WebhookTestResult(BaseModel):
    """Redacted result from a synthetic destination test."""

    status: Literal["succeeded", "failed"]
    http_status: int | None = None
    error_code: str | None = None


class WebhookService:
    """Manage destinations and deliver queued normalized events."""

    def __init__(
        self,
        store: RuntimeStore,
        client: httpx.AsyncClient,
        *,
        allow_private: bool = False,
        resolver: Resolver = resolve_hostname,
        secret_lookup: Callable[[str], str | None] = os.environ.get,
        max_attempts: int = 5,
    ) -> None:
        self._store = store
        self._client = client
        self._allow_private = allow_private
        self._resolver = resolver
        self._secret_lookup = secret_lookup
        self._max_attempts = max_attempts

    async def create_destination(
        self,
        *,
        name: str,
        url: str,
        secret_env_name: str | None,
        categories: list[str],
    ) -> WebhookDestination:
        await validate_webhook_url(url, allow_private=self._allow_private, resolver=self._resolver)
        if secret_env_name is not None and not _ENV_NAME.fullmatch(secret_env_name):
            raise ValueError("secret_env_name must be an uppercase environment variable name")
        normalized_categories = sorted(set(categories))
        if any(not category or len(category) > 128 for category in normalized_categories):
            raise ValueError("webhook categories must be non-empty and at most 128 characters")

        destination_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        async with self._store.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO webhook_destinations (
                    id, name, url, secret_env_name, categories_json, enabled,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    destination_id,
                    name,
                    url,
                    secret_env_name,
                    json.dumps(normalized_categories, separators=(",", ":")),
                    now,
                    now,
                ),
            )
        return WebhookDestination(
            id=destination_id,
            name=name,
            url=url,
            secret_env_name=secret_env_name,
            categories=normalized_categories,
            enabled=True,
        )

    async def list_destinations(self) -> list[WebhookDestination]:
        async with self._store.transaction() as connection:
            result = await connection.execute(
                """
                SELECT id, name, url, secret_env_name, categories_json, enabled
                FROM webhook_destinations ORDER BY name
                """
            )
            rows = await result.fetchall()
        return [
            WebhookDestination(
                id=row[0],
                name=row[1],
                url=row[2],
                secret_env_name=row[3],
                categories=json.loads(row[4]),
                enabled=bool(row[5]),
            )
            for row in rows
        ]

    async def test_destination(self, destination_id: str) -> WebhookTestResult:
        async with self._store.transaction() as connection:
            result = await connection.execute(
                """
                SELECT url, secret_env_name FROM webhook_destinations WHERE id = ?
                """,
                (destination_id,),
            )
            row = await result.fetchone()
        if row is None:
            raise ValueError("webhook destination was not found")

        url, secret_env_name = row
        body = b'{"schema_version":1,"test":true}'
        timestamp = str(int(datetime.now(UTC).timestamp()))
        headers = {"Content-Type": "application/json", "X-UniFi-Timestamp": timestamp}
        if secret_env_name:
            secret = self._secret_lookup(secret_env_name)
            if secret is None:
                return WebhookTestResult(status="failed", error_code="secret_unavailable")
            signature = hmac.new(
                secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
            ).hexdigest()
            headers["X-UniFi-Signature"] = f"sha256={signature}"

        try:
            await validate_webhook_url(
                url, allow_private=self._allow_private, resolver=self._resolver
            )
            response = await self._client.post(
                url, content=body, headers=headers, follow_redirects=False
            )
        except ValueError:
            return WebhookTestResult(status="failed", error_code="destination_rejected")
        except httpx.HTTPError:
            return WebhookTestResult(status="failed", error_code="transport_error")

        if 200 <= response.status_code < 300:
            return WebhookTestResult(status="succeeded", http_status=response.status_code)
        return WebhookTestResult(
            status="failed",
            http_status=response.status_code,
            error_code=f"http_{response.status_code}",
        )

    async def set_destination_enabled(self, destination_id: str, enabled: bool) -> bool:
        async with self._store.transaction() as connection:
            result = await connection.execute(
                """
                UPDATE webhook_destinations SET enabled = ?, updated_at = ? WHERE id = ?
                """,
                (int(enabled), datetime.now(UTC).isoformat(), destination_id),
            )
        return result.rowcount == 1

    async def delete_destination(self, destination_id: str) -> bool:
        async with self._store.transaction() as connection:
            result = await connection.execute(
                "DELETE FROM webhook_destinations WHERE id = ?",
                (destination_id,),
            )
        return result.rowcount == 1

    async def list_deliveries(self, *, limit: int = 100) -> list[StoredDelivery]:
        async with self._store.transaction() as connection:
            result = await connection.execute(
                """
                SELECT id, event_id, destination_id, status, attempt_count,
                       next_attempt_at, http_status, error_code
                FROM webhook_deliveries
                ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            )
            rows = await result.fetchall()
        return [
            StoredDelivery(
                id=row[0],
                event_id=row[1],
                destination_id=row[2],
                status=row[3],
                attempt_count=row[4],
                next_attempt_at=row[5],
                http_status=row[6],
                error_code=row[7],
            )
            for row in rows
        ]

    async def _claim_due(self, now: datetime, limit: int) -> list[tuple[Any, ...]]:
        async with self._store.transaction() as connection:
            result = await connection.execute(
                """
                SELECT d.id, d.attempt_count,
                       w.url, w.secret_env_name,
                       e.id, e.source, e.source_key, e.device_name, e.site,
                       e.category, e.severity, e.occurred_at, e.summary,
                       e.subject_type, e.subject_id, e.details_json
                FROM webhook_deliveries d
                JOIN webhook_destinations w ON w.id = d.destination_id
                JOIN events e ON e.id = d.event_id
                WHERE d.status IN ('pending', 'retry')
                  AND d.next_attempt_at <= ? AND w.enabled = 1
                ORDER BY d.next_attempt_at, d.id
                LIMIT ?
                """,
                (now.isoformat(), limit),
            )
            rows = await result.fetchall()
            for row in rows:
                await connection.execute(
                    "UPDATE webhook_deliveries SET status = 'delivering', updated_at = ? WHERE id = ?",
                    (now.isoformat(), row[0]),
                )
        return rows

    async def _record_result(
        self,
        delivery_id: str,
        *,
        status: str,
        attempts: int,
        now: datetime,
        http_status: int | None,
        error_code: str | None,
    ) -> None:
        next_attempt = now + timedelta(seconds=min(300, 2 ** max(0, attempts - 1)))
        async with self._store.transaction() as connection:
            await connection.execute(
                """
                UPDATE webhook_deliveries
                SET status = ?, attempt_count = ?, next_attempt_at = ?,
                    http_status = ?, error_code = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    attempts,
                    next_attempt.isoformat(),
                    http_status,
                    error_code,
                    now.isoformat(),
                    delivery_id,
                ),
            )

    async def _deliver(self, row: tuple[Any, ...], now: datetime) -> DeliveryResult:
        delivery_id, previous_attempts, url, secret_env_name = row[:4]
        attempts = previous_attempts + 1
        event = {
            "id": row[4],
            "source": row[5],
            "source_key": row[6],
            "device_name": row[7],
            "site": row[8],
            "category": row[9],
            "severity": row[10],
            "occurred_at": row[11],
            "summary": row[12],
            "subject_type": row[13],
            "subject_id": row[14],
            "details": json.loads(row[15]),
        }
        body = json.dumps(
            {"schema_version": 1, "event": event},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        timestamp = str(int(now.timestamp()))
        headers = {
            "Content-Type": "application/json",
            "X-UniFi-Event-ID": event["id"],
            "X-UniFi-Timestamp": timestamp,
        }

        if secret_env_name:
            secret = self._secret_lookup(secret_env_name)
            if secret is None:
                await self._record_result(
                    delivery_id,
                    status="failed",
                    attempts=attempts,
                    now=now,
                    http_status=None,
                    error_code="secret_unavailable",
                )
                return DeliveryResult(
                    delivery_id=delivery_id, status="failed", error_code="secret_unavailable"
                )
            signature = hmac.new(
                secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
            ).hexdigest()
            headers["X-UniFi-Signature"] = f"sha256={signature}"

        try:
            await validate_webhook_url(
                url, allow_private=self._allow_private, resolver=self._resolver
            )
            response = await self._client.post(
                url, content=body, headers=headers, follow_redirects=False
            )
        except ValueError:
            status, error_code, http_status = "failed", "destination_rejected", None
        except httpx.HTTPError:
            status, error_code, http_status = "retry", "transport_error", None
        else:
            http_status = response.status_code
            if 200 <= http_status < 300:
                status, error_code = "delivered", None
            elif http_status in {408, 429} or http_status >= 500:
                status, error_code = "retry", f"http_{http_status}"
            else:
                status, error_code = "failed", f"http_{http_status}"

        database_status = status
        if status == "retry" and attempts >= self._max_attempts:
            status = "failed"
            database_status = "dead_letter"
            error_code = "attempts_exhausted"
        await self._record_result(
            delivery_id,
            status=database_status,
            attempts=attempts,
            now=now,
            http_status=http_status,
            error_code=error_code,
        )
        return DeliveryResult(
            delivery_id=delivery_id,
            status=status,
            http_status=http_status,
            error_code=error_code,
        )

    async def deliver_due(
        self, *, now: datetime | None = None, limit: int = 100
    ) -> list[DeliveryResult]:
        """Claim and deliver due events sequentially with bounded work."""
        current = (now or datetime.now(UTC)).astimezone(UTC)
        rows = await self._claim_due(current, max(1, min(limit, 1000)))
        return [await self._deliver(row, current) for row in rows]
