#!/usr/bin/env python3
"""Pinterest pin extractor — reverse-engineered from www.pinterest.com/pin/* SSR HTML.

How it works:
  1. GET the pin page with a browser UA (unauth, no cookies needed).
  2. The page is server-side rendered. Pin data arrives via a relay script:
     __PWS_RELAY_REGISTER_COMPLETED_REQUEST__("<urlencoded graphql spec>", {json})
     containing GraphQL response for v3GetPinQueryv2.
  3. Brace-match-scan the script body to extract the JSON payload safely.
  4. Normalize into a clean media manifest: images (orig + resized),
     videos (mp4/hls variants), carousels, story-pin (idea pin) pages.
  5. Fallback: og: meta tags if relay extraction ever changes.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Pinterest serves two id shapes: legacy numeric ("7810999345573240") and the
# newer opaque form ("e1_AfqPShy50Pph1fYw8AHXYvOCsd4oe9ssdeNNgw0lGRsTTS7FIqGotA").
# Search results now return the opaque form, so both must be accepted or every
# download of a fresh search hit 400s.
PIN_URL_RE = re.compile(
    r"(?:https?://(?:[a-z-]+\.)?pinterest\.[a-z.]+/)?pin/(?:[^/?#]*?--)?([A-Za-z0-9_-]{5,})"
)
BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{5,}$")
RELAY_RE = re.compile(
    r'__PWS_RELAY_REGISTER_COMPLETED_REQUEST__\("([^"]*)"\s*,\s*'
)
META_RE = re.compile(
    r'<meta\s+([^>]*?(?:property|name)="(og:[^"]+|twitter:[^"]+)"[^>]*)>'
)
META_CONTENT_RE = re.compile(r'content="([^"]*)"')


class PinNotFoundError(Exception):
    """Raised when the pin page loads but contains no pin data (deleted/nonexistent pin)."""


def pin_id_from(url_or_id: str) -> str | None:
    m = PIN_URL_RE.search(url_or_id.strip())
    return m.group(1) if m else None


def _fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


_api_lock = threading.Lock()
_api_sess = None


def _api_session():
    """Warmed session for Pinterest's internal JSON resources (POST).

    Reuses searcher's cookie helpers so PINTEREST_COOKIE (authenticated mode)
    applies here too — which is what unlocks save counts and personalization.
    """
    global _api_sess
    # Self-healing: pick up a rotated cookie without a restart.
    try:
        from searcher import reload_cookie_if_changed
        reload_cookie_if_changed()
    except Exception:
        pass
    with _api_lock:
        if _api_sess is not None:
            return _api_sess
        import requests
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        # Apply the operator cookie BEFORE warming (same reason as
        # searcher._get_session): warming first binds an anonymous csrftoken
        # to an authenticated session, and Pinterest 403s the POST.
        try:
            from searcher import _env_cookie_string, _apply_cookie, _cookie_value
        except Exception:  # pragma: no cover - defensive
            _env_cookie_string = lambda: None          # noqa: E731
            _apply_cookie = lambda sess, c: None       # noqa: E731
            _cookie_value = lambda sess, n: ""         # noqa: E731
        cookie = _env_cookie_string()
        if cookie:
            _apply_cookie(s, cookie)
        s.get("https://www.pinterest.com/", timeout=15)
        s.headers.update({
            "X-CSRFToken": _cookie_value(s, "csrftoken"),
            "X-Requested-With": "XMLHttpRequest",
            "X-App-Version": "6550262",
            "X-Pinterest-AppState": "active",
            "Accept": "application/json",
        })
        _api_sess = s
        return s


def _reset_api_session():
    global _api_sess
    with _api_lock:
        _api_sess = None


def pin_from_resource(pin_id: str, timeout: int = 20) -> dict | None:
    """Fetch a pin as JSON via the internal PinResource (POST).

    Richer and more reliable than scraping the SSR page: carries save counts,
    comment/reaction counts, every image size and all video variants.
    Returns None when Pinterest has no such pin on this surface (which is the
    case for the opaque search-surface ids like "e1_...").
    """
    import requests
    payload = json.dumps({"options": {"id": pin_id, "field_set_key": "detailed"},
                          "context": {}})
    r = None
    for attempt in (0, 1):
        s = _api_session()
        try:
            r = s.post("https://www.pinterest.com/resource/PinResource/get/",
                       data={"source_url": f"/pin/{pin_id}/", "data": payload},
                       timeout=timeout)
        except requests.RequestException:
            return None
        if r.status_code in (401, 403) and attempt == 0:
            # Session went stale mid-flight — rebuild, fail over to the next
            # cookie in the pool if there is one, and retry rather than
            # silently returning no stats (self-healing).
            _reset_api_session()
            try:
                from searcher import rotate_cookie
                rotate_cookie()
            except Exception:
                pass
            continue
        break
    if r is None:  # pragma: no cover - defensive
        return None
    if r.status_code in (401, 403):
        _reset_api_session()
        return None
    if r.status_code != 200:
        return None
    try:
        j = r.json()
    except ValueError:
        return None
    rr = j.get("resource_response", {})
    if rr.get("status") != "success":
        return None
    return rr.get("data") or None


def manifest_from_resource(pin: dict, pin_id: str) -> dict:
    """PinResource JSON (snake_case) -> the same manifest schema as SSR."""
    images = {}
    for size, spec in (pin.get("images") or {}).items():
        if isinstance(spec, dict) and isinstance(spec.get("url"), str):
            images[size] = spec["url"]

    videos = _dedupe(_collect_videos(pin.get("videos") or {}, [])
                     + _collect_videos(pin.get("story_pin_data") or {}, []))
    mp4s = [v for v in videos if v["url"].endswith(".mp4")]
    best_video = None
    if mp4s:
        def rank(v):
            url = v["url"]
            tier = 0 if "/720p/" in url else (2 if "expMp4" in url else 1)
            return (tier, -(v.get("width") or 0), -(v.get("height") or 0))
        best_video = sorted(mp4s, key=rank)[0]
    elif videos:
        best_video = videos[0]

    best_image = images.get("orig") or images.get("736x") or images.get("564x")

    apd = pin.get("aggregated_pin_data") or {}
    stats = apd.get("aggregated_stats") or {}

    if videos or pin.get("is_video"):
        pin_type = "video"
    elif best_image and best_image.lower().endswith(".gif"):
        pin_type = "gif"
    elif best_image:
        pin_type = "image"
    else:
        pin_type = "unknown"

    return {
        "pin_id": pin_id,
        "id": pin_id,  # alias: search results expose the id as `id`
        "type": pin_type,
        "title": pin.get("title") or pin.get("grid_title") or pin.get("seo_title"),
        "description": pin.get("description") or pin.get("seo_description"),
        "alt_text": pin.get("alt_text") or pin.get("seo_alt_text"),
        "creator": (pin.get("pinner") or {}).get("username"),
        "creator_followers": (pin.get("pinner") or {}).get("follower_count"),
        "creator_verified": bool((pin.get("pinner") or {}).get("verified_identity")
                                 or (pin.get("pinner") or {}).get("is_verified_merchant")),
        "board_url": (pin.get("board") or {}).get("url"),
        "link": pin.get("link"),
        "domain": pin.get("domain"),
        # quality metrics the logged-out search payload never carries:
        "saves": stats.get("saves"),
        "comments": pin.get("comment_count"),
        "repins": pin.get("repin_count"),
        "shares": pin.get("share_count"),
        "reactions": pin.get("reaction_counts"),
        "dominant_color": pin.get("dominant_color"),
        "created_at": pin.get("created_at"),
        "image_signature": pin.get("image_signature"),
        "best_image": best_image,
        "images": images,
        "best_video": best_video["url"] if best_video else None,
        "videos": videos,
        "carousel": [],
        "is_idea_pin": bool((pin.get("story_pin_data") or {}).get("pages")),
        "source": "resource_api",
    }


def _scan_json(text: str, start: int) -> tuple[dict, int]:
    """Brace-matching JSON scanner: safely extract a balanced {...} from start."""
    if start >= len(text) or text[start] != "{":
        raise ValueError("not at a JSON object")
    depth, i, in_str, esc = 0, start, False, False
    while i < len(text):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1]), i + 1
        i += 1
    raise ValueError("unbalanced JSON")


def extract_relay_payloads(html: str) -> list[dict]:
    """All completed relay payloads in page order."""
    out = []
    for m in RELAY_RE.finditer(html):
        try:
            payload, _ = _scan_json(html, m.end())
            out.append(payload)
        except (ValueError, json.JSONDecodeError):
            continue
    return out


def _find_pin_obj(node) -> dict | None:
    """Locate the Pin object inside a relay payload."""
    if isinstance(node, dict):
        if node.get("__typename") == "PinResponse" and isinstance(node.get("data"), dict):
            return node["data"]
        if node.get("__typename") == "Pin" and ("images_orig" in node or "videos" in node):
            return node
        for v in node.values():
            r = _find_pin_obj(v)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_pin_obj(v)
            if r is not None:
                return r
    return None


def _og_fallback(html: str) -> dict:
    """og:/twitter: meta tags -> minimal manifest."""
    metas = {}
    for m in META_RE.finditer(html):
        cm = META_CONTENT_RE.search(m.group(1))
        if cm:
            metas[m.group(2)] = html.unescape(cm.group(1)) if hasattr(html, "unescape") else cm.group(1)
    import html as _h
    metas = {k: _h.unescape(v) for k, v in
             ((m.group(2), (META_CONTENT_RE.search(m.group(1)) or [None, ""])[1])
              for m in META_RE.finditer(html)) if META_CONTENT_RE.search(m.group(1))}
    return metas


def _img_sig_urls(pin: dict) -> dict:
    """All static image sizes present on the pin object."""
    urls = {}
    candidates = [
        ("orig", pin.get("images_orig", {}).get("url")),
        ("1200x", pin.get("imageLargeUrl")),
        ("736x", pin.get("images_736x", {}).get("url") or pin.get("images_736", {}).get("url")),
        ("564x", pin.get("images_564x", {}).get("url")),
        ("474x", pin.get("images_474x", {}).get("url") or pin.get("images_474", {}).get("url")),
        ("236x", pin.get("images_236x", {}).get("url") or pin.get("images_236", {}).get("url")),
    ]
    for name, u in candidates:
        if isinstance(u, str) and u.startswith("http"):
            urls[name] = u
    return urls


def _collect_videos(node, acc: list) -> list:
    """Walk any structure collecting video variant dicts {name,url,width,height,duration,thumbnail}."""
    if isinstance(node, dict):
        keys = node.keys()
        if "url" in keys and isinstance(node["url"], str) and (
            node["url"].endswith((".mp4", ".m3u8"))
        ):
            acc.append({
                "variant": None,
                "url": node["url"],
                "width": node.get("width"),
                "height": node.get("height"),
                "durationMs": node.get("duration"),
                "thumbnail": node.get("thumbnail"),
            })
        for k, v in node.items():
            if isinstance(v, dict) and ("url" in v and isinstance(v.get("url"), str)
                                        and v["url"].endswith((".mp4", ".m3u8"))):
                acc.append({
                    "variant": k,
                    "url": v["url"],
                    "width": v.get("width"),
                    "height": v.get("height"),
                    "durationMs": v.get("duration"),
                    "thumbnail": v.get("thumbnail"),
                })
            _collect_videos(v, acc)
    elif isinstance(node, list):
        for v in node:
            _collect_videos(v, acc)
    return acc


def _dedupe(items: list) -> list:
    seen, out = set(), []
    for it in items:
        key = it["url"]
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def manifest_from_pin(pin: dict, pin_id: str) -> dict:
    """Normalize raw pin object -> clean download manifest."""
    images = _img_sig_urls(pin)

    # regular video pins: pin["videos"]["video_list"]
    videos = _collect_videos(pin.get("videos") or {}, [])
    # idea pins / story pins: storyPinData.pages[].blocks[].videoDataV2
    story = pin.get("storyPinData") or {}
    for page in story.get("pages") or []:
        for blk in page.get("blocks") or []:
            if "videoDataV2" in blk:
                videos.extend(_collect_videos(blk["videoDataV2"], []))
    videos = _dedupe(videos)

    # best video = prefer 720p mp4, then plain mp4, then expMp4 experiments
    mp4s = [v for v in videos if v["url"].endswith(".mp4")]
    best_video = None
    if mp4s:
        def video_rank(v):
            url = v["url"]
            if "/720p/" in url:
                tier = 0
            elif "expMp4" in url:
                tier = 2
            else:
                tier = 1
            return (tier, -(v.get("width") or 0), -(v.get("height") or 0))
        best_video = sorted(mp4s, key=video_rank)[0]
    elif videos:
        best_video = videos[0]

    carousel = []
    for slide in pin.get("carouselData") or []:
        urls = _img_sig_urls(slide) if isinstance(slide, dict) else {}
        if urls:
            carousel.append(urls)

    best_image = images.get("orig") or images.get("1200x") or images.get("736x")

    if videos or pin.get("isVideo"):
        pin_type = "video"
    elif best_image and best_image.lower().endswith(".gif"):
        pin_type = "gif"
    elif carousel:
        pin_type = "carousel"
    elif best_image:
        pin_type = "image"
    else:
        pin_type = "unknown"

    creator = (pin.get("nativeCreator") or pin.get("pinner") or {}).get("username")

    return {
        "pin_id": pin_id,
        "id": pin_id,  # alias: search results expose the id as `id`
        "type": pin_type,
        "title": pin.get("title") or pin.get("gridTitle") or pin.get("seoTitle"),
        "description": pin.get("description") or pin.get("seoDescription"),
        "alt_text": pin.get("seoAltText"),
        "creator": creator,
        "board_url": (pin.get("board") or {}).get("url"),
        "link": pin.get("link"),
        "saves": (pin.get("aggregatedPinData") or {}).get("aggregatedStats", {}).get("saves"),
        "dominant_color": pin.get("dominantColor"),
        "created_at": pin.get("createdAt"),
        "best_image": best_image,
        "images": images,
        "best_video": best_video["url"] if best_video else None,
        "videos": videos,
        "carousel": carousel,
        "is_idea_pin": bool(story.get("pages")),
    }


def get_pin(url_or_id: str, timeout: int = 20, retries: int = 2) -> dict:
    """Main entry: pin URL or id -> download manifest. Retries on transient
    SSR variance (Pinterest occasionally serves a page without the relay
    payload — a second fetch usually gets the full one). Manifests are
    cached 1h (pinimg URLs are stable), making repeated video search
    resolution near-instant."""
    pin_id = pin_id_from(url_or_id) or (url_or_id.strip() if BARE_ID_RE.match(url_or_id.strip()) else None)
    if not pin_id:
        raise ValueError(f"cannot parse pin id from {url_or_id!r}")

    from cache import TTLCache, deep_copy_if
    global _pin_cache
    try:
        _pin_cache
    except NameError:
        _pin_cache = TTLCache(max_entries=2048)
    cached = _pin_cache.get(("pin", pin_id))
    if cached is not None:
        return deep_copy_if(cached)

    # 1) Internal JSON resource API first — richer (save counts, all sizes,
    #    every video variant) and immune to SSR/scraping variance.
    if pin_id.isdigit():
        try:
            data = pin_from_resource(pin_id, timeout)
            if data:
                manifest = manifest_from_resource(data, pin_id)
                if manifest["type"] != "unknown":
                    _pin_cache.set(("pin", pin_id), deep_copy_if(manifest), 3600)
                    return manifest
        except Exception:
            pass

    # 2) SSR relay scrape (legacy fallback; also covers pinned older ids)
    last_err = None
    for attempt in range(retries + 1):
        try:
            html = _fetch(f"https://www.pinterest.com/pin/{pin_id}/", timeout)
            for payload in extract_relay_payloads(html):
                pin = _find_pin_obj(payload)
                if pin is not None:
                    manifest = manifest_from_pin(pin, pin_id)
                    _pin_cache.set(("pin", pin_id), deep_copy_if(manifest), 3600)
                    return manifest
            last_err = PinNotFoundError(
                _not_found_message(pin_id))
        except Exception as e:
            last_err = e
    raise last_err


def _not_found_message(pin_id: str) -> str:
    """Explain *why* a pin id is unfetchable, since the two id spaces differ."""
    if not pin_id.isdigit():
        return (f"pin id {pin_id!r} is a search-surface id (opaque, e.g. 'e1_...'). "
                "Pinterest does not serve those at /pin/<id>/, so it cannot be "
                "fetched directly — use the media URLs returned by /search "
                "(best_image / images / videos) or pass them to /download?url=")
    return f"pin {pin_id} not found (page loaded but has no pin data)"


if __name__ == "__main__":
    import sys
    for target in sys.argv[1:]:
        print(f"\n=== {target} ===")
        try:
            man = get_pin(target)
            print(json.dumps(man, indent=1)[:1600])
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
