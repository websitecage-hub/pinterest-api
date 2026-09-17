#!/usr/bin/env python3
"""Spike: inspect video-scope search results for video URL fields + test gif filters."""
import json
import sys

sys.path.insert(0, "/root/pinterest-api/app")
import searcher

# 1) video scope: where do the mp4 URLs live?
res = searcher.search("cooking", scope="videos", page_size=5)
print("hits:", res["hits"])
v0 = res["results"][0]
print("normalized best_video:", v0["best_video"])
print("normalized videos:", json.dumps(v0["videos"], indent=1)[:400] if v0["videos"] else "NONE")
print()

# fetch raw for the same query to inspect raw fields
import urllib.parse
import requests
s = searcher._get_session()
data = searcher._search_payload("cooking", "videos", 5, None, None)
url = ("https://www.pinterest.com/resource/BaseSearchResource/get/"
       "?source_url=" + urllib.parse.quote("/search/videos/?q=cooking", safe="")
       + "&data=" + urllib.parse.quote(data, safe=""))
r = s.get(url, headers={
    "X-Requested-With": "XMLHttpRequest",
    "X-Pinterest-PWS-Handler": "www/search/[scope].js",
    "X-CSRFToken": s.cookies.get("csrftoken", ""),
    "Accept": "application/json",
    "Referer": "https://www.pinterest.com/search/videos/?q=cooking",
}, timeout=20)
j = r.json()
results = j["resource_response"]["data"]["results"]
pin = next(p for p in results if p.get("type") == "pin")
print("RAW keys:", sorted(pin.keys()))
# dump video-bearing parts
for k in ("videos", "story_pin_data", "video_data", "media"):
    if k in pin and pin[k]:
        s2 = json.dumps(pin[k])
        print(f"\nRAW pin['{k}'] (len={len(s2)}):")
        print(s2[:1500])
