#!/usr/bin/env python3
"""Inspect the RAW authenticated search response: is save data present in the
payload (and we're not mapping it), or absent entirely?"""
import json
import sys
import urllib.parse

sys.path.insert(0, "/home/testflowthrowout/pinterest-api/app")
import searcher  # noqa: E402

Q = "batman dark aesthetic"
s = searcher._get_session()
payload = searcher._search_payload(Q, "pins", 25, None, None)
src = urllib.parse.quote(f"/search/pins/?q={Q}", safe="")
url = ("https://www.pinterest.com/resource/BaseSearchResource/get/"
       f"?source_url={src}&data={urllib.parse.quote(payload, safe='')}")
r = s.get(url, headers={
    "Accept": "application/json, text/javascript, */*, q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "X-Pinterest-PWS-Handler": "www/search/pins.js",
    "X-APP-VERSION": "6550262",
    "X-CSRFToken": str(s.cookies.get("csrftoken", "")),
    "Referer": f"https://www.pinterest.com/search/pins/?q={Q}",
})
print("HTTP", r.status_code, "bytes", len(r.content))
d = r.json()
results = (d.get("resource_response", {}).get("data") or {}).get("results") or []
print("raw results:", len(results))
if results:
    p = results[0]
    print("\nraw pin keys:", sorted(p.keys()))
    hits = [k for k in p if any(w in k.lower() for w in ("save", "agg", "react", "stat", "repin", "comment", "share"))]
    print("\nstats-ish keys:", hits)
    for k in hits:
        print(f"  {k} = {json.dumps(p[k])[:400]}")
    print("\nid:", p.get("id"), "| type:", p.get("type"))