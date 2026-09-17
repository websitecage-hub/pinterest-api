#!/usr/bin/env python3
"""Spike: find where search results live in search page HTML (no relay payloads)."""
import re
import sys

sys.path.insert(0, "/root/pinterest-api/app")
from extractor import _fetch

url = "https://www.pinterest.com/search/pins/?q=cats"
html = _fetch(url)
print("bytes:", len(html))

# 1) all script ids
print("script ids:", re.findall(r'id="(__PWS_[A-Z_]+__)"', html))

# 2) count media signals across ALL scripts
scripts = re.findall(r'<script([^>]*)>(.*?)</script>', html, re.S)
print(f"total scripts: {len(scripts)}")
for i, (attrs, body) in enumerate(scripts):
    if len(body) < 200:
        continue
    sig = {
        "pinimg": body.count("pinimg.com"),
        "images_orig": body.count('"images_orig"'),
        "imageSignature": body.count("imageSignature"),
        "orig": body.count("/originals/"),
        "relay": body.count("__PWS_RELAY"),
        "PWS_DATA": body.count("__PWS_DATA__"),
        "redux": body.count("initialReduxState"),
        "bookmark": body.count("bookmark"),
        "v3Search": body.count("v3Search"),
    }
    active = {k: v for k, v in sig.items() if v}
    if active:
        print(f"[{i:3d}] len={len(body):8d} {active}")
        print(f"      attrs: {attrs[:100]}")
