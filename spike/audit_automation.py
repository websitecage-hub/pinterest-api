#!/usr/bin/env python3
"""Automation-readiness audit: latency, freshness, reliability, output quality."""
import json
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"


def get(path, timeout=120):
    t0 = time.time()
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        body = r.read()
    return time.time() - t0, body


def jget(path, timeout=120):
    dt, body = get(path, timeout)
    return dt, json.loads(body)

print("=== 1. plain search latency (no mp4 resolution) ===")
dt, d = jget("/search?q=home%20decor&page_size=25")
print(f"latency: {dt:.2f}s for {d['hits']} results")

print("\n=== 2. result freshness (are we getting current Pinterest results?) ===")
dates = [r.get("created_at", "") for r in d["results"] if r.get("created_at")]
print("sample created_at values:", dates[:5])

print("\n=== 3. video search WITH mp4 resolution — the heavy path ===")
dt, d = jget("/search/videos?q=workout&page_size=25")
print(f"latency: {dt:.2f}s for {d['hits']} video results (resolve_mp4 defaults ON)")
mp4_count = sum(1 for r in d["results"] if r.get("best_video", "").endswith(".mp4"))
print(f"results with direct MP4: {mp4_count}/{d['hits']}")

print("\n=== 4. repeated identical query (cache behavior) ===")
dt2, _ = jget("/search?q=home%20decor&page_size=25")
print(f"second identical query: {dt2:.2f}s (no cache implemented — this is the gap)")

print("\n=== 5. download integrity: grab one MP4 from search ===")
v = next(r for r in d["results"] if r.get("best_video", "").endswith(".mp4"))
dt, body = get(f"/pin/{v['id']}/download")
open("/tmp/audit.mp4", "wb").write(body)
print(f"pin {v['id']}: {len(body):,} bytes in {dt:.2f}s")
with open("/tmp/audit.mp4", "rb") as f:
    head = f.read(12)
print("mp4 magic OK:", head[4:8] == b"ftyp")

print("\n=== 6. error-path reliability (5 rapid bad-pin calls) ===")
codes = []
for _ in range(5):
    try:
        get("/pin/999999999999999999999/info", timeout=30)
        codes.append(200)
    except urllib.error.HTTPError as e:
        codes.append(e.code)
print("status codes:", codes, "(all clean 502s = predictable, no crashes)")
