"""Pinterest Media API — public, Pixabay/Pexels-style. No API key required.

Reverse-engineered from Pinterest's unauthenticated web surface:
  - Pin detail:   SSR relay payload on /pin/{id}/ pages
  - Search:       internal BaseSearchResource endpoint (session cookies only)
  - Media:        streamed directly from i.pinimg.com / v1.pinimg.com CDNs

Endpoints:
  GET /                              API index
  GET /health                        liveness
  GET /search?q=...                  search pins (paginate via bookmark)
  GET /search/videos?q=...           search video pins only
  GET /search/gifs?q=...             search animated (GIF) pins only
  GET /pin/{id}/info                 full manifest for one pin
  GET /pin/{id}/download             best media as attachment
  GET /pin/{id}/download/all         zip of every asset
  GET /pin/{id}/stream               inline stream for <img>/<video>
  GET /resolve?url=...               any pin URL -> manifest
"""
from __future__ import annotations

import io
import json
import os
import sys
import zipfile

# allow "python -m uvicorn app.main:app" from the project root:
# ensure sibling modules (extractor, downloader, searcher) are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import downloader
from extractor import get_pin, pin_id_from
import searcher

app = FastAPI(
    title="Pinterest Media API",
    version="2.0.0",
    description="Search & download images, videos, GIFs from Pinterest. "
                "Public API — no key, no auth. Like Pixabay/Pexels, for Pinterest.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

DOWNLOADS_DIR = os.environ.get("PINTEREST_DOWNLOADS", "/tmp/pinterest-api-downloads")


# ---------- helpers ----------

def _manifest_or_404(target: str) -> dict:
    try:
        return get_pin(target)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Pinterest fetch failed: {e}")


def _best_media_url(manifest: dict) -> str:
    if manifest["type"] == "video" and manifest.get("best_video"):
        return manifest["best_video"]
    if manifest.get("best_image"):
        return manifest["best_image"]
    raise HTTPException(status_code=404, detail="no downloadable media on this pin")


def _search_or_502(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Pinterest search failed: {e}")


def _strip_internal(res: dict) -> dict:
    """Remove internal underscore fields from results before responding."""
    for r in res.get("results", []):
        r.pop("_image_signature", None)
    return res


def _proxy_download(manifest: dict, url: str, inline: bool):
    try:
        r = downloader.stream_media(url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"media fetch failed: {e}")
    fname = downloader.guess_filename(manifest, url)
    return StreamingResponse(
        r.iter_content(chunk_size=1 << 16),
        media_type=downloader.content_type_for(url, dict(r.headers)),
        headers={
            "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{fname}"',
            "Cache-Control": "public, max-age=86400",
        },
    )


# ---------- index / health ----------

@app.get("/")
def index():
    return {
        "name": "Pinterest Media API",
        "version": "2.0.0",
        "auth": "none — public API, no key required",
        "docs": "/docs (Swagger UI)",
        "endpoints": {
            "search": "/search?q=<query>[&page_bookmark=<bookmark>][&page_size=N][&media_type=video|gif]",
            "search_videos": "/search/videos?q=<query>",
            "search_gifs": "/search/gifs?q=<query>",
            "pin_info": "/pin/{id}/info",
            "download_best": "/pin/{id}/download",
            "download_all_zip": "/pin/{id}/download/all",
            "stream_inline": "/pin/{id}/stream",
            "resolve_url": "/resolve?url=<pin url>",
        },
        "pagination": "pass next_bookmark from a response as page_bookmark param",
    }


@app.get("/health")
def health():
    return {"ok": True}


# ---------- search ----------

@app.get("/search")
def search_pins(q: str = Query(..., min_length=1, max_length=100, description="search query"),
                page_size: int = Query(25, ge=1, le=50),
                page_bookmark: str | None = Query(None, description="from previous response"),
                media_type: str | None = Query(None, description="'video' or 'gif' to filter"),
                resolve_mp4: bool = Query(False, description="fetch per-pin detail to get direct MP4 URLs for video results (slower)"),
                ):
    res = _search_or_502(searcher.search, q, "pins", page_size, page_bookmark)
    if media_type == "video":
        res["results"] = [r for r in res["results"] if r["type"] == "video"]
        res["hits"] = len(res["results"])
    elif media_type == "gif":
        res["results"] = [r for r in res["results"] if r["type"] == "gif"]
        res["hits"] = len(res["results"])
    if resolve_mp4:
        vids = [i for i, r in enumerate(res["results"]) if r["type"] == "video"]
        if vids:
            resolved = searcher.resolve_mp4s_many([res["results"][i] for i in vids])
            for i, r in zip(vids, resolved):
                res["results"][i] = r
    return _strip_internal(res)


@app.get("/search/videos")
def search_videos(q: str = Query(..., min_length=1, max_length=100),
                  page_size: int = Query(25, ge=1, le=50),
                  page_bookmark: str | None = None,
                  resolve_mp4: bool = Query(True, description="fetch per-pin detail for direct MP4 URLs"),
                  ):
    res = _search_or_502(searcher.search, q, "videos", page_size, page_bookmark)
    # the videos scope can still return image pins occasionally; filter hard
    res["results"] = [r for r in res["results"] if r["type"] == "video"]
    res["hits"] = len(res["results"])
    if resolve_mp4:
        res["results"] = searcher.resolve_mp4s_many(res["results"])
    return _strip_internal(res)


@app.get("/search/gifs")
def search_gifs(q: str = Query(..., min_length=1, max_length=100),
                page_size: int = Query(25, ge=1, le=50),
                page_bookmark: str | None = None):
    res = _search_or_502(searcher.search, q, "pins", page_size, page_bookmark)
    # Pinterest has no server-side gif filter — probe /originals/{sig}.gif
    # for each result and keep only real animated gifs.
    res["results"] = searcher.detect_gifs(res["results"])
    res["hits"] = len(res["results"])
    return _strip_internal(res)


# ---------- pin detail / download ----------

@app.get("/pin/{pin_id}/info")
def pin_info(pin_id: str):
    return _manifest_or_404(pin_id)


@app.get("/pin/{pin_id}/download")
def pin_download(pin_id: str):
    m = _manifest_or_404(pin_id)
    url = _best_media_url(m)
    return _proxy_download(m, url, inline=False)


@app.get("/pin/{pin_id}/stream")
def pin_stream(pin_id: str):
    m = _manifest_or_404(pin_id)
    url = _best_media_url(m)
    return _proxy_download(m, url, inline=True)


@app.get("/pin/{pin_id}/download/all")
def pin_download_all(pin_id: str):
    """Zip every media asset on the pin: all image sizes, videos, carousel slides."""
    m = _manifest_or_404(pin_id)
    assets: list[tuple[str, str]] = []

    for size, url in (m.get("images") or {}).items():
        assets.append((f"{m['pin_id']}_{size}{downloader.ext_of(url)}", url))
    for i, v in enumerate(m.get("videos") or []):
        assets.append((f"{m['pin_id']}_video_{i}_{v.get('variant') or 'v'}"
                       f"{downloader.ext_of(v['url'])}", v["url"]))
    for ci, slide in enumerate(m.get("carousel") or []):
        for size, url in slide.items():
            assets.append((f"{m['pin_id']}_carousel{ci}_{size}{downloader.ext_of(url)}", url))
    for v in (m.get("videos") or []):
        if v.get("thumbnail"):
            assets.append((f"{m['pin_id']}_thumb{downloader.ext_of(v['thumbnail'])}",
                           v["thumbnail"]))

    if not assets:
        raise HTTPException(status_code=404, detail="no media found")

    seen, uniq = set(), []
    for fname, url in assets:
        if url not in seen:
            seen.add(url)
            uniq.append((fname, url))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        meta = {k: v for k, v in m.items() if k not in ("videos", "carousel", "images")}
        z.writestr("_manifest.json", json.dumps(meta, indent=2))
        for fname, url in uniq:
            try:
                r = downloader.stream_media(url, timeout=30)
                z.writestr(fname, r.content)
            except Exception as e:
                z.writestr(fname + ".ERROR.txt", str(e))
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{m["pin_id"]}_all.zip"'},
    )


@app.get("/resolve")
def resolve(url: str = Query(..., description="Any pinterest pin URL")):
    pid = pin_id_from(url)
    if not pid:
        raise HTTPException(status_code=400, detail=f"not a pinterest pin URL: {url}")
    return _manifest_or_404(url)


# kept for backward compat with v1 clients
@app.get("/pin/{pin_id}/file")
def pin_save_to_server(pin_id: str):
    m = _manifest_or_404(pin_id)
    url = _best_media_url(m)
    try:
        path = downloader.save_to_dir(m, url, DOWNLOADS_DIR)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"save failed: {e}")
    return {"saved": True, "path": path, "size": os.path.getsize(path),
            "type": m["type"], "pin_id": m["pin_id"]}
