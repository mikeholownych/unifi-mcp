"""Tests for the allowlisted interval scheduler."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel

from unifi_mcp.runtime import RuntimeStore
from unifi_mcp.runtime.jobs import JobDefinition, JobRegistry
from unifi_mcp.runtime.scheduler import Scheduler


class ExampleArguments(BaseModel):
    value: int


async def test_scheduler_rejects_unknown_jobs_and_runs_due_job_once(tmp_path):
    calls: list[int] = []

    async def handler(arguments: ExampleArguments) -> dict[str, int]:
        calls.append(arguments.value)
        return {"value": arguments.value}

    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    scheduler = Scheduler(
        store,
        JobRegistry(
            [JobDefinition(name="example", arguments_model=ExampleArguments, handler=handler)]
        ),
    )
    now = datetime(2026, 8, 28, 12, tzinfo=UTC)

    try:
        with pytest.raises(ValueError, match="not an allowlisted job"):
            await scheduler.create_interval_schedule(
                name="unsafe", job_name="shell", interval_seconds=60, arguments={}, now=now
            )
        with pytest.raises(ValueError, match="unknown job arguments"):
            await scheduler.create_interval_schedule(
                name="extra",
                job_name="example",
                interval_seconds=60,
                arguments={"value": 7, "command": "ignored"},
                now=now,
            )

        schedule = await scheduler.create_interval_schedule(
            name="safe",
            job_name="example",
            interval_seconds=60,
            arguments={"value": 7},
            now=now,
        )
        first = await scheduler.run_due(now=now)
        second = await scheduler.run_due(now=now)
        manual = await scheduler.run_schedule_now(schedule.id, now=now + timedelta(seconds=1))
        schedules = await scheduler.list_schedules()
    finally:
        await store.close()

    assert schedule.job_name == "example"
    assert len(first) == 1
    assert first[0].status == "succeeded"
    assert second == []
    assert manual.status == "succeeded"
    assert calls == [7, 7]
    assert schedules[0].running is False
    assert schedules[0].next_run_at > now


async def test_cancelling_active_job_releases_schedule_claim(tmp_path):
    started = asyncio.Event()
    blocked = asyncio.Event()

    async def handler(_arguments: ExampleArguments) -> dict[str, int]:
        started.set()
        await blocked.wait()
        return {"value": 1}

    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    scheduler = Scheduler(
        store,
        JobRegistry(
            [JobDefinition(name="example", arguments_model=ExampleArguments, handler=handler)]
        ),
    )
    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    await scheduler.create_interval_schedule(
        name="safe",
        job_name="example",
        interval_seconds=60,
        arguments={"value": 7},
        now=now,
    )
    task = asyncio.create_task(scheduler.run_due(now=now))

    try:
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        schedules = await scheduler.list_schedules()
        runs = await scheduler.list_job_runs()
    finally:
        blocked.set()
        await store.close()

    assert schedules[0].running is False
    assert runs[0].status == "cancelled"


async def test_stale_schedule_claim_is_recovered_after_restart(tmp_path):
    calls: list[int] = []

    async def handler(arguments: ExampleArguments) -> dict[str, int]:
        calls.append(arguments.value)
        return {"value": arguments.value}

    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    scheduler = Scheduler(
        store,
        JobRegistry(
            [JobDefinition(name="example", arguments_model=ExampleArguments, handler=handler)]
        ),
        stale_run_seconds=60,
    )
    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    schedule = await scheduler.create_interval_schedule(
        name="safe",
        job_name="example",
        interval_seconds=60,
        arguments={"value": 7},
        now=now,
    )
    async with store.transaction() as connection:
        await connection.execute(
            "UPDATE schedules SET running = 1, updated_at = ? WHERE id = ?",
            ((now - timedelta(minutes=2)).isoformat(), schedule.id),
        )

    try:
        runs = await scheduler.run_due(now=now)
    finally:
        await store.close()

    assert calls == [7]
    assert runs[0].status == "succeeded"


async def test_retryable_job_uses_bounded_attempts(tmp_path):
    attempts = 0

    async def handler(_arguments: ExampleArguments) -> dict[str, int]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("transient secret-bearing message")
        return {"attempts": attempts}

    store = RuntimeStore(tmp_path / "runtime.db")
    await store.open()
    scheduler = Scheduler(
        store,
        JobRegistry(
            [
                JobDefinition(
                    name="example",
                    arguments_model=ExampleArguments,
                    handler=handler,
                    retryable=True,
                )
            ]
        ),
        retry_initial_delay_seconds=0,
    )
    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    await scheduler.create_interval_schedule(
        name="safe",
        job_name="example",
        interval_seconds=60,
        arguments={"value": 7},
        now=now,
    )

    try:
        result = await scheduler.run_due(now=now)
        stored = await scheduler.list_job_runs()
    finally:
        await store.close()

    assert result[0].status == "succeeded"
    assert attempts == 3
    assert stored[0].attempt == 3
