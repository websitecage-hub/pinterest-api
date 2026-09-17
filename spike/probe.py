#!/usr/bin/env python3
"""Spike: probe response variants of a Pinterest pin URL to find where media JSON lives."""
import json
import re
import sys
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

def fetch(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

def pws_keys(body):
    ids = re.findall(r'id="(__PWS_[A-Z_]+__)"', body)
    return ids

def find_pin_payloads(body):
    """Find <script id=...__> JSON blobs that mention pinimg media URLs."""
    hits = []
    for m in re.finditer(r'<script[^>]*id="([^"]+)"[^>]*>(.*?)</script>', body, re.S):
        sid, txt = m.group(1), m.group(2)
        if "pinimg.com" in txt and ("\"images\"" in txt or "videos" in txt or "orig" in txt):
            try:
                data = json.loads(txt)
            except Exception:
                continue
            hits.append((sid, data))
    return hits

url = sys.argv[1] if len(sys.argv) > 1 else \
    "https://www.pinterest.com/pin/7810999345573240/"

print(f"URL: {url}")
body = fetch(url)
print("bytes:", len(body))
print("PWS ids:", pws_keys(body))

hits = find_pin_payloads(body)
print(f"JSON payload hits: {len(hits)}")
for sid, data in hits:
    print(f"\n=== script id={sid} ===")
    print("keys:", list(data.keys())[:15])

# Also check the API endpoint used by the site itself: /resource/PinResource/get/
pin_id = re.search(r"/pin/(?:[^/]*--)?(\d{5,})/?", url).group(1)
print(f"\nPin id: {pin_id}")
api = ("https://www.pinterest.com/resource/PinResource/get/"
       f"?source_url=/pin/{pin_id}/&data="
       + urllib.parse.quote(json.dumps({
           "options": {"id": pin_id, "field_set_key": "detailed"},
           "context": {}
       }), safe=""))
try:
    api_body = fetch(api, headers={"X-Requested-With": "XMLHttpRequest",
                                   "Accept": "application/json"})
    j = json.loads(api_body)
    print("API OK, top keys:", list(j.keys()))
    pin = j.get("resource_response", {}).get("data", {})
    print("pin keys:", sorted(pin.keys())[:50])
    if "images" in pin:
        print("image keys:", list(pin["images"].keys()))
    if "videos" in pin:
        print("videos keys:", list(pin["videos"].keys()) if isinstance(pin["videos"], dict) else type(pin["videos"]))
except Exception as e:
    print("API FAILED:", type(e).__name__, e)
