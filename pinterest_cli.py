#!/usr/bin/env python3
"""
pinterest_cli.py - self-contained Pinterest client.

Logs in with email/password (request-based, no browser):
  * Arkose  -> local solver on :8003 (auto-started from ./funcaptcha-solver)
  * reCAPTCHA Enterprise -> ./BypassV3
  * session  -> curl_cffi cookies persisted to ./pinterest_cli_session.json

==========================================================================
 WHAT TO INSTALL  (one-time setup)
==========================================================================
 Python: 3.10+  (verified on 3.11.9)

 1) This script's own deps:
        pip install curl-cffi requests

 2) BypassV3 (folder `BypassV3/` next to this file) - mints the
    reCAPTCHA Enterprise token. It is pure Python; the module imports
    `requests`. Its optional protobuf helper (blackboxprotobuf) is only
    used on some code paths:
        pip install requests
        pip install blackboxprotobuf        # optional

 3) funcaptcha-solver (folder `funcaptcha-solver/` next to this file) -
    solves the Arkose/FunCaptcha challenge. It needs:
        pip install flask curl-cffi colorama pycryptodome cryptography \\
                    javascript PyExecJS numpy colr requests
    The `javascript` package ships the embedded JS engine used by
    `arkose.js` (no separate Node.js install needed).

    Everything above is already installed in this environment; the list
    is here so the script can be rebuilt on a clean machine.

==========================================================================
 HOW TO SET IT UP
==========================================================================
 1) Keep this file next to these two folders:
        E:\\PINTEREST\\pinterest_cli.py
        E:\\PINTEREST\\BypassV3\\
        E:\\PINTEREST\\funcaptcha-solver\\
    (the script adds BypassV3 to sys.path and runs the solver from its
     own folder, so no manual PYTHONPATH / cwd juggling is required)

 2) Do NOT edit site keys: they are pinned below (Arkose sitekey +
    reCAPTCHA Enterprise key for Pinterest's login page).

 3) Start it - the Arkose solver auto-starts on 127.0.0.1:8003 the first
    time you log in (boot takes ~40-60s). Or pre-start it yourself:
        cd funcaptcha-solver
        python main.py

 4) Credentials (defaults are filled in at the bottom of this header):
        --email / --password          CLI flags
        PIN_EMAIL / PIN_PASSWORD      environment variables
    The session is cached after the first login; later runs reuse it.
    Use --fresh to force a brand-new login.

==========================================================================
 USAGE
==========================================================================
  python pinterest_cli.py                     # whoami + feed + pins + boards
  python pinterest_cli.py feed
  python pinterest_cli.py search "cyberpunk"
  python pinterest_cli.py pins
  python pinterest_cli.py boards
  python pinterest_cli.py whoami
  python pinterest_cli.py all --search batman
Options:
  --email X --password Y      credentials (or env PIN_EMAIL / PIN_PASSWORD)
  --fresh                     ignore saved session, log in again
  --limit N                   rows to print (default 10; JSON always full)
==========================================================================
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse

from curl_cffi import requests

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://in.pinterest.com"
SITEKEY = "F5675B21-025B-4843-983C-38D86DEB394B"
RC_KEY = "6Ldx7ZkUAAAAAF3SZ05DRL2Kdh911tCa3qFP0-0r"
RC_ACTION = "login"
SOLVER = "http://127.0.0.1:8003"
SOLVER_DIR = os.path.join(HERE, "funcaptcha-solver")
UA = ("Mozilla/5.0 (Linux; Android 16; Pixel 10) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/156.0.0.0 Mobile Safari/537.36")
SESSION_FILE = os.path.join(HERE, "pinterest_cli_session.json")
RESULTS_FILE = os.path.join(HERE, "pinterest_cli_results.json")
# Default account. Override with --email/--password or PIN_EMAIL/PIN_PASSWORD.
DEFAULT_EMAIL = "testflowthrowout@gmail.com"
DEFAULT_PASSWORD = ""

sys.path.insert(0, os.path.join(HERE, "BypassV3"))
try:
    # Requires ./BypassV3 + `pip install requests` (see header for full setup)
    from bypass import ReCaptchaV3Bypass
except Exception as e:
    ReCaptchaV3Bypass = None
    print("[!] BypassV3 unavailable:", e)


# ------------------------------------------------------------------ solver
def solver_up():
    try:
        with socket.create_connection(("127.0.0.1", 8003), timeout=1):
            return True
    except OSError:
        return False


def ensure_solver():
    if solver_up():
        return True
    print("[*] starting Arkose solver (:8003)…")
    flags = 0x08000000 if os.name == "nt" else 0
    try:
        subprocess.Popen([sys.executable, "main.py"], cwd=SOLVER_DIR,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags)
    except Exception as e:
        print("[!] cannot start solver:", e)
        return False
    deadline = time.time() + 120
    while time.time() < deadline:
        if solver_up():
            print("[*] solver ready")
            return True
        time.sleep(2)
    return solver_up()


# ------------------------------------------------------------------ client
IMPERSONATIONS = ["chrome131", "chrome124", "chrome123", "chrome120"]


class Pinterest:
    def __init__(self):
        self.session = None
        self.user = None
        self.impersonate = IMPERSONATIONS[0]

    # -- session plumbing -------------------------------------------
    def new_session(self):
        s = requests.Session(impersonate=self.impersonate)
        s.headers.update({"user-agent": UA,
                          "accept-language": "en-IN,en-US;q=0.9,en;q=0.8"})
        return s

    def dump_cookies(self):
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

    def cookie_header(self):
        """Cookie header string (k=v; k=v) from the current session."""
        parts = []
        seen = set()
        for c in self.dump_cookies():
            name = c.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            parts.append(f"{name}={c.get('value')}")
        return "; ".join(parts)

    def rebuild(self):
        cookies = self.dump_cookies()
        self.session = self.new_session()
        for c in cookies:
            try:
                self.session.cookies.set(c["name"], c["value"],
                                         domain=c.get("domain") or ".pinterest.com",
                                         path=c.get("path") or "/")
            except Exception:
                pass

    def raw(self, method, url, timeout=30, retries=6, **kw):
        last = None
        for i in range(retries):
            try:
                if self.session is None:
                    self.session = self.new_session()
                r = self.session.request(method, url, timeout=timeout, **kw)
                if r.status_code in (429, 500, 502, 503, 504) and i < retries - 1:
                    time.sleep(1.0 + 1.2 * i)
                    continue
                return r
            except Exception as e:
                last = e
                time.sleep(0.5 + 0.7 * i)
                try:
                    self.rebuild()
                except Exception:
                    pass
        raise last

    def hdr(self, source_url="/", handler=None):
        csrf = self.session.cookies.get("csrftoken") if self.session else ""
        h = {"accept": "application/json, text/javascript, */*, q=0.01",
             "content-type": "application/x-www-form-urlencoded",
             "x-csrftoken": csrf or "",
             "x-requested-with": "XMLHttpRequest",
             "x-pinterest-appstate": "active",
             "x-pinterest-source-url": source_url,
             "x-app-version": "7eb5076",
             "origin": BASE, "referer": BASE + "/"}
        if handler:
            h["x-pinterest-pws-handler"] = handler
        return h

    def resource(self, path, options, source_url="/", handler=None):
        body = urllib.parse.urlencode({
            "source_url": source_url,
            "data": json.dumps({"options": options, "context": {}},
                               separators=(",", ":")),
        })
        return self.raw("POST", BASE + "/resource/" + path,
                        headers=self.hdr(source_url, handler),
                        data=body, timeout=30)

    # -- persistence -------------------------------------------------
    def save(self, email=None):
        data = {"cookies": self.dump_cookies(), "user": self.user,
                "email": email or (self.user or {}).get("email")}
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print("[*] session saved ->", SESSION_FILE)

    def load(self):
        for path in (SESSION_FILE, os.path.join(HERE, "app_session.json"),
                     os.path.join(HERE, "pin_session_requests.json")):
            if not os.path.exists(path):
                continue
            try:
                data = json.load(open(path, encoding="utf-8"))
            except Exception:
                continue
            s = self.new_session()
            cookies = data.get("cookies")
            if isinstance(cookies, dict):
                for k, v in cookies.items():
                    try:
                        s.cookies.set(k, v, domain=".pinterest.com", path="/")
                    except Exception:
                        pass
            else:
                for c in cookies or []:
                    try:
                        s.cookies.set(c["name"], c["value"],
                                      domain=c.get("domain") or ".pinterest.com",
                                      path=c.get("path") or "/")
                    except Exception:
                        pass
            self.session = s
            self.user = data.get("user")
            if self.whoami():
                print("[*] reused session", os.path.basename(path))
                return True
        self.session = None
        return False

    # -- login -------------------------------------------------------
    def arkose(self):
        r = self.raw("GET", BASE + "/secure/arkose_data_exchange/",
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

    def recaptcha(self):
        if ReCaptchaV3Bypass is None:
            return None
        return ReCaptchaV3Bypass.from_site_key(
            RC_KEY, origin=BASE, action=RC_ACTION, enterprise=True,
            user_agent=UA).bypass()

    def login(self, email, password):
        if not ensure_solver():
            raise RuntimeError("Arkose solver did not start on :8003")
        self.session = self.new_session()
        self.raw("GET", BASE + "/login/", timeout=30, retries=5)
        csrf = self.session.cookies.get("csrftoken")
        for _ in range(3):
            if csrf:
                break
            time.sleep(1.5)
            self.raw("GET", BASE + "/login/", timeout=30, retries=3)
            csrf = self.session.cookies.get("csrftoken")
        if not csrf:
            raise RuntimeError("could not get csrftoken")

        print("[*] solving Arkose…")
        ark = self.arkose()
        if not ark:
            raise RuntimeError("Arkose token failed")
        print("[*] solving reCAPTCHA Enterprise…")
        rec = self.recaptcha()
        if not rec:
            raise RuntimeError("reCAPTCHA token failed")

        data = {"options": {
            "get_user": True, "username_or_email": email, "password": password,
            "app_type_from_client": 6,
            "ui_component": "MobileLoginPage.LoginFormClassComponent",
            "handler": "www/login.js",
            "visited_pages_before_login": json.dumps(
                [{"path": "/login/", "pageType": "", "ts": int(time.time() * 1000)}]),
            "arkoseSessionToken": ark, "recaptchaV3Token": rec,
        }, "context": {}}
        hdr = self.hdr("/login/", "www/login.js")
        body = urllib.parse.urlencode({"source_url": "/login/", "data": json.dumps(data)})
        rr = {}
        for _ in range(3):
            r = self.raw("POST", BASE + "/resource/UserSessionResource/create/",
                         headers=hdr, data=body, timeout=30, retries=4)
            try:
                rr = r.json().get("resource_response", {})
            except Exception:
                rr = {}
            if rr.get("status") == "success":
                self.user = self.whoami() or rr.get("data", {}).get("user")
                if self.user and not self.user.get("email"):
                    self.user["email"] = email
                self.save(email)
                return self.user
            if r.status_code == 429:
                time.sleep(4)
                continue
            break
        msg = rr.get("error") if isinstance(rr.get("error"), dict) else {}
        raise RuntimeError(msg.get("message") or "login rejected")

    # -- data --------------------------------------------------------
    @staticmethod
    def img(imgs):
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

    def norm_pin(self, it):
        p = it
        if not p.get("images"):
            p = it.get("pin") or (it.get("aggregatedpindata") or {}).get("pin") or it
        pid = p.get("id")
        board = p.get("board")
        return {"id": pid,
                "title": p.get("grid_title") or p.get("title") or "",
                "description": p.get("description") or "",
                "image": self.img(p.get("images")),
                "link": p.get("link") or p.get("domain") or "",
                "domain": p.get("domain") or "",
                "pin_url": f"https://www.pinterest.com/pin/{pid}/" if pid else "",
                "is_video": bool(p.get("is_video")),
                "board": board.get("name") if isinstance(board, dict) else ""}

    def whoami(self):
        try:
            r = self.resource("UserSettingsResource/get/", {}, "/")
            d = r.json()["resource_response"].get("data") or {}
            if not d:
                return None
            name = " ".join(x for x in [d.get("first_name"), d.get("last_name")] if x).strip()
            self.user = {"username": d.get("username"),
                         "full_name": name or d.get("username"),
                         "email": d.get("email"), "id": d.get("id"),
                         "country": d.get("country"), "gender": d.get("gender"),
                         "age": d.get("age"), "about": d.get("about")}
            return self.user
        except Exception:
            return None

    def feed(self):
        r = self.resource("UserHomefeedResource/get/",
                          {"field_set_key": "mobile_grid_item",
                           "first_page_size": 25, "page_size": 15}, "/")
        items = r.json()["resource_response"].get("data") or []
        return [self.norm_pin(x) for x in items if x.get("type") == "pin"][:40]

    def search(self, q):
        r = self.resource("BaseSearchResource/get/", {"query": q, "scope": "pins"},
                          f"/search/pins/?q={urllib.parse.quote(q)}")
        res = r.json()["resource_response"].get("data", {}).get("results") or []
        return [self.norm_pin(x) for x in res if x.get("type") == "pin"][:40]

    def pins(self):
        fields = ("pin.id,pin.images[236x,474x,orig],pin.grid_title,pin.title,"
                  "pin.description,pin.link,pin.domain,pin.is_video,pin.board()")
        r = self.resource("ApiResource/get/",
                          {"url": "/v3/users/me/filtered/pins/",
                           "data": {"flag_filters": "", "fields": fields}},
                          "/me/pins/", "www/[username]/pins.js")
        return [self.norm_pin(x) for x in (r.json()["resource_response"].get("data") or [])][:40]

    def boards(self):
        fields = "id,name,url,image_thumbnail_url,privacy,pin_count,description"
        r = self.resource("ApiResource/get/",
                          {"url": "/v3/users/me/boards/", "data": {"fields": fields}},
                          "/me/boards/", "www/[username]/boards.js")
        out = []
        for b in (r.json()["resource_response"].get("data") or []):
            out.append({"id": b.get("id"), "name": b.get("name"),
                        "pin_count": b.get("pin_count") or 0,
                        "image": b.get("image_thumbnail_url"),
                        "url": "https://www.pinterest.com" + (b.get("url") or "")})
        return out


# ------------------------------------------------------------------ output
def show_pins(name, pins, limit):
    print(f"\n== {name} ({len(pins)}) ==")
    if not pins:
        print("  (empty)")
    for i, p in enumerate(pins[:limit], 1):
        print(f" [{i:02d}] {p['title'] or p['description'] or '(untitled)'}"
              f"{'  [video]' if p['is_video'] else ''}")
        if p["domain"]:
            print(f"       {p['domain']}")
        if p["pin_url"]:
            print(f"       {p['pin_url']}")
        if p["image"]:
            print(f"       {p['image'][:110]}")
    if len(pins) > limit:
        print(f"  … {len(pins) - limit} more in JSON")


def show_boards(boards, limit):
    print(f"\n== boards ({len(boards)}) ==")
    if not boards:
        print("  (empty)")
    for i, b in enumerate(boards[:limit], 1):
        print(f" [{i:02d}] {b['name']}  ({b['pin_count']} pins)")
        if b["url"]:
            print(f"       {b['url']}")


def main():
    ap = argparse.ArgumentParser(description="Pinterest request-based client")
    ap.add_argument("command", nargs="?", default="all",
                    choices=["all", "whoami", "feed", "search", "pins", "boards"])
    ap.add_argument("query", nargs="*", help="search query (for: search)")
    ap.add_argument("--email", default=os.environ.get("PIN_EMAIL") or DEFAULT_EMAIL)
    ap.add_argument("--password", default=os.environ.get("PIN_PASSWORD") or DEFAULT_PASSWORD)
    ap.add_argument("--fresh", action="store_true", help="force a new login")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--search", dest="extra_search", default=None,
                    help="extra search query to include with 'all'")
    args = ap.parse_args()

    c = Pinterest()
    results = {}

    print("[*] Pinterest CLI — request-only")
    try:
        if args.fresh or not c.load():
            print("[*] logging in as", args.email)
            user = c.login(args.email, args.password)
            print("[+] logged in:", (user or {}).get("username"))
        else:
            user = c.user or c.whoami()

        print("\n== account ==")
        for k in ("username", "full_name", "email", "id", "country", "gender"):
            if user and user.get(k) not in (None, ""):
                print(f"  {k:10s}: {user[k]}")
        results["account"] = user

        cmd = args.command
        q = " ".join(args.query).strip() if args.query else ""

        if cmd in ("all", "feed"):
            pins = c.feed()
            results["feed"] = pins
            show_pins("feed", pins, args.limit)

        if cmd == "search" or (cmd == "all" and (q or args.extra_search)):
            sq = q or args.extra_search or ""
            pins = c.search(sq)
            results["search"] = {"query": sq, "pins": pins}
            show_pins(f"search: {sq}", pins, args.limit)

        if cmd in ("all", "pins"):
            pins = c.pins()
            results["pins"] = pins
            show_pins("my pins", pins, args.limit)

        if cmd in ("all", "boards"):
            bs = c.boards()
            results["boards"] = bs
            show_boards(bs, args.limit)

        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print("\n[*] full results ->", RESULTS_FILE)
        return 0

    except KeyboardInterrupt:
        print("\n[!] interrupted")
        return 130
    except Exception as e:
        print("\n[!] error:", str(e)[:300])
        return 1


if __name__ == "__main__":
    sys.exit(main())
