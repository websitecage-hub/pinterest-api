#!/usr/bin/env python3
"""Probe the MP4 ladder for HLS signatures where _derive_mp4s_from_hls found nothing.

For each signature, tests the candidate URL matrix (mc vs iht, tier dirs,
_v2/_t1 suffixes) and dumps the actual HLS manifest so we can see what
Pinterest itself lists as variants.
"""
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
      "Referer": "https://www.pinterest.com/"}

# sigs from /search/videos?q=cooking that got best_video=NONE
SIGS = [
    "0ae0f76e53795eee727e1d39b861a4f1",
    "7e456fa25cceaf7339d2ab19fbdc0fb8",
    "907d623731d31198cb6e70e8aaf6c842",
    "4c91246131bb899770f2fe39ca54aabb",
    "999ec6b6a7e58bd6019ad1ef7ba3256c",
    "7bd117c1cecc5fe9be835e594b3bca8c",
    "63bf23a3f626577fb44dc4df16cc2557",
    "c48573d8eb9d58365e94810a369087fc",
]
TIERS = ("720p", "540p", "480p", "360p", "240p")


def probe(url, method="HEAD"):
    req = urllib.request.Request(url, headers=UA, method=method)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status, r.read(4000) if method == "GET" else b""
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:
        return f"ERR {type(e).__name__}", b""


def candidates(sig, v2):
    pfx = f"{sig[0:2]}/{sig[2:4]}/{sig[4:6]}"
    tail = "_v2" if v2 else ""
    out = []
    for t in TIERS:
        out.append(f"https://v1.pinimg.com/videos/mc/{t}/{pfx}/{sig}{tail}.mp4")
        out.append(f"https://v1.pinimg.com/videos/iht/{t}/{pfx}/{sig}{tail}.mp4")
    out.append(f"https://v1.pinimg.com/videos/mc/expMp4/{pfx}/{sig}{tail}_t1.mp4")
    out.append(f"https://v1.pinimg.com/videos/iht/expMp4/{pfx}/{sig}{tail}_t1.mp4")
    out.append(f"https://v1.pinimg.com/videos/mc/expMp4/{pfx}/{sig}{tail}_t2.mp4")
    out.append(f"https://v1.pinimg.com/videos/iht/hls/{pfx}/{sig}{tail}.m3u8")
    return out


for sig in SIGS:
    print(f"\n=== {sig} ===")
    hits = []
    for v2 in (False, True):
        for u in candidates(sig, v2):
            code, _ = probe(u)
            if code == 200:
                hits.append(u)
                print(f"  200  {u}")
    if not hits:
        print("  no 200 in matrix")
    # dump the manifest we know exists
    for suffix in ("", "_v2"):
        pfx = f"{sig[0:2]}/{sig[2:4]}/{sig[4:6]}"
        m3u8 = f"https://v1.pinimg.com/videos/iht/hls/{pfx}/{sig}{suffix}.m3u8"
        code, body = probe(m3u8, method="GET")
        if code == 200:
            print(f"  manifest {m3u8}:")
            print("   ", body.decode("utf-8", "replace").replace("\n", "\n    ")[:900])
            break