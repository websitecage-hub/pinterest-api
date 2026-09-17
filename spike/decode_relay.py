#!/usr/bin/env python3
"""Spike: decode the relay completed-request payload holding pin data."""
import json
import re
import sys
import urllib.parse

html = open(sys.argv[1] if len(sys.argv) > 1 else "pin.html", encoding="utf-8").read()

pat = re.compile(
    r'__PWS_RELAY_REGISTER_COMPLETED_REQUEST__\("([^"]+)"\)', re.S
)
payloads = []
for m in pat.finditer(html):
    raw = urllib.parse.unquote(m.group(1))
    try:
        payloads.append(json.loads(raw))
    except Exception as e:
        print("decode fail:", e)
print(f"decoded payloads: {len(payloads)}")
for i, p in enumerate(payloads):
    keys = list(p.keys())
    print(f"[{i}] keys={keys[:8]}")
    s = json.dumps(p)
    if "pinimg.com/videos" in s or '"images"' in s:
        print(f"    ^ this one has media data, len={len(s)}")
        with open(f"relay_{i}.json", "w") as f:
            json.dump(p, f, indent=1)

# Also extract og: meta tags + JSON-LD
print("\n=== META TAGS ===")
for m in re.finditer(r'<meta[^>]+(?:property|name)="(og:[^"]+|twitter:[^"]+)"[^>]+content="([^"]*)"', html):
    c = m.group(2)
    print(f"{m.group(1)}: {c[:100]}")
print("\n=== JSON-LD ===")
for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
    try:
        ld = json.loads(m.group(1))
        print(json.dumps(ld, indent=1)[:800])
    except Exception as e:
        print("ld fail:", e)
