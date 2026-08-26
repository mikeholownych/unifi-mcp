---
name: unifi-mdns-discovery
description: Use when AirPrint, AirPlay, Chromecast, Sonos, casting, or printer discovery fails between devices on different networks/VLANs, devices vanish from apps after segmentation, or when configuring multicast, IGMP snooping, or mDNS settings. Triggers: "devices vanished after vlan change", "sonos not found", "chromecast not discovered", "airplay missing".
argument-hint: [what can't be discovered by what]
---

# UniFi mDNS / Cross-VLAN Discovery

Fix "device works but apps can't find it" — the classic symptom of services
that advertise via **mDNS (Bonjour/Avataar/Cast/Spotify-Connect)** being
separated from their clients by VLANs or firewall zones.

## Mental model

- Discovery = **link-local multicast** to `224.0.0.251:5353`. Routers do not
  forward multicast between subnets by design.
- After the advert is discovered, the actual session is normal unicast — so the
  fix must carry the ADVERTISEMENTS across, and zone-firewall rules must allow
  the unicast session both ways (or rely on return traffic).

## Step 0 & triage ladder

`get_sysinfo` (version facts are 10.x). Then:

1. **Same subnet first** — put the phone ONTO THE SAME SSID as the device and
   retry. If it works there, it's a cross-VLAN problem → continue. This solves
   ~half of all cases instantly.
2. **Confirm both endpoints' networks**: `get_client_details` for each
   (which SSID/network/VLAN). Watch for: phone on guest network, IoT on an IoT
   VLAN, client-isolation enabled on a guest WLAN (`get_wlans`: is_guest /
   l2_isolation) which blocks peer-to-peer even locally.
3. **Check WLAN multicast enhancement**: `get_wlans` summary +
   underlying config — `mcastenhance_enabled:true` can suppress bonjour on that
   SSID. Disable per-SSID if discovery dies only on WiFi, not wired.
4. **Zone-firewall path** (`get_firewall_policies`): look for existing
   `Allow mDNS` policies (udp) between the two zones. UniFi's mDNS repeater/
   proxy typically handles reflection once permitted; if absent, plan:
   - ALLOW udp 5353 src=<client-zone> dst=<service-zone> (+ return), OR
   - enable controller mDNS proxy rather than raw firewall holes when available.
5. **IPTV caution**: if the site has ISP IPTV multicast (look for
   "Allow IPTV Streaming" predefined policies / BELL-TV style zones), do NOT
   enable broad IGMP flooding/snooping changes globally — you can break live TV.
   Scope changes narrowly.

## Common resolutions mapped to causes

| Symptom | Cause | Fix |
|---|---|---|
| Works same-VLAN only | no cross-VLAN mDNS path | mDNS proxy/reflection or scoped 5353 allow |
| Broke right after enabling guest/IoT VLANs | isolation by design | decide policy: proxy discovery vs keep segmented |
| Printer visible, printing fails | discovery OK, session blocked | allow unicast session ports client→printer zone |
| Only WiFi clients affected | multicast enhancement on SSID | disable mcastenhance for that WLAN |
| Cast button appears then vanishes | return-traffic asymmetry | check zone pair has Allow Return Traffic |

## Constraints

- Snapshot `get_firewall_policies` output before adding any rule.
- One zone-pair at a time; verify discovery before generalizing.
- Never disable IGMP snooping/multicast controls network-wide as a "quick test"
  on IPTV-enabled sites.
