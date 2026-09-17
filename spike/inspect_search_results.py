#!/usr/bin/env python3
"""Spike: inspect search result structure and pin fields available."""
import json

j = json.load(open("/root/pinterest-api/spike/search_api_result.json"))
results = j["resource_response"]["data"]["results"]
print(f"results: {len(results)}")
print("bookmark:", j["resource_response"]["bookmark"][:60], "...")
print()
r0 = results[0]
print("result keys:", sorted(r0.keys()))
print()
# check a few result types
types = {}
for r in results:
    t = r.get("type", "?")
    types[t] = types.get(t, 0) + 1
print("result types:", types)
print()
# first pin
pin = next((r for r in results if r.get("type") == "pin"), results[0])
print("=== first pin sample ===")
for k in sorted(pin.keys()):
    v = pin[k]
    s = json.dumps(v)
    if len(s) > 120:
        s = s[:120] + "..."
    print(f"  {k}: {s}")
