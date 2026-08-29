# UniFi MCP Platform Enhancements Design

**Status:** Approved for phased implementation

**Goal:** Evolve UniFi MCP from an on-demand tool server into a reliable, observable automation service while preserving its lightweight local deployment model and controller safety guarantees.

## Scope

The work ships as six independently releasable phases:

1. Runtime and MCP compatibility
2. Event ingestion and scheduled automation
3. Configuration snapshots and report export
4. Historical trends and Prometheus metrics
5. Client organization and QoS controls
6. Plugins, remote transport, and OIDC

Every phase must leave the package usable on its own. A later phase may depend on an earlier phase, but no release may contain a dormant half-implementation of a later feature.

## Design Principles

- Preserve stdio as the default MCP transport and the existing environment-based setup.
- Keep optional capabilities optional; a basic install must not require a database server, Prometheus, an identity provider, or a PDF renderer.
- Detect controller capabilities before invoking version-sensitive APIs.
- Never report a mutation as successful without a controller read-back when the API permits verification.
- Require explicit confirmation for restoration, network policy, QoS, and other disruptive writes.
- Store no UniFi credentials, API keys, WLAN passphrases, or OIDC secrets in history, event, report, or backup metadata logs.
- Preserve existing public tool names unless an MCP SDK migration makes a schema correction unavoidable.
- Preserve unrelated and pre-existing worktree changes during implementation.

## Architecture

### Integrated Runtime

`AppContext` remains the composition root. It will own the existing shared HTTP client and settings plus an optional runtime service. The runtime service contains focused interfaces for:

- SQLite persistence and migrations
- controller capability records
- normalized event ingestion and deduplication
- schedules and job execution
- notification delivery
- configuration snapshots
- historical observations
- metrics collection
- plugin registration

UniFi API clients remain responsible only for controller communication and response normalization. MCP tool modules orchestrate clients and runtime services; they do not issue raw SQL or manage background task lifecycles.

### Persistence

SQLite is the default embedded store. It uses WAL mode, foreign keys, a bounded busy timeout, and schema migrations applied at startup. The default database path is under a configurable application-data directory, not the repository.

Core records use UTC timestamps and stable IDs. Raw controller responses are not retained by default. Stored payloads are normalized, size-bounded JSON with an explicit schema version. Retention jobs delete expired event and observation records in bounded batches.

The server remains operational without persistence when all runtime features are disabled. Enabling schedules, event history, snapshots, or trend history requires a writable database path and fails startup with an actionable configuration error if storage cannot be initialized.

### Capability Detection

Capabilities are identified by authentication mode, controller service, controller version where available, and a safe endpoint probe where necessary. Results are cached with a timestamp and can be refreshed.

Tools return a structured unavailable result containing the missing capability, detected mode/version, and remediation. They do not guess endpoint compatibility or convert HTTP failures into false empty success responses.

## Phase 1: Runtime and MCP Compatibility

### Deliverables

- Reconcile PEP 621 and Poetry MCP dependency constraints so both resolve the same supported SDK range.
- Remove the current environment failure where MCP 2.x is installed while code imports the removed `mcp.server.fastmcp` module.
- Choose one supported server API after a compatibility spike:
  - Prefer standalone `fastmcp` if it preserves tool schemas, annotations, lifespan context, stdio behavior, and supported Python versions with the smallest change.
  - Use SDK `MCPServer` directly only if it provides equivalent typed context injection without adapter complexity.
- Eliminate duplicate editable package identities (`mcp-unifi` and `unifi-mcp`) from supported setup instructions and lock state.
- Add a startup health resource or equivalent read-only tool reporting server version, transport, persistence state, and configured service counts without secrets.
- Establish migration and runtime interfaces without enabling background jobs yet.

### Acceptance Criteria

- A clean `uv sync` installs one project distribution and a compatible MCP stack.
- Imports and tool enumeration pass on supported Python versions.
- Existing tool names, descriptions, input schemas, annotations, and lifespan behavior remain covered by regression tests.
- Stdio startup and shutdown complete without warnings or leaked HTTP clients.
- Existing uncommitted network features remain intact and passing.

## Phase 2: Events and Scheduled Automation

### Event Ingestion

There is no assumption of a universal UniFi webhook API. Each controller source declares one of:

- native push, only when a documented and tested source exists;
- incremental polling using a stable cursor or timestamp;
- unsupported.

Controller events normalize to a common envelope containing event ID, source device, site, category, severity, occurred time, subject references, summary, and a redacted details object. A unique source key prevents duplicate delivery across polling cycles and restarts.

### Scheduling

Schedules invoke an allowlist of registered jobs, not arbitrary MCP tool names or Python expressions. Initial jobs are read-only audits, health snapshots, firmware checks, event polling, history retention, and notification retries.

Schedules use UTC, record last and next run times, prevent overlapping execution by default, and apply bounded retries with backoff. A failed job does not stop unrelated schedules.

### Notifications

Initial delivery supports outbound HTTPS webhooks with optional bearer or HMAC authentication. Destinations are configured outside persisted payloads; secrets are referenced by environment-variable name. Delivery records retain status and error summaries but not secret headers.

### Acceptance Criteria

- Restarting the service does not duplicate normalized events.
- Polling honors controller rate limits and applies jitter.
- Users can create, pause, inspect, run, and delete schedules through approval-appropriate MCP tools.
- Outbound webhook delivery supports retry, dead-letter status, and an explicit test operation.
- Disabled automation creates no background tasks.

## Phase 3: Snapshots and Reports

### Portable Configuration Snapshots

The baseline backup is a portable, versioned snapshot assembled from supported read APIs. It includes topology and configuration required for assessment or assisted reconstruction, plus a manifest describing omissions caused by authentication or controller capabilities.

Secrets are excluded by default. A future encrypted-secrets option is outside this design. Snapshot files use atomic writes, checksums, restrictive file permissions, and a documented schema version.

Native controller backup download and restore are exposed only after endpoints are validated against supported controller families. Native restore requires explicit confirmation, controller identity checks, a pre-restore snapshot, and a post-operation reconnect verification. If those guarantees cannot be met, native restore remains unavailable rather than simulated.

### Reports

Audit and trend data can be rendered to HTML and CSV. PDF is an optional extra generated from the same report model so formatting does not alter findings. Reports include generation time, source scope, data limitations, and redaction status.

### Acceptance Criteria

- Snapshot output is deterministic apart from declared metadata fields.
- Snapshot verification detects truncation or modification.
- No credential or WLAN passphrase appears in a default snapshot or report fixture.
- Report exports represent partial controller data explicitly.

## Phase 4: History and Observability

### Historical Observations

Collectors store bounded, normalized observations for site health, device health, client counts, traffic summaries, and Protect health where available. Default retention is configurable and conservative. Trend tools aggregate observations in SQL and cap result sizes.

This is operational history, not a packet-flow or full telemetry warehouse. High-cardinality per-client labels are excluded from Prometheus output by default.

### Prometheus

An optional HTTP listener exposes process, runtime, controller reachability, job, event, notification, and aggregate UniFi health metrics. It binds to loopback by default. Remote binding requires explicit configuration and authentication or trusted-network documentation.

### Acceptance Criteria

- Collection remains bounded by retention and batch limits.
- Metrics contain no client names, MAC addresses, IP addresses, SSIDs, or secrets by default.
- Prometheus support is absent from the basic dependency set unless enabled.
- Trend queries return explicit gaps rather than interpolated facts.

## Phase 5: Client Organization and QoS

### Local Organization

Local tags and groups are stored by stable controller/device/site/client identity. They enrich inventory, audit, and policy workflows without requiring controller support. A client may have multiple tags and at most one optional local group unless a later requirement proves multi-group membership necessary.

### Controller Policies

Bandwidth limits and QoS use controller-backed APIs only where detected. Policy tools follow a plan, approve, apply, verify flow. They validate rates, reject ambiguous client identity, snapshot affected state, and surface controller normalization of requested values.

Local tags do not imply a controller policy. Applying a policy to a tag resolves and displays the current target set before approval.

### Acceptance Criteria

- Tags survive client renames and randomized display names when stable identity remains available.
- Bulk policy operations are deterministic, previewable, and resumable after partial failure.
- Unsupported QoS APIs return capability guidance without mutation attempts.
- Read-back verifies every successful controller policy change.

## Phase 6: Plugins, HTTP Transport, and OIDC

### Plugins

Plugins use Python entry points and a versioned registration interface for tools, collectors, jobs, notification sinks, and report renderers. Plugins are disabled unless explicitly allowlisted. They execute as trusted local code; this is documented as a security boundary, not a sandbox.

Duplicate names, incompatible API versions, and registration failures prevent the affected plugin from loading and produce actionable diagnostics. Core startup may continue only when the failed plugin is not marked required.

### Remote Transport and OIDC

Stdio remains unauthenticated local process transport. OIDC applies only to the optional remote HTTP MCP transport. Configuration includes issuer, audience, allowed algorithms, required scopes, and transport binding. Tokens are validated locally from cached discovery/JWKS data with bounded refresh behavior.

Write tools require a write scope in addition to existing confirmation gates. Administrative runtime operations such as plugin status and schedule mutation require an admin scope.

### Acceptance Criteria

- No remote listener starts by default.
- OIDC discovery, signature, issuer, audience, expiry, and scope failures are tested.
- Plugin allowlisting is enforced before plugin code registration.
- Existing stdio users require no identity-provider configuration.

## Error Handling

Runtime errors use stable categories: configuration, capability unavailable, validation, authentication, controller API, persistence, job execution, delivery, plugin, and report generation. User-facing MCP results include remediation but exclude stack traces and secrets. Internal logs include correlation IDs and exception context with redaction.

Partial multi-device operations return per-target outcomes and an aggregate status. They never collapse mixed success into a single success boolean.

## Testing Strategy

- Unit tests cover normalization, redaction, migrations, deduplication, retention, scheduling decisions, policy validation, and token claims.
- HTTP client tests use `respx` fixtures for each authentication mode and controller capability branch.
- Persistence integration tests use temporary real SQLite databases and exercise migrations from every released schema version.
- MCP contract tests snapshot tool names, schemas, annotations, and structured unavailable/error results.
- Lifecycle tests verify startup cancellation, task shutdown, database closure, and HTTP client closure.
- Security tests scan snapshots, reports, logs, metrics, and delivery records for fixture secrets.
- End-to-end smoke tests start stdio and optional HTTP transports and call representative read and write-gated tools.

Every behavioral change follows test-first development: introduce a failing behavior test, verify the expected failure, implement the minimum change, and rerun focused plus regression suites.

## Release and Compatibility Policy

Each phase receives a separate version and changelog entry. Database migrations are forward-only within a released major version and are backed up before application. Tool removals or incompatible schema changes require a major release; additive optional fields do not.

Optional extras are grouped by capability, for example `automation`, `metrics`, `reports`, and `oidc`. The Docker image may include selected extras, while the base Python package remains minimal.

## Explicit Non-Goals

- No claim of real-time push for controllers that expose only polling APIs.
- No arbitrary command execution through schedules.
- No credential storage in SQLite or portable snapshots.
- No automatic destructive remediation.
- No plugin sandbox.
- No high-cardinality monitoring warehouse or indefinite retention.
- No emulated native restore when a verified controller endpoint is unavailable.

## Implementation Order

Implementation starts with Phase 1 only. Before each subsequent phase, its controller endpoints and external contracts are validated against current documentation and fixtures. Discoveries may narrow an unsupported adapter, but may not weaken the safety, redaction, verification, or compatibility requirements in this specification.
