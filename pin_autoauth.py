#!/usr/bin/env python3
"""
pin_autoauth.py - cookie-first Pinterest auth with proxy-pool self-heal.

Flow:
  1. valid cookies (file / PIN_COOKIES_B64 / saved session) -> use them
  2. cookies dead -> pick a working exit from the local proxy-scraper pool
     (PIN_POOL_API, default http://127.0.0.1:8899), log in once, verify,
     save the new cookies (json + PIN_COOKIES_B64.txt), then continue
  3. mid-run 401/403 -> heal once and retry the command

Ban-avoidance guardrails (persisted in auth_state.json):
  * login only on a confirmed auth failure, never on network/429 errors
  * minimum interval between login attempts (default 10 min)
  * hard daily cap (default 5) + exponential cooldown after failures
  * "We reset your password" -> hard stop, requires_manual=1
  * one real login POST per heal; proxies pre-flighted with plain GETs
  * bad exits reported back to the pool so it evicts them

Usage:
  python pinterest_cli.py whoami --auto
  PIN_AUTO=1 python pinterest_cli.py feed
  PIN_POOL_API=http://host:8899 PIN_COOKIES_B64=... python <app>
"""
import base64
import json
import os
import time
from datetime import date

import pinterest_cli as pc

POOL_API = os.environ.get("PIN_POOL_API", "http://127.0.0.1:8899").rstrip("/")
STATE_FILE = os.path.join(pc.DATA_DIR, "auth_state.json")
B64_FILE = os.path.join(pc.DATA_DIR, "PIN_COOKIES_B64.txt")

MIN_ATTEMPT_INTERVAL = int(os.environ.get("PIN_LOGIN_MIN_INTERVAL", "600"))
MAX_ATTEMPTS_PER_DAY = int(os.environ.get("PIN_LOGIN_MAX_PER_DAY", "5"))
MAX_PROXY_TRIES = int(os.environ.get("PIN_LOGIN_MAX_PROXIES", "2"))
PREFLIGHT_TIMEOUT = 12
COOLDOWN_AFTER_FAILS = int(os.environ.get("PIN_LOGIN_COOLDOWN", "21600"))


class HealBlocked(Exception):
    pass


def log(msg):
    print("[auth]", msg, flush=True)


class AuthState:
    def __init__(self):
        self.data = {
            "status": "unknown", "requires_manual": False,
            "last_login_ts": 0, "last_attempt_ts": 0, "cooldown_until": 0,
            "fail_streak": 0, "attempts_today": 0, "day": "",
            "last_proxy": None, "last_error": None,
        }
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                self.data.update(json.load(f) or {})
        except Exception:
            pass
        self._roll_day()

    def _roll_day(self):
        today = date.today().isoformat()
        if self.data.get("day") != today:
            self.data["day"] = today
            self.data["attempts_today"] = 0

    def save(self):
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            log("cannot write state: %s" % e)

    def check_allowed(self):
        now = time.time()
        if self.data.get("requires_manual"):
            raise HealBlocked(
                "auth marked REQUIRES_MANUAL (%s); clear auth_state.json after "
                "fixing the account" % (self.data.get("last_error") or "unknown"))
        if now < self.data.get("cooldown_until", 0):
            wait = int(self.data["cooldown_until"] - now)
            raise HealBlocked("cooldown active, retry in %ds" % wait)
        gap = now - self.data.get("last_attempt_ts", 0)
        if gap < MIN_ATTEMPT_INTERVAL:
            raise HealBlocked(
                "login attempts throttled, retry in %ds" % int(MIN_ATTEMPT_INTERVAL - gap))
        if self.data.get("attempts_today", 0) >= MAX_ATTEMPTS_PER_DAY:
            raise HealBlocked("daily login attempt cap reached (%d)"
                              % MAX_ATTEMPTS_PER_DAY)

    def record_attempt(self):
        self._roll_day()
        self.data["last_attempt_ts"] = time.time()
        self.data["attempts_today"] = self.data.get("attempts_today", 0) + 1
        self.save()

    def record_success(self, proxy):
        self.data.update({"status": "ok", "requires_manual": False,
                          "last_login_ts": time.time(), "fail_streak": 0,
                          "cooldown_until": 0, "last_proxy": proxy,
                          "last_error": None})
        self.save()

    def record_failure(self, err):
        self.data["fail_streak"] = self.data.get("fail_streak", 0) + 1
        self.data["status"] = "failed"
        self.data["last_error"] = str(err)[:200]
        if self.data["fail_streak"] >= 3:
            self.data["cooldown_until"] = time.time() + COOLDOWN_AFTER_FAILS
        self.save()

    def block(self, err):
        self.data.update({"status": "blocked", "requires_manual": True,
                          "last_error": str(err)[:200]})
        self.save()


def write_b64(client):
    try:
        raw = json.dumps({"cookies": client.dump_cookies(), "user": client.user},
                         indent=2)
        with open(B64_FILE, "w", encoding="utf-8") as f:
            f.write(base64.b64encode(raw.encode()).decode())
        log("PIN_COOKIES_B64.txt refreshed")
    except Exception as e:
        log("cannot write b64: %s" % e)


def _pool_get(path, timeout=8):
    try:
        r = pc.requests.get(POOL_API + path, timeout=timeout)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def pool_candidates(country=None, limit=12):
    urls = []
    if country:
        txt = _pool_get("/all?https=1&country=%s&format=txt" % country)
        urls += [x.strip() for x in (txt or "").splitlines() if x.strip()]
    txt = _pool_get("/all?https=1&format=txt")
    urls += [x.strip() for x in (txt or "").splitlines() if x.strip()]
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:limit]


def report_proxy(proxy, ok):
    hostport = proxy.split("://", 1)[-1]
    _pool_get("/report?proxy=%s&ok=%d" % (hostport, 1 if ok else 0), timeout=5)


def preflight(proxy):
    prev = pc.PROXY
    pc.PROXY = proxy
    try:
        s = pc.Pinterest().new_session()
        for url in ("https://in.pinterest.com/login/",):
            r = s.get(url, timeout=PREFLIGHT_TIMEOUT)
            if r.status_code != 200:
                return False
        return True
    except Exception:
        return False
    finally:
        pc.PROXY = prev


def heal(client, email, password, country="IN"):
    if not password:
        raise HealBlocked(
            "no PIN_PASSWORD configured; refusing to attempt a login "
            "(seed PIN_COOKIES_B64 or set PIN_PASSWORD to enable healing)")
    state = AuthState()
    state.check_allowed()

    cands = pool_candidates(country=country)
    if not cands:
        raise HealBlocked("proxy pool empty at %s" % POOL_API)

    log("cookies dead; healing through pool (%d candidates)" % len(cands))
    last_err = None
    used = 0
    for proxy in cands:
        if used >= MAX_PROXY_TRIES:
            break
        if not preflight(proxy):
            report_proxy(proxy, False)
            continue
        used += 1
        state.record_attempt()
        prev = pc.PROXY
        pc.PROXY = proxy
        keep = False
        try:
            log("login attempt %d/%d via %s" % (used, MAX_PROXY_TRIES, proxy))
            client.session = None
            user = client.login(email, password)
            write_b64(client)
            state.record_success(proxy)
            report_proxy(proxy, True)
            if os.environ.get("PIN_STICKY_EGRESS") == "1":
                pc.PROXY = proxy
                keep = True
                log("sticky egress: session stays on %s" % proxy)
            log("recovered; new session saved")
            return user
        except RuntimeError as e:
            text = str(e).lower()
            if "reset your password" in text:
                state.block(e)
                raise HealBlocked("account force-reset; manual action required")
            if "rejected" in text:
                state.record_failure(e)
                raise HealBlocked("login rejected by Pinterest (account/IP): %s" % e)
            last_err = e
            state.record_failure(e)
            report_proxy(proxy, False)
        except pc.AuthError as e:
            last_err = e
            state.record_failure(e)
        except Exception as e:
            last_err = e
            state.record_failure(e)
            report_proxy(proxy, False)
        finally:
            if not keep:
                pc.PROXY = prev

    raise HealBlocked("all proxy login attempts failed: %s" % last_err)


def probe(client):
    """Return 'ok' | 'dead' | 'net'. Distinguishes a rejected session from
    a dropped connection, so flaky links never burn a login."""
    try:
        body = pc.urllib.parse.urlencode({
            "source_url": "/",
            "data": pc.json.dumps({"options": {}, "context": {}}),
        })
        r = client.raw("POST", pc.BASE + "/resource/UserSettingsResource/get/",
                       headers=client.hdr("/"), data=body, timeout=20, retries=1)
        if r.status_code in (401, 403):
            return "dead"
        try:
            data = r.json().get("resource_response", {}).get("data")
        except Exception:
            return "net"
        return "ok" if data else "dead"
    except Exception:
        return "net"


def revalidate(client, tries=3, gap=2.0):
    """True only on a confirmed live session; retries absorb network noise."""
    for i in range(tries):
        cls = probe(client)
        if cls == "ok":
            return True
        if cls == "dead" and i >= 1:
            return False
        if i < tries - 1:
            time.sleep(gap)
            try:
                client.rebuild()
            except Exception:
                pass
    return False


def session_state(client, tries=2):
    for i in range(tries):
        cls = probe(client)
        if cls != "net":
            return cls
        if i < tries - 1:
            time.sleep(1.5)
            try:
                client.rebuild()
            except Exception:
                pass
    return "net"


def _load_saved(client):
    for path in (pc.SESSION_FILE, os.path.join(pc.DATA_DIR, "app_session.json")):
        if not os.path.exists(path):
            continue
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        s = client.new_session()
        cookies = data.get("cookies")
        if isinstance(cookies, dict):
            cookies = [{"name": k, "value": v} for k, v in cookies.items()]
        for ck in cookies or []:
            try:
                s.cookies.set(ck["name"], ck["value"],
                              domain=ck.get("domain") or ".pinterest.com",
                              path=ck.get("path") or "/")
            except Exception:
                pass
        client.session = s
        client.user = data.get("user")
        cls = session_state(client)
        if cls == "ok":
            log("reused saved session %s" % os.path.basename(path))
            return True
        if cls == "net":
            log("network flaky; keeping saved cookies (%s) unverified"
                % os.path.basename(path))
            return True
    client.session = None
    client.user = None
    return False


def ensure_client(email=None, password=None, cookies_path=None, fresh=False,
                  country=None):
    c = pc.Pinterest()
    email = email or os.environ.get("PIN_EMAIL") or pc.DEFAULT_EMAIL
    password = password or os.environ.get("PIN_PASSWORD") or pc.DEFAULT_PASSWORD
    if os.environ.get("PIN_STICKY_EGRESS") == "1" and not pc.PROXY:
        last = AuthState().data.get("last_proxy")
        if last:
            pc.PROXY = last
            log("sticky egress from last heal: %s" % last)

    if cookies_path:
        try:
            c.import_cookies(cookies_path)
            c.save()
            write_b64(c)
            return c, "cookie-file"
        except Exception as e:
            log("cookie file rejected: %s" % e)

    env = pc.cookies_from_env()
    if env:
        try:
            c.import_cookie_list(env, "PIN_COOKIES_B64")
            c.save()
            write_b64(c)
            return c, "env-b64"
        except Exception as e:
            log("env cookies rejected: %s" % e)

    if not fresh and _load_saved(c):
        return c, "saved-session"

    heal(c, email, password, country=country or os.environ.get("PIN_LOGIN_COUNTRY", "IN"))
    return c, "proxy-login"


def recover(client, email=None, password=None, country=None):
    heal(client,
         email or os.environ.get("PIN_EMAIL") or pc.DEFAULT_EMAIL,
         password or os.environ.get("PIN_PASSWORD") or pc.DEFAULT_PASSWORD,
         country=country or os.environ.get("PIN_LOGIN_COUNTRY", "IN"))
    return client
