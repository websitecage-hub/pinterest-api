#!/usr/bin/env python3
"""Spike: parse Pinterest __PWS_DATA__ JSON blob from a saved pin HTML page."""
import json
import re
import sys


def extract_pws_data(html: str) -> dict:
    m = re.search(
        r'<script[^>]*id="__PWS_DATA__"[^>]*>(.*?)</script>', html, re.S
    )
    if not m:
        raise ValueError("no __PWS_DATA__ script found")
    return json.loads(m.group(1))


def find_pin_data(node, key="__pinterest_tag", target_id=None):
    """Recursively collect dicts that look like pin payloads."""
    results = []
    if isinstance(node, dict):
        if "images" in node or ("id" in node and ("videos" in node or "story_pin_data" in node)):
            results.append(node)
        for v in node.values():
            results.extend(find_pin_data(v))
    elif isinstance(node, list):
        for v in node:
            results.extend(find_pin_data(v))
    return results


def summarize(node, depth=0, max_depth=4):
    """Print structure of a nested dict/list without dumping everything."""
    pad = "  " * depth
    if depth > max_depth:
        return
    if isinstance(node, dict):
        for k, v in list(node.items())[:40]:
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}: ({type(v).__name__}, len={len(v)})")
                summarize(v, depth + 1, max_depth)
            else:
                s = str(v)
                if len(s) > 90:
                    s = s[:90] + "..."
                print(f"{pad}{k}: {s!r}")
    elif isinstance(node, list):
        for i, v in enumerate(node[:5]):
            print(f"{pad}[{i}]:")
            summarize(v, depth + 1, max_depth)


if __name__ == "__main__":
    html_path = sys.argv[1] if len(sys.argv) > 1 else "pin.html"
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    data = extract_pws_data(html)
    print("TOP-LEVEL KEYS:", list(data.keys()))

    # Look into props -> initialReduxState or route tree
    props = data.get("props", {})
    print("PROPS KEYS:", list(props.keys()) if isinstance(props, dict) else type(props))

    pins = find_pin_data(data)
    print(f"\n=== {len(pins)} pin-like dicts found ===\n")
    for i, p in enumerate(pins[:3]):
        print(f"--- PIN {i} ---")
        summarize(p, max_depth=3)
        print()
