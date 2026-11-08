#!/usr/bin/env python3
"""Can the session renew itself? Three questions:

1. Does Pinterest re-issue `_pinterest_sess` (Set-Cookie) on authenticated
   requests? If yes, we can capture the rotation and keep the session sliding
   forward without a human.
2. How long is the cookie valid for (Max-Age / Expires in the jar)?
3. Does an authenticated request ever EXTEND that deadline?

Prints cookie NAMES and lifetimes only — never values.
"""
import sys
import time

sys.path.insert(0, "/home/testflowthrowout/pinterest-api/app")
import searcher  # noqa: E402
import urllib.parse  # noqa: E402


def lifetimes(sess, label):
    print(f"\n  jar lifetimes ({label}):")
    for c in sess.cookies:
        if c.name in ("_pinterest_sess", "csrftoken", "_auth", "_b"):
            exp = c.expires
            if exp:
                secs = exp - time.time()
                print(f"    {c.name:18s} domain={c.domain:20s} expires in {secs/86400:8.2f} days")
            else:
                print(f"    {c.name:18s} domain={c.domain:20s} session cookie (no expiry)")


s = searcher._get_session()
lifetimes(s, "after warm-up")

# 1 + 2: make an authenticated request and inspect Set-Cookie
payload = searcher._search_payload("cats", "pins", 25, None, None)
url = ("https://www.pinterest.com/resource/BaseSearchResource/get/"
       "?source_url=" + urllib.parse.quote("/search/pins/?q=cats", safe="")
       + "&data=" + urllib.parse.quote(payload, safe=""))
r = s.get(url, headers={
    "X-Requested-With": "XMLHttpRequest",
    "X-Pinterest-PWS-Handler": "www/search/pins.js",
    "X-CSRFToken": searcher._cookie_value(s, "csrftoken"),
    "Accept": "application/json, text/javascript, */*, q=0.01",
    "X-App-Version": "6550262",
    "Referer": "https://www.pinterest.com/search/pins/?q=cats",
}, timeout=25)

print(f"\n  search request: HTTP {r.status_code}")
sc = r.raw.headers.getlist("Set-Cookie") if hasattr(r.raw.headers, "getlist") else []
if not sc:
    sc = [v for k, v in r.headers.items() if k.lower() == "set-cookie"]
print(f"  Set-Cookie headers returned: {len(sc)}")
for h in sc:
    name = h.split("=", 1)[0].strip()
    bits = [p.strip() for p in h.split(";")[1:]]
    life = next((b for b in bits if b.lower().startswith(("max-age", "expires"))), "no lifetime")
    print(f"    {name:24s} {life}")

lifetimes(s, "after authenticated request")

# 3: does a second request move the deadline?
before = {c.name: c.expires for c in s.cookies}
time.sleep(2)
r2 = s.get(url, headers={
    "X-Requested-With": "XMLHttpRequest",
    "X-Pinterest-PWS-Handler": "www/search/pins.js",
    "X-CSRFToken": searcher._cookie_value(s, "csrftoken"),
    "Accept": "application/json, text/javascript, */*, q=0.01",
    "X-App-Version": "6550262",
}, timeout=25)
after = {c.name: c.expires for c in s.cookies}
moved = {k: (before.get(k), v) for k, v in after.items()
         if before.get(k) and v and abs(v - before[k]) > 1}
print(f"\n  second request: HTTP {r2.status_code}")
print(f"  cookie deadlines extended by activity: {moved or 'NO — not extended'}")
print(f"\n  marked authentic: {searcher.session_status().get('verified')} "
      f"as {searcher.session_status().get('authenticated_as')}")