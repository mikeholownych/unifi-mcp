---
name: unifi-whos-home
description: Use when someone asks what devices are connected to their WiFi, who is on the network, whether a stranger is using their WiFi, or to identify an unknown device.
argument-hint: [concern, e.g. "unknown device"]
---

# UniFi Who's Home

Friendly inventory of everything connected to the network, translated into
everyday language — plus careful handling of genuinely unknown devices.

## Key knowledge

- **Randomized MACs are normal**: modern phones/laptops use a different fake MAC
  per WiFi network and often lack hostnames. A phone can appear as
  "Unknown (Apple)" — that is not an intruder.
- **OUI tells you the maker**: the start of a MAC identifies the manufacturer
  (the client `oui` field). Translate: Apple→iPhone/Mac, Samsung→TV/phone,
  Sonos→speaker, Raspberry-Pi/Proxmox→homelab box, etc.
- **Infra devices must never be blocked**: APs, switches, NAS, DNS servers.
  Cross-check candidates against `list_devices` (your actual hardware) before
  proposing any block.

## Workflow

1. **Inventory** — `list_clients` (connected now); group as:
   - **Your equipment** (matches `list_devices`)
   - **Recognizable family stuff** (named or obvious OUI: phones, TVs, printers)
   - **Unknown** — list separately with every clue: maker (oui), name/hostname,
     connection type, first/last seen.
2. **Translate each unknown**: "Unknown 'bc:24:11…' = a virtual machine on your
   Proxmox server", "Unknown 'Apple' = someone's iPhone using private-address mode".
3. **Suspicion checklist** (only flag if several hold):
   - wireless + unknown maker + active right now + nobody recognizes it
   - appeared between dates the user can place
   - NOT seen on wired ports
4. **For each unknown**, ask the owner-in-the-house: "do you own a [maker] device?"
   - Yes → suggest naming it in the UniFi app so future audits are clean.
   - No / unsure → offer `block_client` AFTER stating plainly what blocking does
     ("it will be kicked off and unable to rejoin until we allow it back") and
     get explicit confirmation.
5. **Reassure with facts**: WPA2/WPA3 means strangers can't join without the
   password; unknown entries are usually family gadgets with privacy features.

## Output format

```
Who's home right now: [N devices]
🏠 Your gear: [count] · 👪 Recognized: [count] · ❓ Unknown: [count]

❓ Unknown devices:
1. [maker/OS guess] — [name] — [where seen] — [first seen date]
   Likely is: [best plain-English guess]

Want me to [action] on #X?
```

## Constraints

- Read-only until the user explicitly confirms a block.
- Never block anything matching `list_devices` (network infrastructure).
- Never present randomized-MAC phones as intruders.
- If zero clients show but user insists someone is stealing WiFi, check WLAN
  security mode (`get_wlans`) — open/legacy WEP networks are the real risk.
