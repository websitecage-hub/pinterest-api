"""Email/password Pinterest login -> cookie header, for personalized mode.

This wraps the request-based client in ``pinterest_cli.py`` (Arkose solver +
BypassV3) so the API can mint its own session instead of relying on a
hand-pasted browser cookie. It is entirely optional:

  * configure ``PINTEREST_EMAIL`` + ``PINTEREST_PASSWORD`` (or PIN_EMAIL /
    PIN_PASSWORD) and the API logs in on startup, in the background;
  * when a login succeeds the cookie is handed to ``searcher`` exactly like a
    static PINTEREST_COOKIE, so the public API surface does not change;
  * if no credentials are configured, or the login fails, the API keeps
    serving the anonymous surface (never an error).

Login is deliberately non-blocking: a cold Arkose solve can take ~60s, so it
runs in a daemon thread and searches before it finishes simply go anonymous.
The next request after the cookie lands picks it up through searcher's normal
cookie hot-reload path.
"""
from __future__ import annotations

import os
import sys
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_lock = threading.Lock()
_cookie = None            # cached cookie header string
_user = None              # last logged-in user dict
_error = None             # last failure (string)
_attempt_at = 0.0         # unix time of last attempt
_in_flight = False
_attempts = 0
_ok_at = None

# Don't hammer the login flow if it is failing (e.g. captcha provider outage).
_RETRY_COOLDOWN = 300.0


def credentials() -> tuple[str | None, str | None]:
    email = os.environ.get("PINTEREST_EMAIL") or os.environ.get("PIN_EMAIL")
    password = os.environ.get("PINTEREST_PASSWORD") or os.environ.get("PIN_PASSWORD")
    return (email or None, password or None)


def enabled() -> bool:
    email, password = credentials()
    return bool(email and password)


def get_cookie():
    """The cached cookie, or None. Never blocks, never triggers a login."""
    return _cookie


def status() -> dict:
    return {
        "enabled": enabled(),
        "cookie_ready": bool(_cookie),
        "authenticated_as": (_user or {}).get("username") if _user else None,
        "attempts": _attempts,
        "in_flight": _in_flight,
        "last_error": _error,
        "last_success_ago_s": (round(time.time() - _ok_at) if _ok_at else None),
    }


def _persist(cookie: str) -> bool:
    """Write the cookie to PINTEREST_COOKIE_FILE when configured (survives
    restarts on hosts with a mounted disk). Returns True when written."""
    path = os.environ.get("PINTEREST_COOKIE_FILE")
    if not path:
        return False
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(cookie)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def _do_login() -> bool:
    """Perform one login. Caller holds the lock. Returns True on success."""
    global _cookie, _user, _error, _attempt_at, _in_flight, _attempts, _ok_at
    email, password = credentials()
    if not (email and password):
        return False
    _attempt_at = time.time()
    _attempts += 1
    _in_flight = True
    try:
        from pinterest_cli import Pinterest
        client = Pinterest()
        # Reuse a saved session file when one exists (fast path); otherwise a
        # full login (Arkose + reCAPTCHA) runs.
        if not client.load():
            client.login(email, password)
        cookie = client.cookie_header()
        if not cookie or "_pinterest_sess" not in cookie:
            raise RuntimeError("login produced no session cookie")
        _cookie = cookie
        _user = client.user or {}
        _error = None
        _ok_at = time.time()
        _persist(cookie)
        return True
    except Exception as e:  # noqa: BLE001 - report, never crash the API
        _error = f"{type(e).__name__}: {e}"[:300]
        return False
    finally:
        _in_flight = False


def login_now() -> dict:
    """Blocking login (used by the admin endpoint). Returns status()."""
    with _lock:
        _do_login()
    return status()


def start_background(force: bool = False) -> bool:
    """Kick off a login in a daemon thread unless one is already running.

    Returns True when a thread was started. Respects the retry cooldown after
    a failure so repeated requests cannot spin the captcha solver.
    """
    global _in_flight
    if not enabled():
        return False
    with _lock:
        if _in_flight:
            return False
        if not force and _error and (time.time() - _attempt_at) < _RETRY_COOLDOWN:
            return False
        if not force and _cookie:
            return False
        _in_flight = True  # reserve before spawning; _do_login sets it too

    def run():
        global _in_flight
        with _lock:
            _do_login()

    t = threading.Thread(target=run, name="pinterest-login", daemon=True)
    t.start()
    return True


def invalidate() -> None:
    """Drop the cached cookie so the next check can re-login."""
    global _cookie, _user
    with _lock:
        _cookie = None
        _user = None
