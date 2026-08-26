---
name: unifi-troubleshoot-client
description: Use when a specific device or client has network problems on UniFi — slow WiFi, dropped connections, can't connect, blocked from the internet, or roaming issues. Triggers: "iphone keeps disconnecting", "laptop slow wifi", "device can't connect", "dropped connection".
argument-hint: [device name, IP, or MAC]
---

## Step 0 — Version check (always first)

Fetch `get_sysinfo` and note the Network application version. The controller
facts in this skill were verified on **Network 10.x / UniFi OS 5.x**; on older
versions expect differences (e.g., legacy `stat/alarm` exists, band steering
uses an older flag). Adapt claims to the version you see.

# UniFi Client Troubleshooting

Systematic diagnosis of a single misbehaving client: connectivity state, RF
quality, roaming history, blocking/firewall status, and path to fix.

## Context

1. Resolve the client: `list_all_clients` matches name/MAC (includes offline);
   `list_clients` for currently connected only. Try `get_client_details` with
   MAC once found. If given an IP only, match it against both lists.
2. Auth note: in Integration API mode client details are degraded; prefer local.

## Workflow

1. **Presence & identity** — is it known? online? wired or wireless? which AP/switch?
2. **Block check** — `blocked` flag on details; also scan `get_firewall_policies`
   for BLOCK rules whose source zone contains the client.
3. **RF quality** (wireless): signal/RSSI, noise, tx/rx rate, satisfaction,
   channel + band vs the AP's radio table (`list_devices`).
   - signal < -70 dBm → coverage problem
   - low tx_rate despite good signal → interference or legacy protocol
   - roam_count high → steering/flapping issue
4. **IP layer** — has an IP? correct VLAN/network? DHCP reservation conflicts
   (`use_fixedip` vs current IP mismatch)?
5. **History & events** — `troubleshoot_client` deep-dive; `get_recent_events`
   may be empty on Network 10+ (endpoints removed) — say so once if so.
6. **Compare peers** — other clients on same AP/band via `list_clients`: if all
   bad → AP problem; only this one → client problem.
7. **Verdict + fix plan**, e.g.:
   - Blocked → confirm with user → `unblock_client`
   - Weak signal → suggest AP placement/channel plan (defer to unifi-wifi-optimize)
   - IP conflict → propose reservation update
   - Flapping → check min-RSSI/bss_transition settings

## Output format

```
Client: [name] ([mac])
Status: [connected/offline] via [AP/port], [band] ch[channel]
Diagnosis: [primary cause]
Evidence:
- [measurement | observation]
Recommended fix(es):
1. [action — tool call if applicable, else UI/manual step]
Needs confirmation: [yes/no]
```

## Constraints

- Read-only skill: fixes require explicit user approval before any write tool.
- Never kick/reboot anything without asking; a kick drops the client briefly.
- If the device simply isn't seen at all, check wired switches' port tables
  (`get_device_details` on switches) before concluding it's gone.
