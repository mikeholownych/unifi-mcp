---
name: unifi-dns-triage
description: Use when some websites or services won't load but others work, names don't resolve, "server DNS address could not be found" errors appear, internal hostnames fail, or after changes to DNS servers, domain controllers, or VLANs.
argument-hint: [what fails]
---

# UniFi DNS Triage

Separate **name resolution** failures from **connectivity** failures — they look
identical to users ("the internet is broken") but have completely different fixes.

## Step 0 — Version & context

`get_sysinfo` for Network version (facts verified on 10.x). Then `get_networks`
— note each network's `domain_name` and topology.

## The test ladder (run in order, stop at first break)

Have the user (or use your own knowledge of results) run:

1. `ping 8.8.8.8` — works? → connectivity is FINE; this is DNS. Skip to 3.
   fails? → genuine connectivity issue → route to `unifi-internet-down`.
2. `ping google.com` — resolves? Public DNS works.
   fails with *"could not be resolved"* → name resolution broken. Continue.
3. `nslookup google.com` (uses DHCP-given resolver) vs `nslookup google.com 8.8.8.8`:
   - Direct-to-8.8.8.8 works but default resolver fails → **the configured
     internal resolver is dead or unreachable** → step 4.
   - Both fail → device-side (wrong DNS manually set, captive portal, VPN app).
4. Identify the resolver chain: `get_networks` (per-network domain_name),
   `get_client_details` on the affected device (which network/DNS it holds).
   On networks where an AD/domain exists (`ad.holownych.com` style), the
   resolvers are typically domain controllers — check those hosts are up
   (`list_clients` / `get_device_details`).

## Controller-specific patterns (Network 9+/10 zone firewall)

- Internal-DNS enforcement is commonly done by **BLOCK rules on outbound
  tcp/udp 53** per zone (look for names like "external DNS block",
  "Block WORK External DNS" in `get_firewall_policies`). Consequences:
  - Devices with **hardcoded 8.8.8.8** silently fail to resolve → fix the
    device, not the firewall.
  - **DoH/DoT escape** (443/853) is NOT blocked by port-53 rules — devices may
    resolve via encrypted DNS and bypass internal names entirely.
  - Allow-rules to DNS-server zones are often scoped `tcp_udp 53` ONLY —
    other DNS transports will fail while basic lookups work.
- Split-horizon: internal names (`*.ad.holownych.com`) resolve ONLY via
  internal resolvers. "Works at office, fails at home" (or vice versa) is normal.
- If ALL resolution dies house-wide but WAN is up: prime suspect is the DNS
  server zone being down or a changed zone-policy (verify with
  `get_firewall_policies`: are the "X to DNS Servers" allows still enabled?).

## Fixes mapped to causes

| Cause | Fix |
|---|---|
| Resolver host down | Restore/restart that server; check its zone-firewall coverage |
| Device hardcoded DNS | Clear static DNS on device (set to auto) |
| New device on blocked zone | Add scoped allow rule to DNS zone (`create_firewall_policy`, protocol `tcp_udp`, port 53) |
| DoH bypass breaking internal names | Disable DoH in browser/OS, or accept public-name-only |
| Everything else healthy, one site fails | That site's problem, not yours |

## Constraints

- Read-only diagnosis; any new firewall rule needs explicit approval + snapshot.
- Never "fix" by disabling the external-DNS block — explain what it protects
  (forced internal resolution, malware-C2 resistance) and let the owner decide.
