#!/usr/bin/env python3
"""Stability + latency check for the running API, aimed at unattended use.

Runs: warm-up, sequential mixed-endpoint mix, concurrent burst, and reports
latency percentiles plus a hard error list. Exit code 1 if anything failed.
"""
import json
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
QUERIES = ["cats", "nature", "sunset aesthetic", "batman dark aesthetic",
           "goku fight scenes", "aesthetic wallpaper", "cyberpunk city night"]

results = []
lock = threading.Lock()


def call(path, timeout=120):
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            body = r.read()
            ok, code = r.status == 200, r.status
    except urllib.error.HTTPError as e:
        body, ok, code = e.read(), False, e.code
    except Exception as e:
        body, ok, code = str(e).encode(), False, f"ERR {type(e).__name__}"
    ms = (time.perf_counter() - t0) * 1000
    with lock:
        results.append((path, ok, code, ms, len(body)))
    return ok, code, ms, body


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))] if xs else 0


def main():
    print("== warm-up (first call pays session + probe cost) ==")
    ok, code, ms, body = call("/search/videos?q=cooking&page_size=5")
    print(f"  /search/videos warm: {code} in {ms/1000:.1f}s ({len(body)}B)")

    print("\n== sequential mixed mix ==")
    seq = []
    for q in QUERIES:
        for path in (f"/search?q={urllib.parse.quote(q)}&page_size=10",
                     f"/search/gifs?q={urllib.parse.quote(q)}&page_size=25"):
            ok, code, ms, _ = call(path)
            seq.append(ms)
            if not ok:
                print(f"  FAIL {code}: {path}")
    print(f"  {len(seq)} calls, median {statistics.median(seq):.0f}ms, "
          f"p95 {pct(seq,0.95):.0f}ms, max {max(seq):.0f}ms")

    print("\n== concurrent burst (8 threads x 3 rounds, cold queries) ==")
    burst = []
    def worker(i, rnd):
        q = f"{QUERIES[(i+rnd) % len(QUERIES)]}"
        ok, code, ms, _ = call(f"/search?q={urllib.parse.quote(q)}&page_size=15")
        with lock:
            burst.append((ok, ms, code))
    threads = []
    for rnd in range(3):
        for i in range(8):
            t = threading.Thread(target=worker, args=(i, rnd))
            threads.append(t); t.start()
        for t in threads:
            t.join()
        threads = []
    bad = [b for b in burst if not b[0]]
    bms = [b[1] for b in burst]
    print(f"  {len(burst)} calls, median {statistics.median(bms):.0f}ms, "
          f"p95 {pct(bms,0.95):.0f}ms, errors {len(bad)}")
    for b in bad[:5]:
        print(f"    FAIL {b[2]}")

    print("\n== endpoint contract check ==")
    checks = [
        ("/health", 200),
        ("/", 200),
        ("/gallery?q=cats", 200),
        ("/session/status", 200),
        ("/search?q=cats&page_size=5", 200),
        ("/search/videos?q=cooking&page_size=5", 200),
        ("/search/gifs?q=funny+cat&page_size=25", 200),
        ("/search/suggestions?q=asthetic", 200),
        ("/pin/7810999345573240/info", 200),
        ("/pin/7810999345573240/download", 200),
        ("/download?url=https://evil.example.com/x.jpg", 400),
        ("/search?q=", 422),
        ("/pin/e1_AfqPShy50Pph1fYw8AHXYvOCsd4oe9ssdeNNgw0lGRsTTS7FIqGotA/info", 404),
    ]
    fails = 0
    for path, want in checks:
        ok, code, ms, _ = call(path)
        mark = "ok " if code == want else "FAIL"
        if code != want:
            fails += 1
        extra = "" if code in (200, 400, 404, 422) else f" ({code})"
        print(f"  {mark} {path[:62]:62s} -> {code} (want {want}) {ms:.0f}ms{extra}")

    total = len(results)
    errs = sum(1 for r in results if not r[1])
    print(f"\n== summary: {total} requests, {errs} errors ==")
    if errs or fails:
        print("RESULT: UNSTABLE")
        return 1
    print("RESULT: STABLE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())