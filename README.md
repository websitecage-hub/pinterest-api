# Pinterest Media API

A **public, key-free API** for searching and downloading images, videos, and
GIFs from Pinterest — like the Pixabay/Pexels APIs, but for Pinterest content.
No API key, no login, no auth. Host it and it's live.

Built by reverse-engineering Pinterest's unauthenticated web surface:

| Function | Pinterest internal mechanism |
|---|---|
| Pin detail | internal `PinResource` JSON endpoint (POST) — primary; SSR relay payload (`v3GetPinQueryv2`) as fallback |
| Search | internal `BaseSearchResource` resource endpoint (session cookies, no login) |
| Media files | streamed straight from `i.pinimg.com` / `v1.pinimg.com` CDNs |

### Result quality (read this)

Out of the box this API is **anonymous** — it serves the exact same result set
that pinterest.com serves in a private window (verified: identical pin ids, same
order). That surface is deliberately thin: it carries **no save counts** and no
personalized ranking.

Two things change that:

| Mode | How | What you get |
|---|---|---|
| Anonymous (default) | nothing to configure | logged-out ranking; `reaction_counts` only |
| Personalized | set `PINTEREST_COOKIE` (or `PINTEREST_COOKIE_FILE`) on the host | your logged-in ranking + save counts on `/pin/{id}/info` |

    # e.g. on Render: Environment -> PINTEREST_COOKIE = "<paste browser cookie>"
    # then: GET /session/status  ->  {"authenticated": true, ...}

Read that cookie from your own browser (DevTools → Network → any pinterest.com
request → Request Headers → `cookie`). **Never commit it.** Use a throwaway
account if you point the API at a public URL — a leaked session cookie is a
hijackable account.

### Opaque "e1_..." ids

Pinterest's search now returns some hits under opaque ids (e.g.
`e1_AfqPShy50Pph1fYw8...`). Pinterest does **not** serve those at `/pin/<id>/`
(its own API answers `PinNotFound`) and they cannot be resolved to a numeric id.
Their media is still public on the CDN, so:

* `/search` already returns `best_image`, `images.*` and `videos[].url` for them
* download them through `GET /download?url=<that CDN url>` (allow-listed to Pinterest CDNs)

`/pin/{id}/info|download|stream` return a 404 with that explanation for opaque ids.
Legacy numeric ids work normally and now return **save counts** via `PinResource`.

## Quick start

### Docker (recommended for hosting)

    git clone https://github.com/websitecage-hub/pinterest-api.git
    cd pinterest-api
    docker compose up -d
    # API live at http://localhost:8000 — that's it.

### Without Docker

    git clone https://github.com/websitecage-hub/pinterest-api.git
    cd pinterest-api
    bash setup.sh          # creates .venv, installs fastapi/uvicorn/requests
    .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

Open http://localhost:8000/ for the endpoint index,
http://localhost:8000/docs for interactive Swagger UI.

**Want to just look at results?** Open http://localhost:8000/gallery — type any
query, get a grid of thumbnails (hover a video to play it, click a tile to open
the pin). Media-filter and page-size controls are in the bar, and the query is
deep-linkable: `/gallery?q=sunset+aesthetic`.

## Endpoints

### Gallery

    GET /gallery?q=<query>       # browser view: thumbnail grid for any query

Self-contained HTML page (no build step). It renders media through the
`/download?url=` CDN proxy rather than `/pin/{id}/stream`, because most search
hits now carry opaque ids that do not resolve at `/pin/<id>/`.

### Search

    GET /search?q=<query>&page_size=25[&page_bookmark=<bookmark>][&media_type=video|gif][&resolve_mp4=false]
    # page_size accepts 1..100 (Pinterest returns up to 99 per page)

    GET /search/videos?q=<query>&page_size=25[&page_bookmark=...][&resolve_mp4=true]

    GET /search/gifs?q=<query>&page_size=25[&page_bookmark=...]

    GET /search/suggestions?q=<partial>[&limit=8]   # autocomplete + typo correction

    GET /session/status                             # anonymous vs personalized mode

    GET /download?url=<i.pinimg.com media url>[&inline=false]   # CDN proxy (opaque-id results)

Example:

    curl "http://localhost:8000/search?q=sunset%20aesthetic&page_size=10"

Response shape (Pixabay/Pexels-like):

    {
      "query": "sunset aesthetic",
      "scope": "pins",
      "page_size": 10,
      "hits": 10,
      "results": [
        {
          "id": "1234567890",
          "type": "image",              // image | video | gif
          "title": "...",
          "description": "...",
          "alt_text": "...",
          "creator": "username",
          "pin_url": "https://www.pinterest.com/pin/1234567890/",
          "best_image": "https://i.pinimg.com/originals/....jpg",
          "images": { "236x": "...", "474x": "...", "736x": "...", "orig": "..." },
          "best_video": null,           // for video pins: direct MP4 (if resolved)
          "videos": [ ...variants... ]
        }, ...
      ],
      "next_bookmark": "Y2J...",        // pass as page_bookmark for next page
      "has_more": true
    }

**Pagination**: Pinterest uses opaque bookmarks, not page numbers. Take
`next_bookmark` from a response and pass it as `page_bookmark`. Repeat while
`has_more` is true.

**Videos**: Pinterest's search endpoint only returns HLS (.m3u8) URLs.
With `resolve_mp4=true` (default ON for `/search/videos`, opt-in for
`/search`), the API resolves direct MP4 URLs, in two ways:

1. Numeric pin ids — fetch the pin's detail page and read its MP4 ladder.
2. Opaque "e1_..." ids — no pin page exists, so the MP4 path is *derived*
   from the HLS signature (`.../hls/aa/bb/cc/<sig>.m3u8` →
   `.../720p/aa/bb/cc/<sig>.mp4`), probing 720p downward and stopping at the
   first tier that exists. Results are cached 6h per signature.

**Not every video has an MP4.** Some newer pins are published HLS-only —
measured 10 of 22 on one `/search/videos` page, 13 of 25 on another. For those
`best_video` is `null` and `videos[]` carries the `V_HLSV4` manifest URL, which
plays fine in a browser player (hls.js) but is not a progressive MP4 download.
Treat `best_video` as "MP4 available", not "video available":

    mp4  = result['best_video']                                     # download this
    hls  = next((v['url'] for v in result['videos']
                 if v['url'].endswith('.m3u8')), None)              # play this

**GIFs**: Pinterest has no server-side GIF filter; `/search/gifs` searches
pins and filters to results whose original file is an animated `.gif`.
GIFs are rarer than videos — expect fewer hits than image search.

**Suggestions** (`/search/suggestions?q=`): query autocomplete / typo
correction via Pinterest's own `AdvancedTypeaheadResource`. Type a partial
or misspelled term ("asthetic") and the top suggested query is the fixed
form ("aesthetic"). Item `type`: query | recent | pin | board | guide |
user. Take the top `query` suggestion to re-run a corrected search.

### Search accuracy (aligned with the real web app)

The search request replicates an actual captured Pinterest
`BaseSearchResource` call wholesale — same options field set and
`rs: "typed"` + `auto_correction_disabled: False`, so Pinterest's typo
auto-correction stays ON, plus the `X-App-Version` header the browser
sends. Verified against a 93 MB HAR captured from a real Pinterest session.

### Pin detail & download

    GET /pin/{id}/info           -> full manifest (all sizes, variants, metadata)
    GET /pin/{id}/download       -> best media as attachment (orig image / 720p MP4)
    GET /pin/{id}/download/all   -> ZIP of every asset on the pin
    GET /pin/{id}/stream         -> inline stream (use in <img>/<video> tags)
    GET /resolve?url=<pin url>   -> manifest from any pin URL (with slug)

`{id}` = numeric pin ID or any full pin URL. IDs come from search results
or any pinterest.com link.

## Client examples

Python:

    import requests
    r = requests.get("http://localhost:8000/search", params={"q": "cosy interior", "page_size": 10})
    pins = r.json()["results"]
    media = requests.get(f"http://localhost:8000/pin/{pins[0]['id']}/download")
    open("pin.jpg", "wb").write(media.content)

JavaScript:

    const res = await fetch("/search?q=workout%20motivation&page_size=20");
    const { results, next_bookmark } = await res.json();
    const mp4 = results.find(r => r.type === "video")?.best_video;

## How the reverse-engineering works

1. `GET pinterest.com/pin/{id}/` with a browser User-Agent — server-side
   rendered, no auth needed. Pin data sits in a relay script:
   `__PWS_RELAY_REGISTER_COMPLETED_REQUEST__("<urlencoded spec>", {json})`.
   A brace-matching scanner extracts the JSON (regex on nested JSON is fragile).
2. Search hits `pinterest.com/resource/BaseSearchResource/get/` after
   warming a session on the homepage (grabbing csrftoken + session
   cookies — no login). `options.query`/`scope`/`bookmarks` drive
   everything; results carry image variants + HLS video.
3. Media comes straight from the pinimg CDNs with a Referer header.

`spike/` contains the full reverse-engineering toolkit (12 probe scripts) —
if Pinterest ever changes their markup and endpoints start 502ing, re-run
those probes to re-map the structure.

## Verified against (2026-11-07)

- authenticated mode, live account: anonymous search vs logged-in search on the
  same query share **0 of 25 pins**; 25/25 save counts populated when the
  session is accepted (`include_stats=true`), 4-5 s for 25 pins
- self-healing: expiring the cookie file makes `/health` report
  `healthy:false` (and search degrade to anonymous, HTTP 200); restoring the
  file heals it with no restart — `verified:true, authenticated_as:<user>`
- `bash test_api.sh` — all 7 groups pass

## Verified against (2026-10-17)

- `bash test_api.sh` — all 7 groups pass live (search / videos / gifs /
  pagination / pin downloads / search→download, plus the opaque-id path)
- `/gallery?q=aesthetic+wallpaper` — 200, grid renders opaque-id media through
  `/download?url=` (image → 200 `image/jpeg`; video → 200 `video/mp4` 4.8 MB)
- video search timing — first call ~8-10 s (22 pins, 22 opaque, ladder probes),
  repeat call 0.02-0.05 s (search + ladder caches)
- `spike/test_hls_ladder_cache.py` — asserts positive and negative ladder
  caching, sig extraction, and that HLS-only assets are skipped

## Verified against (2026-09-17)

- `/search?q=cats` — 8+ hits/page, image/gif/video typing correct
- `/search/videos?q=cooking&resolve_mp4=true` — video pins with direct MP4s
- `/search/gifs?q=funny cat` — gif-only results
- Pagination — page 2 has zero overlap with page 1
- Pin endpoints: image pin → orig JPEG (151,040 B), video pin → 720p MP4
  (3,067,381 B), gif pin → original GIF (136,217 B)
- `/download/all` — 7.5 MB zip, 14 assets
- Search → download integration: end-to-end media fetch from a search hit

## Repo layout

    app/
      main.py        FastAPI endpoints
      extractor.py   pin detail: relay payload -> manifest
      searcher.py    search: BaseSearchResource -> normalized results
      downloader.py  CDN streaming, content types, save-to-disk
    spike/           reverse-engineering probes (the "how we cracked it" toolkit)
    test_api.sh      end-to-end test suite (bash test_api.sh)
    Dockerfile       one-command hosting
    docker-compose.yml

## Notes & limits

- Rides Pinterest's unauth surface: if they change markup/endpoints, the
  API returns clean 502s — fix by re-probing with spike/.
- No rate limiting implemented — add your own (nginx, slowapi) if you host
  this publicly. Don't hammer Pinterest.
- `downloads/` (server-side saves) default to /tmp/pinterest-api-downloads;
  override with PINTEREST_DOWNLOADS env var.
- Carousel pins: `info.carousel` lists per-slide URLs (not yet verified
  against a live carousel pin — all test candidates were single-image).
- Legal: this is a technical interface to publicly accessible data. You're
  responsible for how you use downloaded content (copyright, ToS).
