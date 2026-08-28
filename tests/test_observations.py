"""Tests for bounded aggregate observation persistence and gaps."""

from datetime import UTC, datetime, timedelta

from unifi_mcp.observability.models import DeviceCountMetrics, Observation
from unifi_mcp.runtime import RuntimeStore
from unifi_mcp.runtime.observations import ObservationRepository


async def test_observation_repository_deduplicates_and_returns_explicit_gaps(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    repository = ObservationRepository(store)
    start = datetime(2026, 8, 28, 12, tzinfo=UTC)
    observations = [
        Observation(
            source="network",
            controller="gateway",
            site="default",
            kind="device_counts",
            status="ok",
            observed_at=start,
            metrics=DeviceCountMetrics(total=3, online=2, offline=1),
        ),
        Observation(
            source="network",
            controller="gateway",
            site="default",
            kind="device_counts",
            status="ok",
            observed_at=start + timedelta(minutes=2),
            metrics=DeviceCountMetrics(total=4, online=4, offline=0),
        ),
    ]

    try:
        first = await repository.insert_batch(observations)
        second = await repository.insert_batch(observations[:1])
        trend = await repository.query_trend(
            kind="device_counts",
            metric="online",
            start=start,
            end=start + timedelta(minutes=3),
            bucket_seconds=60,
            source="network",
            controller="gateway",
            site="default",
        )
    finally:
        await store.close()

    assert first == 2
    assert second == 0
    assert [bucket.present for bucket in trend] == [True, False, True]
    assert [bucket.value for bucket in trend] == [2.0, None, 4.0]
