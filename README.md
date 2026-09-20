# Pinterest Media API

A **public, key-free API** for searching and downloading images, videos, and
GIFs from Pinterest — like the Pixabay/Pexels APIs, but for Pinterest content.
No API key, no login, no auth. Host it and it's live.

Built by reverse-engineering Pinterest's unauthenticated web surface:

| Function | Pinterest internal mechanism |
|---|---|
| Pin detail | SSR relay payload (`v3GetPinQueryv2` GraphQL) embedded in `/pin/{id}/` pages |
| Search | internal `BaseSearchResource` resource endpoint (session cookies, no login) |
| Media files | streamed straight from `i.pinimg.com` / `v1.pinimg.com` CDNs |

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

## Endpoints

### Search

    GET /search?q=<query>&page_size=25[&page_bookmark=<bookmark>][&media_type=video|gif][&resolve_mp4=false]

    GET /search/videos?q=<query>&page_size=25[&page_bookmark=...][&resolve_mp4=true]

    GET /search/gifs?q=<query>&page_size=25[&page_bookmark=...]

    GET /search/suggestions?q=<partial>[&limit=8]   # autocomplete + typo correction

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
`/search`), the API additionally fetches each pin's detail page to extract
direct MP4 URLs. Costs one HTTP request per video result.

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
