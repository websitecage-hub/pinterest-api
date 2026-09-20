# HANDOFF.md — Pinterest Media API — Session Continuation Guide

This file lets ANY new machine (and a fresh Hermes Agent session) resume this
project exactly where it left off. It was created because the working VM could
shut down at any moment.

Last updated: 2026-09-18 (UTC), pushed right after the resilience-fix commit.

## What this project is

A public, key-free REST API for searching and downloading Pinterest media
(images / videos / GIFs), reverse-engineered from Pinterest's unauthenticated
web surface (SSR relay payloads for pin detail, BaseSearchResource for
search, pinimg CDNs for media). FastAPI + Python 3.12, no API key required.

Repo: https://github.com/websitecage-hub/pinterest-api (public), branch `main`.

## Session 2026-09-19 — v2.3 (HAR-aligned / accuracy pass)

Work done this session (from a fresh clone, then live-verified):

- Cloned repo fresh, ran setup.sh + test_api.sh: all 7 groups passed live
  against Pinterest (state was already at v2.2.1 — /gallery had landed).
- Analyzed a 93 MB HAR (`pinterest-hars.har`, 866 entries) captured from a
  real Pinterest session in a browser. Key findings applied:
  1. `BaseSearchResource` — the real web app sends a fuller options object
     than v2.2 did. Rewrote `app/searcher.py::_search_payload` to replicate
     the captured payload field-for-field (added domains/user/seoDrawerEnabled/
     applied_unified_filters/filter_genai/journey_depth/source_url/static_feed/
     selected_one_bar_modules/query_pin_sigs/gated/price_max/price_min/
     query_image_pins/request_params; kept `rs:"typed"` + `auto_correction_
     disabled:False` so Pinterest's typo auto-correction stays ON). Kept the
     scripted `page_size` (the API is page-based) instead of the browser's
     `null`.
  2. Added the `X-App-Version: 6550262` header and corrected
     `X-Pinterest-PWS-Handler` to `www/search/{scope}.js`, matching the real
     request fingerprint.
  3. NEW endpoint `GET /search/suggestions?q=<partial>[&limit=N]` using the
     real `AdvancedTypeaheadResource` (autocomplete + typo correction).
     Verified live: q=asthetic -> top suggestion "aesthetic"; q=motivat ->
     "motivational wallpaper", "motivation", etc. Items typed as query/
     recent/pin/board/guide/user.
- Re-ran full test suite after changes: still 7/7 pass, zero regression.

Note: the HAR captures an authenticated/dummy session (cookies _auth=1 +
_pinterest_sess; user-agent was an Android/Pixel 9 mobile Chrome). The API
continues to work on the unauth path (warm session on pinterest.com). The
captured cookies are session-specific and NOT reusable/committed — the code
only cribs the request SHAPE, never the tokens.

## State at handoff — v2.2 (all fixes applied AND live-verified)
Work done in this session, in order:

1. Cloned repo, reviewed all code (app/main.py, searcher.py, extractor.py,
   downloader.py, cache.py, spike/ probes, test_api.sh).
2. Ran the full end-to-end test suite — everything passed EXCEPT gif search
   (0 hits) — root-caused it: not a code bug; generic queries like "funny cat"
   just don't surface GIF pins in Pinterest's ranking.
3. Applied three fixes:

   F1 — GIF search actually returns gifs (`app/main.py` `/search/gifs`):
   - Appends " gif" to queries that don't already contain the word
     (echoed back as `effective_query` so callers know what ran).
   - New `pages` param (1-3, default 1): when 0 hits, probes deeper pages
     (deduped by pin id) until hits or pages exhausted.

   F2 — Resilience against transient Pinterest failures (`app/searcher.py`):
   - Retries once on: Timeout (retry with +10s budget), ConnectionError,
     401/403 (session reset + fresh cookies), 429/502/503 (2s backoff).
   - Raises `SearchError` when retries are exhausted (was a raw exception).
   - `X-CSRFToken` header coerced to str (Pyright fix).

   F3 — Correct HTTP semantics for missing pins (`app/extractor.py` + `main.py`):
   - New `PinNotFoundError`: page loads (HTTP 200) but relay payloads contain
     no pin object → API now returns 404 instead of 502.
   - Real markup changes still 502, as intended.

4. Re-ran verification after fixes (see "Verified" below).
5. `spike/inspect_404.py` added — probe script that distinguished
   "nonexistent pin" (2 relay payloads, no pin object) from "real pin".

## Verified (live against Pinterest, post-fix)

- `bash test_api.sh` end-to-end suite: PASS
  - /search pins: hits with correct typing + metadata
  - /search/videos: all video-typed, direct MP4s resolved (720p present)
  - /search/gifs?q=funny+cat: returns real gifs now (via effective_query
    "funny cat gif"; 8+ hits observed during testing)
  - pagination: page 2 zero overlap with page 1
  - /pin/{id}/download: image → 151,040 B JPEG; video → 3,067,381 B MP4
    (verified with `file`)
  - search→download integration: end-to-end fetch OK
- Nonexistent pin `/pin/999999999999999999/info` → 404 with clear detail
- `/resolve?url=<non-pinterest>` → 400; empty `q` → 422
- /pin/{id}/download/all → valid zips (6 files image pin / 13 files video
  pin, integrity checked)
- /pin/{id}/stream → inline JPEG with correct content-type

## Remaining TODO (next session picks up here)

1. Optional hardening: add rate limiting (nginx / slowapi) if hosting
   publicly. Not implemented; README notes this.
2. Carousel pins: `info.carousel` lists per-slide URLs — still unverified
   against a live carousel pin (all test candidates were single-image).
3. Idea: a static results-gallery page (static/gallery.html + StaticFiles
   mount) so non-technical users can view search results as a grid instead
   of raw JSON. Was next in the queue at handoff time.
4. Cloudflare quick tunnels (cloudflared --url) are EPHEMERAL — the public
   URL given in the session died with the VM. For a durable public URL use
   `cloudflared tunnel` with a named tunnel + your Cloudflare account DNS.

## How to resume on a new machine (with Hermes or without)

### A. If you use Hermes Agent (recommended — this continues the session)

1. Install Hermes Agent (docs: https://hermes-agent.nousresearch.com/docs).
2. Open a new Hermes session and paste this prompt:

       Clone https://github.com/websitecage-hub/pinterest-api, read its
       HANDOFF.md fully, and continue the project from its "Remaining TODO"
       section. Verify the current state first by running setup.sh and
       test_api.sh before changing anything.

   That gives the new session the full context: what the project is, what
   was done, what passed, and what's next.

### B. Plain terminal (no Hermes)

    git clone https://github.com/websitecage-hub/pinterest-api
    cd pinterest-api
    bash setup.sh                 # creates .venv, installs fastapi/uvicorn/requests
    .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
    # in a second terminal:
    bash test_api.sh              # full end-to-end suite against the running server

Docker alternative: `docker compose up -d` then hit http://localhost:8000.

### C. Pushing changes back to the repo

The repo is public — anyone can clone, but pushing requires a GitHub token:

1. Create a fine-grained PAT at github.com/settings/personal-access-tokens
   with Contents: Read+Write on websitecage-hub/pinterest-api.
2. Push without persisting the token anywhere:

       git push https://websitecage-hub:<NEW_PAT>@github.com/websitecage-hub/pinterest-api.git main

3. IMPORTANT: the PAT used during the original session was pasted in chat
   and must be considered burned. ROTATE it (revoke + create new) at
   https://github.com/settings/personal-access-tokens before doing anything
   else. Never write tokens into files or commits.

## Environment notes (the handoff machine)

- Linux x86_64, Python 3.12, venv at .venv/ (gitignored)
- cloudflared binary was at /home/runner/bin/cloudflared (v2026.9.1) —
  download fresh from GitHub releases for a new machine
- Server was run as: `.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
- First search after a cold start takes ~2-3s (session warm-up on
  pinterest.com homepage for csrftoken); subsequent searches are fast.

## API quick reference (for the next session)

    GET /search?q=<query>[&page_size=N][&page_bookmark=<bm>][&media_type=video|gif][&resolve_mp4=true]
    GET /search/videos?q=<query>[&resolve_mp4=true]
    GET /search/gifs?q=<query>[&pages=1-3]        # appends " gif" automatically, echoes effective_query
    GET /pin/{id}/info | /pin/{id}/download | /pin/{id}/download/all | /pin/{id}/stream
    GET /resolve?url=<pin url>
    GET /health

Error contract: 400 bad input (unparseable pin/url), 404 pin not found,
422 invalid params, 502 Pinterest upstream/markup failure (retryable).
