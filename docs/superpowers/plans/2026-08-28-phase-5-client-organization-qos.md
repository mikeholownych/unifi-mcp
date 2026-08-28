# Phase 5 Client Organization and QoS Implementation Plan

**Goal:** Add durable local client tags/groups and a deterministic, approval-ready QoS workflow that never mutates unsupported controllers.

**Architecture:** SQLite schema v4 keys organization records by a controller/site-scoped SHA-256 client key derived from the transient normalized MAC, independent of mutable names or randomized display labels. Raw MACs do not enter persistence. A resolver maps user input to one current stable client identity and rejects ambiguity. Policy planning resolves tags/groups to a sorted target snapshot. Controller policy adapters are capability-gated; this release reports built-in QoS unavailable because no validated endpoint exists.

**Safety Contracts:**

- Persist only scoped one-way client keys, tag/group metadata, and timestamps; never persist raw MACs or controller credentials.
- Client names/hostnames are lookup hints only and never form persistence identity.
- Ambiguous or missing names cause no writes.
- Tags do not imply controller policy and policy previews never mutate.
- Apply requires an explicit supported adapter, immutable preview token, confirmation, per-target read-before state, bounded execution, and read-back verification.
- With no validated built-in adapter, all apply requests return capability guidance before any controller mutation request.

## Task 1: Schema v4 and Repository

- Add `client_tags`, `client_groups`, and `client_group_memberships` with controller/site/client identity scoping.
- Enforce unique tags, unique group names per scope, and at most one group membership per client/scope.
- Implement atomic replace-tags, create/delete group, assign/unassign group, list organization, and deterministic target queries.
- Normalize MAC addresses and strict tag/group names; cap bulk sizes.

## Task 2: Stable Client Resolution

- Resolve exact normalized MAC directly or exact case-insensitive name/hostname from fresh known-client reads.
- Reject zero or multiple matches with structured candidate counts and no persisted changes.
- Test renames preserve existing tags/groups because identity remains MAC-based.

## Task 3: Organization MCP Tools

- Add `get_client_organization`, `set_client_tags`, `create_client_group`, `delete_client_group`, `assign_client_group`, `list_client_groups`, and `list_clients_by_organization`.
- Require runtime persistence and `confirm=true` for mutations.
- Return stable identity and local metadata while clearly labeling it local-only.

## Task 4: QoS Capability and Preview

- Add `get_client_qos_capabilities` with controller mode/version guidance and no speculative support.
- Add `plan_client_qos_policy` accepting one client, tag, or group plus validated up/down rates.
- Resolve and sort the exact current target set, reject empty/ambiguous identities, and issue a short-lived preview token tied to scope/rates/targets.
- Add `apply_client_qos_policy`; without a validated adapter it returns unsupported before any network write.
- Define adapter/read-before/apply/read-back interfaces and tests so future support cannot bypass verification.

## Task 5: Documentation and Release Gate

- Document local-only semantics, stable identity, rename behavior, ambiguity, and unsupported QoS guidance.
- Test deterministic/resumable bulk state and prove unsupported apply performs zero client mutation calls.
- Update MCP contracts and run full tests, Ruff, locks, builds, Docker, skills, and diff checks.

Do not commit or push unless explicitly requested.
