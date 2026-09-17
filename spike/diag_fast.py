#!/usr/bin/env python3
"""Fast diagnose: (1) the 502 on image pin download, (2) gif detection in search."""
import json
import sys

sys.path.insert(0, "/root/pinterest-api/app")

print("=== 1. what does the 502 say? ===")
try:
    print(open("/tmp/pintest2/img.jpg").read())
except FileNotFoundError:
    print("no saved body")

print("\n=== 2. direct extractor test on the same pin ===")
from extractor import get_pin
try:
    m = get_pin("369858188161092508")
    print("extract OK:", m["type"], m["best_image"][:70] if m["best_image"] else None)
except Exception as e:
    print("extract FAILED:", type(e).__name__, str(e)[:200])

print("\n=== 3. are the filters=gif pins actual gifs? ===")
for pid in ("957014989586539911", "1093741459787733543"):
    try:
        m = get_pin(pid)
        print(f"pin {pid}: type={m['type']} orig={m['best_image']}")
    except Exception as e:
        print(f"pin {pid}: FAILED {type(e).__name__}: {str(e)[:100]}")

print("\n=== 4. raw search-result images keys (do we ever get 'orig'?) ===")
import searcher
res = searcher.search("funny cat gif", "pins", 10)
raw = searcher._search_payload("funny cat gif", "pins", 10, None, None)
import urllib.parse, requests
s = searcher._get_session()
url = ("https://www.pinterest.com/resource/BaseSearchResource/get/"
       "?source_url=" + urllib.parse.quote("/search/pins/?q=funny cat gif", safe="")
       + "&data=" + urllib.parse.quote(raw, safe=""))
r = s.get(url, headers={
    "X-Requested-With": "XMLHttpRequest",
    "X-CSRFToken": s.cookies.get("csrftoken", ""),
    "Accept": "application/json",
    "Referer": "https://www.pinterest.com/search/pins/?q=funny cat gif",
}, timeout=20)
j = r.json()
pins = [p for p in j["resource_response"]["data"]["results"] if p.get("type") == "pin"]
for p in pins[:6]:
    imgs = p.get("images") or {}
    print(f"pin {p['id']}: image keys={list(imgs.keys())}")
    # any gif anywhere?
    pj = json.dumps(p)
    print(f"   .gif in payload: {'.gif' in pj}, is_video field: {p.get('is_video')}, videos: {bool(p.get('videos'))}")
