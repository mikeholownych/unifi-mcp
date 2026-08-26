#!/usr/bin/env python3
"""Validate that each skill's description can match realistic user phrases.

Run: python scripts/validate_skills.py
"""
import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# Each tuple: (user_phrase, expected_skill_name_or_None)
# None means "no skill should match" — a negative-test case.
TRIGGER_PHRASES: list[tuple[str, str | None]] = [
    # --- internet down ---
    ("the internet is down", "unifi-internet-down"),
    ("nothing will load on my phone", "unifi-internet-down"),
    ("wifi works but no internet", "unifi-internet-down"),
    # --- who's home ---
    ("who is on my wifi", "unifi-whos-home"),
    ("is anyone using my network", "unifi-whos-home"),
    ("slow wifi in the house", "unifi-wifi-optimize"),
    ("optimize my wifi channels", "unifi-wifi-optimize"),
    # --- troubleshoot client ---
    ("my iphone keeps disconnecting from wifi", "unifi-troubleshoot-client"),
    ("this laptop has slow wifi", "unifi-troubleshoot-client"),
    # --- network audit ---
    ("audit my network", "unifi-network-audit"),
    ("check my network health", "unifi-network-audit"),
    ("network status report", "unifi-network-audit"),
    # --- setup new device ---
    ("help me set up my new tv", "unifi-setup-new-device"),
    ("connect my printer to wifi", "unifi-setup-new-device"),
    # --- grant device access ---
    ("give my desktop full access to everything", "unifi-grant-device-access"),
    ("never block my laptop", "unifi-grant-device-access"),
    # --- DNS triage ---
    ("some websites won't load but others do", "unifi-dns-triage"),
    ("internal hostname not resolving", "unifi-dns-triage"),
    ("dns server address could not be found", "unifi-dns-triage"),
    # --- mDNS discovery ---
    ("airplay devices not showing up", "unifi-mdns-discovery"),
    ("chromecast not discovered on other vlan", "unifi-mdns-discovery"),
    ("sonos speakers vanished after vlan change", "unifi-mdns-discovery"),
    # --- port forwarding ---
    ("port forward my nas to the internet", "unifi-port-forwarding"),
    ("expose my home assistant externally", "unifi-port-forwarding"),
    ("works externally but not internally", "unifi-port-forwarding"),
    # --- VPN ---
    ("set up wireguard vpn on unifi", "unifi-vpn"),
    ("vpn connects but can't reach anything", "unifi-vpn"),
    ("teleport not working", "unifi-vpn"),
    # --- firmware ---
    ("update my access points firmware", "unifi-firmware-campaign"),
    ("device stuck after firmware update", "unifi-firmware-campaign"),
    ("firmware update all devices", "unifi-firmware-campaign"),
    # --- mesh backhaul ---
    ("wifi near my extender is slow", "unifi-mesh-backhaul"),
    ("full bars but terrible speed in back bedroom", "unifi-mesh-backhaul"),
    ("mesh node performance bad", "unifi-mesh-backhaul"),
    # --- IDS/IPS ---
    ("threat detected on my network", "unifi-ids-ips-triage"),
    ("website stopped working after enabling ips", "unifi-ids-ips-triage"),
    ("false positive intrusion alert", "unifi-ids-ips-triage"),
    # --- backup/migration ---
    ("backup my unifi settings", "unifi-backup-migration"),
    ("migrate to new gateway", "unifi-backup-migration"),
    ("do backups exist", "unifi-backup-migration"),
    # --- network map ---
    ("map my network topology", "unifi-network-map"),
    ("document my zones and vlans", "unifi-network-map"),
    ("onboard someone to my network", "unifi-network-map"),
]


def load_descriptions() -> dict[str, str]:
    """Load skill name → description from SKILL.md frontmatter."""
    descriptions: dict[str, str] = {}
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        md = skill_dir / "SKILL.md"
        if not md.exists():
            continue
        content = md.read_text()
        # Extract description from YAML frontmatter (may not be on first line)
        m = re.search(r"description:\s*(.+?)(?:\n|$)", content)
        if m:
            desc = m.group(1).strip().strip('"').strip("'")
            descriptions[skill_dir.name] = desc
    return descriptions


STOP_WORDS = {"the", "is", "a", "an", "and", "or", "but", "in", "on", "at", "to",
              "for", "of", "with", "by", "from", "my", "me", "i", "it", "its",
              "this", "that", "not", "no", "do", "does", "can", "will", "has",
              "have", "was", "were", "are", "be", "been", "being", "their",
              "they", "them", "than", "then", "so", "if", "when", "how", "what",
              "who", "which", "where", "why", "all", "any", "some", "other"}


def match_phrase_to_skill(phrase: str, descriptions: dict[str, str]) -> str | None:
    """Keyword matching with phrase detection.

    Priority:
    1. Exact phrase substring match in description (highest confidence)
    2. Word-level keyword overlap (fallback)
    """
    phrase_lower = phrase.lower()

    # Phase 1: check for exact phrase matches in descriptions
    for name, desc in descriptions.items():
        desc_lower = desc.lower()
        if phrase_lower in desc_lower:
            return name

    # Phase 2: word-level overlap with threshold
    best: str | None = None
    best_score = 0
    for name, desc in descriptions.items():
        desc_lower = desc.lower()
        words = [w for w in phrase_lower.split() if len(w) > 2 and w not in STOP_WORDS]
        score = sum(1 for w in words if w in desc_lower)
        if score > best_score:
            best_score = score
            best = name
    return best if best_score >= 1 else None


def main():
    descriptions = load_descriptions()
    print(f"Loaded {len(descriptions)} skill descriptions\n")

    passed = 0
    failed = 0
    for phrase, expected in TRIGGER_PHRASES:
        got = match_phrase_to_skill(phrase, descriptions)
        ok = got == expected
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
            print(f"  {status}: '{phrase}' → expected={expected}, got={got}")
        else:
            passed += 1

    print(f"\n{passed}/{passed+failed} trigger phrases matched correctly")
    if failed:
        print(f"{failed} failures — review skill descriptions for coverage")
    else:
        print("All triggers validated.")


if __name__ == "__main__":
    main()
