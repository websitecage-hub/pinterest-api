#!/usr/bin/env python3
"""Spike: hunt for an mp4-bearing field set in video search + test gif filter param."""
import json
import sys
import urllib.parse

sys.path.insert(0, "/root/pinterest-api/app")
import searcher

s = searcher._get_session()

def try_search(query, scope, extra_options=None, label=""):
    data = searcher._search_payload(query, scope, 5, None, extra_options)
    url = ("https://www.pinterest.com/resource/BaseSearchResource/get/"
           "?source_url=" + urllib.parse.quote(f"/search/{scope}/?q={query}", safe="")
           + "&data=" + urllib.parse.quote(data, safe=""))
    r = s.get(url, headers={
        "X-Requested-With": "XMLHttpRequest",
        "X-Pinterest-PWS-Handler": "www/search/[scope].js",
        "X-CSRFToken": s.cookies.get("csrftoken", ""),
        "Accept": "application/json",
        "Referer": f"https://www.pinterest.com/search/{scope}/?q={query}",
    }, timeout=20)
    if r.status_code != 200:
        print(f"[{label}] HTTP {r.status_code}")
        return None
    j = r.json()
    results = (j.get("resource_response", {}).get("data") or {}).get("results") or []
    pins = [p for p in results if p.get("type") == "pin"]
    print(f"[{label}] pins: {len(pins)}")
    # scan every pin json for .mp4
    for p in pins:
        pj = json.dumps(p)
        n_mp4 = pj.count(".mp4")
        n_hls = pj.count(".m3u8")
        n_gif = pj.count(".gif")
        v = p.get("videos") or {}
        vl = v.get("video_list") or {}
        variants = list(vl.keys())
        print(f"   pin {p.get('id')}: mp4={n_mp4} hls={n_hls} gif={n_gif} video_variants={variants}")
    return pins

# Try field_set variations used by the web app
try_search("cooking", "videos", {"field_set_key": "detailed"}, "videos+detailed")
try_search("cooking", "videos", {"field_set_key": "unauth_reacted"}, "videos+unauth_reacted")
try_search("funny cat", "pins", {"filters": "gif"}, "pins+filters=gif")
try_search("funny cat", "pins", {"custom_filters": "gif"}, "pins+custom_filters=gif")
try_search("funny cat", "pins", {"query_pin_titles": "gif"}, "pins+query_pin_titles=gif")
try_search("funny cat", "gifs", None, "scope=gifs")
