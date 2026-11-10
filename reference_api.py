#!/usr/bin/env python3
"""
reference_api.py - the exact API shape to deploy on Render.

  GET  /app                 the Pinterest-style UI (same HTML as PINTEREST)
  GET  /                    redirects view (same UI)
  GET  /api/status          {ok, authenticated, user, auth_state, pool}
  GET  /api/feed            feed pins
  GET  /api/search?q=...    search pins
  GET  /api/pins            own pins
  GET  /api/boards          own boards
  POST /api/logout          drop local cookies (does NOT revoke the Pinterest session)

Auth is cookie-first with proxy-pool self-heal (pin_autoauth). Never expose a
password-login endpoint: `ensure_client()` logs in only when cookies are dead,
inside the guardrails. Optional API token: set API_TOKEN and send
`X-Api-Token` (or `?token=`) on /api/* calls.
"""
import os
import threading

from flask import Flask, Response, jsonify, request

from pinterest_app import HTML
import pinterest_cli as pc
import pin_autoauth as auto

app = Flask(__name__)
# RLock: with_heal() holds it while calling client(), which re-acquires it.
_lock = threading.RLock()
_client = None


def client():
    global _client
    with _lock:
        if _client is None:
            _client, how = auto.ensure_client()
            print("[api] auth ready via", how, flush=True)
        return _client


def with_heal(fn):
    with _lock:
        c = client()
        try:
            return fn(c)
        except pc.AuthError:
            if not auto.revalidate(c):
                auto.recover(c)
            return fn(c)


def _guard():
    tok = os.environ.get("API_TOKEN")
    if not tok:
        return None
    got = request.headers.get("X-Api-Token") or request.args.get("token")
    if got != tok:
        return jsonify(ok=False, error="unauthorized"), 401
    return None


def _err(e):
    return jsonify(ok=False, error=str(e)[:300]), 200


@app.get("/")
@app.get("/app")
def ui():
    return Response(HTML, mimetype="text/html")


@app.get("/api/status")
def api_status():
    g = _guard()
    if g:
        return g
    try:
        c = client()
        st = auto.AuthState()
        pool = None
        try:
            r = pc.requests.get(auto.POOL_API + "/count", timeout=4)
            pool = r.json() if r.status_code == 200 else None
        except Exception:
            pass
        return jsonify(ok=True, authenticated=bool(c.user), user=c.user,
                       auth_state=st.data, pool=pool)
    except auto.HealBlocked as e:
        return jsonify(ok=False, authenticated=False, error=str(e)), 503


@app.get("/api/feed")
def api_feed():
    g = _guard()
    if g:
        return g
    try:
        return jsonify(ok=True, pins=with_heal(lambda c: c.feed()))
    except Exception as e:
        return _err(e)


@app.get("/api/search")
def api_search():
    g = _guard()
    if g:
        return g
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify(ok=False, error="q required"), 400
    try:
        return jsonify(ok=True, query=q, pins=with_heal(lambda c: c.search(q)))
    except Exception as e:
        return _err(e)


@app.get("/api/pins")
def api_pins():
    g = _guard()
    if g:
        return g
    try:
        return jsonify(ok=True, pins=with_heal(lambda c: c.pins()))
    except Exception as e:
        return _err(e)


@app.get("/api/boards")
def api_boards():
    g = _guard()
    if g:
        return g
    try:
        return jsonify(ok=True, boards=with_heal(lambda c: c.boards()))
    except Exception as e:
        return _err(e)


@app.post("/api/logout")
def api_logout():
    g = _guard()
    if g:
        return g
    global _client
    with _lock:
        _client = None
    for p in (pc.SESSION_FILE, os.path.join(pc.DATA_DIR, "app_session.json")):
        try:
            os.remove(p)
        except Exception:
            pass
    return jsonify(ok=True)


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    print(f"[api] listening on {host}:{port}  (UI: /app)")
    app.run(host=host, port=port, threaded=True, debug=False)
