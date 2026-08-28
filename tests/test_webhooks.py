"""Tests for secure outbound webhook destinations and delivery."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from unifi_mcp.events.models import NormalizedEvent
from unifi_mcp.runtime import RuntimeStore
from unifi_mcp.runtime.events import EventRepository
from unifi_mcp.runtime.webhooks import WebhookService
from unifi_mcp.security.destinations import validate_webhook_url


async def test_webhook_url_rejects_private_resolution_and_credentials():
    async def private_resolver(_hostname: str) -> set[str]:
        return {"127.0.0.1"}

    with pytest.raises(ValueError, match="private or reserved"):
        await validate_webhook_url(
            "https://hooks.example.test/events",
            resolver=private_resolver,
        )

    with pytest.raises(ValueError, match="credentials"):
        await validate_webhook_url(
            "https://user:pass@hooks.example.test/events",
            resolver=private_resolver,
        )

    with pytest.raises(ValueError, match="HTTPS"):
        await validate_webhook_url(
            "http://hooks.example.test/events",
            resolver=private_resolver,
        )


async def test_new_event_is_delivered_with_environment_secret_signature(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    async def public_resolver(_hostname: str) -> set[str]:
        return {"93.184.216.34"}

    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    service = WebhookService(
        store,
        client,
        resolver=public_resolver,
        secret_lookup=lambda name: "signing-secret" if name == "WEBHOOK_SECRET" else None,
    )
    repository = EventRepository(store)

    try:
        await service.create_destination(
            name="automation",
            url="https://hooks.example.test/events",
            secret_env_name="WEBHOOK_SECRET",
            categories=[],
        )
        await repository.insert_batch(
            [
                NormalizedEvent(
                    source="network",
                    source_key="event-1",
                    device_name="gateway",
                    site="default",
                    category="network.connected",
                    severity="info",
                    occurred_at=datetime(2026, 8, 28, 12, tzinfo=UTC),
                    summary="Connected",
                )
            ],
            source="network",
            device_name="gateway",
            site="default",
            cursor={"watermark_ms": 1},
        )
        results = await service.deliver_due()
    finally:
        await client.aclose()
        await store.close()

    assert [result.status for result in results] == ["delivered"]
    assert len(requests) == 1
    request = requests[0]
    timestamp = request.headers["X-UniFi-Timestamp"]
    expected = hmac.new(
        b"signing-secret",
        timestamp.encode() + b"." + request.content,
        hashlib.sha256,
    ).hexdigest()
    assert request.headers["X-UniFi-Signature"] == f"sha256={expected}"
    assert json.loads(request.content)["event"]["source_key"] == "event-1"
    assert b"signing-secret" not in request.content


async def test_retryable_failures_end_in_dead_letter(tmp_path):
    async def public_resolver(_hostname: str) -> set[str]:
        return {"93.184.216.34"}

    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        follow_redirects=False,
    )
    service = WebhookService(
        store,
        client,
        resolver=public_resolver,
        max_attempts=2,
    )
    repository = EventRepository(store)
    occurred_at = datetime(2026, 8, 28, 12, tzinfo=UTC)

    try:
        await service.create_destination(
            name="automation",
            url="https://hooks.example.test/events",
            secret_env_name=None,
            categories=[],
        )
        await repository.insert_batch(
            [
                NormalizedEvent(
                    source="network",
                    source_key="event-1",
                    category="network.connected",
                    severity="info",
                    occurred_at=occurred_at,
                    summary="Connected",
                )
            ],
            source="network",
            cursor={},
        )
        now = datetime.now(UTC)
        first = await service.deliver_due(now=now)
        second = await service.deliver_due(now=now + timedelta(seconds=2))
        deliveries = await service.list_deliveries()
    finally:
        await client.aclose()
        await store.close()

    assert first[0].status == "retry"
    assert second[0].status == "failed"
    assert second[0].error_code == "attempts_exhausted"
    assert deliveries[0].status == "dead_letter"
    assert deliveries[0].attempt_count == 2


async def test_destination_can_be_tested_without_persisting_an_event(tmp_path):
    requests: list[httpx.Request] = []

    async def public_resolver(_hostname: str) -> set[str]:
        return {"93.184.216.34"}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = WebhookService(store, client, resolver=public_resolver)

    try:
        destination = await service.create_destination(
            name="automation",
            url="https://hooks.example.test/events",
            secret_env_name=None,
            categories=[],
        )
        result = await service.test_destination(destination.id)
        events = await EventRepository(store).list_events()
    finally:
        await client.aclose()
        await store.close()

    assert result.status == "succeeded"
    assert result.http_status == 202
    assert json.loads(requests[0].content) == {"schema_version": 1, "test": True}
    assert events == []
