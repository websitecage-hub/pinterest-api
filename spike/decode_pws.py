#!/usr/bin/env python3
"""Spike: decode __PWS_DATA__ JSON blob structure (type-o-rama escape decoding)."""
import json
import re
import sys

def extract_script(html, sid):
    m = re.search(
        r'<script[^>]*id="' + re.escape(sid) + r'"[^>]*>(.*?)</script>',
        html, re.S,
    )
    if not m:
        return None
    return m.group(1)

def decode_pws(raw: str):
    """Pinterest escapes the JSON blob with a type-based obfuscation."""
    # Fast path: try plain JSON first
    try:
        return json.loads(raw), "plain"
    except Exception:
        pass
    # Type-o-rama: unescape via json.loads on the quoted form
    try:
        return json.loads(json.loads(f'"{raw}"')), "double-quoted"
    except Exception:
        pass
    return None, "failed"

html = open(sys.argv[1] if len(sys.argv) > 1 else "pin.html", encoding="utf-8").read()
for sid in ["__PWS_DATA__", "__PWS_INITIAL_PROPS__"]:
    raw = extract_script(html, sid)
    if not raw:
        print(f"{sid}: not found")
        continue
    print(f"{sid}: raw len={len(raw)}")
    data, mode = decode_pws(raw)
    if not data:
        print("  decode FAILED, first 120 chars:", raw[:120])
        continue
    print(f"  decode OK via {mode}, keys: {list(data.keys())[:20]}")

    def hunt(node, path="root", depth=0):
        found = []
        if depth > 12:
            return found
        if isinstance(node, dict):
            if "pinimg.com" in json.dumps(node)[:200000] and ("images" in node or "videos" in node):
                found.append(path)
            for k, v in node.items():
                if k in ("__pinterest_tag", "pin", "pins", "data", "pinsInfo", "pinData"):
                    found.extend(hunt(v, f"{path}.{k}", depth + 1))
                else:
                    found.extend(hunt(v, f"{path}.{k}", depth + 1))
        elif isinstance(node, list):
            for i, v in enumerate(node[:50]):
                found.extend(hunt(v, f"{path}[{i}]", depth + 1))
        return found

    paths = hunt(data)
    print(f"  media-bearing paths: {len(paths)}")
    for p in paths[:10]:
        print("   ", p)

    # Save decoded blob for inspection
    out = sid.strip("_") + ".json"
    with open(out, "w") as f:
        json.dump(data, f)
    print(f"  saved -> {out}")
