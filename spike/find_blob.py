#!/usr/bin/env python3
"""Spike: find ALL <script> tags in the pin page and rank them by media signal."""
import re
import sys

html = open(sys.argv[1] if len(sys.argv) > 1 else "pin.html", encoding="utf-8").read()
scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
print(f"total <script> tags: {len(scripts)}")
for i, s in enumerate(scripts):
    if len(s) < 40:
        continue
    signals = {
        "pinimg": s.count("pinimg.com"),
        "images": s.count('"images"'),
        "videos": s.count("videos"),
        "orig": s.count("/originals/"),
        "PWS": s.count("__PWS_"),
        "type-o": s.count("type-o-rama"),
        "esc": s.count("escapedString"),
        "redux": s.count("initialReduxState"),
    }
    active = {k: v for k, v in signals.items() if v > 0}
    if active:
        head = s.strip().replace("\n", " ")[:80]
        print(f"[{i:3d}] len={len(s):8d} {active}  head={head!r}")

# Also: search for the video URL we know exists, see which script holds it
needle = "40f386d534eaacf614abec03fbf148ab"
idx = html.find(needle)
print(f"\nneedle {needle[:16]}... first at byte {idx}")
# Which script contains it? Walk script spans
for m in re.finditer(r'<script([^>]*)>(.*?)</script>', html, re.S):
    if needle in m.group(2):
        print("needle is in script with attrs:", m.group(1)[:120])
