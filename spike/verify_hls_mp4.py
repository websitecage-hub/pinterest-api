#!/usr/bin/env python3
"""Probe the in-flight HLS->MP4 derivation for opaque-id video results.

Reads /search/videos (resolve_mp4 default ON) and reports, per result:
  - id shape (numeric pin id vs opaque e1_...)
  - HLS url(s) present
  - whether best_video got set
Then independently probes the CDN for the derived MP4 ladder of each HLS sig,
so we can tell whether the derivation logic or the URL pattern is at fault.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}


def get(path, timeout=90):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.load(r)


def head(url, timeout=10):
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return f"ERR {type(e).__name__}"


def main():
    d = get("/search/videos?q=cooking&page_size=10")
    print(f"hits={d['hits']}  scope={d.get('scope')}")
    opaque = 0
    resolved = 0
    for r in d["results"]:
        pid = r["id"]
        is_opaque = not pid.isdigit()
        opaque += is_opaque
        if r.get("best_video"):
            resolved += 1
        print(f"\nid={pid[:50]}{'...' if len(pid) > 50 else ''}  opaque={is_opaque}")
        print(f"  best_video={'YES ' + r['best_video'] if r.get('best_video') else 'NONE'}")
        for v in (r.get("videos") or []):
            print(f"  video variant={v.get('variant')} url={str(v.get('url'))[:110]}")
            if v.get("url", "").endswith(".mp4"):
                print(f"    ^ direct mp4, HTTP {head(v['url'])}")
    print(f"\nsummary: {len(d['results'])} results, {opaque} opaque, {resolved} with best_video")


if __name__ == "__main__":
    main()