---
name: unifi-grant-device-access
description: Use when someone wants a specific device to always have full network access, never be blocked, get a reserved static IP, or reach other VLANs/zones on UniFi.
argument-hint: [device name or IP]
disable-model-invocation: true
---

# UniFi Grant Device Access

Guarantee a specific device (e.g., a desktop, server, or NAS) can always reach
everything on the network: DHCP reservation + zone-based firewall allow rules,
scoped to that device's MACs.

## Context (read first)

1. Require `UNIFI_MODE=local`. Resolve the device:
   - If given an IP/name, find it via `list_all_clients` (has MACs) and
     `get_client_details`.
   - If not found in known clients, ask the user to connect it once, or accept
     a MAC address directly.
2. Map zones: `get_firewall_policies` — note each policy's source/destination
   `zone_id`. Identify:
   - The zone containing the device's current network.
   - Which destination zones are already covered by existing rules for these MACs.

## Controller facts

- Zone firewall policies are per src-zone→dst-zone pairs; there is no "any zone"
  target. One rule per pair is required.
- **Deriving the source zone**: the controller does not expose zone names or a
  networks→zones mapping. Find it by locating an existing custom policy scoped
  to known devices on the same network (`source.client_macs` of rules like
  "Allow <user> to X ALL") and copying its `source.zone_id`. Do not guess by
  elimination — gateway-like zones allow-all everywhere and look similar to
  home zones in policy dumps.
- The controller auto-creates "(Return)" companion policies for custom rules.
- Some zone pairs are **rejected at creation** ("traffic not allowed") — typically
  ISP-managed IPTV and WAN pairs. Surface the verbatim error and skip that pair;
  it is usually intentional (nothing to access there anyway).
- Do not create rules targeting the EXTERNAL/WAN zone — internet access is
  governed by the home zone's general policy, and bypassing it undermines
  forced-internal-DNS designs.
- DHCP reservation = `use_fixedip:true` + `fixed_ip` on the client record.

## Workflow

1. Confirm the device identity with the user (name, MAC, current IP).
2. Check `list_all_clients`: if `blocked:true`, call `unblock_client` first.
3. Reserve the IP via client details update (`use_fixedip`, keep current IP
   unless user requests another — avoid colliding with existing leases).
4. Compute uncovered zone pairs (all internal zones minus: device's own zone,
   already-covered zones, EXTERNAL, Gateway). Present the plan:
   - Reservation: MAC → IP
   - N new ALLOW policies: "Allow [device] to [zone] ALL", scoped by
     `client_macs:[macs]`
5. Apply after approval: `create_firewall_policy` per pair with
   `client_macs` set. Skip-and-log any pair the controller rejects.
6. Verify: re-read `get_firewall_policies`; confirm rules exist and are enabled
   (return companions appear automatically).

## Constraints

- Scope every rule to explicit MACs — never create device-wide ANY-source allows.
- Never delete or modify existing custom rules without explicit instruction.
- Max ~10 new policies per run; batch larger requests into groups.
- Report which zones remain unreachable for the device and why.
