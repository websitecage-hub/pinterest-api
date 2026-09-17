#!/bin/bash
# End-to-end test suite for the Pinterest Media API v2 (search + pin endpoints)
set -u
BASE=http://127.0.0.1:8000
DIR=/tmp/pintest2
rm -rf "$DIR" && mkdir -p "$DIR"

echo "=== 1. health + index ==="
curl -s "$BASE/health"; echo
curl -s "$BASE/" -o "$DIR/index.json" -w "index: HTTP %{http_code}\n"

echo "=== 2. search pins ==="
curl -s "$BASE/search?q=cats&page_size=10" -o "$DIR/search.json" -w "search: HTTP %{http_code}, %{size_download} bytes\n"
python3 - <<'PY'
import json
d = json.load(open('/tmp/pintest2/search.json'))
print(f"hits: {d.get('hits')}, has_more: {d.get('has_more')}")
types = {}
for r in d.get('results', []):
    types[r['type']] = types.get(r['type'], 0) + 1
print("types:", types)
r0 = d['results'][0] if d.get('results') else {}
print("first pin:", {k: r0.get(k) for k in ('id', 'type', 'title', 'creator', 'pin_url')})
print("has best_image:", bool(r0.get('best_image')))
PY

echo "=== 3. search videos ==="
curl -s "$BASE/search/videos?q=cooking&page_size=10" -o "$DIR/videos.json" -w "videos: HTTP %{http_code}, %{size_download} bytes\n"
python3 - <<'PY'
import json
d = json.load(open('/tmp/pintest2/videos.json'))
print(f"hits: {d.get('hits')}")
if d.get('results'):
    v0 = d['results'][0]
    print("first video best_video:", (v0.get('best_video') or 'NONE')[:80])
    all_videos = all(r['type'] == 'video' for r in d['results'])
    print("all results are videos:", all_videos)
PY

echo "=== 4. search gifs ==="
curl -s "$BASE/search/gifs?q=funny+cat&page_size=25" -o "$DIR/gifs.json" -w "gifs: HTTP %{http_code}, %{size_download} bytes\n"
python3 - <<'PY'
import json
d = json.load(open('/tmp/pintest2/gifs.json'))
print(f"hits: {d.get('hits')}")
if d.get('results'):
    print("all results are gifs:", all(r['type'] == 'gif' for r in d['results']))
    print("first gif url:", (d['results'][0].get('best_image') or 'NONE')[:90])
PY

echo "=== 5. pagination ==="
python3 - <<'PY'
import json, urllib.request, urllib.parse
url = "http://127.0.0.1:8000/search?q=cats&page_size=5"
with urllib.request.urlopen(url, timeout=30) as r:
    p1 = json.load(r)
bm = p1.get("next_bookmark")
print("page1 hits:", p1["hits"], "bookmark:", (bm or "NONE")[:40])
if bm:
    u2 = "http://127.0.0.1:8000/search?q=cats&page_size=5&page_bookmark=" + urllib.parse.quote(bm, safe="")
    with urllib.request.urlopen(u2, timeout=30) as r:
        p2 = json.load(r)
    ids1 = {x["id"] for x in p1["results"]}
    ids2 = {x["id"] for x in p2["results"]}
    print("page2 hits:", p2["hits"])
    print("overlap between pages:", len(ids1 & ids2), "(should be 0)")
PY

echo "=== 6. pin endpoints (regression) ==="
curl -s "$BASE/pin/369858188161092508/download" -o "$DIR/img.jpg" -w "image dl: HTTP %{http_code}, %{size_download} bytes\n"
curl -s "$BASE/pin/7810999345573240/download" -o "$DIR/vid.mp4" -w "video dl: HTTP %{http_code}, %{size_download} bytes\n"
file "$DIR/img.jpg" "$DIR/vid.mp4" | cut -c1-95

echo "=== 7. search->download integration ==="
python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:8000/search?q=cats&page_size=10", timeout=30) as r:
    d = json.load(r)
pin_id = d["results"][0]["id"]
url = f"http://127.0.0.1:8000/pin/{pin_id}/download"
with urllib.request.urlopen(url, timeout=60) as r:
    data = r.read()
print(f"downloaded search-result pin {pin_id}: {len(data)} bytes, "
      f"content-type: {r.headers.get('content-type')}")
PY

echo
echo "=== summary ==="
ls -la "$DIR" | awk '{print $5, $9}' | tail -n +2
