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
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

PIN_URL_RE = re.compile(
    r"(?:https?://(?:[a-z-]+\.)?pinterest\.[a-z.]+/)?pin/(?:[^/?#]*?--)?(\d{5,25})"
)
RELAY_RE = re.compile(
    r'__PWS_RELAY_REGISTER_COMPLETED_REQUEST__\("([^"]*)"\s*,\s*'
)
META_RE = re.compile(
    r'<meta\s+([^>]*?(?:property|name)="(og:[^"]+|twitter:[^"]+)"[^>]*)>'
)
META_CONTENT_RE = re.compile(r'content="([^"]*)"')


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
    pin_id = pin_id_from(url_or_id) or (url_or_id if url_or_id.isdigit() else None)
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
            last_err = RuntimeError(
                f"relay extraction failed for pin {pin_id} (page structure changed?)")
        except Exception as e:
            last_err = e
    raise last_err


if __name__ == "__main__":
    import sys
    for target in sys.argv[1:]:
        print(f"\n=== {target} ===")
        try:
            man = get_pin(target)
            print(json.dumps(man, indent=1)[:1600])
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
