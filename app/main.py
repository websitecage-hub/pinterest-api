"""Pinterest media API — reverse-engineered unauth endpoints.

Endpoints:
  GET /                        -> API index (endpoint list)
  GET /health                  -> liveness
  GET /pin/{id}/info           -> full media manifest (images, videos, carousel, metadata)
  GET /pin/{id}/download       -> proxy-download best media (image/video/gif) as attachment
  GET /pin/{id}/download/all   -> zip of every media asset (all sizes + videos + carousel)
  GET /pin/{id}/stream         -> inline stream (for <img>/<video> embedding)
  GET /pin/{id}/file           -> save server-side to ./downloads, return path
  GET /resolve?url=...         -> parse any pinterest pin URL -> pin id + manifest
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import zipfile

# allow "python -m uvicorn app.main:app" from the project root:
# ensure sibling modules (extractor, downloader) are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

import downloader
from extractor import get_pin, pin_id_from

app = FastAPI(title="Pinterest Media API", version="1.0.0",
              description="Download images, videos, GIFs from any Pinterest pin. "
                          "Reverse-engineered from unauth SSR; no API key needed.")

DOWNLOADS_DIR = os.environ.get("PINTEREST_DOWNLOADS", "/root/pinterest-api/downloads")


def _manifest_or_404(target: str) -> dict:
    try:
        return get_pin(target)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Pinterest fetch failed: {e}")


def _best_media_url(manifest: dict) -> str:
    if manifest["type"] in ("video",) and manifest.get("best_video"):
        return manifest["best_video"]
    if manifest.get("carousel"):
        raise HTTPException(status_code=415,
                            detail="carousel pin: use /download/all or pick slide from info.carousel")
    if manifest.get("best_image"):
        return manifest["best_image"]
    raise HTTPException(status_code=404, detail="no downloadable media on this pin")


@app.get("/")
def index():
    return {
        "service": "Pinterest Media API",
        "endpoints": {
            "health": "/health",
            "pin_info": "/pin/{id}/info",
            "download_best": "/pin/{id}/download",
            "download_all_zip": "/pin/{id}/download/all",
            "stream_inline": "/pin/{id}/stream",
            "save_to_server": "/pin/{id}/file",
            "resolve_url": "/resolve?url=<pin url>",
        },
        "note": "id can be the numeric pin id or any full pin URL",
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/pin/{pin_id}/info")
def pin_info(pin_id: str):
    return _manifest_or_404(pin_id)


@app.get("/resolve")
def resolve(url: str = Query(..., description="Any pinterest pin URL")):
    pid = pin_id_from(url)
    if not pid:
        raise HTTPException(status_code=400, detail=f"not a pinterest pin URL: {url}")
    return _manifest_or_404(url)


def _proxy_download(manifest: dict, url: str, inline: bool):
    try:
        r = downloader.stream_media(url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"media fetch failed: {e}")
    fname = downloader.guess_filename(manifest, url)
    headers = {
        "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{fname}"',
        "Cache-Control": "public, max-age=86400",
    }
    return StreamingResponse(
        r.iter_content(chunk_size=1 << 16),
        media_type=downloader.content_type_for(url, dict(r.headers)),
        headers=headers,
    )


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


@app.get("/pin/{pin_id}/download/all")
def pin_download_all(pin_id: str):
    """Zip every media asset on the pin: all image sizes, videos, carousel slides."""
    m = _manifest_or_404(pin_id)
    assets: list[tuple[str, str]] = []  # (filename, url)

    for size, url in (m.get("images") or {}).items():
        assets.append((f"{m['pin_id']}_{size}{downloader.ext_of(url)}", url))
    for i, v in enumerate(m.get("videos") or []):
        assets.append((f"{m['pin_id']}_video_{i}_{v.get('variant') or 'v'}"
                       f"{downloader.ext_of(v['url'])}", v["url"]))
    for ci, slide in enumerate(m.get("carousel") or []):
        for size, url in slide.items():
            assets.append((f"{m['pin_id']}_carousel{ci}_{size}{downloader.ext_of(url)}", url))
    # thumbnails from video variants
    for v in (m.get("videos") or []):
        if v.get("thumbnail"):
            assets.append((f"{m['pin_id']}_thumb{downloader.ext_of(v['thumbnail'])}",
                           v["thumbnail"]))

    if not assets:
        raise HTTPException(status_code=404, detail="no media found")

    # dedupe by filename
    seen, uniq = set(), []
    for fname, url in assets:
        if url not in seen:
            seen.add(url)
            uniq.append((fname, url))
    assets = uniq

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        meta = {k: v for k, v in m.items() if k not in ("videos", "carousel", "images")}
        z.writestr("_manifest.json", json.dumps(meta, indent=2))
        for fname, url in assets:
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


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"run: .venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port {port}")
