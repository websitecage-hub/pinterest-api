#!/usr/bin/env python3
"""Unit-check the HLS->MP4 ladder cache in app/searcher.py.

Proves three things without touching the network twice:
  1. a sig with an MP4 resolves to its best tier, and the second call is a
     cache hit (no HEAD requests),
  2. an HLS-only sig returns "" and is negative-cached (second call instant),
  3. the derivch function reports best-tier-first and skips HLS-only assets.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import searcher  # noqa: E402

GOOD = "48ae55f448c111db2692b41aac856c18"   # /videos/mc/720p/... exists
ONLY_HLS = "0ae0f76e53795eee727e1d39b861a4f1"  # matrix probe found no .mp4 anywhere


def timed(fn, *a):
    t0 = time.perf_counter()
    out = fn(*a)
    return out, round((time.perf_counter() - t0) * 1000)


tier1, ms1 = timed(searcher._mp4_tier_for_sig, GOOD)
tier2, ms2 = timed(searcher._mp4_tier_for_sig, GOOD)
print(f"good sig:      first={tier1!r} in {ms1}ms | second={tier2!r} in {ms2}ms")

hls1, hms1 = timed(searcher._mp4_tier_for_sig, ONLY_HLS)
hls2, hms2 = timed(searcher._mp4_tier_for_sig, ONLY_HLS)
print(f"hls-only sig:  first={hls1!r} in {hms1}ms | second={hls2!r} in {hms2}ms")

sigs = {searcher._hls_sig(f"https://v1.pinimg.com/videos/iht/hls/48/ae/55/{GOOD}.m3u8"): GOOD,
        searcher._hls_sig(f"https://v1.pinimg.com/videos/iht/hls/0a/e0/f7/{ONLY_HLS}.m3u8"): ONLY_HLS}
print("sig extraction:", sigs)

derived = searcher._derive_mp4s_from_hls(
    [{"url": f"https://v1.pinimg.com/videos/iht/hls/48/ae/55/{GOOD}.m3u8", "width": 720, "height": 1280},
     {"url": f"https://v1.pinimg.com/videos/iht/hls/0a/e0/f7/{ONLY_HLS}.m3u8", "width": 720, "height": 1280}])
print("derived:", derived)

assert tier1 == tier2 == "720p", "good sig should cache to 720p"
assert ms2 < ms1, "second call should be a cache hit"
assert hls1 == hls2 == "", "hls-only sig should be empty"
assert hms2 < hms1, "negative result should be cached"
assert len(derived) == 1 and derived[0]["variant"] == "720p", "HLS-only asset must be skipped"
assert not searcher._is_opaque_id("7810999345573240"), "numeric id must not be opaque"
assert searcher._is_opaque_id("e1_AfqPShy50Pph1fYw8AHXYvOCsd4oe9ssdeNNgw0lGRsTTS7FIqGotA")
print("\nALL ASSERTIONS PASSED")