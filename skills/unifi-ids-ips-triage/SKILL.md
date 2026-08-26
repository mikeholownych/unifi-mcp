---
name: unifi-ids-ips-triage
description: Use when investigating UniFi threat management alerts, IDS/IPS events, blocked "threats", a device or website stopped working after enabling IPS, or tuning intrusion prevention. Triggers: "threat detected", "intrusion alert", "ips blocked my device", "false positive".
argument-hint: [alert or symptom]
---

# UniFi IDS/IPS Triage

Interpret Threat Management alerts, separate real threats from false positives,
and understand what enabling IPS costs.

## Mental model

- **IDS** = detect + alert only. **IPS** = actively drop matched packets.
  IPS mode adds inspection cost (throughput/latency on the gateway) and can
  break legitimate traffic via false positives.
- Alerts name a signature/category and usually the internal source + external
  destination. The pair tells the story.

## Workflow

1. **Pull context**: `get_sysinfo` (is IPS even enabled?), `get_networks`,
   and identify the flagged source device via `get_client_details`.
2. **Classify each alert**:
   - Internal host → weird external IP/port, repeated: possible compromise OR
     telemetry/update service misclassified. Check the destination's reputation
     and whether the vendor is expected in the house ("Sonos phoning home" ≠ attack).
   - External → internal on odd ports: scan noise; normally ignorable unless
     targeted/repeated against forwarded ports (see unifi-port-forwarding).
   - Internal → internal: lateral movement signal — take seriously; correlate
     with `get_firewall_policies` to see what that zone could touch.
3. **False-positive remediation**: UniFi supports per-signature/category
   suppression — prefer suppressing the specific noisy signature over disabling
   IPS wholesale; document why.
4. **Performance note**: if WAN throughput regressed after switching IDS→IPS,
   that's the inspection cost — measure with a speed test before/after and let
   the owner choose detection vs throughput.
5. **Real-suspicion handling**: if compromise is plausible, isolate first:
   propose `block_client` on the suspect host (confirm-gated), then dig.

## Constraints

- Read-only by default; blocks/suppression changes need explicit approval.
- Never dismiss repeated internal→internal alerts without explanation.
- Don't claim "you were hacked" from external scan-noise alone — quantify.
