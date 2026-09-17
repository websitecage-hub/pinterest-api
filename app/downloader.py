"""Pinterest media downloader — fetch media bytes from pinimg CDNs with proper headers."""
from __future__ import annotations

import os
import re
import urllib.parse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

MIME_BY_EXT = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bitmap",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
    ".m3u8": "application/vnd.apple.hlsplaylist", ".vtt": "text/vtt",
}


def ext_of(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    return os.path.splitext(path)[1].lower()


def guess_filename(manifest: dict, url: str) -> str:
    """pin id + type + extension, e.g. 7810999345573240_video.mp4"""
    t = manifest.get("type") or "media"
    return f"{manifest['pin_id']}_{t}{ext_of(url) or '.bin'}"


def stream_media(url: str, timeout: int = 30):
    """Requests stream to pinimg CDN. Raises on HTTP error."""
    r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://www.pinterest.com/"},
                     stream=True, timeout=timeout)
    r.raise_for_status()
    return r


def content_type_for(url: str, resp_headers: dict) -> str:
    cd = (resp_headers.get("Content-Type") or "").split(";")[0].strip()
    if cd and cd not in ("application/octet-stream", "binary/octet-stream"):
        return cd
    return MIME_BY_EXT.get(ext_of(url), "application/octet-stream")


def save_to_dir(manifest: dict, url: str, out_dir: str) -> str:
    """Download media to out_dir, return absolute path. Skips if exists."""
    os.makedirs(out_dir, exist_ok=True)
    fname = guess_filename(manifest, url)
    path = os.path.join(out_dir, fname)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    r = stream_media(url)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 16):
            if chunk:
                f.write(chunk)
    os.replace(tmp, path)
    return path
