#!/usr/bin/env python3
"""Verify: does HEAD work on pinimg /originals/*.gif, or do we need GET?"""
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
      "Referer": "https://www.pinterest.com/"}

# known-good gif (verified earlier via curl GET: 200, 136KB)
gif = "https://i.pinimg.com/originals/56/f8/64/56f864bde74533a9ce279b8414916bf2.gif"
# known-good jpg
jpg = "https://i.pinimg.com/originals/3e/05/cf/3e05cf5044bd54e4ef299d339c1440cd.jpg"

for u in (gif, jpg):
    r = requests.head(u, headers=UA, timeout=10, allow_redirects=True)
    print(f"HEAD {u[-20:]}: {r.status_code} content-type={r.headers.get('content-type')}")
    r2 = requests.get(u, headers=UA, timeout=10, stream=True)
    print(f"GET  {u[-20:]}: {r2.status_code} content-type={r2.headers.get('content-type')}")
    r2.close()

# also: does search "funny gif" surface pins that ARE gifs? test detect on 1 page
import sys
sys.path.insert(0, "/root/pinterest-api/app")
import searcher
res = searcher.search("funny gif", "pins", 25)
print(f"\nsearch 'funny gif': {res['hits']} results")
gif_hits = searcher.detect_gifs(res["results"])
print(f"detect_gifs found: {len(gif_hits)}")
for g in gif_hits[:3]:
    print("  ", g["id"], g["best_image"])
