---
name: unifi-wifi-optimize
description: Use when someone wants to optimize UniFi WiFi performance, fix slow WiFi, tune AP channels or channel width, enable WPA3, set band steering, or improve wireless coverage. Triggers: "slow wifi", "optimize wifi", "wifi channels", "slow house wifi", "wifi performance".
argument-hint: [SSID name]
disable-model-invocation: true
---

## Step 0 — Version check (always first)

Fetch `get_sysinfo` and note the Network application version. The controller
facts in this skill were verified on **Network 10.x / UniFi OS 5.x**; on older
versions expect differences (e.g., legacy `stat/alarm` exists, band steering
uses an older flag). Adapt claims to the version you see.

# UniFi WiFi Optimization

Diagnose and fix wireless performance issues on a UniFi site: channel conflicts,
suboptimal widths, security mode upgrades, and steering. Every change is shown
to the user for approval before it is applied.

## Context (read first)

1. Require `UNIFI_MODE=local`; if tools error with Integration API messages,
   stop and explain how to switch (local admin required — SSO+MFA won't work).
2. Gather baseline: `get_wlans`, `list_devices` (AP radio tables),
   `get_client_experience_report`, `list_clients`.

## Known controller facts (learned the hard way)

- **Band steering**: Network 9/10 replaced the old flag with `bss_transition`
  (802.11k/v) on the WLAN. There is no separate band_steering knob.
- **WPA3 transition** = `wpa3_support:true` + `wpa3_transition:true` +
  `pmf_mode:"optional"`. Keep `wpa_mode:"wpa2"` so legacy IoT still connects.
  Pure WPA3 (`pmf_mode:"required"`) breaks older devices.
- **Channel plan**: 2.4GHz must be non-overlapping (1/6/11); with >3 APs one
  shared pair is acceptable — pick the two physically farthest apart.
- **5GHz width**: use 80MHz unless DFS/radar issues are documented; 40MHz halves
  throughput. 160MHz only for AX-class dense deployments.
- Config pushes to APs briefly interrupt clients (state 5 = provisioning).

## Workflow

1. **Baseline report** — per-AP: radio, channel, width; per-WLAN: security,
   transition flags; client satisfaction distribution. Present findings.
2. **Build a change plan**, each item as: what → from → to → why → impact:
   - Channel conflicts → staggered 1/6/11 plan
   - Width < 80MHz on 5GHz → 80MHz
   - Security < WPA2 → WPA2 minimum; offer WPA3 transition (warn about IoT)
   - `bss_transition:false` → true
3. **Approval gate** — show the full plan; apply only items the user approves.
4. **Apply via `update_wlan`** for SSID-level fields (by SSID name works);
   device radio changes are not exposed by MCP tools — if needed, say so and
   point to Settings > WiFi in the UI rather than improvising raw API calls
   unless the user explicitly requests it.
5. **Verify** — re-read `get_wlans`; confirm values stuck. Note APs may take
   ~30s to finish provisioning.
6. **Follow-up check** — after changes settle, compare client satisfaction.

## Constraints

- Never change the passphrase without an explicit user request.
- Never enable pure WPA3 / required PMF on an SSID serving IoT devices.
- One SSID at a time; never bulk-modify all WLANs in one pass.
- If a client reports breakage right after a change, revert that specific field
  immediately (`update_wlan`) before investigating further.

## Rollback
## Snapshot before writing

Before ANY change: dump current state with the relevant read tools
(`get_wlans`, `get_firewall_policies`) and save the JSON to
`./unifi-backups/<YYYYMMDD>-<scope>.json`. Reference that file for exact
rollback values if anything misbehaves. Create the directory if needed.
