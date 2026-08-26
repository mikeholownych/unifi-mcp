---
name: unifi-network-audit
description: Use when someone asks to audit their UniFi network, check network health, review devices or clients, find network issues, or wants a UniFi status report.
argument-hint: [site name]
---

# UniFi Network Audit

Comprehensive read-only audit of a UniFi site: device health, client experience,
configuration posture, and security observations, delivered as a structured report.

## Context (read first)

1. Confirm MCP connectivity with `list_unifi_devices` and `list_sites`.
2. Determine the auth mode in effect:
   - **local** (session auth): full data — WLANs, firewall policies, events.
   - **local_api_key / cloud**: degraded — some tools return errors or empty
     results. Report the limitation once and continue with what is available.
   - If most tools fail with "not available via the Integration API", tell the
     user to switch `UNIFI_MODE=local` with a local admin account (SSO accounts
     with MFA cannot log in) and restart their MCP client.

## Workflow

1. **Device inventory** — `get_device_health_summary`
   - Note any device offline, pending adoption, or upgradable.
   - Record firmware versions and uptime anomalies (very low uptime = recent reboot/crash).
2. **Deep issue analysis** — `analyze_network_issues` + `get_optimization_recommendations`
3. **Client experience** — `get_client_experience_report` + `list_clients`
   - Flag clients with satisfaction < 80, signal < -70 dBm, or high roam counts.
4. **WiFi posture** — `get_wlans` and per-AP radio state via `list_devices`
   - Check for: co-channel 2.4GHz overlap between APs, channel widths < 80MHz on
     5GHz, legacy WPA (non-WPA3), hidden/guest SSIDs exposed unexpectedly.
5. **Firewall posture** — `get_firewall_policies` (Network 9+)
   - Count custom vs predefined rules; note BLOCK/ALLOW ratio per zone pair;
     surface any ALLOW ALL rules to sensitive zones.
6. **Networks/VLANs** — `get_networks`
   - Flag flat networks without VLANs, missing DHCP ranges, or IGMP settings
     inconsistent with IPTV needs.
7. **Optional live checks** — offer (do not run unprompted): `run_speed_test`,
   then `get_speed_test_status` after ~60s.

> Network 10 note: `get_alarms` / `get_recent_events` may return empty because
> Ubiquiti removed those endpoints — do not treat as an incident; say so once.

## Output format

```markdown
# UniFi Audit — [site] ([date])

## Verdict: [HEALTHY | ISSUES FOUND] — [one-line summary]

## Devices (N online / M total)
| Name | Type | Firmware | State | Notes |

## Findings
### Critical
- [finding | evidence | recommended fix]
### Warnings
### Informational

## WiFi Scorecard
[per-AP: channel plan, width, clients, satisfaction avg]

## Security Posture
[firewall summary, SSID security modes, guest isolation]

## Recommended Actions (priority order)
1. ...
```

## Constraints

- Read-only skill: never call write tools (update/create/delete/restart/etc.).
- Never expose client MACs/IPs in the report beyond what's needed for findings.
- If the controller is unreachable, report connection details from `.env`
  config keys only (never print secrets).
