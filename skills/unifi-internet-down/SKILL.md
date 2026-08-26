---
name: unifi-internet-down
description: Use when someone says the internet is down, nothing will load, WiFi is broken, they can't get online, or the network seems dead.
argument-hint: [what's failing, e.g. "whole house" or "the TV"]
---

# UniFi Internet Down Triage

Calm, plain-English diagnosis when someone loses internet. No jargon without
translation. Find the broken link before recommending anyone call their ISP.

## Golden rule

Work from the wall outward: **provider line → router → home network → the
device**. Each step either finds the problem or rules it out.

## Workflow

1. **Scope it** — if the user hasn't said: "Is it everything in the house, or
   one device?" Everything → steps 2–4. One device → step 5.
2. **Check the provider line (WAN)** — `get_site_health` / `get_network_health`:
   - WAN status `ok` with a public IP → line is fine, skip to 4/5.
   - WAN down/no IP → the problem is the modem or provider. Go to step 3.
3. **Modem/provider playbook** — say this plainly:
   1. Unplug the modem's power for 30 seconds, plug back in, wait 2 minutes.
   2. Still down after also restarting the gateway? Note the exact status you
      observed and give the user a short script for calling their ISP
      ("my line is down at the router; the modem shows no signal" + account info).
   - Only restart network gear with explicit approval; warn it drops all
     connections for ~2 minutes.
4. **Whole-house check with line up** — rare; look for:
   - Devices restarting (`list_devices`, uptime minutes = recent crash)
   - Speed collapse → offer `run_speed_test` (tell them it pauses internet ~1 min)
5. **Single device** — pivot: is the rest of the house fine?
   - Device not on the network at all → `unifi-setup-new-device` style checks
     (wrong password, smart gadget needing 2.4GHz, airplane mode).
   - Connected but no internet → try `unblock_client` check first (blocked
     devices silently fail), then reboot guidance for that device.

## Translation table (use these phrasings)

| Technical | Say |
|---|---|
| WAN down | "The line from your provider is down" |
| DHCP | "Getting an address on the network" |
| Latency high | "Slow responses, likely congestion" |
| Client blocked | "This device was blocked from the network (someone may have paused it)" |

## Output format

```
Diagnosis: [one sentence in plain English]
What I checked: [bullet list w/ results]
Do this now:
1. [step — who does it: you / me]
If that doesn't work: [next step or ISP script]
```

## Constraints

- NEVER restart/reboot any gear without explicit approval.
- Never claim the ISP is at fault without WAN evidence.
- If tools are unavailable (degraded MCP mode), fall back to physical triage:
  modem lights guide + restart sequence.
