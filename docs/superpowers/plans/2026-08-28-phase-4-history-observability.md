# Phase 4 History and Observability Implementation Plan

**Goal:** Retain bounded aggregate UniFi health observations, expose honest trend queries, and optionally serve low-cardinality Prometheus metrics on loopback.

**Architecture:** SQLite schema v3 stores strict aggregate observations by source/controller/site/kind/time. Capability-aware collectors emit only bounded counts, health states, latency, and traffic summaries. SQL trend queries return buckets plus explicit missing intervals. Prometheus support is an optional dependency and lifecycle-owned listener; no listener or import is activated by default.

**Safety Contracts:**

- Observation payloads and metric labels exclude client names, MAC addresses, IP addresses, SSIDs, usernames, and secrets.
- Collectors store aggregate counts, not per-client or packet-flow telemetry.
- Persistence, observation scheduling, and Prometheus serving remain disabled by default.
- Prometheus binds to loopback by default. Non-loopback binding requires explicit remote opt-in and a configured bearer token environment-variable reference.
- Metric names and label values come from fixed enums; controller/site/device identifiers are not labels.
- Collection concurrency, query windows, bucket counts, payload sizes, retention, and HTTP response sizes are bounded.
- Missing collection intervals are returned as gaps, never interpolated values.

## Task 1: Schema v3 and Observation Models

- Add migration tests from released v2 and extend `src/unifi_mcp/runtime/store.py` to schema v3.
- Create `observations` with source/controller/site/kind/time/status and strict aggregate JSON.
- Add indexes for kind/scope/time and retention scans; reject future schema versions as before.
- Create strict models for site health, device counts, client counts, traffic summary, and Protect health.

## Task 2: Observation Repository and Trends

- Create `src/unifi_mcp/runtime/observations.py` with atomic batch insertion, bounded retention, and query APIs.
- Validate UTC timestamps, fixed kinds/statuses, finite non-negative metrics, and payload limits.
- Aggregate fixed UTC buckets in SQL/Python with caller-bounded windows and at most 1000 buckets.
- Return each expected bucket with `present=true/false`; do not synthesize missing values.

## Task 3: Capability-Aware Collectors

- Create `src/unifi_mcp/observability/collectors.py` with independent Network and Protect collectors.
- Collect site subsystem health, online/offline device totals, wired/wireless client totals, bounded traffic totals, and Protect online/offline camera totals where APIs permit.
- Continue after independent source failure and return redacted exception class/capability limitations.
- Add `capture_observations` to the fixed job registry and direct-run path.

## Task 4: MCP History Tools

- Add `capture_observations_now`, `query_observation_trends`, `list_observation_scopes`, and `get_observation_retention_status`.
- Require persistence for storage/query operations and return structured unavailability otherwise.
- Cap lookback, bucket width, rows, and returned precision; expose gaps and limitations explicitly.
- Update and inspect the native MCP wire-contract fixture.

## Task 5: Optional Prometheus Exporter

- Add an `observability` optional dependency group containing `prometheus-client`; keep base dependencies unchanged.
- Add disabled-by-default host/port settings, loopback default, remote-bind opt-in, and bearer-token environment-variable reference.
- Fail configuration before binding if a non-loopback host lacks both explicit opt-in and a referenced token.
- Export fixed process/runtime/controller reachability/job/event/webhook/observation aggregate metrics without identity labels.
- Own listener startup/shutdown in application lifespan and verify clean port release.
- If the optional package is absent while enabled, raise actionable configuration guidance.

## Task 6: Retention, Documentation, and Release Gate

- Extend the runtime prune job for observation retention in bounded deletes.
- Document collection semantics, gaps, cardinality exclusions, optional installation, and secure remote binding.
- Test fixtures containing names/MACs/IPs/SSIDs/secrets never appear in observations or metrics.
- Run full pytest, Ruff, both lock checks, wheel/sdist build, Docker build/smoke, skill validation, stdio contracts, and dependency inspection proving Prometheus is absent from the base install.

Do not commit or push unless explicitly requested.
