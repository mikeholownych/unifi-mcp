# Phase 3 Snapshots and Reports Implementation Plan

**Goal:** Export deterministic, verifiable, secret-free portable UniFi snapshots and render the same model as safe HTML or CSV reports.

**Architecture:** A capability-aware collector builds one strict `SnapshotDocument`. Canonical serialization and SHA-256 verification are pure functions. A bounded export service writes only beneath a configured export root using same-directory temporary files, `fsync`, `0600` permissions, and atomic replacement. JSON snapshots, HTML reports, and CSV reports all consume the same redacted document so presentation cannot change findings.

**Safety Contracts:**

- Default exports never contain credentials, API keys, cookies, authorization headers, WLAN passphrases, webhook secrets, or environment values.
- Export tools accept a filename, not an arbitrary filesystem path; traversal and symlink escapes are rejected.
- Snapshot content ordering is deterministic. `generated_at` is declared volatile metadata and excluded from the content checksum.
- Every omitted or failed source appears in `limitations`; partial data is never represented as complete.
- Native controller backup download/restore remains unavailable until controller-family endpoints and restore safeguards are proven.
- HTML values are escaped and CSV cells beginning with formula characters are neutralized.
- Export size, collection concurrency, API calls, and returned MCP payloads are bounded.

## Task 1: Strict Snapshot Schema

- Create `src/unifi_mcp/snapshots/models.py` and `tests/test_snapshot_models.py`.
- Define schema version, generated time, source scope, redaction status, capabilities, limitations, sites, devices, networks, WLAN metadata, firewall metadata, and Protect inventory.
- Reject timezone-naive metadata, extra fields, duplicate stable identities, and secret-shaped keys recursively.
- Sort all identity-bearing collections by documented stable keys.

## Task 2: Canonical Serialization and Verification

- Create `src/unifi_mcp/snapshots/codec.py` and `tests/test_snapshot_codec.py`.
- Serialize UTF-8 canonical JSON with sorted keys and fixed separators.
- Compute `content_sha256` over schema/content excluding declared volatile metadata and checksum fields.
- Verify schema support, checksum format, checksum match, truncation/JSON errors, and maximum input size.
- Prove equivalent documents produce identical content bytes/checksums despite input ordering or generation time.

## Task 3: Capability-Aware Collection

- Create `src/unifi_mcp/snapshots/collector.py` and `tests/test_snapshot_collector.py`.
- Collect supported Network inventory/configuration and Protect inventory through existing clients with bounded concurrency and fresh reads.
- Persist allowlisted fields only; WLAN security mode may be included but passphrases and private keys may not.
- Record source, device, site, capability mode, and redacted error code for each omission.
- Continue independent sources after partial failures.

## Task 4: Atomic Export Service

- Add export settings to `src/unifi_mcp/config.py`; create `src/unifi_mcp/snapshots/export.py` and `tests/test_snapshot_export.py`.
- Default export root to `<data_dir>/exports`; require an absolute override.
- Validate a plain filename with an allowlisted extension and resolve it beneath the root.
- Reject existing symlinks and parent escapes; create directories with restrictive permissions.
- Write a same-directory temporary file, flush and `fsync`, chmod `0600`, atomically replace, and `fsync` the directory.
- Delete temporary files on cancellation/failure without modifying an existing destination.

## Task 5: Shared Report Model and Renderers

- Create `src/unifi_mcp/reports/models.py`, `html.py`, and `csv.py` with focused tests.
- Derive summary/findings/limitations/source scope from `SnapshotDocument` only.
- Render standalone accessible HTML with escaped values, semantic headings/tables, print styles, and generation/redaction metadata.
- Render RFC 4180 CSV with a fixed column contract and neutralize cells beginning with `=`, `+`, `-`, or `@`.
- Keep PDF outside the base dependency set and report it as an unavailable optional renderer.

## Task 6: MCP Tools and Contracts

- Create `src/unifi_mcp/tools/exports.py`; register tools in `src/unifi_mcp/server.py`.
- Add read-only `get_snapshot_capabilities` and `verify_snapshot`.
- Add confirmation-gated `export_portable_snapshot` and `export_network_report` accepting only filenames and supported formats.
- Return checksum, byte size, schema version, source counts, limitations, and relative export identity; do not return raw large documents.
- Update and inspect `tests/fixtures/tool_contracts.json` and stdio compatibility coverage.

## Task 7: Documentation and Release Gate

- Update `.env.example`, `README.md`, and `CHANGELOG.md` with export root, omissions, verification, redaction, and native-backup limitations.
- Add fixtures containing fake credentials/passphrases and assert they never appear in JSON/HTML/CSV output.
- Run full pytest, Ruff, lock checks, wheel/sdist build, Docker build/smoke, skill validation, wire contracts, and a repository secret scan.

Do not commit or push unless explicitly requested.
