# UniFi MCP Skills Guide

Complete reference for all 16 bundled agent skills — what they do, how to use them, expected results, and how to request changes.

## What are skills?

Skills are structured workflows that teach AI agents how to use UniFi MCP tools effectively. Each skill is a markdown file (`SKILL.md`) that contains:

- **Trigger phrases** — when the agent should activate this skill
- **Workflow** — step-by-step instructions using MCP tools
- **Output format** — what the agent should produce
- **Constraints** — safety rules and boundaries

Skills are **automatically loaded** by your MCP client (Claude Code, Claude Desktop, opencode, etc.) when your request matches their trigger phrases. You don't need to invoke them manually.

## How to use a skill

Simply describe your problem in natural language. The agent will match your request to the appropriate skill and follow its workflow.

### Examples

| You say | Skill activated | What happens |
|---------|----------------|--------------|
| "My internet is down" | `unifi-internet-down` | Agent checks WAN status, modem, gateway, then guides you through fixes |
| "Who's on my WiFi?" | `unifi-whos-home` | Agent lists all connected devices, flags unknowns, explains each one |
| "Audit my network" | `unifi-network-audit` | Agent produces a full health report: devices, clients, WiFi, firewall |
| "Set up my new TV" | `unifi-setup-new-device` | Agent checks WiFi bands, WPA settings, guides pairing |
| "Optimize my WiFi" | `unifi-wifi-optimize` | Agent proposes channel/width/security changes, asks approval before applying |
| "Port forward my NAS" | `unifi-port-forwarding` | Agent checks WAN type, creates forward + firewall rule, verifies |
| "Update all APs" | `unifi-firmware-campaign` | Agent snapshots config, stages updates, verifies after each |

### Write-gated skills

Some skills modify your network (creating rules, updating settings, etc.). These are **write-gated** — the agent will:

1. Show you exactly what it plans to change
2. Ask for your approval before applying
3. Confirm the change took effect afterward

You can always say "no" or "show me more detail" before approving.

## Skill inventory

### Read-only skills (safe, no changes made)

| Skill | Purpose | Expected result |
|-------|---------|-----------------|
| `unifi-network-audit` | Full site health report | Markdown report with device table, findings, WiFi scorecard, security posture |
| `unifi-troubleshoot-client` | Diagnose a specific device | Connection history, signal quality, AP associations, root cause |
| `unifi-internet-down` | Internet outage triage | Diagnosis (WAN/device/DNS), plain-English fix steps, ISP escalation script |
| `unifi-whos-home` | Device inventory | Table of all connected devices with names, IPs, vendors, connection type |
| `unifi-dns-triage` | DNS resolution issues | Resolution vs connectivity split, DNS server status, fix recommendations |
| `unifi-mdns-discovery` | AirPlay/Chromecast/Sonos issues | mDNS reflection status, VLAN isolation diagnosis, fix guidance |
| `unifi-mesh-backhaul` | Mesh/extender performance | Uplink quality, hop count, channel utilization, backhaul recommendations |
| `unifi-ids-ips-triage` | Threat alert investigation | Alert analysis, false-positive vs real assessment, suppression options |
| `unifi-network-map` | Network topology documentation | Persistent labeled topology file (zones/VLANs/devices/dependencies) |

### Write-gated skills (require approval before changes)

| Skill | Purpose | Expected result |
|-------|---------|-----------------|
| `unifi-wifi-optimize` | WiFi performance tuning | Channel plan, width changes, WPA3 upgrade — each item approval-gated |
| `unifi-grant-device-access` | Give a device full access | DHCP reservation + zone-firewall rules scoped to that device |
| `unifi-setup-new-device` | Get a new gadget online | WiFi band guidance, pairing steps, IP reservation, naming |
| `unifi-port-forwarding` | Expose a service to internet | Port forward + zone-firewall rule + CGNAT check + verification |
| `unifi-vpn` | VPN setup and troubleshooting | WireGuard/Teleport configuration, failure diagnosis |
| `unifi-firmware-campaign` | Staged firmware updates | Config snapshot → canary device → batch update → verification |
| `unifi-backup-migration` | Backup/migration planning | What backups contain, migration checklist, pre-snapshot guidance |

## What results to expect

### Report format

Most skills produce structured markdown output. Example from `unifi-network-audit`:

```
# UniFi Audit — default (2026-08-26)

## Verdict: ISSUES FOUND — 2 warnings, 3 informational

## Devices (8 online / 8 total)
| Name | Type | Firmware | State | Notes |
|------|------|----------|-------|-------|
| CSIS Van | UDM Pro | 5.1.31 | online | Gateway |
| U6 LR | AP | 6.6.73 | online | 42 clients |

## Findings
### Warnings
- [WiFi] 2.4GHz ch 6 overlaps between U6 Lite and AC Mesh — consider 1/6/11 plan
### Informational
- [Security] WPA3 transition enabled on main SSID
```

### Response time

- Simple queries (who's home, device status): 2-5 seconds
- Complex audits (full network audit): 10-30 seconds
- Firmware campaigns: 30-120 seconds per device

### Data limitations

Some tools require **session auth** (`UNIFI_MODE=local`) and won't work with API keys alone. When this happens, the skill will tell you exactly what's missing and how to fix it.

## Requesting new functionality

### Suggest a new skill

Open an issue at [github.com/mikeholownych/unifi-mcp/issues](https://github.com/mikeholownych/unifi-mcp/issues) with:

- **Title**: `[Skill] Short description` (e.g., `[Skill] VLAN migration wizard`)
- **Description**:
  - What problem does this solve?
  - What UniFi features/APIs does it need?
  - What should the workflow look like?
  - What output do you expect?

### Modify an existing skill

Same process — open an issue with:

- **Title**: `[Skill: skill-name] Change description`
- **Description**:
  - What's missing or broken?
  - What should change?
  - Any edge cases to handle?

### Add a tool

If a skill needs a tool that doesn't exist yet:

1. Check if the UniFi API supports the operation
2. Open an issue with `[Tool]` prefix
3. Include the API endpoint and expected request/response format

## Troubleshooting

### Skill doesn't activate

- Ensure skills are installed in `.claude/skills/` (or your client's skill directory)
- Check the skill's `description` field contains relevant trigger phrases
- Try rephrasing your request to match the skill's triggers

### Tools return errors

- **"Not available via the Integration API"**: Switch to `UNIFI_MODE=local` with a local admin account
- **"Device not found"**: Use `list_unifi_devices` to check configured device names
- **"Connection refused"**: Check your `.env` configuration and network connectivity

### Agent makes unexpected changes

- Write-gated skills always ask approval before changes — if this isn't happening, check your client's permission settings
- Read-only skills should never modify your network — if they do, file a bug

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines on creating new skills, modifying existing ones, or adding tools.
