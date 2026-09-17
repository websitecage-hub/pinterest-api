#!/usr/bin/env python3
"""Spike: try Pinterest internal search resource API with session cookies."""
import json
import sys

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

# 1) warm up: get cookies (csrftoken, _pinterest_sess)
r0 = s.get("https://www.pinterest.com/search/pins/?q=cats", timeout=20)
print("warmup:", r0.status_code, "cookies:", list(s.cookies.keys()))

csrf = s.cookies.get("csrftoken", "")

data = json.dumps({
    "options": {
        "article": None,
        "appliedProductFilters": "---",
        "auto_correction_disabled": False,
        "corpus": None,
        "custom_filters": None,
        "entry": None,
        "explicit_filters": None,
        "filters": None,
        "lang": "en",
        "lat": None,
        "lng": None,
        "page_size": 25,
        "price_max": None,
        "price_min": None,
        "query": "cats",
        "query_pin_titles": None,
        "rs": "typed",
        "scope": "pins",
        "source_id": None,
        "source_module_id": None,
        "top_pin_id": None,
        "top_pin_ids": None,
        "no_fetch_context_on_resource": False,
    },
    "context": {},
})

url = ("https://www.pinterest.com/resource/BaseSearchResource/get/"
       f"?source_url=%2Fsearch%2Fpins%2F%3Fq%3Dcats&data={data}")

r = s.get(url, headers={
    "X-Requested-With": "XMLHttpRequest",
    "X-App-Version": "9c6b1f8",
    "X-Pinterest-AppState": "active",
    "X-Pinterest-PWS-Handler": "www/search/[scope].js",
    "X-CSRFToken": csrf,
    "Accept": "application/json, text/javascript, */*, q=0.01",
    "Referer": "https://www.pinterest.com/search/pins/?q=cats",
}, timeout=20)
print("search API:", r.status_code, "bytes:", len(r.content))
ct = r.headers.get("content-type", "")
print("content-type:", ct)
if r.status_code == 200 and "json" in ct:
    j = r.json()
    keys = list(j.keys())
    print("top keys:", keys)
    rr = j.get("resource_response", {})
    print("resource_response keys:", list(rr.keys())[:10])
    results = rr.get("data", {})
    if isinstance(results, dict):
        print("data keys:", list(results.keys())[:15])
    elif isinstance(results, list):
        print(f"results list len={len(results)}")
        if results:
            print("first result keys:", sorted(results[0].keys())[:18])
            print("bookmark:", rr.get("bookmark"))
    with open("search_api_result.json", "w") as f:
        json.dump(j, f, indent=1)
    print("saved -> search_api_result.json")
else:
    print("body head:", r.text[:300])
