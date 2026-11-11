"""
Pinterest Console - a local web app for your own account.

Login is fully request-based:
  * Arkose (okra)      -> local funcaptcha solver (:8003, auto-started)
  * reCAPTCHA v3 Ent.  -> BypassV3 (anchor + protobuf reload)
  * Session            -> curl_cffi cookies, persisted to app_session.json

Run:  python pinterest_app.py   ->  http://127.0.0.1:5000
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse

from curl_cffi import requests
from flask import Flask, Response, jsonify, request

BASE = "https://in.pinterest.com"
SITEKEY = "F5675B21-025B-4843-983C-38D86DEB394B"
RC_KEY = "6Ldx7ZkUAAAAAF3SZ05DRL2Kdh911tCa3qFP0-0r"
RC_ACTION = "login"
SOLVER = "http://127.0.0.1:8003"
SOLVER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "funcaptcha-solver")
UA = ("Mozilla/5.0 (Linux; Android 16; Pixel 10) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/156.0.0.0 Mobile Safari/537.36")
SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_session.json")
FALLBACK_SESSION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pin_session_requests.json")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "BypassV3"))
try:
    from bypass import ReCaptchaV3Bypass
except Exception as e:  # pragma: no cover
    ReCaptchaV3Bypass = None
    print("[!] BypassV3 import failed:", e)


# ---------------------------------------------------------------- solver
_solver_lock = threading.Lock()
_solver_started = False


def solver_up():
    try:
        with socket.create_connection(("127.0.0.1", 8003), timeout=1):
            return True
    except OSError:
        return False


def ensure_solver():
    global _solver_started
    if solver_up():
        return True
    with _solver_lock:
        if solver_up():
            return True
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        try:
            subprocess.Popen([sys.executable, "main.py"], cwd=SOLVER_DIR,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=flags)
            _solver_started = True
        except Exception as e:
            print("[!] cannot start solver:", e)
            return False
        deadline = time.time() + 120
        while time.time() < deadline:
            if solver_up():
                return True
            time.sleep(2)
    return solver_up()


# ---------------------------------------------------------------- client
class AuthError(Exception):
    pass


IMPERSONATIONS = ["chrome131", "chrome124", "chrome123", "chrome120"]


class PinterestClient:
    def __init__(self):
        self.session = None
        self.user = None
        self.authenticated = False
        self.lock = threading.Lock()
        self.impersonate = IMPERSONATIONS[0]

    # -- persistence -------------------------------------------------
    def _dump_cookies(self):
        out = []
        jar = getattr(self.session.cookies, "jar", None)
        if jar is not None:
            for c in jar:
                out.append({"name": c.name, "value": c.value,
                            "domain": c.domain, "path": c.path or "/"})
        else:
            for k, v in self.session.cookies.get_dict().items():
                out.append({"name": k, "value": v,
                            "domain": ".pinterest.com", "path": "/"})
        return out

    def save(self, email=None):
        data = {"cookies": self._dump_cookies(), "user": self.user,
                "email": email or (self.user or {}).get("email")}
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load(self):
        for path in (SESSION_FILE, FALLBACK_SESSION):
            if not os.path.exists(path):
                continue
            try:
                data = json.load(open(path, encoding="utf-8"))
            except Exception:
                continue
            s = requests.Session(impersonate="chrome131")
            s.headers.update({"user-agent": UA,
                              "accept-language": "en-IN,en-US;q=0.9,en;q=0.8"})
            for c in data.get("cookies", []):
                try:
                    s.cookies.set(c["name"], c["value"],
                                  domain=c.get("domain") or ".pinterest.com",
                                  path=c.get("path") or "/")
                except Exception:
                    pass
            # also handle dict-style cookie files
            if isinstance(data.get("cookies"), dict):
                for k, v in data["cookies"].items():
                    s.cookies.set(k, v, domain=".pinterest.com")
            self.session = s
            self.user = data.get("user")
            if self._probe():
                self.authenticated = True
                self.user = self._whoami() or self.user
                return True
        self.session = None
        self.user = None
        return False

    # -- low level ---------------------------------------------------
    def _new_session(self, impersonate=None):
        self.impersonate = impersonate or self.impersonate or IMPERSONATIONS[0]
        s = requests.Session(impersonate=self.impersonate)
        s.headers.update({"user-agent": UA,
                          "accept-language": "en-IN,en-US;q=0.9,en;q=0.8"})
        return s

    def _rebuild(self):
        """Fresh connection + fresh TLS session, same cookies."""
        cookies = self._dump_cookies()
        s = self._new_session()
        for c in cookies:
            try:
                s.cookies.set(c["name"], c["value"],
                              domain=c.get("domain") or ".pinterest.com",
                              path=c.get("path") or "/")
            except Exception:
                pass
        self.session = s
        return s

    def _raw(self, method, url, timeout=30, retries=5, **kw):
        """curl calls with retries on TLS resets / dropped keep-alive sockets."""
        last = None
        for i in range(retries):
            try:
                if self.session is None:
                    self.session = self._new_session()
                r = self.session.request(method, url, timeout=timeout, **kw)
                if r.status_code in (429, 500, 502, 503, 504) and i < retries - 1:
                    time.sleep(1.0 + 1.2 * i)
                    continue
                return r
            except AuthError:
                raise
            except Exception as e:
                last = e
                time.sleep(0.5 + 0.7 * i)
                try:
                    self._rebuild()
                except Exception:
                    pass
        raise last

    def _hdr(self, source_url="/", handler=None):
        csrf = self.session.cookies.get("csrftoken") if self.session else None
        h = {
            "accept": "application/json, text/javascript, */*, q=0.01",
            "content-type": "application/x-www-form-urlencoded",
            "x-csrftoken": csrf or "",
            "x-requested-with": "XMLHttpRequest",
            "x-pinterest-appstate": "active",
            "x-pinterest-source-url": source_url,
            "x-app-version": "7eb5076",
            "origin": BASE,
            "referer": BASE + "/",
        }
        if handler:
            h["x-pinterest-pws-handler"] = handler
        return h

    def _post(self, path, options, source_url="/", handler=None):
        body = urllib.parse.urlencode({
            "source_url": source_url,
            "data": json.dumps({"options": options, "context": {}},
                               separators=(",", ":")),
        })
        r = self._raw("POST", BASE + "/resource/" + path,
                      headers=self._hdr(source_url, handler),
                      data=body, timeout=30, retries=6)
        if r.status_code in (401, 403):
            self.authenticated = False
            raise AuthError("session is no longer authorized")
        return r

    def _probe(self):
        try:
            r = self._post("UserSettingsResource/get/", {}, "/")
            return r.status_code == 200 and r.json().get("resource_response", {}).get("status") == "success"
        except Exception:
            return False

    def _whoami(self):
        try:
            r = self._post("UserSettingsResource/get/", {}, "/")
            d = r.json()["resource_response"].get("data") or {}
            if not d:
                return None
            name = " ".join(x for x in [d.get("first_name"), d.get("last_name")] if x).strip()
            return {
                "username": d.get("username"),
                "full_name": name or d.get("username"),
                "email": d.get("email"),
                "id": d.get("id"),
                "country": d.get("country"),
                "gender": d.get("gender"),
                "age": d.get("age"),
                "about": d.get("about"),
                "image": None,
            }
        except Exception:
            return None

    # -- login -------------------------------------------------------
    def _arkose(self):
        r = self._raw("GET", BASE + "/secure/arkose_data_exchange/",
                      headers={"x-csrftoken": self.session.cookies.get("csrftoken") or "",
                               "referer": BASE + "/"}, timeout=30)
        blob = r.json()["blob"]
        t = requests.post(SOLVER + "/funcaptcha/createTask",
                          json={"preset": "pinterest_login", "blob": blob}, timeout=30).json()
        for _ in range(90):
            g = requests.post(SOLVER + "/funcaptcha/getTask",
                              json={"task_id": t["task_id"]}, timeout=30).json()
            if g.get("status") == "completed":
                return (g.get("captcha") or {}).get("token")
            time.sleep(1)
        return None

    def _recaptcha(self):
        if ReCaptchaV3Bypass is None:
            return None
        return ReCaptchaV3Bypass.from_site_key(
            RC_KEY, origin=BASE, action=RC_ACTION, enterprise=True,
            user_agent=UA).bypass()

    def login(self, email, password):
        with self.lock:
            if not ensure_solver():
                return {"ok": False, "error": "Arkose solver did not start on :8003"}

            old_session, old_auth, old_user = self.session, self.authenticated, self.user
            self.session = self._new_session()
            self.authenticated = False

            try:
                r = self._raw("GET", BASE + "/login/", timeout=30, retries=5)
                csrf = self.session.cookies.get("csrftoken")
                for _ in range(3):
                    if csrf:
                        break
                    time.sleep(1.5)
                    self._raw("GET", BASE + "/login/", timeout=30, retries=3)
                    csrf = self.session.cookies.get("csrftoken")
                if not csrf:
                    raise RuntimeError("could not get csrftoken from /login/")

                ark = self._arkose()
                if not ark:
                    raise RuntimeError("Arkose token failed (solver :8003)")

                rec = self._recaptcha()
                if not rec:
                    raise RuntimeError("reCAPTCHA token failed (BypassV3)")

                data = {"options": {
                    "get_user": True,
                    "username_or_email": email,
                    "password": password,
                    "app_type_from_client": 6,
                    "ui_component": "MobileLoginPage.LoginFormClassComponent",
                    "handler": "www/login.js",
                    "visited_pages_before_login": json.dumps(
                        [{"path": "/login/", "pageType": "", "ts": int(time.time() * 1000)}]),
                    "arkoseSessionToken": ark,
                    "recaptchaV3Token": rec,
                }, "context": {}}
                hdr = self._hdr("/login/", "www/login.js")
                hdr["x-pinterest-source-url"] = "/login/"
                body = urllib.parse.urlencode({"source_url": "/login/", "data": json.dumps(data)})

                rr = {}
                for _ in range(3):
                    r = self._raw("POST", BASE + "/resource/UserSessionResource/create/",
                                  headers=hdr, data=body, timeout=30, retries=4)
                    try:
                        rr = r.json().get("resource_response", {})
                    except Exception:
                        rr = {}
                    if rr.get("status") == "success":
                        self.authenticated = True
                        self.user = self._whoami() or rr.get("data", {}).get("user")
                        if self.user and not self.user.get("email"):
                            self.user["email"] = email
                        self.save(email)
                        return {"ok": True, "user": self.user}
                    if r.status_code == 429 or rr.get("status") == "error":
                        time.sleep(4)
                        continue
                    break
                msg = rr.get("error", {}) if isinstance(rr.get("error"), dict) else {}
                raise RuntimeError(msg.get("message") or "login rejected by Pinterest")

            except Exception as e:
                self.session, self.authenticated, self.user = old_session, old_auth, old_user
                return {"ok": False, "error": str(e)[:200]}

    # -- data --------------------------------------------------------
    @staticmethod
    def _img(imgs):
        if not isinstance(imgs, dict):
            return None
        for k in ("orig", "736x", "474x", "236x", "170x"):
            v = imgs.get(k)
            if isinstance(v, dict) and v.get("url"):
                return v["url"]
        for v in imgs.values():
            if isinstance(v, dict) and v.get("url"):
                return v["url"]
        return None

    def _norm_pin(self, it):
        p = it
        if not p.get("images"):
            p = it.get("pin") or (it.get("aggregatedpindata") or {}).get("pin") or it
        pid = p.get("id")
        board = p.get("board")
        return {
            "id": pid,
            "title": p.get("grid_title") or p.get("title") or "",
            "description": p.get("description") or "",
            "image": self._img(p.get("images")),
            "link": p.get("link") or p.get("domain") or "",
            "domain": p.get("domain") or "",
            "pin_url": f"https://www.pinterest.com/pin/{pid}/" if pid else "",
            "is_video": bool(p.get("is_video")),
            "board": board.get("name") if isinstance(board, dict) else "",
        }

    def feed(self):
        r = self._post("UserHomefeedResource/get/",
                       {"field_set_key": "mobile_grid_item",
                        "first_page_size": 25, "page_size": 15}, "/")
        items = r.json()["resource_response"].get("data") or []
        return [self._norm_pin(x) for x in items if x.get("type") == "pin"][:40]

    def search(self, q):
        r = self._post("BaseSearchResource/get/",
                       {"query": q, "scope": "pins"},
                       f"/search/pins/?q={urllib.parse.quote(q)}")
        res = r.json()["resource_response"].get("data", {}).get("results") or []
        return [self._norm_pin(x) for x in res if x.get("type") == "pin"][:40]

    def my_pins(self):
        fields = ("pin.id,pin.images[236x,474x,orig],pin.grid_title,pin.title,"
                  "pin.description,pin.link,pin.domain,pin.is_video,pin.board(),"
                  "aggregatedpindata.id")
        r = self._post("ApiResource/get/",
                       {"url": "/v3/users/me/filtered/pins/",
                        "data": {"flag_filters": "", "fields": fields}},
                       "/me/pins/", "www/[username]/pins.js")
        data = r.json()["resource_response"].get("data") or []
        return [self._norm_pin(x) for x in data][:40]

    def boards(self):
        fields = "id,name,url,image_thumbnail_url,privacy,pin_count,description"
        r = self._post("ApiResource/get/",
                       {"url": "/v3/users/me/boards/", "data": {"fields": fields}},
                       "/me/boards/", "www/[username]/boards.js")
        data = r.json()["resource_response"].get("data") or []
        out = []
        for b in data:
            out.append({"id": b.get("id"), "name": b.get("name"),
                        "pin_count": b.get("pin_count") or 0,
                        "image": b.get("image_thumbnail_url"),
                        "url": "https://www.pinterest.com" + (b.get("url") or "")})
        return out


# ---------------------------------------------------------------- app
app = Flask(__name__)
client = PinterestClient()
booted = False
boot_lock = threading.Lock()


def boot():
    global booted
    if booted:
        return
    with boot_lock:
        if booted:
            return
        client.load()
        booted = True


@app.before_request
def _boot():
    boot()


def _json_ok(**kw):
    return jsonify({"ok": True, **kw})


def _json_err(msg):
    m = str(msg or "request failed")
    low = m.lower()
    if "reset your password" in low:
        m = ("Pinterest force-reset this account (risk control). The password and all "
             "sessions are invalid. Reset via email, or sign in and reuse the session.")
    elif "curl: (35)" in m or "connection was reset" in low or "recv failure" in low:
        m = "Pinterest dropped the connection. It was retried — reload the tab."
    elif "curl: (28)" in m or "timed out" in low:
        m = "Pinterest timed out. Try again."
    elif "curl: (56)" in m or "connection reset by peer" in low:
        m = "Connection closed by Pinterest. Try again."
    return jsonify({"ok": False, "error": m[:200]}), 200


@app.get("/")
@app.get("/app")
def index():
    return Response(HTML, mimetype="text/html")


@app.get("/api/status")
def api_status():
    user = client.user if client.authenticated else None
    return _json_ok(authenticated=client.authenticated, user=user)


@app.post("/api/logout")
def api_logout():
    client.session = None
    client.user = None
    client.authenticated = False
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception:
        pass
    return _json_ok()


def _guard(fn):
    def inner():
        if not client.authenticated:
            return jsonify({"ok": False, "error": "not_authenticated", "auth": False}), 401
        try:
            with client.lock:
                data = fn()
            return _json_ok(**({"boards": data} if isinstance(data, list) and data and "name" in data[0] else {"pins": data}))
        except Exception as e:
            return _json_err(str(e)[:200])
    inner.__name__ = fn.__name__
    return inner


@app.get("/api/feed")
def api_feed():
    if not client.authenticated:
        return jsonify({"ok": False, "auth": False}), 401
    try:
        with client.lock:
            pins = client.feed()
        return _json_ok(pins=pins)
    except Exception as e:
        return _json_err(str(e)[:200])


@app.get("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return _json_ok(pins=[])
    if not client.authenticated:
        return jsonify({"ok": False, "auth": False}), 401
    try:
        with client.lock:
            pins = client.search(q)
        return _json_ok(pins=pins)
    except Exception as e:
        return _json_err(str(e)[:200])


@app.get("/api/pins")
def api_pins():
    if not client.authenticated:
        return jsonify({"ok": False, "auth": False}), 401
    try:
        with client.lock:
            pins = client.my_pins()
        return _json_ok(pins=pins)
    except Exception as e:
        return _json_err(str(e)[:200])


@app.get("/api/boards")
def api_boards():
    if not client.authenticated:
        return jsonify({"ok": False, "auth": False}), 401
    try:
        with client.lock:
            boards = client.boards()
        return _json_ok(boards=boards)
    except Exception as e:
        return _json_err(str(e)[:200])


# ---------------------------------------------------------------- HTML
HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pinterest Console</title>
<style>
:root{--bg:#0b0b0d;--panel:#151518;--panel2:#1c1c20;--line:#2a2a2f;--txt:#f2f2f3;--mut:#9a9aa2;--accent:#e60023;--radius:16px}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--txt);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
button{font-family:inherit}
.hidden{display:none!important}
header{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:18px;padding:14px 26px;background:rgba(11,11,13,.82);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;letter-spacing:.2px}
.dot{width:26px;height:26px;border-radius:50%;background:var(--accent);display:grid;place-items:center;font-size:13px;color:#fff}
.search{flex:1;max-width:560px;display:flex;align-items:center;gap:10px;background:var(--panel2);border:1px solid var(--line);border-radius:999px;padding:9px 16px}
.search input{flex:1;background:transparent;border:0;outline:0;color:var(--txt);font-size:14px}
.search input::placeholder{color:var(--mut)}
.acct{display:flex;align-items:center;gap:10px;margin-left:auto}
.avatar{width:34px;height:34px;border-radius:50%;background:linear-gradient(135deg,#e60023,#7a0012);display:grid;place-items:center;font-weight:700;font-size:14px;text-transform:uppercase}
.acct small{color:var(--mut);display:block;font-size:11px}
.btn{border:1px solid var(--line);background:var(--panel2);color:var(--txt);padding:9px 14px;border-radius:999px;cursor:pointer;font-size:13px;transition:.15s}
.btn:hover{border-color:#444;background:#242429}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.btn.primary:hover{filter:brightness(1.1)}
.btn:disabled{opacity:.55;cursor:default}
main{padding:26px;max-width:1600px;margin:0 auto}
/* login */
.login-wrap{min-height:calc(100vh - 62px);display:grid;place-items:center;padding:24px}
.card{width:100%;max-width:420px;background:var(--panel);border:1px solid var(--line);border-radius:22px;padding:34px;box-shadow:0 30px 80px rgba(0,0,0,.45)}
.card h1{margin:0 0 6px;font-size:26px}
.card p.sub{margin:0 0 26px;color:var(--mut);font-size:14px;line-height:1.5}
.field{margin-bottom:14px}
.field label{display:block;font-size:12px;color:var(--mut);margin-bottom:7px;letter-spacing:.3px}
.field input{width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--txt);border-radius:12px;padding:13px 14px;font-size:14px;outline:0}
.field input:focus{border-color:var(--accent)}
.note{font-size:12px;color:var(--mut);margin-top:16px;line-height:1.5}
.err{color:#ff6b7a;font-size:13px;min-height:18px;margin-top:10px}
.spin{width:15px;height:15px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;display:inline-block;animation:sp .7s linear infinite;vertical-align:-3px;margin-right:8px}
@keyframes sp{to{transform:rotate(360deg)}}
/* profile */
.profile{display:flex;align-items:center;gap:18px;padding:22px;border:1px solid var(--line);border-radius:var(--radius);background:linear-gradient(180deg,#17171b,#121214);margin-bottom:22px}
.profile .big{width:64px;height:64px;border-radius:50%;background:linear-gradient(135deg,#e60023,#7a0012);display:grid;place-items:center;font-size:24px;font-weight:800}
.profile h2{margin:0 0 3px;font-size:20px}
.profile .meta{color:var(--mut);font-size:13px}
.stats{display:flex;gap:22px;margin-left:auto;text-align:right}
.stats b{display:block;font-size:20px}
.stats span{font-size:11px;color:var(--mut);letter-spacing:.4px;text-transform:uppercase}
.tabs{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.tab{border:1px solid var(--line);background:transparent;color:var(--mut);padding:9px 16px;border-radius:999px;cursor:pointer;font-size:13px}
.tab.active{background:var(--txt);color:#111;border-color:var(--txt);font-weight:600}
/* grid */
.grid{columns:5;column-gap:16px}
@media(max-width:1400px){.grid{columns:4}}
@media(max-width:1050px){.grid{columns:3}}
@media(max-width:720px){.grid{columns:2}}
.pin{break-inside:avoid;margin-bottom:16px;border-radius:14px;overflow:hidden;background:var(--panel);position:relative;cursor:pointer;border:1px solid var(--line);transition:transform .16s,border-color .16s}
.pin:hover{transform:translateY(-2px);border-color:#3a3a41}
.pin img{width:100%;display:block;background:#202024;min-height:60px}
.pin .ov{position:absolute;inset:auto 0 0 0;padding:26px 14px 12px;background:linear-gradient(transparent,rgba(0,0,0,.86));opacity:0;transition:.16s}
.pin:hover .ov{opacity:1}
.pin .ov h3{font-size:13px;margin:0 0 3px;line-height:1.3;font-weight:600}
.pin .ov span{font-size:11px;color:#cfcfd4}
.tag{position:absolute;top:10px;left:10px;background:rgba(0,0,0,.66);padding:3px 8px;border-radius:999px;font-size:10px;letter-spacing:.4px;text-transform:uppercase}
.board{break-inside:avoid;margin-bottom:16px;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden;cursor:pointer}
.board img{width:100%;height:170px;object-fit:cover;background:#202024;display:block}
.board .b{padding:13px 14px}
.board .b h3{margin:0 0 3px;font-size:14px}
.board .b span{font-size:12px;color:var(--mut)}
.empty{text-align:center;color:var(--mut);padding:70px 20px;font-size:14px}
.empty b{display:block;color:var(--txt);font-size:17px;margin-bottom:6px}
.loader{display:flex;gap:8px;align-items:center;color:var(--mut);padding:50px;justify-content:center;font-size:13px}
.toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:#2a1215;border:1px solid #57232a;color:#ffb3bc;padding:11px 18px;border-radius:12px;font-size:13px;opacity:0;pointer-events:none;transition:.2s;z-index:50}
.toast.show{opacity:1}
</style>
</head>
<body>
<header>
  <div class="brand"><div class="dot">P</div> Pinterest Console</div>
  <div class="search hidden" id="searchBar">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9a9aa2" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
    <input id="q" placeholder="Search Pinterest from your account…" autocomplete="off">
  </div>
  <div class="acct hidden" id="acct">
    <div class="avatar" id="av">?</div>
    <div><b id="acctName" style="font-size:13px"></b><small id="acctMail"></small></div>
    <button class="btn" id="logoutBtn">Log out</button>
  </div>
</header>

<div class="login-wrap" id="loginView">
  <div class="card">
    <h1>Session unavailable</h1>
    <p class="sub">This service authenticates with a server-side session cookie. Passwords are never accepted from the browser.</p>
    <div class="note">The server will recover automatically when possible. If this persists, the session needs a manual cookie refresh.</div>
  </div>
</div>

<main id="appView" class="hidden">
  <section class="profile">
    <div class="big" id="pAv">?</div>
    <div>
      <h2 id="pName">—</h2>
      <div class="meta" id="pMeta"></div>
    </div>
    <div class="stats">
      <div><b id="statPins">0</b><span>Saved</span></div>
      <div><b id="statBoards">0</b><span>Boards</span></div>
    </div>
  </section>
  <div class="tabs">
    <button class="tab active" data-tab="feed">Home feed</button>
    <button class="tab" data-tab="search">Search</button>
    <button class="tab" data-tab="pins">My pins</button>
    <button class="tab" data-tab="boards">Boards</button>
  </div>
  <div id="content"></div>
</main>
<div class="toast" id="toast"></div>

<script>
let USER=null, TAB='feed', LASTQ='';
const $=id=>document.getElementById(id);
const content=$('content');

function toast(msg){const t=$('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3200);}
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function loader(){return '<div class="loader"><span class="spin" style="border-color:rgba(255,255,255,.2);border-top-color:#e60023"></span> Loading from your account…</div>';}
function empty(title,sub){return `<div class="empty"><b>${esc(title)}</b>${esc(sub||'')}</div>`;}

function showLogin(){ $('loginView').classList.remove('hidden'); $('appView').classList.add('hidden'); $('searchBar').classList.add('hidden'); $('acct').classList.add('hidden'); }
function showApp(u){
  USER=u;
  $('loginView').classList.add('hidden'); $('appView').classList.remove('hidden');
  $('searchBar').classList.remove('hidden'); $('acct').classList.remove('hidden');
  const name=u.full_name||u.username||'Account';
  $('pName').textContent=name; $('pAv').textContent=(name[0]||'?');
  $('av').textContent=(name[0]||'?'); $('acctName').textContent=name;
  $('acctMail').textContent=u.email||('@'+(u.username||''));
  const bits=[]; if(u.username)bits.push('@'+u.username); if(u.country)bits.push(u.country); if(u.age)bits.push(u.age+'y'); if(u.gender)bits.push(u.gender);
  $('pMeta').textContent=bits.join(' · ');
  loadTab('feed');
}

function pinCard(p){
  const img=p.image?`<img loading="lazy" src="${esc(p.image)}" alt="">`:'<div style="height:180px"></div>';
  const tag=p.is_video?'<span class="tag">Video</span>':'';
  return `<article class="pin" data-url="${esc(p.pin_url||p.link)}">
    ${img}${tag}
    <div class="ov"><h3>${esc(p.title||p.description||'Untitled pin')}</h3><span>${esc(p.domain||p.board||'')}</span></div>
  </article>`;
}
function boardCard(b){
  return `<article class="board" data-url="${esc(b.url)}">
    ${b.image?`<img loading="lazy" src="${esc(b.image)}" alt="">`:'<div style="height:170px;background:#202024"></div>'}
    <div class="b"><h3>${esc(b.name||'Board')}</h3><span>${b.pin_count||0} pins</span></div>
  </article>`;
}
let NEXT=null, LOADING=false, SEEN=new Set();

content.addEventListener('click', e=>{
  const el=e.target.closest('.pin,.board'); if(!el) return;
  const u=el.dataset.url; if(u) window.open(u,'_blank','noopener');
});

function addPins(ps, append){
  const fresh=[];
  (ps||[]).forEach(p=>{ const k=String(p.id||p.pin_url||p.image||''); if(k && !SEEN.has(k)){ SEEN.add(k); fresh.push(p); }});
  if(!append) content.innerHTML='<div class="grid"></div>';
  const grid=content.querySelector('.grid');
  if(grid) grid.insertAdjacentHTML('beforeend', fresh.map(pinCard).join(''));
  return fresh.length;
}

function updateMore(total){
  let more=document.getElementById('more');
  if(!more){ more=document.createElement('div'); more.id='more'; more.className='loader'; content.appendChild(more); }
  if(NEXT){ more.style.display='block'; more.innerHTML='<span class="spin" style="border-color:rgba(255,255,255,.2);border-top-color:#e60023"></span> Scroll for more…'; }
  else { more.style.display=total?'block':'none'; more.innerHTML=total?`That\u2019s all \u2014 ${total} pins.`:''; }
}

async function loadMore(){
  if(LOADING || !NEXT) return;
  LOADING=true;
  const more=document.getElementById('more');
  if(more) more.innerHTML='<span class="spin" style="border-color:rgba(255,255,255,.2);border-top-color:#e60023"></span> Loading more…';
  const old=NEXT;
  let url='/api/feed?bookmark='+encodeURIComponent(NEXT);
  if(TAB==='search') url='/api/search?q='+encodeURIComponent(LASTQ||'')+'&bookmark='+encodeURIComponent(NEXT);
  try{
    const j=await (await fetch(url)).json();
    if(!j.ok){ toast(j.error||'Request failed'); NEXT=null; }
    else{
      const n=addPins(j.pins||[], true);
      NEXT=(j.bookmark && j.bookmark!==old && n>0)?j.bookmark:null;
      updateMore(SEEN.size);
    }
  }catch(e){ toast('Network error'); }
  LOADING=false;
}

window.addEventListener('scroll', ()=>{
  if(!NEXT || LOADING) return;
  if(window.innerHeight+window.scrollY >= document.documentElement.scrollHeight-900) loadMore();
}, {passive:true});

async function loadTab(tab, q){
  TAB=tab; LASTQ=q||LASTQ; NEXT=null; LOADING=false; SEEN=new Set();
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===tab));
  content.innerHTML=loader();
  let url='/api/feed';
  if(tab==='search') url='/api/search?q='+encodeURIComponent(LASTQ||'');
  if(tab==='pins') url='/api/pins';
  if(tab==='boards') url='/api/boards';
  try{
    const r=await fetch(url); const j=await r.json();
    if(j.auth===false){ showLogin(); return; }
    if(!j.ok){ toast(j.error||'Request failed'); content.innerHTML=empty('Could not load','Try again in a moment.'); return; }
    if(tab==='boards'){
      const bs=j.boards||[]; $('statBoards').textContent=bs.length;
      content.innerHTML = bs.length? `<div class="grid">${bs.map(boardCard).join('')}</div>` : empty('No boards yet','Boards you create will appear here.');
    } else {
      const ps=j.pins||[];
      if(tab==='search' && !LASTQ){ content.innerHTML=empty('Search Pinterest','Type a query above and press Enter.'); return; }
      if(tab==='pins') $('statPins').textContent=ps.length;
      if(!ps.length){ content.innerHTML=empty(tab==='search'?'No results':(tab==='pins'?'No saved pins yet':'Your feed is empty'),'Results come from your own account.'); return; }
      addPins(ps, false);
      NEXT=(tab==='feed'||tab==='search')?(j.bookmark||null):null;
      updateMore(SEEN.size);
    }
  }catch(e){ toast('Network error'); content.innerHTML=empty('Network error','Could not reach the app.'); }
}

document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===tab));
  content.innerHTML=loader();
  let url='/api/feed';
  if(tab==='search') url='/api/search?q='+encodeURIComponent(LASTQ||'');
  if(tab==='pins') url='/api/pins';
  if(tab==='boards') url='/api/boards';
  try{
    const r=await fetch(url); const j=await r.json();
    if(j.auth===false){ showLogin(); return; }
    if(!j.ok){ toast(j.error||'Request failed'); content.innerHTML=empty('Could not load','Try again in a moment.'); return; }
    if(tab==='boards'){
      const bs=j.boards||[]; $('statBoards').textContent=bs.length;
      content.innerHTML = bs.length? `<div class="grid">${bs.map(boardCard).join('')}</div>` : empty('No boards yet','Boards you create will appear here.');
    } else {
      const ps=j.pins||[];
      if(tab==='pins') $('statPins').textContent=ps.length;
      if(tab==='search' && !LASTQ){ content.innerHTML=empty('Search Pinterest','Type a query above and press Enter.'); return; }
      content.innerHTML = ps.length? `<div class="grid">${ps.map(pinCard).join('')}</div>`
        : empty(tab==='search'?'No results':(tab==='pins'?'No saved pins yet':'Your feed is empty'),'Results come from your own account.');
    }
    bindCards();
  }catch(e){ toast('Network error'); content.innerHTML=empty('Network error','Could not reach the app.'); }
}

document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
  const tab=t.dataset.tab;
  if(tab==='search'){ $('q').focus(); if(!LASTQ){ loadTab('search'); return; } }
  loadTab(tab);
}));
$('q').addEventListener('keydown',e=>{ if(e.key==='Enter'){ loadTab('search', $('q').value.trim()); }});

$('logoutBtn').addEventListener('click', async ()=>{
  await fetch('/api/logout',{method:'POST'}); USER=null; showLogin();
});

(async function init(){
  try{
    const j=await (await fetch('/api/status')).json();
    if(j.authenticated && j.user) showApp(j.user);
    else showLogin();
  }catch(e){ showLogin(); }
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    print(f"[*] Pinterest Console -> http://{host}:{port}/app")
    app.run(host=host, port=port, threaded=True, debug=False)
