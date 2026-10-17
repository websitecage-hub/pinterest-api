#!/usr/bin/env python3
"""Verify the gallery's actual render path for a real query.

For each result the page renders media through /download?url=<cdn>&inline=true.
This checks that path for images AND videos, including opaque ids, and reports
content-type + byte count so we know the grid will not show broken tiles.
"""
import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"


def fetch(url, timeout=90):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.headers.get("content-type"), r.read()


def search(q, media=None, resolve=True, size=25):
    p = {"q": q, "page_size": size}
    if media:
        p["media_type"] = media
    if resolve:
        p["resolve_mp4"] = "true"
    url = f"{BASE}/search?" + urllib.parse.urlencode(p)
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


def check(label, cdn_url, expect_prefix):
    u = f"{BASE}/download?url=" + urllib.parse.quote(cdn_url, safe="") + "&inline=true"
    try:
        st, ct, body = fetch(u)
        ok = st == 200 and body and (ct or "").startswith(expect_prefix)
        print(f"  {'OK ' if ok else 'BAD'} {label}: HTTP {st}, {ct}, {len(body)} bytes")
        return ok
    except Exception as e:
        print(f"  BAD {label}: {type(e).__name__}: {e}")
        return False


def report(q, media=None):
    d = search(q, media)
    res = d["results"]
    opaque = sum(1 for r in res if not r["id"].isdigit())
    vids = [r for r in res if r["type"] == "video"]
    with_bv = [r for r in vids if r.get("best_video")]
    print(f"\n{q!r} (media={media}): hits={d['hits']} opaque={opaque} "
          f"videos={len(vids)} videos_with_best_video={len(with_bv)}")
    img = next((r for r in res if r.get("best_image")), None)
    if img:
        check(f"image (opaque={not img['id'].isdigit()})", img["best_image"], "image/")
    if with_bv:
        check("video best_video", with_bv[0]["best_video"], "video/")
    return d


if __name__ == "__main__":
    report("aesthetic wallpaper")
    report("cooking", media="video")
    report("funny cat", media="gif")