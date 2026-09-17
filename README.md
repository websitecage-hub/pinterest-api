# Pinterest Media API

Download images, videos, and GIFs from any Pinterest pin. No API key, no
login, no cookies — works via reverse-engineered unauthenticated SSR data
that Pinterest embeds in every pin page.

## How it works (the reverse-engineering)

1. `GET https://www.pinterest.com/pin/{id}/` with a browser User-Agent.
2. The page embeds a GraphQL response inside a relay script tag:
   `__PWS_RELAY_REGISTER_COMPLETED_REQUEST__("<urlencoded spec>", {json})`
   containing the `v3GetPinQueryv2` payload with the full pin object.
3. A brace-matching JSON scanner extracts that payload safely (no regex
   on nested JSON). Fallback structure-walkers locate the pin object.
4. The pin object is normalized into a manifest:
   - images: `images_orig.url` + 236x/474x/564x/736x/1200x variants
   - videos: `videos` (regular pins) + `storyPinData.pages[].blocks[].videoDataV2`
     (idea pins) -> 720p MP4, HLS .m3u8, experimental MP4s, thumbnails, captions
   - gifs: originals/*.gif detected by extension
   - carousels: `carouselData[]` slides with per-slide image sizes
5. Media is streamed from `i.pinimg.com` / `v1.pinimg.com` CDNs with a
   Referer header (works without it too, but polite).

## Run

    git clone https://github.com/<you>/pinterest-api.git
    cd pinterest-api
    bash setup.sh          # creates .venv, installs fastapi/uvicorn/requests
    .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

Then open http://localhost:8000/ for the endpoint index.

## Endpoints

| Endpoint | What it does |
|---|---|
| `GET /` | API index |
| `GET /health` | liveness check |
| `GET /pin/{id}/info` | full manifest: type, title, creator, saves, all image sizes, all video variants, carousel slides, alt text |
| `GET /pin/{id}/download` | proxy-download the BEST media as an attachment (720p MP4 for videos, /originals/ for images/GIFs) |
| `GET /pin/{id}/download/all` | ZIP of every asset: all image sizes + all video encodings + carousel + thumbnails + _manifest.json |
| `GET /pin/{id}/stream` | inline stream (embeddable in `<img src>` / `<video src>`) |
| `GET /pin/{id}/file` | save server-side to ./downloads, returns path + size |
| `GET /resolve?url=<full pin url>` | accepts any pin URL (with slug) and returns the manifest |

`{id}` accepts either the numeric pin ID or any full pin URL.

## Verified against (2026-09-17)

- Video pin 7810999345573240 -> 720p MP4 (3,067,381 bytes) + HLS + captions
- Image pin 369858188161092508 -> original JPEG (151,040 bytes, 675x1200)
- GIF pin 840765824214269718 -> original GIF (136,217 bytes, 498x472), typed "gif"
- /download/all on video pin -> 7.5 MB zip, 14 files
- Invalid pin id -> clean JSON 502 with explanation

## Files

    app/extractor.py   pin page -> manifest (relay extraction, type detection)
    app/downloader.py  CDN streaming, filename/content-type logic, save-to-dir
    app/main.py        FastAPI endpoints
    spike/             reverse-engineering probes (parse_pin, decode_relay, dump_keys...)
    test_api.sh        end-to-end curl test suite

## Notes / limits

- This rides on Pinterest's SSR structure (the relay script). If they
  change it, extraction fails with a 502 and the spike probes in spike/
  are the tools to re-map it.
- Video "best" preference: /720p/ MP4 > plain MP4 > expMp4 experiments > HLS.
- Carousel pins: use /download/all or read info.carousel (per-slide URLs).
  Not yet verified against a live carousel pin (couldn't find one to test).
- Rate limits: not hit during testing, but don't hammer — this is unauth.
