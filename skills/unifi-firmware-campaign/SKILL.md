---
name: unifi-firmware-campaign
description: Use when updating UniFi firmware, upgrading access points or the gateway, planning firmware updates, a device stuck after an update, or deciding whether to apply an available update.
argument-hint: [device | all | plan]
disable-model-invocation: true
---

# UniFi Firmware Campaign

Update firmware deliberately — with backups, staging, and verification — not
one blind click across everything.

## Step 0

`get_sysinfo`: note controller (UniFi OS) version AND Network application
version. `get_device_health_summary`: inventory `upgradable` flags per device.

## Order of operations (strict)

1. **Snapshot**: save `list_devices`, `get_wlans`, `get_firewall_policies`
   output to `./unifi-backups/<date>-pre-firmware.json`.
2. **Controller first, then devices**: if the UniFi OS / Network application
   itself has an update, do that in its own maintenance window and let it settle
   before touching device firmware.
3. **Canary before fleet**: update ONE least-critical AP first; verify ~15 min;
   then proceed one device at a time. Never "update all" on a production site.

## During each update

- Expect **state 5 (provisioning)** for several minutes — this is NORMAL, not a
  failure. Do not reboot anything that is merely provisioning.
- APs re-provision after firmware: clients briefly drop (~1–2 min).
- The gateway/UDM updating = whole-site outage window; schedule explicitly with
  the user and confirm twice.

## Post-update verification (per device)

- `get_device_health_summary`: state back to online, version matches target,
  uptime reset (expected).
- `list_clients`: clients re-associated; satisfaction recovers within minutes.
- Spot-check the primary SSID connects (`get_wlans` unchanged).

## Stuck-device ladder

1. Still state≠online after 20 min → single `provision_device` attempt.
2. Still bad → `restart_device`.
3. Still bad → flag for manual recovery (local UI/SSH) — beyond MCP scope; say so.

## Constraints

- One device per message/stage; report between stages.
- Refuse to run updates when user says "quickly" without acknowledging the
  per-device downtime — get explicit timing approval.
- If a known-bad firmware version is suspected (user reports breakage right
  after), stop the campaign; document which version rolled out where.
