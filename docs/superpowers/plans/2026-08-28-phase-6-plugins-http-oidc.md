# Phase 6 Plugins, HTTP Transport, and OIDC Implementation Plan

**Goal:** Add disabled-by-default trusted plugins and an optional authenticated Streamable HTTP transport without changing stdio behavior.

**Architecture:** Plugins are discovered as metadata through the `unifi_mcp.plugins` Python entry-point group and loaded only after exact-name allowlist checks. A versioned registry accepts tools, collectors, jobs, notification sinks, and report renderers while rejecting duplicates. Streamable HTTP uses the MCP SDK's native server, authentication middleware, and token-verifier protocol. An OIDC verifier validates discovery, JWKS signatures, algorithms, issuer, audience, expiry, and scopes with bounded caches and one forced key refresh.

**Security Contracts:**

- Stdio remains the default and never requires OIDC.
- HTTP cannot start unless issuer, audience, public resource URL, algorithms, and scope names validate.
- Non-loopback HTTP binding additionally requires explicit remote-binding opt-in.
- Every HTTP request requires the read scope; write tools also require write; plugin status and runtime administration require admin.
- Confirmation gates remain mandatory and are not replaced by authorization scopes.
- Plugin entry-point code is never imported unless its distribution/name is allowlisted.
- Plugins are trusted local code, not sandboxed. Required plugin failure aborts startup; optional failure is isolated and reported.
- Tokens, authorization headers, claims, and signing keys are never logged or persisted.

## Task 1: Plugin Contract and Loader

- Define API version 1 registration models for tools, collectors, jobs, sinks, and renderers.
- Discover entry points without loading them, enforce exact allowlists, then load/register.
- Reject duplicate names, incompatible versions, malformed registrations, and core tool collisions.
- Add redacted plugin status with loaded/skipped/failed state and actionable reason codes.

## Task 2: HTTP and OIDC Configuration

- Add `stdio`/`streamable-http` transport configuration with loopback host default and no listener by default.
- Require OIDC issuer, audience, public resource URL, allowed asymmetric algorithms, and read/write/admin scope names for HTTP.
- Add an optional `oidc` dependency extra while keeping imports lazy for base stdio users.

## Task 3: OIDC Verification

- Fetch issuer discovery and JWKS using bounded timeouts and TLS verification.
- Cache discovery/JWKS for a bounded interval and force at most one refresh for unknown/rotated keys.
- Validate key ID, asymmetric algorithm allowlist, signature, issuer, audience, expiry, subject/client identity, and scope shape.
- Return MCP `AccessToken` only after full validation; all failures return unauthenticated without secret-bearing details.

## Task 4: Scope Authorization and Server Startup

- Use SDK request middleware and authenticated access-token context, never client-provided headers as identity.
- Derive core write scope policy from audited tool names and require admin for runtime/plugin administration.
- Require plugins to declare `read`, `write`, or `admin` for every tool and merge those policies after registration.
- Start native Streamable HTTP only when explicitly configured; otherwise run existing stdio unchanged.

## Task 5: Documentation and Release Gate

- Document plugin trust boundaries, entry-point contract, allowlisting, HTTP/OIDC configuration, and scope matrix.
- Add plugin loading, OIDC failure-mode, scope, config, stdio compatibility, and HTTP smoke tests.
- Update public MCP contracts, dependency locks, README, environment example, and changelog.
- Run full tests, Ruff, lock validation, builds, Docker, skill validation, and diff checks.

Do not commit or push unless explicitly requested.
