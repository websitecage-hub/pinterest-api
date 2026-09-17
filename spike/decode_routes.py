#!/usr/bin/env python3
"""Spike: decode __PWS_ROUTES__ from a search page and map the pin results structure."""
import json
import re
import sys

sys.path.insert(0, "/root/pinterest-api/app")
from extractor import _fetch

html = _fetch("https://www.pinterest.com/search/pins/?q=cats")
m = re.search(r'<script[^>]*id="__PWS_ROUTES__"[^>]*>(.*?)</script>', html, re.S)
routes = json.loads(m.group(1))
print("routes top keys:", list(routes.keys()))

def hunt(n, path="root", depth=0, acc=None, hits=None):
    """Find lists of dicts that look like pins."""
    if acc is None: acc = []
    if hits is None: hits = []
    if depth > 10:
        return acc
    if isinstance(n, dict):
        for k, v in n.items():
            hunt(v, f"{path}.{k}", depth+1, acc)
    elif isinstance(n, list) and n and isinstance(n[0], dict):
        sample = n[0]
        if "images" in sample or "imageSignature" in sample or "images_orig" in sample:
            acc.append((path, len(n), sorted(sample.keys())[:16]))
        for j, v in enumerate(n[:2]):
            hunt(v, f"{path}[{j}]", depth+1, acc)
    return acc

# breadth-first summary of routes structure
def summarize(n, depth=0, max_depth=3):
    pad = "  " * depth
    if isinstance(n, dict):
        for k, v in list(n.items())[:25]:
            if isinstance(v, (dict, list)):
                size = len(v)
                print(f"{pad}{k} ({type(v).__name__}, {size})")
                if depth < max_depth:
                    summarize(v, depth+1, max_depth)
            else:
                print(f"{pad}{k}: {str(v)[:60]!r}")

summarize(routes, max_depth=2)
print("\n--- pin-like arrays ---")
for path, ln, keys in hunt(routes):
    print(f"{path}  len={ln}  keys={keys}")
