# UniFi MCP Server

mcp-name: io.github.mikeholownych/unifi-mcp

[![CI](https://github.com/mikeholownych/unifi-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/mikeholownych/unifi-mcp/actions/workflows/ci.yml)
[![unifi-mcp MCP server](https://glama.ai/mcp/servers/mikeholownych/unifi-mcp/badges/score.svg)](https://glama.ai/mcp/servers/mikeholownych/unifi-mcp)
[![Smithery](https://img.shields.io/badge/Smithery-mike--holownych%2Funifi--mcp-purple)](https://smithery.ai/server/mike-holownych/unifi-mcp)

An MCP (Model Context Protocol) server that provides AI assistants like Claude with access to UniFi Network and Protect infrastructure management and analysis capabilities. It uses the native MCP SDK 2 `MCPServer` API (not FastMCP 3) and communicates over stdio by default.

> **Credits:** This project started as a fork of [gbassaragh/Unifi-mcp](https://github.com/gbassaragh/Unifi-mcp) and has since evolved into a fully independent project. Thanks to [@gbassaragh](https://github.com/gbassaragh) for the excellent starting point.

## Improvements Over Upstream

- **Fixed local session authentication routing** — in `UNIFI_MODE=local`, requests now correctly use the traditional controller API (`/proxy/network`) with cookie + CSRF session auth. Upstream always routed through the Integration API regardless of mode.
- **Mode-aware base URL resolution** — `api_base_url` now respects the configured auth mode instead of unconditionally returning the Integration API endpoint.
- **Expanded test suite** — 250+ passing tests covering configuration, MCP compatibility, runtime persistence, network client behavior, server tool registration, and Protect integrations.

## Features

### UniFi Network
- **Device Management**: List, restart, locate, and upgrade UniFi devices (APs, switches, routers)
- **Client Management**: Monitor connected clients, block/unblock, view traffic statistics
- **Site Management**: View site health, network configurations, VLANs, and wireless settings
- **Statistics & Monitoring**: Events, alarms, speed tests, and DPI statistics
- **AI-Powered Insights**: Network analysis, optimization recommendations, and troubleshooting

### UniFi Protect
- **Camera Management**: List cameras, view status, get live snapshots
- **System Monitoring**: NVR status, camera health summaries
- **Accessories**: Manage lights, sensors, chimes, and viewers
- **Liveviews**: Access configured camera view layouts

### Multi-Device Support
- Configure multiple UniFi devices (gateways, NVRs, etc.)
- Target specific devices by name — **all** network and Protect tools accept an optional `device` parameter
- Per-device API keys: each configured device authenticates with its own key
- Mix of Network and Protect services across devices

### Events and Safe Automation
- Normalize and durably deduplicate Network and Protect events in optional SQLite storage
- Poll each configured source independently and report unsupported capabilities explicitly
- Run only built-in interval jobs: `poll_events`, `retry_webhook_deliveries`, `capture_observations`, and `prune_runtime_data`
- Deliver filtered, signed HTTPS webhooks with bounded retries and dead-letter state
- Keep persistence, background automation, and private webhook destinations disabled by default

### Authentication Modes

| Mode | Auth | Best for |
|------|------|----------|
| `local_api_key` | Integration API key | Recommended default; broad read access |
| `local` | Username/password session | Full feature access: firewall rules, WLAN configs, site settings, events, alarms, DPI |
| `cloud` | api.ui.com key | Remote/cloud-managed controllers |

When API keys are used (Integration API), a subset of controller features is only available via legacy session auth (`UNIFI_MODE=local`): network events, alarms, DPI statistics, speed tests, WLAN configs, firewall rules, port profiles, and routing tables. Tools for these features return a clear error explaining how to enable them rather than failing silently. Insight tools degrade gracefully and report data limitations.

> **Note on local accounts:** SSO/Ubiquiti-account admins protected by MFA cannot complete session login. Create a **local admin** on your console (*Restrict to Local Access Only*) for `UNIFI_MODE=local`.

## Agent Skills

Bundled skills (in [`skills/`](skills/)) teach agents proven workflows for this server — including
controller-specific gotchas (Network 10 removed endpoints, zone-pair rules, WPA3 transition).

**Full documentation**: See [`SKILLS.md`](SKILLS.md) for usage guide, expected results, troubleshooting, and how to request new functionality.

### Quick reference

| Skill | Type | Purpose |
|---|---|---|
| `unifi-network-audit` | read-only | Full site audit: devices, clients, WiFi posture, firewall, structured report |
| `unifi-troubleshoot-client` | read-only | Diagnose a misbehaving device: RF, roaming, blocking, IP layer |
| `unifi-wifi-optimize` | write-gated | Channel plan, widths, WPA3 transition, band steering — approval-gated |
| `unifi-grant-device-access` | write-gated | Give a device a reserved IP + scoped zone-firewall access |
| `unifi-internet-down` | read-only triage | "Internet is dead!" — plain-English outage diagnosis, ISP escalation script |
| `unifi-whos-home` | read-only | "Who's on my WiFi?" — friendly inventory, intruder checks with randomized-MAC awareness |
| `unifi-setup-new-device` | write-gated | Get any new gadget online: pairing pitfalls (2.4GHz/WPA3), naming, IP reservation |
| `unifi-dns-triage` | read-only | "Site won't load but ping works" — resolution vs connectivity split, forced-internal-DNS patterns |
| `unifi-mdns-discovery` | read-only+ | AirPrint/Cast broken across VLANs — mDNS reflection, IGMP/IPTV cautions |
| `unifi-port-forwarding` | write-gated | Self-hosted service exposure incl. hairpin NAT, CGNAT detection, zone-policy pairing |
| `unifi-vpn` | write-gated | WireGuard/Teleport setup + failure ladder (handshake/MTU/zone-policies) |
| `unifi-firmware-campaign` | write-gated | Staged firmware updates: snapshot, canary, verify, stuck-device ladder |
| `unifi-mesh-backhaul` | read-only | Slow far-room WiFi: wireless-uplink/hop diagnosis, wired-backhaul guidance |
| `unifi-ids-ips-triage` | read-only+ | Threat alerts: false-positive vs real, suppression, IPS throughput cost |
| `unifi-backup-migration` | write-gated | What backups contain, migration rules of thumb, pre-migration snapshots |
| `unifi-network-map` | doc-writer | Persistent labeled topology (zones/VLANs/deps) that sharpens every other skill |

### How skills work

Just describe your problem naturally — the agent matches your request to the right skill and follows its workflow:

- **"My internet is down"** → `unifi-internet-down` diagnoses WAN, modem, gateway
- **"Who's on my WiFi?"** → `unifi-whos-home` lists devices, flags unknowns
- **"Audit my network"** → `unifi-network-audit` produces a full health report
- **"Set up my new TV"** → `unifi-setup-new-device` guides WiFi pairing

**Write-gated skills** (marked above) modify your network — they always ask approval before applying changes.

Skills for non-technical users avoid jargon, translate every technical term,
and require confirmation before disruptive actions.

**Install** (per project): copy into `.claude/skills/`:

```bash
git clone https://github.com/mikeholownych/unifi-mcp.git
mkdir -p .claude/skills && cp -r unifi-mcp/skills/* .claude/skills/
```

See [`SKILLS.md`](SKILLS.md) for full usage guide, expected results, troubleshooting, and how to request new functionality.

Skills reference MCP tools by their plain names (`get_firewall_policies`, …);
your MCP client prefixes them automatically.

## Supported Hardware

- UniFi Dream Machine (UDM, UDM-Pro, UDM-SE)
- UniFi Cloud Gateway (UCG-Ultra, UCG-Fiber)
- UniFi Network Video Recorder (UNVR, UNVR-Pro)
- UniFi Network Application (self-hosted)
- Traditional Cloud Key (Gen1, Gen2, Gen2+)

## Limitations & Supported Versions

This server is built for operation **on a trusted local network**, talking to UniFi
consoles by IP address. With that in mind:

- **TLS verification is disabled by default** (`UNIFI_VERIFY_SSL=false`). UniFi OS
  ships self-signed certificates, and controllers are reached by IP on the LAN, so
  certificate verification is expected to fail. Enable `UNIFI_VERIFY_SSL=true` only
  when your controller presents a CA-trusted certificate.
- **No device configured at startup is allowed.** The server boots and exposes all
  tools even before `UNIFI_*` credentials are supplied (e.g. when deployed and
  configured via environment variables). Device-bound tool calls then return a clear
  `No device configured` error until a device is set.
- **Scope enforcement applies to remote transports only.** When running over
  Streamable HTTP, every `tools/call` is gated by read/write/admin OIDC scopes, and
  startup fails if any tool is unclassified. Over stdio (local IPC) no auth is
  required — stdio is assumed to be a trusted local process.
- **Integration API key limitations.** A subset of controller features is only
  available via legacy session auth (`UNIFI_MODE=local`): network events, alarms,
  DPI statistics, speed tests, WLAN/firewall configs, port profiles, and routing
  tables. Tools for these return a clear error explaining how to enable them.
- **Tested against recent UniFi OS / Network / Protect.** Newer controllers that
  removed legacy endpoints (e.g. UniFi Network 10 removed alarms/events endpoints)
  are handled by degrading gracefully rather than erroring.
- **Not a substitute for controller backups.** Snapshots and reports are read-only
  exports; they do not configure or restore a controller.

## Installation

### Using uv (Recommended)

```bash
# Clone the repository
git clone https://github.com/mikeholownych/unifi-mcp.git
cd unifi-mcp

# Install dependencies
uv sync
```

### Using pip

```bash
pip install -e .
```

## Configuration

Create a `.env` file in the project root (or set environment variables). See [.env.example](.env.example) for all options.

`UNIFI_CACHE_TTL` controls the shared GET cache lifetime across client instances (default: 30
seconds). Mutation verification defaults to five fresh reads with exponential delays of 0.5, 1,
2, and 2 seconds. Tune this with `UNIFI_MUTATION_VERIFY_ATTEMPTS`,
`UNIFI_MUTATION_VERIFY_INITIAL_DELAY`, and `UNIFI_MUTATION_VERIFY_MAX_DELAY` when a controller
converges more slowly or quickly.

### Optional Runtime Persistence

SQLite-backed runtime persistence is disabled by default. Enable it only when persistent runtime state is needed:

```bash
UNIFI_RUNTIME_ENABLED=true
```

By default, the database is `runtime.db` under `UNIFI_DATA_DIR`. If `UNIFI_DATA_DIR` is not set, the server follows the XDG data convention: `$XDG_DATA_HOME/unifi-mcp` when `XDG_DATA_HOME` is an absolute path, otherwise `~/.local/share/unifi-mcp`. The resulting default database is therefore `$XDG_DATA_HOME/unifi-mcp/runtime.db` or `~/.local/share/unifi-mcp/runtime.db`.

Set an explicit data directory or database path when needed:

```bash
UNIFI_DATA_DIR=/var/lib/unifi-mcp
UNIFI_RUNTIME_DATABASE=/var/lib/unifi-mcp/runtime.db
```

`UNIFI_DATA_DIR` and `UNIFI_RUNTIME_DATABASE` must resolve to absolute paths. `UNIFI_RUNTIME_DATABASE` overrides the database derived from `UNIFI_DATA_DIR`.

### Events, Schedules, and Webhooks

Runtime persistence enables event storage and management tools, but does not start background work. Enable the scheduler separately:

```bash
UNIFI_RUNTIME_ENABLED=true
UNIFI_AUTOMATION_ENABLED=true
```

Event ingestion is capability-based polling, not a claim of universal UniFi push support:

- Network event polling requires traditional local session auth with `UNIFI_MODE=local`.
- Protect event polling requires a configured local `username` and `password` for each Protect device.
- Integration API and cloud Network configurations are reported as unsupported for event polling.
- Polling uses overlap plus durable source-key deduplication so timestamp boundaries do not create duplicate records.

Schedules can invoke only `poll_events`, `retry_webhook_deliveries`, `capture_observations`, or `prune_runtime_data`. Schedule and webhook mutations require `confirm=true`; arbitrary MCP tool names, commands, imports, and expressions are rejected.

Webhook destinations use HTTPS, do not follow redirects, and are resolved and checked before every attempt. Loopback, private, link-local, multicast, and reserved addresses are rejected unless `UNIFI_WEBHOOK_ALLOW_PRIVATE=true`. The dedicated webhook client retains certificate verification even when a UniFi controller uses a self-signed certificate.

Signing secrets never enter SQLite or MCP arguments. Set a secret in the server environment, then pass only its variable name as `secret_env_name`:

```bash
WEBHOOK_SECRET_AUTOMATION='replace-with-a-random-secret'
```

Useful tools include `get_event_polling_status`, `poll_events_now`, `list_runtime_events`, `create_interval_schedule`, `run_schedule_now`, `list_job_runs`, `create_webhook_destination`, `test_webhook_destination`, and `list_webhook_deliveries`. Retryable jobs and webhook failures use bounded exponential backoff; exhausted deliveries enter `dead_letter` state.

### Portable Snapshots and Reports

Portable snapshots are versioned, canonical JSON exports assembled from supported read APIs. They include source scope, explicit data limitations, Network/Protect inventory, networks, WLAN metadata, and firewall rule/policy metadata. Credentials, API keys, cookies, authorization headers, and WLAN passphrases are structurally excluded.

```bash
# Optional absolute override; defaults to <UNIFI_DATA_DIR>/exports
UNIFI_EXPORT_DIR=/var/lib/unifi-mcp/exports
```

Export tools accept a plain filename rather than an arbitrary path, reject traversal and symlinks, and atomically write files with `0600` permissions. `export_portable_snapshot` includes a SHA-256 content checksum; `verify_snapshot` detects malformed, truncated, or modified snapshots. `export_network_report` renders the same strict model as escaped standalone HTML or formula-safe CSV.

Native controller backup download and restore are intentionally reported as unavailable until controller-family endpoints and safe restore verification are validated. Portable snapshots support assessment and assisted reconstruction; they are not represented as restorable native controller backups.

### History and Prometheus

With runtime persistence enabled, `capture_observations_now` stores bounded aggregate site health, device/client counts, traffic totals, and Protect camera health. It never stores per-client history or packet-flow telemetry. `query_observation_trends` returns bounded UTC buckets with `present=false` for missed collections rather than inventing interpolated values.

Prometheus support is not part of the base dependency set and starts no listener by default:

```bash
uv sync --extra observability
UNIFI_RUNTIME_ENABLED=true
UNIFI_PROMETHEUS_ENABLED=true
UNIFI_PROMETHEUS_HOST=127.0.0.1
```

Metrics use fixed names without controller, site, client, MAC, IP, or SSID labels. Binding beyond loopback additionally requires `UNIFI_PROMETHEUS_ALLOW_REMOTE=true` and `UNIFI_PROMETHEUS_BEARER_TOKEN_ENV` naming an environment variable that contains the bearer token. The token value is read at request time and is never persisted.

### Client Organization and QoS Previews

With runtime persistence enabled, clients can have multiple local tags and at most one local group. Membership is keyed by a controller/site-scoped SHA-256 value derived from the stable client MAC; raw MACs and mutable client names are not stored. Exact names and hostnames can be used as transient lookup hints, but ambiguous matches are rejected and the exact MAC must be supplied. Tags and groups survive client renames and do not change controller configuration.

Organization mutations require `confirm=true`. Use `set_client_tags`, `create_client_group`, `assign_client_group`, `list_client_groups`, and `list_clients_by_organization` to manage or query local metadata.

`plan_client_qos_policy` persists a one-hour deterministic target snapshot selected by one client, tag, or group. The target ledger contains only scoped one-way client keys and supports future resumable per-target apply state. This release has no validated controller QoS adapter: `get_client_qos_capabilities` reports that limitation, and `apply_client_qos_policy` returns without making a controller mutation. Local tags never imply a QoS policy.

### Trusted Plugins

Plugins are disabled unless their Python entry-point name is explicitly listed in `UNIFI_PLUGIN_ALLOWLIST`. They execute as trusted local code in the server process and are not sandboxed. Required plugins must also be allowlisted and are listed in `UNIFI_PLUGIN_REQUIRED`; missing, incompatible, duplicate, or failed required plugins stop startup. Optional failures are isolated and visible through `get_plugin_status`.

Plugins use API version 1 and the `unifi_mcp.plugins` entry-point group:

```toml
[project.entry-points."unifi_mcp.plugins"]
example = "example_package.plugin:plugin"
```

The loaded object declares `api_version = 1` and implements `register(registry)`. The registry supports `register_tool` with an explicit `read`, `write`, or `admin` scope, plus named collectors, `JobDefinition` jobs, notification sinks, and byte-returning report renderers. Plugin names cannot shadow core tools or jobs.

### Streamable HTTP and OIDC

Stdio remains the default local process transport and requires no identity-provider configuration. Remote MCP starts only when `UNIFI_TRANSPORT=streamable-http`; install the declared authentication capability with `uv sync --extra oidc` and provide complete OIDC settings:

```bash
UNIFI_TRANSPORT=streamable-http
UNIFI_HTTP_HOST=127.0.0.1
UNIFI_HTTP_PORT=8000
UNIFI_HTTP_PATH=/mcp
UNIFI_HTTP_PUBLIC_URL=https://mcp.example.com/mcp
UNIFI_OIDC_ISSUER=https://identity.example.com
UNIFI_OIDC_AUDIENCE=unifi-mcp
UNIFI_OIDC_ALGORITHMS=RS256
```

Discovery and JWKS data are fetched over HTTPS with bounded timeouts, cached for five minutes by default, and refreshed once for an unknown signing key. Tokens are validated locally for allowed asymmetric algorithm, signature, issuer, audience, expiry, subject, and scopes. Authorization headers, tokens, claims, and signing keys are not logged or persisted.

All HTTP tool calls require `UNIFI_OIDC_READ_SCOPE` (`unifi:read` by default). Mutations additionally require `UNIFI_OIDC_WRITE_SCOPE`; runtime administration and plugin status require `UNIFI_OIDC_ADMIN_SCOPE`. Existing `confirm=true` gates still apply. Non-loopback binding additionally requires `UNIFI_HTTP_ALLOW_REMOTE=true`; production TLS should terminate at the declared HTTPS public URL.

### Multi-Device Configuration (Recommended)

Configure multiple UniFi devices with different services:

```bash
UNIFI_DEVICES='[
  {
    "name": "main-gateway",
    "url": "https://192.168.1.1",
    "api_key": "your-gateway-api-key",
    "services": ["network"],
    "site": "default"
  },
  {
    "name": "nvr",
    "url": "https://192.168.1.2",
    "api_key": "your-nvr-api-key",
    "services": ["network", "protect"],
    "site": "default"
  }
]'
UNIFI_VERIFY_SSL=false
```

**Device configuration fields:**
| Field | Description | Default |
|-------|-------------|---------|
| `name` | Friendly name for targeting the device | (required) |
| `url` | Base URL of the UniFi device | (required) |
| `api_key` | API key from UniFi OS Control Plane | (required) |
| `services` | Array: `["network"]`, `["protect"]`, or both | `["network"]` |
| `site` | Site name for network operations | `"default"` |
| `verify_ssl` | Verify SSL certificates | `false` |
| `username` | Username for Protect events (optional) | `null` |
| `password` | Password for Protect events (optional) | `null` |

**Note:** The `username` and `password` fields are only required for Protect event tools (motion events, smart detections). Basic camera operations work with just the API key.

To create an API key:
1. Log into your UniFi controller
2. Go to Settings → Control Plane → API
3. Create a new API key with appropriate permissions

### Legacy Single-Device Configuration

For backwards compatibility, single-device configuration is still supported:

```bash
UNIFI_MODE=local_api_key
UNIFI_CONTROLLER_URL=https://192.168.1.1
UNIFI_CLOUD_API_KEY=your-api-key
UNIFI_SITE=default
UNIFI_VERIFY_SSL=false
```

### Local Session Auth (Traditional)

For full-feature access with username/password authentication:

```bash
UNIFI_MODE=local
UNIFI_CONTROLLER_URL=https://192.168.1.1
UNIFI_USERNAME=local-admin
UNIFI_PASSWORD=your-password
UNIFI_SITE=default
UNIFI_IS_UDM=true
UNIFI_VERIFY_SSL=false
```

### Cloud API (api.ui.com)

For Ubiquiti Cloud API access:

```bash
UNIFI_MODE=cloud
UNIFI_CLOUD_API_KEY=your-api-key
```

Get your API key from [unifi.ui.com](https://unifi.ui.com) → API section.

## Usage with Claude Desktop

Add to your Claude Desktop configuration (`~/.config/claude/claude_desktop_config.json` on Linux or `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "unifi": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/unifi-mcp", "python", "-m", "unifi_mcp.server"],
      "env": {
        "UNIFI_DEVICES": "[{\"name\":\"gateway\",\"url\":\"https://192.168.1.1\",\"api_key\":\"your-key\",\"services\":[\"network\"]},{\"name\":\"nvr\",\"url\":\"https://192.168.1.2\",\"api_key\":\"your-key\",\"services\":[\"network\",\"protect\"]}]",
        "UNIFI_VERIFY_SSL": "false"
      }
    }
  }
}
```

## Usage with Claude Code / opencode

```bash
# Add the MCP server
claude mcp add unifi -- uv run --directory /path/to/unifi-mcp python -m unifi_mcp.server
```

Or in `opencode.json`:

```json
{
  "mcp": {
    "unifi": {
      "type": "local",
      "command": ["/path/to/unifi-mcp/.venv/bin/python", "-m", "unifi_mcp.server"],
      "enabled": true
    }
  }
}
```

## Available Tools

### Server Health
- `get_server_health` - Report the server version, stdio transport, configured service counts, and optional persistence status. The response deliberately omits credentials, controller addresses, device names, and database paths.

### Multi-Device Management
- `list_unifi_devices` - List all configured UniFi devices and their services

### Device Management
- `list_devices` - List all UniFi network devices
- `get_device_details` - Get detailed device information
- `restart_device` - Restart a device
- `locate_device` - Blink LED to locate device
- `get_device_stats` - Get performance statistics
- `upgrade_device` - Upgrade firmware
- `provision_device` - Force re-provision
- `get_device_ports` - List switch/gateway port configuration and link state
- `set_device_port` - Configure one port; requires `confirm=true` and verifies controller read-back

### Client Management
- `list_clients` - List connected clients
- `list_all_clients` - List all known clients (including offline)
- `get_client_details` - Get client details
- `block_client` / `unblock_client` - Block/unblock clients
- `kick_client` - Disconnect a client
- `forget_client` - Remove from known clients
- `get_client_traffic` - Get traffic statistics
- `reserve_client_ip` - Reserve IP via DHCP reservation
- `get_client_organization` / `set_client_tags` - Read or replace durable local tags
- `create_client_group` / `delete_client_group` - Manage local-only groups
- `assign_client_group` / `list_client_groups` - Manage and inspect single-group membership
- `list_clients_by_organization` - Resolve deterministic tag or group target sets
- `get_client_qos_capabilities` - Report validated controller QoS support
- `plan_client_qos_policy` / `apply_client_qos_policy` - Preview QoS targets and apply only when a validated adapter exists

### Site Management
- `list_sites` - List all sites
- `get_site_health` - Get site health status
- `get_site_settings` - Get site settings
- `get_sysinfo` - Get system information
- `get_networks` - Get network/VLAN configs
- `get_wlans` - Get wireless network configs
- `get_port_profiles` - Get switch port profiles
- `get_firewall_rules` - Get legacy firewall rules
- `get_firewall_policies` - Get zone-based firewall policies (UniFi Network 9+)
- `get_routing_table` - Get routing table
- `get_port_forwards` - Get port forwarding rules
- `create_port_forward` / `delete_port_forward` - Manage port forwards

### Configuration Management (writes)
- `create_network` / `update_network` / `delete_network` - Manage networks and VLANs; each requires `confirm=true` and verifies controller read-back
- `create_wlan` / `update_wlan` / `delete_wlan` - Manage wireless networks
- `create_firewall_policy` / `set_firewall_policy_enabled` / `delete_firewall_policy` - Manage zone-based firewall policies
- `export_camera_clip` - Export an MP4 beneath `UNIFI_EXPORT_DIR`; requires `confirm=true`
- `get_all_sites_health` - Health overview across all sites

Write tools that remove data or cause disruption are confirm-gated or flagged destructive via MCP annotations.

### Statistics & Monitoring
- `get_network_health` - Overall network health
- `get_recent_events` - Recent events
- `get_alarms` - Active alarms
- `archive_all_alarms` - Archive all alarms
- `run_speed_test` - Start speed test
- `get_speed_test_status` - Get speed test results
- `get_dpi_stats` - DPI statistics
- `get_traffic_summary` - Traffic summary

### AI Insight Tools
- `analyze_network_issues` - Comprehensive issue analysis
- `get_optimization_recommendations` - Configuration recommendations
- `get_client_experience_report` - Client quality metrics
- `get_device_health_summary` - Device health overview
- `get_traffic_analysis` - Traffic pattern analysis
- `get_all_sites_health` - Health overview across all sites

### Multi-Site Orchestration
- `get_global_inventory` - Unified device inventory across all controllers
- `get_global_health` - Aggregated health report across all controllers
- `get_global_client_summary` - Client counts, top talkers, blocked clients across all controllers
- `troubleshoot_client` - Deep-dive client troubleshooting

### UniFi Protect
- `list_cameras` - List all cameras with connection status
- `get_camera_details` - Get detailed camera information
- `get_camera_snapshot` - Get live snapshot (base64 JPEG)
- `get_protect_system_info` - Get NVR system information
- `get_camera_health_summary` - Camera health overview with issues
- `get_liveviews` - Get configured liveview layouts
- `get_protect_accessories` - List lights, sensors, chimes, viewers

### UniFi Protect Events (require username/password)
- `get_motion_events` - Get recent motion events
- `get_smart_detections` - Get smart detection events (person, vehicle, animal, package)
- `get_protect_event_summary` - Summary of all events by type
- `get_recent_protect_activity` - Quick overview of recent activity

## Example Conversations

After connecting the MCP server, you can ask Claude:

### Network Management
- "List all my UniFi devices"
- "What's the current network health?"
- "Analyze my network for any issues"
- "What optimization recommendations do you have?"
- "Show me client experience metrics"
- "Troubleshoot the client with MAC aa:bb:cc:dd:ee:ff"
- "Which clients are using the most bandwidth?"
- "Are there any devices that need firmware updates?"
- "Show me the recent network events"
- "Run a speed test"

### UniFi Protect
- "List all my cameras"
- "Show me the camera health summary"
- "Get a snapshot from the Front Door camera"
- "What's the status of my NVR?"
- "Are any cameras disconnected?"
- "Show me the protect accessories"

### Protect Events (requires credentials)
- "Show me recent motion events"
- "What smart detections happened in the last 24 hours?"
- "Were there any person detections today?"
- "Give me an event summary for the past week"
- "Show recent activity from the Front Door camera"

### Multi-Device
- "List my configured UniFi devices"
- "Show cameras on my NVR"
- "Get network health from the main gateway"

## Development

### Running Tests

```bash
uv run pytest
```

### Code Formatting

```bash
uv run ruff check .
uv run ruff format .
```

### Docker

```bash
docker build -t unifi-mcp .
docker run -i --rm --env-file .env unifi-mcp
```

To enable optional runtime persistence, mount a named volume at the image's writable `/data` directory:

```bash
docker run -i --rm \
  --env-file .env \
  --env UNIFI_RUNTIME_ENABLED=true \
  --env UNIFI_DATA_DIR=/data \
  --volume unifi-mcp-data:/data \
  unifi-mcp
```

`--rm` removes the stopped container, but the `unifi-mcp-data` named volume remains and preserves `/data/runtime.db` for subsequent runs.

## Requesting new functionality

- **New skills**: Open an issue with `[Skill]` prefix — describe the problem, workflow, and expected output
- **Modify skills**: Open an issue with `[Skill: skill-name]` prefix — what's missing or broken
- **New tools**: Open an issue with `[Tool]` prefix — include the UniFi API endpoint and expected format

See [`SKILLS.md`](SKILLS.md) for detailed contribution guidelines.

See [CHANGELOG.md](CHANGELOG.md) for release history and [CONTRIBUTING.md](CONTRIBUTING.md) to contribute.

## Security Notes

- Credentials are passed via environment variables — never commit `.env`
- **TLS verification is disabled by default** (`UNIFI_VERIFY_SSL=false`) because the
  server is designed to run on a trusted LAN against UniFi consoles reached by IP
  with self-signed certificates. Enable it only with a CA-trusted certificate.
- Over stdio (local IPC), no authentication is required — the transport is assumed
  to be a trusted local process. Over Streamable HTTP, all tool calls require a
  valid OIDC token with the appropriate read/write/admin scope, enforced server-side.
- The server exposes both read and write tools
- Disruptive or destructive tools are annotated and/or explicitly confirm-gated where implemented; MCP clients decide how to present or honor annotations
- Especially dangerous operations such as factory reset remain unexposed
- API keys should be kept secure and rotated periodically

## License

MIT License

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
