#!/usr/bin/env python3
"""For an HLS-only pin, inspect the variant playlist + audio playlist to see if
the segments are fMP4 (concat-able with -c copy) or transport stream (needs
remux), and whether an audio track is separable.
"""
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
      "Referer": "https://www.pinterest.com/"}
SIG = "999ec6b6a7e58bd6019ad1ef7ba3256c"
PFX = f"{SIG[0:2]}/{SIG[2:4]}/{SIG[4:6]}"
HLS = f"https://v1.pinimg.com/videos/iht/hls/{PFX}"


def get(url, n=2500):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(n)
    except Exception as e:
        return f"ERR {type(e).__name__}", b""


for name in (f"{SIG}_720w.m3u8", f"{SIG}_360w.m3u8", f"{SIG}_audio.m3u8"):
    st, body = get(f"{HLS}/{name}")
    print(f"\n=== {name}: HTTP {st} ===")
    print(body.decode("utf-8", "replace")[:900])