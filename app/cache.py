"""Thread-safe in-memory TTL cache. No external deps."""
from __future__ import annotations

import copy
import threading
import time


class TTLCache:
    """Simple TTL cache with a size cap and oldest-first eviction.

    get() returns None on miss or expiry; store "" (empty string) for
    negative caching — it is a hit, not a miss.
    """

    def __init__(self, max_entries: int = 4096):
        self._store: dict = {}
        self._lock = threading.Lock()
        self._max = max_entries

    def get(self, key):
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires, value = entry
            if expires < time.monotonic():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key, value, ttl: float):
        with self._lock:
            if len(self._store) >= self._max:
                oldest = min(self._store.items(), key=lambda kv: kv[1][0])[0]
                self._store.pop(oldest, None)
            self._store[key] = (time.monotonic() + ttl, value)

    def get_or_set(self, key, factory, ttl: float):
        hit = self.get(key)
        if hit is not None:
            return hit
        value = factory()
        self.set(key, value, ttl)
        return value

    def clear(self):
        with self._lock:
            self._store.clear()


def deep_copy_if(value):
    """deepcopy for cache round-trips (callers mutate returned structures)."""
    return copy.deepcopy(value)
