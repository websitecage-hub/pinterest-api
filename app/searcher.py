"""Pinterest search — reverse-engineered unauth resource API.

Works by warming a session on pinterest.com (gets csrftoken + _pinterest_sess
cookies) and then calling the same internal resource endpoint the web app
uses: /resource/BaseSearchResource/get/. Returns up to ~25 pins per page
with a bookmark for pagination — exactly like Pixabay/Pexels page params.

No API key, no login. Scope: pins, videos, or all via the scope field.
"""
from __future__ import annotations

import json
import urllib.parse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    """Lazily create (and reuse) a session with Pinterest cookies."""
    global _session
    if _session is not None:
        # refresh if cookies are > ~30 min old (cheap: they last long; keep simple)
        return _session
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
    })
    r = s.get("https://www.pinterest.com/", timeout=15)
    r.raise_for_status()
    if "csrftoken" not in s.cookies:
        raise RuntimeError("Pinterest did not set csrftoken")
    _session = s
    return s


def _reset_session():
    global _session
    _session = None


def _search_payload(query: str, scope: str, page_size: int, bookmark: str | None,
                    filters: dict | None) -> str:
    options = {
        "article": None,
        "appliedProductFilters": "---",
        "auto_correction_disabled": False,
        "corpus": None,
        "custom_filters": None,
        "entry": None,
        "explicit_filters": None,
        "filters": None,
        "lang": "en",
        "page_size": page_size,
        "query": query,
        "query_pin_titles": None,
        "rs": "typed",
        "scope": scope,
        "source_id": None,
        "source_module_id": None,
        "top_pin_id": None,
        "top_pin_ids": None,
        "no_fetch_context_on_resource": False,
    }
    if filters:
        options.update(filters)
    if bookmark:
        options["bookmarks"] = [bookmark]
    return json.dumps({"options": options, "context": {}})


def search(query: str, scope: str = "pins", page_size: int = 25,
           bookmark: str | None = None, filters: dict | None = None,
           timeout: int = 20, _retried: bool = False) -> dict:
    """Search Pinterest. Returns {results, bookmark, total_hits_like, scope, query}."""
    s = _get_session()
    data = _search_payload(query, scope, page_size, bookmark, filters)
    url = ("https://www.pinterest.com/resource/BaseSearchResource/get/"
           "?source_url=" + urllib.parse.quote(f"/search/{scope}/?q={query}", safe="")
           + "&data=" + urllib.parse.quote(data, safe=""))
    r = s.get(url, headers={
        "X-Requested-With": "XMLHttpRequest",
        "X-Pinterest-PWS-Handler": "www/search/[scope].js",
        "X-CSRFToken": s.cookies.get("csrftoken", ""),
        "Accept": "application/json, text/javascript, */*, q=0.01",
        "Referer": f"https://www.pinterest.com/search/{scope}/?q={query}",
    }, timeout=timeout)
    if r.status_code == 401 and not _retried:
        # session went stale mid-flight — one retry with fresh cookies
        _reset_session()
        return search(query, scope, page_size, bookmark, filters, timeout,
                      _retried=True)
    r.raise_for_status()
    j = r.json()
    rr = j.get("resource_response", {})
    data_obj = rr.get("data") or {}
    raw_results = data_obj.get("results") or []
    next_bookmark = rr.get("bookmark") or None
    if next_bookmark == "-end-":
        next_bookmark = None

    pins = [_normalize_pin(p) for p in raw_results if p.get("type") == "pin"]
    return {
        "query": query,
        "scope": scope,
        "page": {"bookmark": bookmark} if bookmark else None,
        "page_size": page_size,
        "hits": len(pins),
        "results": pins,
        "next_bookmark": next_bookmark,
        "has_more": bool(next_bookmark),
    }


def _collect_videos(node, acc: list) -> list:
    """Collect video variants from a search-result pin (same layout as relay pins)."""
    if isinstance(node, dict):
        url = node.get("url")
        if isinstance(url, str) and url.endswith((".mp4", ".m3u8")):
            acc.append({
                "variant": None,
                "url": url,
                "width": node.get("width"),
                "height": node.get("height"),
                "durationMs": node.get("duration"),
                "thumbnail": node.get("thumbnail"),
            })
        for k, v in node.items():
            if isinstance(v, dict) and isinstance(v.get("url"), str) \
                    and v["url"].endswith((".mp4", ".m3u8")):
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
        if it["url"] not in seen:
            seen.add(it["url"])
            out.append(it)
    return out


def resolve_mp4s(pin: dict, timeout: int = 15) -> dict:
    """Given a normalized search-result pin with only HLS, fetch the pin's
    detail page (relay payload) and pull its MP4 variants + best_video.

    Pinterest search results only expose .m3u8 (HLS) URLs; the detail page
    embeds av1Mp4/expMp4 files at 240/360/540/720 widths. This makes results
    directly downloadable/playable in any client.
    """
    pid = pin.get("id")
    if not pid:
        return pin
    try:
        from extractor import get_pin
        manifest = get_pin(pid, timeout=timeout)
    except Exception:
        return pin  # leave HLS-only on failure — still playable via hls.js
    if manifest.get("best_video"):
        pin["best_video"] = manifest["best_video"]
    if manifest.get("videos"):
        pin["videos"] = _dedupe(list(manifest["videos"]) + list(pin.get("videos") or []))
    return pin


def detect_gifs(pins: list, timeout: int = 8) -> list:
    """Filter search results to real animated GIFs.

    Pinterest's resized variants are always .jpg, so a GIF is only visible at
    /originals/{sig}.gif. Build that URL from each pin's image signature and
    HEAD-probe it: 200 = animated gif, 403/404 = not.
    """
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    out = []
    for pin in pins:
        sig = pin.pop("_image_signature", None)
        if not sig:
            continue
        gif_url = f"https://i.pinimg.com/originals/{sig[0:2]}/{sig[2:4]}/{sig[4:6]}/{sig}.gif"
        try:
            r = requests.head(gif_url, headers={"User-Agent": UA}, timeout=timeout)
            if r.status_code == 200:
                pin["type"] = "gif"
                pin["best_image"] = gif_url
                pin["images"]["orig"] = gif_url
                out.append(pin)
        except requests.RequestException:
            continue
    return out


def _normalize_pin(p: dict) -> dict:
    """Search-result pin -> clean schema (Pixabay/Pexels-like item)."""
    images = p.get("images") or {}
    # images dict in search results: keys like "170x", "236x", "474x", "736x", "orig"
    img_urls = {}
    for size, spec in images.items():
        if isinstance(spec, dict) and isinstance(spec.get("url"), str):
            img_urls[size] = spec["url"]
    best_image = None
    for pref in ("orig", "736x", "474x", "236x"):
        if pref in img_urls:
            best_image = img_urls[pref]
            break

    videos = _dedupe(_collect_videos(p.get("story_pin_data") or {}, []))
    videos += _dedupe(_collect_videos(p.get("videos") or {}, []))
    videos = _dedupe(videos)

    mp4s = [v for v in videos if v["url"].endswith(".mp4")]
    best_video = None
    if mp4s:
        def video_rank(v):
            url = v["url"]
            tier = 0 if "/720p/" in url else (2 if "expMp4" in url else 1)
            # prefer plain mp4 encodings over experiments; higher width first
            return (tier, -(v.get("width") or 0), -(v.get("height") or 0))
        best_video = sorted(mp4s, key=video_rank)[0]

    if videos:
        ptype = "video"
    elif best_image and best_image.lower().endswith(".gif"):
        ptype = "gif"
    elif best_image:
        ptype = "image"
    else:
        ptype = "unknown"

    return {
        "id": p.get("id"),
        "type": ptype,
        "title": p.get("grid_title") or p.get("title"),
        "description": (p.get("description") or "").strip() or None,
        "alt_text": p.get("seo_alt_text") or p.get("auto_alt_text"),
        "creator": (p.get("pinner") or {}).get("username")
                   or (p.get("pinner") or {}).get("full_name"),
        "creator_avatar": (p.get("pinner") or {}).get("image_medium_url"),
        "board": (p.get("board") or {}).get("url"),
        "link": p.get("link"),
        "dominant_color": p.get("dominant_color"),
        "created_at": p.get("created_at"),
        "saves": None,
        "reactions": p.get("reaction_counts") or None,
        "pin_url": f"https://www.pinterest.com/pin/{p.get('id')}/",
        "best_image": best_image,
        "images": img_urls,
        "best_video": best_video["url"] if best_video else None,
        "videos": videos,
        "_image_signature": p.get("image_signature"),
    }
