#!/usr/bin/env python3
"""Spike: dump raw pin object keys for a pin, search for carousel-like fields."""
import json
import sys

from extractor import _fetch, extract_relay_payloads, _find_pin_obj

url = sys.argv[1]
pin_id = url.rstrip("/").split("--")[-1].split("/")[-1]
html = _fetch(url)
payloads = extract_relay_payloads(html)
print(f"relay payloads: {len(payloads)}")
for i, p in enumerate(payloads):
    pin = _find_pin_obj(p)
    if pin is None:
        continue
    keys = sorted(pin.keys())
    print(f"\npayload {i}: pin object with {len(keys)} keys")
    # any key mentioning carousel / slot / card / pages
    interesting = [k for k in keys if any(w in k.lower() for w in
                   ("carousel", "slot", "card", "page", "story", "image", "video", "media"))]
    print("interesting keys:", interesting)
    for k in interesting:
        v = pin[k]
        s = json.dumps(v)
        print(f"  {k}: {s[:300]}")
    # save full pin for inspection
    with open(f"rawpin_{pin_id}.json", "w") as f:
        json.dump(pin, f, indent=1)
    print(f"saved rawpin_{pin_id}.json")
    break
else:
    print("NO PIN OBJECT FOUND in any payload!")
    # dump payload keys instead
    for i, p in enumerate(payloads):
        print(f"payload {i} keys:", list(p.keys()))
        s = json.dumps(p)
        print("  has 'carousel' string:", "carousel" in s.lower(), "len:", len(s))
