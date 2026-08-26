---
name: unifi-network-map
description: Use when asked to document the network, create a network map or topology overview, explain how the network is organized, build a reference of zones/VLANs/devices for future troubleshooting, or onboard someone to managing this network.
argument-hint: [output path]
---

# UniFi Network Map

Build a **persistent, labeled topology file** from live controller data plus
owner interviews. This becomes shared context that makes every other skill
smarter (zone IDs are opaque; names live only here).

## Output artifact

Write to `$ARGUMENTS` path if provided, else `./unifi-network-map.md`.
Structure:

```markdown
# Network Map — [site] (generated [date], Network [version])

## Zones (id → human name → networks/subnets)
| Zone ID | Name | Contains | Purpose |
|---|---|---|---|
| 6a2f…791a | HOME | Default 192.168.1.0/24 | family + NAS + AD |
…

## Hardware
| Name | Model | Role | Uplink | Location (if known) |

## Dependencies ("who breaks if this dies")
- [host] provides [service] to [zones/clients] — e.g. "ns1 = internal DNS for ALL zones"

## Firewall philosophy summary
[2-4 sentences: what's default-blocked, notable exceptions and WHY]

## Open questions
- [unidentified zone/host/purpose → owner]
```

## Workflow

1. **Harvest everything automatic**:
   - `get_networks` (subnets, VLANs, domain names)
   - `get_firewall_policies` (zone ids + custom rule names — rule names often
     reveal purpose, e.g. "Allow Mike to DNS ALL")
   - `list_devices` + per-device `get_device_details` (uplink chains)
   - `get_wlans` (SSIDs → which network they serve)
   - `list_all_clients`: cluster clients by subnet/OUI/naming into roles.
2. **Infer candidate names** for opaque zone ids using rule-name anchors
   (e.g., the source zone of "Allow Mike to…" rules = the home/people zone).
3. **Interview the owner** — ask ONLY what data can't answer, in batches:
   - Confirm/correct each inferred zone name + purpose
   - What is [unidentified zone/host]? (e.g., TMX_NET, Microtik, INFRA_SPECIAL)
   - Critical services & their hosts (DNS, AD, NVR, hypervisors)
   - Any known "do not touch" constraints.
4. **Write the map** with an Open Questions section for anything unanswered.
5. **Maintain**: when re-run later, diff against the existing file and update
   changed sections rather than overwriting blindly.

## Constraints

- Never invent purposes — mark unknowns as questions.
- Keep MAC/IP detail minimal in the map itself (link to backups for specifics).
- This skill writes one documentation file; ask before overwriting an existing map.
