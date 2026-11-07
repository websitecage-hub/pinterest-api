# Pinterest Media API — Usage Guide

Public, key-free API for searching and downloading images, videos, and GIFs
from Pinterest, plus query autocomplete / typo correction and a browser
gallery. No API key, no auth — just call it.

- **Version:** v2.5
- **Tech:** FastAPI + Python 3.12, no key required
- **Repo:** https://github.com/websitecage-hub/pinterest-api

<br>

## Base URL

Pick the one you're using:

| Deployment | Base URL |
|---|---|
| Render (live, public) | `https://pinterest-api-inyg.onrender.com` |
| Local (dev) | `http://127.0.0.1:8000` |

- Swagger docs (interactive): `<base>/docs`
- API index (JSON): `<base>/`
- Browser gallery: `<base>/gallery`

All examples below use the live Render URL. For local, swap the host.

<br>

## Quickstart (30 seconds)

```bash
BASE="https://pinterest-api-inyg.onrender.com"

# 1. is it alive?
curl -s "$BASE/health"

# 2. search
curl -s "$BASE/search?q=dark%20aesthetic&page_size=5"

# 3. look at results in a browser
open "$BASE/gallery?q=dark+aesthetic"
```

<br>

## 0. Concepts (read first)

### 0.1 Anonymous vs personalized (your own account's results)

**Default = anonymous.** Results are byte-identical to what pinterest.com shows
in a private window (verified: same pin ids, same order). This surface carries no
save counts and no personalized ranking — that's a Pinterest limit, not an API one.

**Personalized mode = your account.** Set `PINTEREST_COOKIE` and every search
runs with your logged-in session: your interest graph ranks the results, and
pins carry save/reaction counts.

**Only three cookies matter:**

| cookie | why it's needed |
|---|---|
| `_pinterest_sess` | the login session — without it nothing is personalized |
| `csrftoken` | must be sent as `X-CSRFToken` on POSTs (pin detail); a mismatch = 403 |
| `_auth=1` | marks the session authenticated |

Everything else in the header (`datr`, `_routing_id`, `_pinterest_id`, …) is
optional. Easiest is to copy the **entire** `cookie` header and paste it whole.

**How to copy it**

1. Log into pinterest.com in Chrome/Firefox.
2. F12 → **Network** → click any request to `pinterest.com`.
3. **Request Headers** → `cookie` → copy the whole value.
   (Or **Application → Cookies → https://www.pinterest.com** and copy the three above.)

**Where to put it** (do not paste it into chat or a ticket — it is a hijackable
credential, same class as a password):

```bash
# Render: Dashboard -> your service -> Environment -> add
#   PINTEREST_COOKIE = <full cookie header>      then Save (auto-redeploys)

# Local:
export PINTEREST_COOKIE='_pinterest_sess=...; csrftoken=...; _auth=1'
# or keep it in a file and point at it:
export PINTEREST_COOKIE_FILE=$HOME/pinterest.cookie
```

**Verify it was accepted** — and this is the part that used to lie:

```bash
curl -s "$BASE/session/status"
```

| field | meaning |
|---|---|
| `authenticated` | a cookie is *configured* on the host |
| `verified` | Pinterest **actually accepted** it (`isAuthenticated: true`) |
| `authenticated_as` | the username Pinterest reports for that session |

`authenticated: true` with `verified: false` means the cookie is expired or
incomplete and your results are silently anonymous — recopy it.

**Reality check:** personalized ranking is not pixel-identical to your phone
feed — Pinterest also uses app-state and device signals we can't replay. What
you get is the logged-in search surface: your interest graph ordering, save
counts, and richer pin metadata. Also, Pinterest sees requests from your
server's IP carrying your account, which from a datacenter can look like
automation — use a secondary account and keep request rates modest.

### 0.1.1 Self-healing & monitoring

A Pinterest session cannot be made to never expire, and unattended re-login is
not something you want (2FA, captcha, account-flag risk). So the design is:
**heal automatically when you replace the cookie, and shout the moment it
expires** instead of silently degrading.

- **Hot reload.** The cookie is re-read on every request when either the
  `PINTEREST_COOKIE` value or the mtime of `PINTEREST_COOKIE_FILE` changes.
  Sessions rebuild themselves; the service is never restarted and never serves
  a stale cookie. On a VM/Docker with a mounted cookie file, an external job
  can refresh it and the API heals on the next request.
  (On Render, editing an env var triggers a redeploy anyway, so that path is
  for volume-mounted/file-based setups.)
- **Mid-flight recovery.** A 401/403 from Pinterest rebuilds the session and
  retries the request once — for search *and* pin detail — instead of returning
  empty stats.
- **Graceful degradation.** With a dead cookie the API keeps serving
  (anonymous results, HTTP 200) rather than erroring.
- **`/health` now tells you the truth:**

```json
{"ok": true, "session": {"mode": "personalized", "verified": true,
 "healthy": true, "authenticated_as": "you", "cookie_source": "env:PINTEREST_COOKIE",
 "last_checked_ago_s": 3}}
```

  `healthy` is `false` only when a cookie IS configured but Pinterest rejected
  it — the one state where results silently go anonymous.
- **Alerting.** Point a monitor at `/health` with keyword `"healthy":true`.
  UptimeRobot flags it the moment the cookie dies, instead of you noticing odd
  results days later.
- **`GET /session/refresh`** — force a re-check and hot-reload right now.

### 0.2 Opaque ids (`e1_...`)

Pinterest's search returns some hits under opaque ids such as
`e1_AfqPShy50Pph1fYw8AHXYvOCsd4oe9ssdeNNgw0lGRsTTS7FIqGotA`. Pinterest will not
serve those at `/pin/<id>/` — its own API returns `PinNotFound` — and they can't
be resolved to a numeric id. Their media is still public, so:

- read `best_image` / `images.*` / `videos[].url` straight from the search response
- download it with `GET /download?url=<that CDN url>`

`/pin/{id}/info|download|stream` answer **404** (with that explanation) for
opaque ids. Legacy numeric ids resolve normally.

### 0.3 Videos: MP4 vs HLS

Pinterest's search only exposes HLS (`.m3u8`) for videos. With `resolve_mp4=true`
the API tries to resolve a **direct MP4**:

1. **Numeric pin id** → fetch the pin page, read its MP4 ladder.
2. **Opaque `e1_...` id** → derive the MP4 path from the HLS signature
   (`.../hls/aa/bb/cc/<sig>.m3u8` → `.../<tier>/aa/bb/cc/<sig>.mp4`, probing
   720p→240p, cached 6h including negative results).

Some pins are genuinely **HLS-only** (Pinterest publishes no MP4). Then
`best_video` is `null` and `videos[]` carries the `.m3u8`, which plays in a
browser (hls.js) but is not a progressive download.

```python
mp4 = result["best_video"]                                  # direct download (may be None)
hls = next((v["url"] for v in result["videos"]
            if v["url"].endswith(".m3u8")), None)           # fallback player url
```

<br>

## Endpoint reference

| Method | Path | What it does |
|---|---|---|
| GET | `/` | API index (JSON) |
| GET | `/health` | liveness — `{"ok": true}` |
| GET | `/gallery` | browser: visual result grid for any query |
| GET | `/search` | search pins (images/videos/gifs), paginate |
| GET | `/search/videos` | video pins only, MP4 resolution on by default |
| GET | `/search/gifs` | animated GIF pins only |
| GET | `/search/suggestions` | autocomplete / typo correction |
| GET | `/session/status` | anonymous vs personalized mode |
| GET | `/pin/{id}/info` | full manifest for one pin |
| GET | `/pin/{id}/download` | best media as attachment |
| GET | `/pin/{id}/download/all` | ZIP of every asset on the pin |
| GET | `/pin/{id}/stream` | inline stream for `<img>` / `<video>` |
| GET | `/resolve?url=` | any pin URL → manifest |
| GET | `/download?url=` | proxy-download any Pinterest CDN media URL |

<br>

### 0.4 Explore mode — results that change every search

Pinterest's first page for a query is deterministic, so repeating a search the
same way returns the same pins and feels frozen. `explore=true` fixes that the
way the app does — by drawing from a bigger pool:

```bash
curl -s "$BASE/search?q=cyberpunk+city+night&page_size=25&explore=true&pages=3"
```

It fetches up to `pages` pages (max 5), dedupes them into a pool, then samples
`page_size` pins at random. Measured on the same query three times in a row:
overlap 9/25, 3/25, 4/25 — different pins each call, from a 125-pin pool. First
call ~6.5s (builds the pool), every call after ~10ms because the pages are
cached individually.

- `explore=true` — rotating sample (app-like "new results each time")
- `pages=1..5` — pool depth (more pages = more variety, slower first call)
- `fresh=true` — bypass the 10-minute cache and hit Pinterest live

## 1. Search pins

```
GET /search?q=<query>[&page_size=25][&page_bookmark=<bm>][&media_type=video|gif][&resolve_mp4=true]
```

Params:
- `q` (required) — search text, 1–100 chars
- `page_size` — **1..100**, default 25
- `page_bookmark` — opaque value from a previous response's `next_bookmark`
- `media_type` — `video` or `gif` to filter the current page
- `resolve_mp4` — `true` to fetch/derive direct MP4 URLs for video results (slower)

Example:

```bash
curl "https://pinterest-api-inyg.onrender.com/search?q=motivational%20quotes&page_size=10"
```

Response (Pixabay/Pexels-style):

```json
{
  "query": "motivational quotes",
  "scope": "pins",
  "page_size": 10,
  "hits": 10,
  "results": [
    {
      "id": "10344274147036450",
      "type": "image",                      // image | video | gif
      "title": "FOCUS | Motivational wallpaper",
      "description": "Eliminate distractions...",
      "alt_text": "...",
      "creator": "talktomitch_1",
      "creator_avatar": "https://i.pinimg.com/75x75_RS/....jpg",
      "board": "/talktomitch_1/focus/",
      "link": null,
      "dominant_color": "#1d1d1e",
      "created_at": "Tue, 25 Aug 2026 00:08:19 +0000",
      "saves": null,                        // populated only in personalized mode
      "reactions": {"1": 37},
      "pin_url": "https://www.pinterest.com/pin/10344274147036450/",
      "domain": "Uploaded by user",
      "is_promoted": false,
      "creator_followers": 3,
      "creator_verified": false,
      "best_image": "https://i.pinimg.com/originals/....jpg",
      "images": { "170x": "...", "236x": "...", "474x": "...", "736x": "...", "orig": "..." },
      "best_video": null,
      "videos": []
    }
  ],
  "next_bookmark": "Y2JVSG81...",           // pass as page_bookmark
  "has_more": true
}
```

**Pagination** — Pinterest uses opaque bookmarks, not page numbers. Loop while
`has_more` is true, passing `next_bookmark` as `page_bookmark`.

```python
bm, page = None, 0
while page < 5:
    p = {"q": "dark aesthetic", "page_size": 50}
    if bm: p["page_bookmark"] = bm
    d = requests.get(f"{BASE}/search", params=p).json()
    for r in d["results"]:
        ...
    if not d["has_more"]: break
    bm = d["next_bookmark"]; page += 1
```

<br>

## 2. Videos

```
GET /search/videos?q=<query>[&page_size=25][&page_bookmark=<bm>][&resolve_mp4=true]
```

`resolve_mp4` defaults to **true** here. `best_video` holds a direct MP4 URL
(possibly `null` for HLS-only pins); `videos` lists all variants.

```bash
curl "https://pinterest-api-inyg.onrender.com/search/videos?q=goku%20fight&page_size=5"
```

Measured: on one page, ~10 of 23 results had a direct MP4; the rest were
HLS-only. Handle both (see §0.3).

<br>

## 3. GIFs

```
GET /search/gifs?q=<query>[&page_size=25][&page_bookmark=<bm>][&pages=1]
```

Pinterest has no server-side GIF filter, so the API searches a gif-oriented
variant and keeps only results whose original file is really animated (GIF89a).
`pages` (1–3) probes deeper results when a query returns few GIFs. The query
actually sent is echoed back as `effective_query`.

```bash
curl "https://pinterest-api-inyg.onrender.com/search/gifs?q=funny%20cat&pages=2"
```

<br>

## 4. Autocomplete / typo correction

```
GET /search/suggestions?q=<partial>[&limit=8]
```

Great for search boxes and fixing misspellings. Type "asthetic" and the top
suggestion is "aesthetic". Item `type`: `query | recent | pin | board | guide | user`.
Use the top `query` item to re-run a corrected search.

```bash
curl "https://pinterest-api-inyg.onrender.com/search/suggestions?q=asthetic"
```

```python
sug = requests.get(f"{BASE}/search/suggestions", params={"q": "motivat"}).json()
corrected = [x["query"] for x in sug["suggestions"] if x["type"] == "query"]
```

<br>

## 5. Pin detail

```
GET /pin/{id}/info          # full manifest
GET /resolve?url=<pin url>  # same manifest from any pin URL
```

`{id}` = numeric pin ID *or* any full Pinterest pin URL (slug allowed).
The manifest contains all image sizes, video variants, metadata, and carousel slides.

```bash
curl -s "https://pinterest-api-inyg.onrender.com/pin/369858188161092508/info"
curl -s "https://pinterest-api-inyg.onrender.com/resolve?url=https://www.pinterest.com/pin/369858188161092508/"
```

<br>

## 6. Downloads & streaming

```
GET /pin/{id}/download          -> best media as attachment (orig image / 720p MP4 / gif)
GET /pin/{id}/download/all      -> ZIP of every asset on the pin
GET /pin/{id}/stream            -> inline stream (use in <img>/<video> tags)
GET /download?url=<cdn url>     -> proxy any pinimg CDN media URL (works for opaque ids)
```

```bash
curl -O "https://pinterest-api-inyg.onrender.com/pin/369858188161092508/download"
curl -o pin.zip "https://pinterest-api-inyg.onrender.com/pin/369858188161092508/download/all"

# opaque-id result (from /search): grab best_image and proxy it
IMG=$(curl -s "$BASE/search?q=cats&page_size=1" | jq -r '.results[0].best_image')
curl -O "$BASE/download?url=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=""))' "$IMG")"
```

`/download?url=` only accepts Pinterest CDN hosts (`i.pinimg.com`,
`v1.pinimg.com`, `v.pinimg.com`). Add `&inline=true` to serve inline.

<br>

## 7. Gallery (browser view)

```
GET /gallery?q=<query>
```

Self-contained HTML page (no build step). Type any query, get a grid of
thumbnails; hover a video to play it; click a tile to open the pin. Media-filter
and page-size controls are in the bar, and the query is deep-linkable
(`/gallery?q=sunset+aesthetic`). It renders media through `/download?url=`, so
opaque-id results render too.

```
https://pinterest-api-inyg.onrender.com/gallery?q=cyberpunk+city+night
```

<br>

## 8. Session status

```
GET /session/status
```

```json
{
  "authenticated": false,
  "mode": "anonymous (logged-out surface)",
  "has_session_cookie": true,
  "cookie_count": 4,
  "note": "Anonymous results are byte-identical to pinterest.com in a private window. Set PINTEREST_COOKIE to get personalized ranking."
}
```

Use this in automation to assert whether personalized mode is active.

<br>

## 9. Health

```
GET /health        -> {"ok": true}
```

<br>

## Full tutorial: build an asset harvester

End-to-end recipe: search several queries, download every image/video/gif into
per-query folders, dedupe by id.

```python
import os, re, urllib.parse, requests

BASE = "https://pinterest-api-inyg.onrender.com"
OUT  = "./assets"

def slug(s): return re.sub(r"\W+", "_", s).strip("_")

def harvest(queries):
    seen = set()
    for q in queries:
        d = requests.get(f"{BASE}/search",
                         params={"q": q, "page_size": 50, "resolve_mp4": "true"},
                         timeout=120).json()
        folder = os.path.join(OUT, slug(q)); os.makedirs(folder, exist_ok=True)
        for i, pin in enumerate(d["results"], 1):
            if pin["id"] in seen:      # dedupe across queries
                continue
            seen.add(pin["id"])

            # pick the media url: direct MP4 if available, else best image
            url = pin.get("best_video") or pin.get("best_image")
            if not url:
                continue

            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".jpg"
            dest = f"{folder}/{i:03d}_{slug(pin.get('creator') or 'x')}{ext}"
            r = requests.get(f"{BASE}/download",
                             params={"url": url}, timeout=180)
            if r.ok and r.content:
                open(dest, "wb").write(r.content)
                print(dest, len(r.content), r.headers.get("content-type"))

harvest(["dark aesthetic", "cyberpunk city night",
         "space galaxy 4k", "lofi anime aesthetic"])
```

**Tips**
- Always dedupe by `pin["id"]` (queries overlap).
- Prefer `best_video` (MP4) when present; fall back to the `.m3u8` in `videos[]` if you can play HLS.
- Download through `/download?url=` (not the raw CDN) so it works for opaque ids and gets cached.
- `dominant_color` is handy as an instant placeholder color in a UI.

<br>

## Client examples

**Python**

```python
import requests
BASE = "https://pinterest-api-inyg.onrender.com"

s = requests.get(f"{BASE}/search", params={"q": "cosy interior", "page_size": 10}).json()
for pin in s["results"]:
    url = pin.get("best_video") or pin["best_image"]
    media = requests.get(f"{BASE}/download", params={"url": url})
    open(f"{pin['id']}.jpg", "wb").write(media.content)
```

**JavaScript**

```javascript
const base = "https://pinterest-api-inyg.onrender.com";
const res = await fetch(`${base}/search?q=workout%20motivation&page_size=20`);
const { results, next_bookmark } = await res.json();
const mp4 = results.find(r => r.type === "video")?.best_video;

// embed an image (proxy works for opaque ids)
const img = document.createElement("img");
img.src = `${base}/download?url=${encodeURIComponent(results[0].best_image)}&inline=true`;
```

**curl one-liners**

```bash
B="https://pinterest-api-inyg.onrender.com"
curl -s "$B/search?q=nature&page_size=5"                 | jq '.results[].pin_url'
curl -s "$B/search/videos?q=ocean&page_size=5"           | jq '.results[].best_video'
curl -s "$B/search/gifs?q=funny+cat&pages=2"             | jq '.hits'
curl -s "$B/search/suggestions?q=asthetic"               | jq '.suggestions[0].query'
curl -s -o pin.zip "$B/pin/369858188161092508/download/all"
```

<br>

## 8. Browser gallery (the UI)

Open `/gallery` — a Pinterest-style masonry browser, no build step, no external
dependencies. `/gallery?q=<query>` deep-links a query.

- **Search box** + media tabs (All / Videos / GIFs) + result count.
- **Re-roll (↻)** — same query, new pins. This is `explore=true` under the hood.
- **explore** toggle — on by default; turn it off for stable pagination with
  infinite scroll (the grid auto-loads the next page as you scroll).
- **stats** toggle — on by default; shows save/repin/reaction counts and creator
  on each tile (uses `include_stats=true`).
- **Hover** a tile for stats and quick actions: download, copy media URL.
  **Click** for the lightbox: full media, metadata, and on video pins a
  **Get MP4** button that resolves the direct MP4 on demand.
- **Keys**: `/` focus search, `r` re-roll, `Esc` close, `←/→` move through
  results, `Enter` search.
- Media is served through `/download?url=`, so opaque `e1_...` pins render too.

The status line reports hits, latency, pool size and whether the result came
from cache — so you can see exactly what the API did.

## Error codes

| HTTP | Meaning |
|---|---|
| 400 | Bad input (unparseable pin/URL, non-Pinterest media URL) |
| 404 | Pin not found on Pinterest (also: opaque id at `/pin/<id>/`) |
| 422 | Invalid params (e.g. empty `q`, `page_size` out of range) |
| 502 | Pinterest upstream/markup failure — transient, retry |

<br>

## Notes & limits

- Rides Pinterest's unauthenticated surface — if Pinterest changes their markup,
  the API returns clean 502s (fixable via the `spike/` re-probe toolkit).
- Anonymous ranking ≠ your logged-in app ranking. Set a session cookie
  (§0.1) for personalized results.
- No rate limiting implemented — don't hammer Pinterest. Add your own
  (nginx / slowapi) if you host publicly.
- Media streams are proxied; `Cache-Control: public, max-age=86400` so repeat
  requests are fast.
- Legal: technical interface to publicly accessible data — you're responsible
  for how you use downloaded content (copyright, ToS).

<br>

## Verified against (2026-10-17)

- `bash test_api.sh` — all 7 groups pass live (search / videos / gifs /
  pagination / pin downloads / search→download + opaque-id path)
- `/search/videos?q=goku fight` — 23 hits, 10 with direct MP4, 13 HLS-only
- `/gallery?q=cats` — 200, grid renders opaque-id media via `/download?url=`
- specific searches (`batman dark aesthetic`, `cyberpunk city night`,
  `naruto sad moments`, `space galaxy 4k`, `gym motivation dark`,
  `lofi anime aesthetic`) — all on-theme, correct media types
