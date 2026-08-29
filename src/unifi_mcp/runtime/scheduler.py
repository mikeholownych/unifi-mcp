"""SQLite-backed allowlisted interval scheduler."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from unifi_mcp.runtime.jobs import JobRegistry
from unifi_mcp.runtime.store import RuntimeStore


class Schedule(BaseModel):
    """Persisted interval schedule."""

    id: str
    name: str
    job_name: str
    interval_seconds: int = Field(ge=10)
    arguments: dict[str, Any]
    enabled: bool
    running: bool
    next_run_at: datetime
    last_run_at: datetime | None = None

    @field_validator("next_run_at", "last_run_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("schedule timestamps must include a timezone")
        return value.astimezone(UTC) if value is not None else None


class JobRun(BaseModel):
    """Result of one scheduler execution."""

    id: str
    schedule_id: str
    job_name: str
    status: Literal["succeeded", "failed", "cancelled"]
    started_at: datetime
    finished_at: datetime
    error_code: str | None = None


class StoredJobRun(BaseModel):
    """Redacted persisted job run."""

    id: str
    schedule_id: str | None
    job_name: str
    status: str
    attempt: int
    started_at: datetime
    finished_at: datetime | None


def _schedule_from_row(row: tuple[Any, ...]) -> Schedule:
    return Schedule(
        id=row[0],
        name=row[1],
        job_name=row[2],
        interval_seconds=row[3],
        arguments=json.loads(row[4]),
        enabled=bool(row[5]),
        running=bool(row[6]),
        next_run_at=row[7],
        last_run_at=row[8],
    )


class Scheduler:
    """Claim and execute interval schedules through a fixed job registry."""

    def __init__(
        self,
        store: RuntimeStore,
        registry: JobRegistry,
        *,
        job_timeout_seconds: float = 300,
        stale_run_seconds: float = 900,
        max_job_attempts: int = 3,
        retry_initial_delay_seconds: float = 1,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self._store = store
        self._registry = registry
        self._job_timeout_seconds = job_timeout_seconds
        self._stale_run_seconds = stale_run_seconds
        self._max_job_attempts = max(1, max_job_attempts)
        self._retry_initial_delay_seconds = max(0, retry_initial_delay_seconds)
        self._sleep = sleep

    async def create_interval_schedule(
        self,
        *,
        name: str,
        job_name: str,
        interval_seconds: int,
        arguments: dict[str, object],
        now: datetime | None = None,
    ) -> Schedule:
        validated_arguments = self._registry.validate(job_name, arguments)
        if interval_seconds < 10:
            raise ValueError("interval_seconds must be at least 10")
        current = (now or datetime.now(UTC)).astimezone(UTC)
        schedule_id = str(uuid4())
        encoded_arguments = json.dumps(
            validated_arguments.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        async with self._store.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO schedules (
                    id, name, job_name, interval_seconds, arguments_json, enabled,
                    running, next_run_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?, ?)
                """,
                (
                    schedule_id,
                    name,
                    job_name,
                    interval_seconds,
                    encoded_arguments,
                    current.isoformat(),
                    current.isoformat(),
                    current.isoformat(),
                ),
            )
        return Schedule(
            id=schedule_id,
            name=name,
            job_name=job_name,
            interval_seconds=interval_seconds,
            arguments=validated_arguments.model_dump(mode="json"),
            enabled=True,
            running=False,
            next_run_at=current,
        )

    async def list_schedules(self) -> list[Schedule]:
        async with self._store.transaction() as connection:
            result = await connection.execute(
                """
                SELECT id, name, job_name, interval_seconds, arguments_json,
                       enabled, running, next_run_at, last_run_at
                FROM schedules ORDER BY name
                """
            )
            rows = await result.fetchall()
        return [_schedule_from_row(row) for row in rows]

    async def set_schedule_enabled(self, schedule_id: str, enabled: bool) -> bool:
        now = datetime.now(UTC).isoformat()
        async with self._store.transaction() as connection:
            result = await connection.execute(
                "UPDATE schedules SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), now, schedule_id),
            )
        return result.rowcount == 1

    async def delete_schedule(self, schedule_id: str) -> bool:
        async with self._store.transaction() as connection:
            result = await connection.execute(
                "DELETE FROM schedules WHERE id = ? AND running = 0",
                (schedule_id,),
            )
        return result.rowcount == 1

    async def list_job_runs(self, *, limit: int = 100) -> list[StoredJobRun]:
        async with self._store.transaction() as connection:
            result = await connection.execute(
                """
                SELECT id, schedule_id, job_name, status, attempt, started_at, finished_at
                FROM job_runs ORDER BY started_at DESC, id DESC LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            )
            rows = await result.fetchall()
        return [
            StoredJobRun(
                id=row[0],
                schedule_id=row[1],
                job_name=row[2],
                status=row[3],
                attempt=row[4],
                started_at=row[5],
                finished_at=row[6],
            )
            for row in rows
        ]

    async def _claim_due(self, now: datetime, limit: int) -> list[Schedule]:
        async with self._store.transaction() as connection:
            stale_before = now - timedelta(seconds=self._stale_run_seconds)
            await connection.execute(
                """
                UPDATE job_runs
                SET status = 'interrupted', error_json = '{"code":"stale_claim"}',
                    finished_at = ?
                WHERE status = 'running' AND started_at <= ?
                """,
                (now.isoformat(), stale_before.isoformat()),
            )
            await connection.execute(
                """
                UPDATE schedules SET running = 0, updated_at = ?
                WHERE running = 1 AND updated_at <= ?
                """,
                (now.isoformat(), stale_before.isoformat()),
            )
            result = await connection.execute(
                """
                SELECT id, name, job_name, interval_seconds, arguments_json,
                       enabled, running, next_run_at, last_run_at
                FROM schedules
                WHERE enabled = 1 AND running = 0 AND next_run_at <= ?
                ORDER BY next_run_at, id LIMIT ?
                """,
                (now.isoformat(), limit),
            )
            rows = await result.fetchall()
            for row in rows:
                await connection.execute(
                    "UPDATE schedules SET running = 1, updated_at = ? WHERE id = ?",
                    (now.isoformat(), row[0]),
                )
        claimed = [_schedule_from_row(row) for row in rows]
        return [schedule.model_copy(update={"running": True}) for schedule in claimed]

    async def _execute(self, schedule: Schedule, started_at: datetime) -> JobRun:
        run_id = str(uuid4())
        async with self._store.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO job_runs (
                    id, schedule_id, job_name, status, attempt, started_at
                ) VALUES (?, ?, ?, 'running', 1, ?)
                """,
                (run_id, schedule.id, schedule.job_name, started_at.isoformat()),
            )

        error_code = None
        result_payload: dict[str, Any] | None = None
        cancelled = False
        attempt = 1
        try:
            definition = self._registry.get(schedule.job_name)
        except ValueError:
            status = "failed"
            error_code = "job_unavailable"
        else:
            try:
                arguments = self._registry.validate(schedule.job_name, schedule.arguments)
            except ValueError:
                status = "failed"
                error_code = "job_configuration_invalid"
            else:
                attempt = 0
                max_attempts = self._max_job_attempts if definition.retryable else 1
                try:
                    while True:
                        attempt += 1
                        try:
                            async with asyncio.timeout(self._job_timeout_seconds):
                                result_payload = await definition.handler(arguments)
                        except Exception as exc:
                            if attempt >= max_attempts:
                                status = "failed"
                                error_code = type(exc).__name__
                                break
                            delay = self._retry_initial_delay_seconds * (2 ** (attempt - 1))
                            await self._sleep(delay)
                        else:
                            status = "succeeded"
                            break
                except asyncio.CancelledError:
                    status = "cancelled"
                    error_code = "CancelledError"
                    cancelled = True

        finished_at = datetime.now(UTC)
        next_run = started_at + timedelta(seconds=schedule.interval_seconds)
        async with self._store.transaction() as connection:
            await connection.execute(
                """
                UPDATE job_runs
                SET status = ?, result_json = ?, error_json = ?, attempt = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    json.dumps(result_payload, sort_keys=True)
                    if result_payload is not None
                    else None,
                    json.dumps({"code": error_code}) if error_code else None,
                    attempt,
                    finished_at.isoformat(),
                    run_id,
                ),
            )
            await connection.execute(
                """
                UPDATE schedules
                SET running = 0, last_run_at = ?, next_run_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    started_at.isoformat(),
                    next_run.isoformat(),
                    finished_at.isoformat(),
                    schedule.id,
                ),
            )

        run = JobRun(
            id=run_id,
            schedule_id=schedule.id,
            job_name=schedule.job_name,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            error_code=error_code,
        )
        if cancelled:
            raise asyncio.CancelledError
        return run

    async def run_due(self, *, now: datetime | None = None, limit: int = 10) -> list[JobRun]:
        """Claim and execute currently due schedules."""
        current = (now or datetime.now(UTC)).astimezone(UTC)
        schedules = await self._claim_due(current, max(1, min(limit, 100)))
        return list(
            await asyncio.gather(*(self._execute(schedule, current) for schedule in schedules))
        )

    async def run_schedule_now(self, schedule_id: str, *, now: datetime | None = None) -> JobRun:
        """Atomically claim and run one schedule regardless of its next due time."""
        current = (now or datetime.now(UTC)).astimezone(UTC)
        async with self._store.transaction() as connection:
            result = await connection.execute(
                """
                SELECT id, name, job_name, interval_seconds, arguments_json,
                       enabled, running, next_run_at, last_run_at
                FROM schedules WHERE id = ? AND running = 0
                """,
                (schedule_id,),
            )
            row = await result.fetchone()
            if row is None:
                raise ValueError("schedule was not found or is already running")
            await connection.execute(
                "UPDATE schedules SET running = 1, updated_at = ? WHERE id = ?",
                (current.isoformat(), schedule_id),
            )
        schedule = _schedule_from_row(row).model_copy(update={"running": True})
        return await self._execute(schedule, current)

    async def serve(self, *, tick_seconds: float = 5, max_jobs: int = 10) -> None:
        """Run due work until the owning lifespan cancels this task."""
        while True:
            await self.run_due(limit=max_jobs)
            await asyncio.sleep(tick_seconds)
