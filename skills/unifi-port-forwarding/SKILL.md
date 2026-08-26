---
name: unifi-port-forwarding
description: Use when someone needs remote access to a self-hosted service (NAS, camera NVR, home assistant, game server), asks about port forwarding, NAT, hairpin NAT, "works externally but not internally", or exposing any LAN service to the internet.
argument-hint: [service and port]
disable-model-invocation: true
---

# UniFi Port Forwarding & Hairpin NAT

Expose a LAN service to the internet safely — including the infamous case where
it works from outside but fails *inside* your own walls.

## Step 0 — Reality checks BEFORE any forwarding

1. **Version**: `get_sysinfo`.
2. **Is the WAN even forwardable?** `get_site_health` → WAN IP:
   - Public IP (not 100.64.x.x, not RFC1918) → good.
   - CGNAT/carrier-grade range → forwarding CANNOT work; stop and offer
     alternatives (VPN + reverse connection, tunnel like Tailscale/cloudflared).
3. **What service/port?** Map well-known risks: RDP/SSH/SMB exposed publicly =
   under constant attack — always propose VPN-first alternatives.

## The three-part requirement on Network 9+/10 (zone firewall)

A working external→internal flow needs ALL of:

1. **Port forward entry** — UI: Settings → Firewall & Traffic Management →
   Port Forwarding (no MCP tool exists for this; give exact click-path:
   name, protocol tcp/udp, WAN port, forward-to IP, target port).
2. **Zone policy EXTERNAL→<service zone>** ALLOW for that port
   (`create_firewall_policy`, source zone = External/WAN zone id,
   destination = service's zone). Predefined catch-alls usually BLOCK this
   direction — verify in `get_firewall_policies`.
3. **Service actually listening** on the target host + its own firewall
   allowing the router/NAT source.

## Hairpin NAT (works outside, fails inside)

LAN client hitting your public URL loops back at the gateway. On UDM Pro this
generally works automatically once the forward exists; if it doesn't:
- Test with external DNS name vs internal: if internal-only failure persists,
  add a **split-horizon DNS record** (public name → internal IP on your internal
  resolver) instead of fighting NAT — cleaner and faster.

## Verification ladder

1. From cellular (real external path): connect to `WANIP:port`.
2. From LAN via public hostname (hairpin test).
3. `get_firewall_policies`: watch hit counters on your new EXTERNAL→zone rule
   increase on attempts — counters prove path reachability and pinpoint which
   leg fails (rule hits=0 means packets never arrive: recheck forward + ISP).

## Constraints

- NEVER forward: 22/3389/445/80/443 of admin surfaces, controller UI, iLO/IPMI.
- Prefer VPN-in (`unifi-vpn`) over any exposure; frame forwards as last resort.
- Source-limit allows to known countries/IP groups where feasible.
- Snapshot `get_firewall_policies` before creating policies; confirm-gate every write.
