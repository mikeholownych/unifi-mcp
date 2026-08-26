# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2026-08-26

### Added
- **Multi-site orchestration tools**: `get_global_inventory`, `get_global_health`,
  `get_global_client_summary` — aggregate data across all configured controllers.
- **Benchmark harness** (`scripts/benchmark_skills.py`): 8 test scenarios with
  rubric scoring (correctness, safety, depth, communication). Generates JSON reports.
- `conftest.py` with shared `mock_ctx` fixture for unit tests.

## [0.7.0] - 2026-08-26

### Added
- **Port forwarding CRUD tools**: `get_port_forwards`, `create_port_forward`,
  `delete_port_forward` — full lifecycle management of gateway port forwards.
  Uses `/api/s/{site}/rest/portforward` (session-auth only).
- **Zone-name inference**: `infer_zone_names()` helper automatically maps opaque
  hex zone IDs to human-readable names from firewall rule names.
- **Skill trigger validation script** (`scripts/validate_skills.py`): 43/43
  trigger phrases matched correctly via phrase-level + word-level matching.
- `unifi-port-forwarding` skill updated to use new CRUD tools.
- WPA3 fields test for `get_wlans`.

### Fixed
- `update_wlan` return statement was corrupted during earlier edit (F821/F841).

## [0.6.0] - 2026-08-26

### Added
- Five more skills: `unifi-firmware-campaign`, `unifi-mesh-backhaul`,
  `unifi-ids-ips-triage`, `unifi-backup-migration`, and `unifi-network-map`
  (persistent labeled topology artifact that other skills reference).
- Sixteen bundled skills total.

## [0.5.0] - 2026-08-26

### Added
- Four advanced networking skills: `unifi-dns-triage`,
  `unifi-mdns-discovery`, `unifi-port-forwarding`, `unifi-vpn`.
- Skills now total eleven; advanced set encodes zone-firewall interplay
  (per-pair rules, hit-counter diagnosis), hairpin NAT/CGNAT checks,
  DoH/DoT escape behavior, and IPTV multicast cautions.

## [0.4.1] - 2026-08-26

### Added
- `reserve_client_ip` tool - DHCP reservations by client name/MAC/IP
  (closes a gap where skills referenced an operation no tool performed).
- Seven bundled agent skills (audit, troubleshoot-client, wifi-optimize,
  grant-device-access, internet-down, whos-home, setup-new-device) encoding
  live-verified controller knowledge; write skills approval-gated.
- Skills include pre-change snapshot discipline and controller-version checks.

### Fixed
- `set_client_fixed_ip` verifies via read-back when controllers return an
  empty data array on no-op PUTs.

## [0.4.0] - 2026-08-26

### Added
- WLAN write tools: `create_wlan`, `update_wlan` (partial updates by ID or
  SSID name), `delete_wlan` (confirm-gated).
- Zone firewall write tools: `create_firewall_policy`,
  `set_firewall_policy_enabled`, `delete_firewall_policy` (confirm-gated,
  refuses to delete predefined controller policies).
- `export_camera_clip` Protect tool — exports MP4 clips to a local file
  (requires Protect username/password in device config).
- `get_all_sites_health` multi-site overview tool.
- PyPI release workflow (tag-triggered trusted publishing).
- Empty-response handling for DELETE endpoints returning 204.

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
