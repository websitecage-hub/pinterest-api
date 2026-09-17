#!/usr/bin/env python3
"""Spike: find the mp4 CDN URL pattern by direct URL probing + check pin detail page."""
import sys

sys.path.insert(0, "/root/pinterest-api/app")
from extractor import _fetch
import re

# Video pin we know well: 7810999345573240 (720p mp4 at .../mc/720p/40/f3/86/40f386...mp4)
# HLS from video search: v1.pinimg.com/videos/iht/hls/82/1b/38/821b3870a807b7fe475849eefc073a9a_v2.m3u8
# question: does .../iht/... also have expMp4/720p siblings on the CDN?

import requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}

sig = "82/1b/38/821b3870a807b7fe475849eefc073a9a"
base = f"https://v1.pinimg.com/videos"
candidates = [
    f"{base}/iht/expMp4/{sig}_t1.mp4",
    f"{base}/iht/expMp4/{sig}_t2.mp4",
    f"{base}/iht/720p/{sig}.mp4",
    f"{base}/mc/expMp4/{sig}_t1.mp4",
    f"{base}/mc/720p/{sig}.mp4",
    f"{base}/iht/hls/{sig}_v2.m3u8",   # known-good control
]
for u in candidates:
    try:
        r = requests.head(u, headers=UA, timeout=10)
        print(f"{r.status_code}  {u}")
    except Exception as e:
        print(f"ERR  {u}  {e}")

# also: fetch the pin detail page for a video-search pin and look for mp4 fields
html = _fetch("https://www.pinterest.com/pin/869828115534204101/")
mp4s = re.findall(r'https://v1\.pinimg\.com/videos/[^"\\]+\.mp4', html)
print(f"\npin detail page mp4 URLs: {len(mp4s)}")
for u in sorted(set(mp4s))[:8]:
    print("  ", u)
