---
name: unifi-backup-migration
description: Use when backing up UniFi controller settings, exporting configuration, preparing a gateway replacement or migration, checking if backups exist, or recovering a dead console.
argument-hint: [backup | migrate | check]
disable-model-invocation: true
---

# UniFi Backup & Migration

Protect the configuration investment: verify backups exist, create them,
understand what they contain, and move between consoles without surprises.

## What a Network backup contains (and what it doesn't)

- ✅ Sites, networks/VLANs, WLANs, firewall policies/groups, port profiles,
  device provisioning data, admin list, hotspot config.
- ❌ Time-series statistics/history beyond short retention, **UniFi Protect
  recordings** (Protect has its OWN backup/restore path), client history depth
  varies. Say this explicitly when someone asks for "a full backup".

## Check & create (UI-driven; no MCP backup tool)

1. UI path: Settings → System → Backups → Create Backup (choose to include
   statistics only if explicitly wanted — large files).
2. Verify recency: the UI lists existing backups w/ timestamps. If none within
   ~30 days, make one now.
3. Download the `.unf` file OFF the console to another disk — a backup stored
   only on the dying box is not a backup.

## Migration rules of thumb

- Target console should run the **same or newer** Network application major
  version as the export; cross-version restores fail or degrade silently.
- Same-model swap: restore → adopt devices → done (devices re-appear because
  provisioning info travels).
- Different site/controller: devices must be re-adopted; SSH adoption or the
  "Set Inform" step may be needed — expect it, don't panic when APs show pending.
- Protect/NVR: migrate separately via Protect's own backup or disk moves.

## Pre-migration snapshot (use MCP while it's still up)

Save `get_networks`, `get_wlans`, `get_firewall_policies`, `list_devices` JSON
to `./unifi-backups/<date>-pre-migration.json` — invaluable if zone/policy
mapping gets lost in translation.

## Constraints

- Never store credentials in exported files shared with others (.unf contains
  config, but treat it as sensitive).
- Confirm-gate any destructive step during recovery discussions.
