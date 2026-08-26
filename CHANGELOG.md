# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-08-26

### Fixed
- Nine tools (`list_sites`, `list_devices`, `get_network_health`, `get_alarms`,
  `archive_all_alarms`, `run_speed_test`, `get_speed_test_status`,
  `get_dpi_stats`, `get_traffic_summary`) failed with argument-count errors;
  all now accept the standard `device` parameter.
- Alarms/events endpoints were removed by UniFi Network 10; affected tools now
  degrade gracefully with an empty result instead of erroring.

### Added
- `get_firewall_policies` tool exposing zone-based firewall policies
  (UniFi Network 9+) including source/destination zones and hit counters.
- Short-TTL read cache (15s) for GET requests to reduce redundant API calls;
  mutations always bypass it.
- MCP tool annotations: `readOnlyHint` for read tools, `destructiveHint` for
  restart/upgrade/provision/forget, `idempotentHint` for safe repeated actions.
- GitHub Actions CI (ruff + pytest), Dockerfile, CONTRIBUTING.md.

## [0.2.0] - 2026-08-26

### Fixed
- Local session authentication (`UNIFI_MODE=local`) now routes requests through
  the traditional controller API (`/proxy/network`) with cookie + CSRF session
  auth instead of always using the Integration API transport.
- Mode-aware `api_base_url` resolution in settings.

### Added
- This CHANGELOG and expanded test suite.
