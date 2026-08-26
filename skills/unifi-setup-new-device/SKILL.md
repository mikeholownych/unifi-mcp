---
name: unifi-setup-new-device
description: Use when someone bought a new TV, camera, console, speaker, smart plug, thermostat or any gadget and needs help getting it online, connecting it, or fixing its setup. Triggers: "connect my printer", "new tv setup", "get it online", "gadget won't connect".
argument-hint: [device type, e.g. new smart plug]
---

# UniFi Setup New Device

Get a new gadget online and properly registered — written for people who have
never touched a router settings page.

## Why smart gadgets fail (explain these first)

1. **They need 2.4GHz**: most smart plugs/cameras only speak the older
   "2.4GHz" WiFi. Modern routers broadcast both bands under ONE name — usually
   fine — but during setup the phone doing the pairing must ALSO be on 2.4GHz
   sometimes.
2. **WPA3 transition hiccups**: very old or cheap IoT chips choke on newer
   security. If a device loops "connecting…" forever, temporary fix options:
   guest-network trick or (last resort) disabling WPA3 transition briefly via
   `update_wlan(wpa3_transition=false)` — remember to restore it after!
3. **Password typos**: passwords are case-sensitive; watch for confusables (l/I, O/0).

## Workflow

1. **Find out what they're setting up** — type matters (smart plug vs TV vs console).
2. **Search for it**: `list_all_clients` — match by maker (oui), recent
   last_seen, or partial name. Also `list_clients` for live view.
   - **Found** → go to 3.
   - **Not found** → walk them through the device app pairing attempt while you
     watch `list_clients`; if still invisible after 2 tries, apply Fix #1/#2 above.
3. **Verify it landed correctly**: has an IP, sits on the expected network,
   decent connection (`get_client_details`).
4. **Register it properly**:
   - Naming has no MCP tool — give exact UniFi-app taps: Clients → [device] →
     ⋯ → Rename. (Explain WHY: named devices make every future audit/troubleshoot clearer.)
   - If it's something that should always be reachable (NAS, camera hub,
     printer): offer `reserve_client_ip` so its address never changes — explain
     "like a reserved parking spot".
5. **Wrap-up**: confirm internet works ON the device (have them test), summarize
   what was done in one friendly paragraph.

## Output style

- Short numbered steps; one action per step.
- Every instruction names WHO does it: "You: open the plug's app…" /
  "Me: checking your network now…"
- Celebrate completion briefly. No technical recap unless asked.

## Constraints

- Read-only by default; `reserve_client_ip` only after offering and getting a yes.
- Never change SSID security settings for one stubborn gadget without warning
  that it affects EVERYONE — prefer the guest-network workaround.
- Don't dump jargon: translate VLAN→"section of the network", DHCP→"address assignment".
