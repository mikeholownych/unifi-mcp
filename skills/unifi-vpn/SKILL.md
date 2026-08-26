---
name: unifi-vpn
description: Use when setting up remote access to home/office via VPN on UniFi, WireGuard or Teleport configuration, VPN connects but can't reach devices, slow VPN, or diagnosing tunnel problems. Triggers: "vpn setup", "teleport not working", "wireguard", "vpn slow", "tunnel problems".
argument-hint: [setup | diagnose]
disable-model-invocation: true
---

# UniFi VPN (WireGuard / Teleport)

Remote access done right: prefer inbound VPN over any port-forward exposure.
Covers setup, and the three classic failure modes.

## Step 0

`get_sysinfo` (version facts 10.x). `get_firewall_policies`: note the EXTERNAL
zone id and whether a VPN zone exists; `get_site_health` wan subsystem.

## Setup checklist (WireGuard user on UDM/UCG — UI-driven; no MCP CRUD tool)

1. Controller: Settings → VPN → WireGuard (or Teleport for quick links) →
   create server, add client profile, export config/QR to the phone.
2. Note the listen port (default 51820/udp). If the controller does not open it
   externally, add forward + zone policy exactly per `unifi-port-forwarding`
   (udp only).
3. Client side: endpoint = public IP/DDNS hostname; keep default AllowedIPs
   (`0.0.0.0/0`) for full-tunnel, or split-tunnel subnets only.
4. Verify from cellular (not the same LAN).

## Failure-mode ladder (diagnose in this order)

| Symptom | Meaning | Fix direction |
|---|---|---|
| No handshake at all | packets not arriving | wrong endpoint/port, UDP blocked by ISP/carrier, key mismatch |
| Handshake OK, zero data | routing/firewall | AllowedIPs on client missing target subnets; VPN→LAN zone policies absent |
| Reach some zones, not others | zone-firewall scoping | create ALLOW policies VPN-zone→each needed zone (per-pair rules!) |
| Connects, websites hang, small pings fine | **MTU** | lower client MTU to ~1380–1420 (double-NAT/PPPoE overhead) |
| Works then dies after N min | NAT/idle timeout | persistent keepalive 25s on client |

## Zone firewall specifics (Network 9+/10)

- VPN clients typically land in a dedicated VPN/Guest zone that is BLOCKED from
  internal zones by predefined catch-alls. "Connected but can't reach LAN" is
  almost always missing `ALLOW` policies from the VPN zone to HOME/Servers/etc.
  Create them scoped (not ANY) with `create_firewall_policy`, mirroring how
  per-device grants work — plus the auto-generated Return companions.
- Check hit counters on those rules while the client attempts traffic: hits=0 ⇒
  problem is client-side (AllowedIPs), hits rising but failing ⇒ service/port issue.

## Verification & hygiene

- Test both directions: reach internal services AND confirm internet traffic
  still flows while tunneled.
- Snapshot firewall policies before changes (`./unifi-backups/`).
- Remove test clients and unused peers when done; one peer per device.

## Constraints

- Never disable the external-DNS-block style protections for VPN convenience;
  point VPN DNS at an internal resolver instead.
- Confirm-gate every policy write; never widen beyond requested subnets.
