#!/usr/bin/env python3
"""Compare anonymous vs authenticated (cookie) search output.

Proves the personalization is real, not just a cookie sitting in a jar:
  - are the pin sets/order different?
  - do authenticated results carry save counts that anonymous ones lack?
"""
import json
import os
import sys

sys.path.insert(0, "/home/testflowthrowout/pinterest-api/app")
import searcher  # noqa: E402

QUERY = "batman dark aesthetic"
out = {}
res = searcher.search(QUERY, "pins", 25, None)
pins = res["results"]
out["hits"] = res["hits"]
out["ids"] = [p.get("id") for p in pins]
out["with_saves"] = sum(1 for p in pins if (p.get("saves") or
                                             (p.get("stats") or {}).get("saves")))
out["with_stats"] = sum(1 for p in pins if p.get("stats") or p.get("saves"))
out["sample_keys"] = sorted(pins[0].keys()) if pins else []
out["sample"] = [{k: p.get(k) for k in ("id", "saves", "stats", "creator_followers",
                                        "is_promoted")} for p in pins[:3]]

label = "AUTH" if searcher._env_cookie_string() else "ANON"
path = f"/tmp/cmp_{label.lower()}.json"
with open(path, "w") as fh:
    json.dump(out, fh, indent=2)
print(f"{label}: hits={out['hits']} with_saves={out['with_saves']} "
      f"with_stats={out['with_stats']} -> {path}")
print("first 5 ids:", out["ids"][:5])