#!/usr/bin/env python3
"""Spike: decode relay completed-request payloads (2-arg call format)."""
import json
import re
import sys
import urllib.parse

html = open(sys.argv[1] if len(sys.argv) > 1 else "pin.html", encoding="utf-8").read()

# Two-arg call: REGISTER_COMPLETED_REQUEST(decodeURIComponent(querySpec), responseData)
pat = re.compile(
    r'__PWS_RELAY_REGISTER_COMPLETED_REQUEST__\("([^"]*)",\s*(\{.*?\})\s*\)\s*(?:;|</script>|$)',
    re.S,
)
payloads = []
for m in pat.finditer(html):
    spec = urllib.parse.unquote(m.group(1))
    try:
        body = json.loads(m.group(2))
    except Exception as e:
        # try to salvage progressively
        txt = m.group(2)
        for end in range(len(txt), 1000, -500):
            try:
                body = json.loads(txt[:end])
                break
            except Exception:
                continue
        else:
            print("decode fail:", e)
            continue
    payloads.append((spec, body))

print(f"decoded payloads: {len(payloads)}")
for i, (spec, body) in enumerate(payloads):
    s = json.dumps(body)
    has_media = "pinimg.com" in s
    print(f"[{i}] spec={spec[:90]}")
    print(f"    body keys: {list(body.keys())[:10]}, len={len(s)}, media={has_media}")
    if has_media:
        with open(f"relay_{i}.json", "w") as f:
            json.dump(body, f, indent=1)
        print(f"    saved -> relay_{i}.json")
