---
name: unifi-mesh-backhaul
description: Use when WiFi near a mesh extender or far room is slow, checking wireless uplink quality, Beacon HD / FlexHD / mesh AP performance, deciding where to add an AP, or diagnosing multi-hop mesh issues. Triggers: "full bars but slow", "mesh extender slow", "back bedroom speed", "wireless uplink".
argument-hint: [problem area or AP name]
---

# UniFi Mesh Backhaul Health

Diagnose slow zones caused by weak **wireless uplinks** between mesh APs — the
invisible half of WiFi problems that channel tuning can't fix.

## Mental model

A wirelessly-uplinked AP re-broadcasts everything over its backhaul radio:
client throughput ≤ backhaul capacity ÷ 2 (same radio serves both sides), and
every extra hop compounds the loss. A "great signal" client on a mesh node with
a poor uplink still gets terrible speed.

## Workflow

1. **Identify the topology**: for each AP, `get_device_details` — inspect the
   `uplink` block: `is_wireless` (true = meshed), remote AP, signal/strength,
   number of hops.
   - Wired uplink → backhaul excluded from suspicion.
   - Wireless + strong (>-60 dBm equivalent) single hop → probably fine.
   - Wireless + weak, or **multi-hop** (meshed onto another meshed AP) → prime suspect.
2. **Correlate complaints**: map affected clients' APs (`get_client_details`)
   against the weak-backhaul nodes.
3. **Quantify**: compare satisfaction/tx rates of clients ON the mesh node vs
   clients on wired APs (`list_clients`).
4. **Fixes, in order of preference**:
   - Run Ethernet to the extender (wired backhaul = full speed; even cheap
     cable beats any mesh hop) — say this plainly, it's the real answer.
   - Reposition the extender closer/more line-of-sight to its uplink AP.
   - Reduce hops: re-home the node onto a wired AP rather than another mesh node.
   - Last resort: remove the node if it does more harm than good.
5. **Verify** post-change via step 1–3 again (uplink signal, client rates).

## Output format

```
Mesh map:
[AP name] --(wireless, -67, 1 hop)--> [U6 LR] --(wired)--> [UDM Pro]
Suspect: [name/reason]
Options: [ranked fixes w/ tradeoffs]
```

## Constraints

- Read-only skill: placement/cabling changes are physical actions for the user.
- Don't recommend more mesh nodes as a fix for mesh slowness (common trap).
