# Pinterest Media API — Usage Guide

Public, key-free API for searching and downloading images, videos, and GIFs
from Pinterest, plus query autocomplete / typo correction. No API key, no
auth — just call it.

<br>

## Base URL

Pick the one you're using:

| Deployment | Base URL |
|---|---|
| Render (live, public) | `https://pinterest-api-inyg.onrender.com` |
| Local (dev) | `http://127.0.0.1:8000` |

Swagger docs (interactive): `<base>/docs`
API index: `<base>/`

All examples below use the live Render URL. For local, swap the host.

<br>

## 0. Result quality, session mode & opaque ids (read first)

**Default = anonymous.** Results are byte-identical to what pinterest.com shows
in a private window (verified: same pin ids, same order). That surface carries no
save counts and no personalized ranking — that is a Pinterest limit, not an API one.

**Personalized mode.** Set `PINTEREST_COOKIE` (or `PINTEREST_COOKIE_FILE` = path
to a file holding it, or `PINTEREST_SESSION` = just the `_pinterest_sess` value)
as an environment variable on the host, then restart. All searches then run with
your logged-in session and return your personalized ranking.

    # Render: Dashboard -> your service -> Environment -> add
    #   PINTEREST_COOKIE = <full cookie header from your browser DevTools>
    # verify:
    GET /session/status
    -> {"authenticated": true, "mode": "personalized (session cookie injected)", ...}

Grab the cookie from DevTools → Network → any pinterest.com request → Request
Headers → `cookie`. Never commit it; prefer a throwaway account if the URL is
public (a leaked session cookie is a hijackable account).

**Opaque ids.** Pinterest's search returns some hits under opaque ids such as
`e1_AfqPShy50Pph1fYw8AHXYvOCsd4oe9ssdeNNgw0lGRsTTS7FIqGotA`. Pinterest will not
serve those at `/pin/<id>/` — its own API returns `PinNotFound` — and they can't
be resolved to a numeric id. Their media is still public, so:

- read `best_image` / `images.*` / `videos[].url` straight from the search response
- download with `GET /download?url=<that CDN url>`

`/pin/{id}/info|download|stream` answer 404 with that explanation for opaque ids.
Legacy numeric ids resolve normally and now include **save counts**.

<br>

## 1. Search pins

    GET /search?q=<query>[&page_size=25][&page_bookmark=<bm>][&media_type=video|gif][&resolve_mp4=true]

`page_size` accepts 1–100 (Pinterest returns up to 99 pins per page).

Params:
- `q` (required) — search text
- `page_size` — 1..50, default 25
- `page_bookmark` — opaque value from a previous response's `next_bookmark`
- `media_type` — `video` or `gif` to filter a page
- `resolve_mp4` — `true` to fetch direct MP4 URLs for video results (1 HTTP
  request per video result; slower)

Example:

    curl "https://pinterest-api-inyg.onrender.com/search?q=motivational%20quotes&page_size=10"

Response (Pixabay/Pexels-style):

    {
      "query": "motivational quotes",
      "scope": "pins",
      "page_size": 10,
      "hits": 10,
      "results": [
        {
          "id": "10344274147036450",
          "type": "image",                      // image | video | gif
          "title": "FOCUS 🎯 | Motivational wallpaper",
          "description": "Eliminate distractions...",
          "alt_text": "...",
          "creator": "talktomitch_1",
          "pin_url": "https://www.pinterest.com/pin/10344274147036450/",
          "best_image": "https://i.pinimg.com/originals/....jpg",
          "images": { "170x": "...", "236x": "...", "474x": "...", "736x": "...", "orig": "..." },
          "best_video": null,
          "videos": [],
          "dominant_color": "#1d1d1e",
          "created_at": "Tue, 25 Aug 2026 00:08:19 +0000"
        }
      ],
      "next_bookmark": "Y2JVSG81...",           // pass as page_bookmark
      "has_more": true
    }

Pagination: Pinterest uses opaque bookmarks, not page numbers. Loop while
`has_more` is true, passing `next_bookmark` as `page_bookmark`.

<br>

## 2. Videos

    GET /search/videos?q=<query>[&page_size=25][&resolve_mp4=true]

`resolve_mp4` defaults to `true` here. `best_video` holds a direct MP4
URL; `videos` lists all variants.

Example:

    curl "https://pinterest-api-inyg.onrender.com/search/videos?q=goku%20fight&page_size=5"

<br>

## 3. GIFs

    GET /search/gifs?q=<query>[&page_size=25][&pages=1]

Pinterest has no server-side GIF filter, so the API searches a
gif-oriented variant and keeps only results whose original file is
really animated. `pages` (1-3) probes deeper results when a query
returns few GIFs. The query actually sent is echoed back as
`effective_query`.

Example:

    curl "https://pinterest-api-inyg.onrender.com/search/gifs?q=funny%20cat&pages=2"

<br>

## 4. Autocomplete / typo correction

    GET /search/suggestions?q=<partial>[&limit=8]

Great for search boxes and fixing misspellings. Type "asthetic" and the
top suggestion is "aesthetic". Item `type`: query | recent | pin | board
| guide | user. Use the top `query` item to re-run a corrected search.

Example:

    curl "https://pinterest-api-inyg.onrender.com/search/suggestions?q=asthetic"

<br>

## 5. Pin detail

    GET /pin/{id}/info

Full manifest: all image sizes, video variants, metadata, carousel
slides. `{id}` = numeric pin ID *or* any full Pinterest pin URL (slug
allowed).

    GET /resolve?url=<any pin url>      # same manifest from a URL

<br>

## 6. Downloads & streaming

    GET /pin/{id}/download          -> best media as attachment (orig image / 720p MP4 / gif)
    GET /pin/{id}/download/all      -> ZIP of every asset on the pin
    GET /pin/{id}/stream            -> inline stream (use in <img>/<video> tags)

Examples:

    curl -O "https://pinterest-api-inyg.onrender.com/pin/10344274147036450/download"
    curl -o pin.zip "https://pinterest-api-inyg.onrender.com/pin/10344274147036450/download/all"

<br>

## 7. Health

    GET /health        -> {"ok": true}

<br>

## Client examples

Python:

    import requests
    base = "https://pinterest-api-inyg.onrender.com"

    s = requests.get(f"{base}/search", params={"q": "cosy interior", "page_size": 10}).json()
    for pin in s["results"]:
        media = requests.get(f"{base}/pin/{pin['id']}/download")
        open(f"{pin['id']}.jpg", "wb").write(media.content)

    # autocomplete + corrected search
    sug = requests.get(f"{base}/search/suggestions", params={"q": "motivat"}).json()
    corrected = [x["query"] for x in sug["suggestions"] if x["type"] == "query"]

JavaScript:

    const base = "https://pinterest-api-inyg.onrender.com";
    const res = await fetch(`${base}/search?q=workout%20motivation&page_size=20`);
    const { results, next_bookmark } = await res.json();
    const mp4 = results.find(r => r.type === "video")?.best_video;

    // gallery-style embed
    const img = document.createElement("img");
    img.src = `${base}/pin/${results[0].id}/stream`;

<br>

## Error codes

| HTTP | Meaning |
|---|---|
| 400 | Bad input (unparseable pin/URL, non-Pinterest URL) |
| 404 | Pin not found on Pinterest |
| 422 | Invalid params (e.g. empty `q`) |
| 502 | Pinterest upstream/markup failure — transient, retry |

<br>

## Notes & limits

- Rides Pinterest's unauthenticated surface — if Pinterest changes their
  markup, the API returns clean 502s (fixable via the `spike/` re-probe toolkit).
- No rate limiting implemented — don't hammer Pinterest. Add your own
  (nginx / slowapi) if you host publicly.
- Media streams are proxied; `Cache-Control: public, max-age=86400` so
  repeat requests are fast.
- Legal: technical interface to publicly accessible data — you're
  responsible for how you use downloaded content (copyright, ToS).
