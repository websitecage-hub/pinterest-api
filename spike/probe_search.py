#!/usr/bin/env python3
"""Spike: probe Pinterest search SSR for result structure + pagination bookmark."""
import json
import sys
import urllib.parse

sys.path.insert(0, "/root/pinterest-api/app")
from extractor import _fetch, extract_relay_payloads

def probe(url: str):
    print(f"\n{'='*60}\nURL: {url}")
    html = _fetch(url)
    print(f"bytes: {len(html)}")
    payloads = extract_relay_payloads(html)
    print(f"relay payloads: {len(payloads)}")
    for i, p in enumerate(payloads):
        s = json.dumps(p)
        if len(s) < 2000:
            continue  # small ones are ads/config noise
        print(f"\n--- payload {i}: len={len(s)} ---")
        # top-level graphql op name
        def find_ops(n, path="root", depth=0, acc=None):
            if acc is None: acc = []
            if depth > 6: return acc
            if isinstance(n, dict):
                for k, v in n.items():
                    if k.startswith("v3") or k.startswith("v5") or "Search" in k or "search" in k:
                        acc.append(f"{path}.{k}")
                    find_ops(v, f"{path}.{k}", depth+1, acc)
            elif isinstance(n, list):
                for j, v in enumerate(n[:3]):
                    find_ops(v, f"{path}[{j}]", depth+1, acc)
            return acc
        ops = find_ops(p)
        print("op-like keys:", ops[:8])
        # look for arrays of pin-ish dicts (have images_orig or images_236x)
        def find_pin_arrays(n, path="root", depth=0, acc=None):
            if acc is None: acc = []
            if depth > 8: return acc
            if isinstance(n, list) and n and isinstance(n[0], dict):
                if any(isinstance(v, dict) and ("images" in v or "images_orig" in v or "imageSignature" in v) for v in n[:3]):
                    acc.append((path, len(n), sorted(n[0].keys())[:14]))
            if isinstance(n, dict):
                for k, v in n.items():
                    find_pin_arrays(v, f"{path}.{k}", depth+1, acc)
            elif isinstance(n, list):
                for j, v in enumerate(n[:5]):
                    find_pin_arrays(v, f"{path}[{j}]", depth+1, acc)
            return acc
        arrays = find_pin_arrays(p)
        for path, ln, keys in arrays[:4]:
            print(f"  pin array: {path} (len={ln}) keys={keys}")
        # bookmark / endCursor
        for m in ("bookmark", "endCursor", "pageInfo", "nextBookmark"):
            if m in s:
                print(f"  contains '{m}'")
        if arrays:
            with open(f"search_payload_{i}.json", "w") as f:
                json.dump(p, f, indent=1)
            print(f"  saved -> search_payload_{i}.json")

for u in [
    "https://www.pinterest.com/search/pins/?q=cats",
    "https://www.pinterest.com/search/videos/?q=cats",
]:
    probe(u)
