# UniFi MCP Server

mcp-name: io.github.mikeholownych/unifi-mcp

[![CI](https://github.com/mikeholownych/unifi-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/mikeholownych/unifi-mcp/actions/workflows/ci.yml)

An MCP (Model Context Protocol) server that provides AI assistants like Claude with access to UniFi Network and Protect infrastructure management and analysis capabilities.

> **Credits:** This project started as a fork of [gbassaragh/Unifi-mcp](https://github.com/gbassaragh/Unifi-mcp) and has since evolved into a fully independent project. Thanks to [@gbassaragh](https://github.com/gbassaragh) for the excellent starting point.

## Improvements Over Upstream

- **Fixed local session authentication routing** — in `UNIFI_MODE=local`, requests now correctly use the traditional controller API (`/proxy/network`) with cookie + CSRF session auth. Upstream always routed through the Integration API regardless of mode.
- **Mode-aware base URL resolution** — `api_base_url` now respects the configured auth mode instead of unconditionally returning the Integration API endpoint.
- **Expanded test suite** — 57 passing tests covering config, network client behavior, server tool registration, and Protect integrations.

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

### Client Management
- `list_clients` - List connected clients
- `list_all_clients` - List all known clients (including offline)
- `get_client_details` - Get client details
- `block_client` / `unblock_client` - Block/unblock clients
- `kick_client` - Disconnect a client
- `forget_client` - Remove from known clients
- `get_client_traffic` - Get traffic statistics
- `reserve_client_ip` - Reserve IP via DHCP reservation

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
- `create_wlan` / `update_wlan` / `delete_wlan` - Manage wireless networks
- `create_firewall_policy` / `set_firewall_policy_enabled` / `delete_firewall_policy` - Manage zone-based firewall policies
- `export_camera_clip` - Export a camera recording clip as MP4 (Protect)
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

## Requesting new functionality

- **New skills**: Open an issue with `[Skill]` prefix — describe the problem, workflow, and expected output
- **Modify skills**: Open an issue with `[Skill: skill-name]` prefix — what's missing or broken
- **New tools**: Open an issue with `[Tool]` prefix — include the UniFi API endpoint and expected format

See [`SKILLS.md`](SKILLS.md) for detailed contribution guidelines.

See [CHANGELOG.md](CHANGELOG.md) for release history and [CONTRIBUTING.md](CONTRIBUTING.md) to contribute.

## Security Notes

- Credentials are passed via environment variables — never commit `.env`
- SSL verification is disabled by default for self-signed certificates
- The server only exposes read operations and safe management commands
- Destructive operations (delete site, factory reset) are not exposed
- API keys should be kept secure and rotated periodically

## License

MIT License

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
