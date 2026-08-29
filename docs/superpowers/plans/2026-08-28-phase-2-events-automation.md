# Phase 2 Events and Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable, deduplicated UniFi event ingestion, safe interval scheduling, and retryable outbound webhook delivery without enabling background work by default.

**Architecture:** Extend the embedded runtime to schema version 2 and keep controller clients stateless. Source adapters normalize Network and Protect polling results into a strict event envelope; repositories atomically deduplicate and advance cursors. A lifecycle-owned scheduler invokes only registered jobs, while a delivery worker sends signed webhooks using environment-referenced secrets and conservative network-destination validation.

**Tech Stack:** Python 3.11-3.14, MCP SDK 2, asyncio, aiosqlite, httpx, Pydantic, pytest/respx

---

## Safety Contracts

- `UNIFI_AUTOMATION_ENABLED` defaults to `false`; no worker task starts otherwise.
- Polling is described as polling unless a documented source-specific push adapter exists.
- Schedules reference an allowlisted job name and validated JSON arguments; they never execute MCP names, Python expressions, commands, or imports.
- Webhook secrets are environment-variable references. Secret values never enter SQLite, tool responses, logs, fixtures, or delivery errors.
- Webhooks default to HTTPS, reject URL credentials and redirects, and reject loopback/private/link-local/multicast/reserved destinations unless `UNIFI_WEBHOOK_ALLOW_PRIVATE=true`.
- Every worker has bounded concurrency, timeout, retry, payload size, retention, and shutdown behavior.
- Partial multi-device polling records per-source outcomes and never advances a failed source cursor.

## Task 1: Runtime Schema Version 2

**Files:**
- Modify: `src/unifi_mcp/runtime/store.py`
- Create: `src/unifi_mcp/runtime/models.py`
- Create: `tests/test_runtime_migrations.py`

- [ ] Write migration tests starting from empty and released v1 databases, plus rollback and future-version refusal tests.
- [ ] Increase `SCHEMA_VERSION` to 2 and apply v2 in one transaction after v1.
- [ ] Create `events` with stable `id`, unique `(source, source_key)`, device/site/category/severity/timestamps, subject/details JSON, and insertion timestamp.
- [ ] Create `event_cursors` keyed by source/device/site.
- [ ] Create `schedules` with allowlisted job name, interval, enabled/running state, next/last run, arguments JSON, and timestamps.
- [ ] Create `job_runs` with schedule/job identity, status, bounded result/error JSON, started/finished times, and retry count.
- [ ] Create `webhook_destinations` containing name, URL, enabled state, optional secret environment-variable name, event category filter JSON, and timestamps.
- [ ] Create `webhook_deliveries` with event/destination identity, status, attempt count, next attempt, HTTP status, redacted error category, and timestamps; enforce one delivery per event/destination.
- [ ] Add indexes for event time/category, due schedules, due deliveries, and retention scans.
- [ ] Use strict Pydantic models with UTC-aware timestamp validation and bounded JSON fields.

## Task 2: Event Repository and Normalization

**Files:**
- Create: `src/unifi_mcp/runtime/events.py`
- Create: `src/unifi_mcp/events/models.py`
- Create: `src/unifi_mcp/events/normalize.py`
- Create: `tests/test_events.py`

- [ ] Write tests for duplicate insert, cursor atomicity, ordering, pagination limits, category filters, and retention batches.
- [ ] Define `NormalizedEvent` with schema version, source key, source/device/site, category, severity, occurred time, summary, optional subject type/id, and allowlisted details.
- [ ] Normalize Network events using controller ID where present; otherwise derive a SHA-256 source key from stable source fields.
- [ ] Normalize Protect events using event ID and map motion/smart/ring categories and timestamps.
- [ ] Strip keys matching credential/token/password/cookie/authorization patterns recursively and cap summaries/details.
- [ ] Insert events and update a source cursor in one transaction only after a complete successful source page.
- [ ] Queue webhook deliveries atomically for newly inserted matching events.

## Task 3: Capability-Based Polling Sources

**Files:**
- Create: `src/unifi_mcp/events/sources.py`
- Modify: `src/unifi_mcp/clients/network.py`
- Modify: `src/unifi_mcp/clients/protect.py`
- Create: `tests/test_event_sources.py`

- [ ] Add incremental Network event reads accepting bounded start time/cursor parameters and explicit fresh reads.
- [ ] Add bounded Protect event reads accepting start/end time and deterministic ordering.
- [ ] Implement one source per configured controller/service and report `polling`, `unsupported`, or future `native_push` capability.
- [ ] Mark Integration/Cloud Network events unsupported with existing remediation rather than empty success.
- [ ] Mark Protect polling unavailable without local credentials.
- [ ] Apply jitter and controller rate-limit metadata without sleeping inside repository transactions.
- [ ] Test overlapping pages, equal timestamps, source failure, rate limiting, and clock skew.

## Task 4: Polling Orchestrator

**Files:**
- Create: `src/unifi_mcp/events/poller.py`
- Create: `tests/test_event_poller.py`

- [ ] Poll sources independently with bounded concurrency and per-source timeout.
- [ ] Start from the persisted cursor with a configurable overlap window to avoid timestamp-boundary loss; rely on source-key deduplication.
- [ ] Persist successful pages and cursor atomically; retain old cursor on normalization, API, or storage failure.
- [ ] Return aggregate and per-source counts/status without credentials or raw payloads.
- [ ] Add `poll_events` allowlisted job and a direct run path sharing the same orchestrator.

## Task 5: Allowlisted Scheduler

**Files:**
- Create: `src/unifi_mcp/runtime/jobs.py`
- Create: `src/unifi_mcp/runtime/scheduler.py`
- Modify: `src/unifi_mcp/config.py`
- Modify: `src/unifi_mcp/clients/base.py`
- Create: `tests/test_scheduler.py`

- [ ] Add settings for automation enabled, tick interval, max concurrent jobs, stale-run timeout, and retention with validated bounds.
- [ ] Implement a registry containing only `poll_events`, `retry_webhook_deliveries`, and `prune_runtime_data` in Phase 2.
- [ ] Validate each job's arguments through a dedicated Pydantic model before schedule creation and execution.
- [ ] Claim due schedules atomically, prevent overlap, record each run, calculate next UTC run from `interval_seconds`, and recover stale running claims.
- [ ] Retry only jobs whose registered policy permits it; use bounded exponential backoff and retain a redacted final result.
- [ ] Start one scheduler task only when persistence and automation are enabled; cancel and await it before closing SQLite.
- [ ] Test no-task defaults, cancellation during sleep/work, one-claim concurrency, restart recovery, failure isolation, and cleanup ordering.

## Task 6: Secure Webhook Delivery

**Files:**
- Create: `src/unifi_mcp/runtime/webhooks.py`
- Create: `src/unifi_mcp/security/destinations.py`
- Create: `tests/test_webhooks.py`

- [ ] Validate destination scheme, hostname, no credentials/fragments, resolved IP classes, and opt-in private destinations.
- [ ] Re-resolve before every attempt, disable redirects, and use a dedicated HTTP client with timeout and connection limits.
- [ ] Send a versioned JSON envelope with event ID/source/category/severity/time/summary/subject/details.
- [ ] Add `X-UniFi-Event-ID`, timestamp, and optional HMAC-SHA256 signature over timestamp plus raw body.
- [ ] Read the secret from the referenced environment variable only at send time; missing secrets produce a redacted permanent configuration failure.
- [ ] Treat 2xx as delivered, 408/429/5xx and transport failures as retryable, other 4xx as permanent, honoring bounded `Retry-After`.
- [ ] Claim deliveries atomically, cap attempts, and mark dead-letter state without blocking other destinations.
- [ ] Test DNS/private rejection, redirects, HMAC, retry classes, duplicate suppression, concurrent claims, payload redaction, and secret leakage.

## Task 7: MCP Management Tools

**Files:**
- Create: `src/unifi_mcp/tools/runtime.py`
- Modify: `src/unifi_mcp/server.py`
- Modify: `tests/fixtures/tool_contracts.json`
- Create: `tests/test_runtime_tools.py`

- [ ] Add read-only `list_runtime_events`, `get_event_polling_status`, `list_schedules`, `list_job_runs`, `list_webhook_destinations`, and `list_webhook_deliveries`.
- [ ] Add `poll_events_now` with bounded source selection and no requirement for the background scheduler.
- [ ] Add confirmation-gated `create_interval_schedule`, `set_schedule_enabled`, and `delete_schedule`.
- [ ] Add confirmation-gated `create_webhook_destination`, `set_webhook_destination_enabled`, `delete_webhook_destination`, and `test_webhook_destination`.
- [ ] Return structured capability-unavailable responses when persistence is disabled, and automation-unavailable responses where background execution is required.
- [ ] Never return destination secret values or secret environment contents.
- [ ] Regenerate and inspect the complete wire-contract fixture; add real in-memory calls for representative read/write-gated tools.

## Task 8: Retention, Documentation, and Release Gate

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `Dockerfile` only if runtime defaults require no behavior change

- [ ] Document polling limitations, runtime requirement, intervals, retention, webhook security, private-network opt-in, and retry/dead-letter semantics.
- [ ] Add safe examples that reference `UNIFI_WEBHOOK_SECRET_*` by name and never contain real secrets.
- [ ] Prune events, completed job runs, and terminal deliveries in bounded transactions using configured retention.
- [ ] Run migration tests from v1 artifacts, full pytest, Ruff, both lock validations, wire-contract and stdio tests, wheel/sdist build, Docker build/smoke, and secret scan.
- [ ] Verify automation disabled creates no tasks or outbound requests; enabled shutdown leaves no task, HTTP client, or SQLite warnings.

Do not commit or push unless explicitly requested.
