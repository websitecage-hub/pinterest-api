#!/usr/bin/env python3
"""
proxy_test.py - test every proxy from PrOxY (success/good.json) and ProxyProwler
(proxy_output/*.txt), verify real connectivity, classify residential vs datacenter
via proxy-ip-check (ip-api.com) + ipinfo.io, and write the passing residential
ones to best_proxies.txt.

Usage:
  python proxy_test.py
  python proxy_test.py --pinterest   # also try a real HTTPS request to Pinterest
"""
import argparse
import json
import os
import socket
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
PR = os.path.join(HERE, "PrOxY", "success", "good.json")
PP = os.path.join(HERE, "ProxyProwler", "proxy_output")

sys.path.insert(0, HERE)
try:
    from proxy_ip_check import lookup, is_residential
except Exception as e:
    print("[!] proxy_ip_check unavailable:", e)
    lookup = None
    is_residential = None


def load_candidates():
    out = []
    # PrOxY good.json
    try:
        for x in json.load(open(PR, encoding="utf-8")):
            out.append((x["proxy"], "PrOxY"))
    except Exception as e:
        print("[!] could not read PrOxY good.json:", e)
    # ProxyProwler txt files
    for fn in ("SOCKS5.txt", "SOCKS4.txt", "HTTPS.txt"):
        p = os.path.join(PP, fn)
        try:
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#"):
                    out.append((line, "ProxyProwler/" + fn))
        except FileNotFoundError:
            pass
    # dedup
    seen = set()
    uniq = []
    for proxy, src in out:
        if proxy not in seen:
            seen.add(proxy)
            uniq.append((proxy, src))
    return uniq


def ipinfo_lookup(ip):
    try:
        req = urllib.request.Request(f"https://ipinfo.io/{ip}/json",
                                    headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
        return d.get("org"), d.get("country")
    except Exception as e:
        return None, str(e)[:40]


def test_proxy(proxy, src, do_pinterest=False):
    host, port = proxy.rsplit(":", 1)
    port = int(port)
    # 1) TCP connect
    t0 = time.time()
    try:
        s = socket.create_connection((host, port), timeout=8)
        s.close()
        tcp_ms = round((time.time() - t0) * 1000)
    except Exception as e:
        return {"proxy": proxy, "src": src, "tcp": False, "http": False,
                "residential": False, "ip": None, "org": None,
                "country": None, "note": f"tcp fail: {str(e)[:50]}"}

    # 2) HTTP through proxy
    http_ok = False
    egress_ip = None
    http_ms = None
    t0 = time.time()
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": "http://" + proxy,
                                         "https": "http://" + proxy}))
        opener.addheaders = [("User-Agent", "Mozilla/5.0")]
        with opener.open("http://httpbin.org/ip", timeout=15) as r:
            body = json.loads(r.read().decode())
        egress_ip = (body.get("origin") or "").split(",")[0].strip()
        http_ok = True
        http_ms = round((time.time() - t0) * 1000)
    except Exception as e:
        http_ms = round((time.time() - t0) * 1000)
        note = f"http fail: {str(e)[:50]}"
        # still try residential classification on the proxy's own IP
        note = note

    # 3) residential classification (proxy-ip-check + ipinfo.io)
    ip_to_check = egress_ip or host
    residential = False
    org = None
    country = None
    pic = {}
    if lookup is not None:
        try:
            pic = lookup(ip_to_check) or {}
            _ir = (is_residential(ip_to_check) if is_residential else False)
            residential = bool(pic.get("isResidentialLike")) or bool(_ir)
        except Exception as e:
            pic = {"error": str(e)[:40]}
    ip_org, ip_country = ipinfo_lookup(ip_to_check)
    if ip_org:
        org = ip_org
    if ip_country:
        country = ip_country
    if not org:
        org = pic.get("org") or pic.get("isp") or pic.get("asName")
    if not country:
        country = pic.get("country") or pic.get("countryCode")

    # 4) optional Pinterest HTTPS test
    pinterest_ok = None
    if do_pinterest and http_ok:
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": "http://" + proxy,
                                             "https": "http://" + proxy}))
            opener.addheaders = [("User-Agent",
                "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36")]
            with opener.open("https://www.pinterest.com/", timeout=20) as r:
                pinterest_ok = (r.status == 200)
        except Exception:
            pinterest_ok = False

    return {
        "proxy": proxy, "src": src,
        "tcp": True, "tcp_ms": tcp_ms,
        "http": http_ok, "http_ms": http_ms,
        "egress_ip": egress_ip,
        "residential": residential,
        "org": org, "country": country,
        "networkType": pic.get("networkType"),
        "pinterest": pinterest_ok,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--pinterest", action="store_true",
                    help="also probe https://www.pinterest.com/ through each proxy")
    ap.add_argument("--out", default="best_proxies.txt")
    args = ap.parse_args()

    cands = load_candidates()
    print(f"[*] {len(cands)} unique candidates "
          f"({sum(1 for _,s in cands if s=='PrOxY')} PrOxY, "
          f"{sum(1 for _,s in cands if s.startswith('ProxyProwler'))} ProxyProwler)")

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(test_proxy, p, s, args.pinterest): (p, s) for p, s in cands}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            results.append(r)
            tag = "RES" if r["residential"] else "DC "
            status = "OK " if r["http"] else "BAD"
            print(f"[{i:3d}/{len(cands)}] {r['proxy']:22s} {status} "
                  f"{tag} {r.get('country') or '?':3s} "
                  f"{(r.get('org') or '')[:38]:38s} "
                  f"egress={r.get('egress_ip') or '-'}")

    # sort: residential + working first, then by http_ms
    results.sort(key=lambda r: (not (r["http"] and r["residential"]),
                                r.get("http_ms") or 99999))

    passed = [r for r in results if r["http"] and r["residential"]]
    print("\n" + "=" * 70)
    print(f"TESTED: {len(results)}  |  HTTP-OK: {sum(r['http'] for r in results)}  "
          f"|  RESIDENTIAL: {sum(1 for r in results if r.get('residential'))}  "
          f"|  PASSED (http+res): {len(passed)}")
    print("=" * 70)

    # write best list
    out_path = os.path.join(HERE, args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in passed:
            f.write(r["proxy"] + "\n")
    print(f"[*] {len(passed)} passing residential proxies -> {out_path}")

    # also dump full report
    report = os.path.join(HERE, "proxy_test_report.json")
    with open(report, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"[*] full report -> {report}")

    if passed:
        print("\n-- best proxies --")
        for r in passed[:15]:
            print(f"  {r['proxy']:22s} {r.get('country') or '?':3s} "
                  f"{(r.get('org') or '')[:40]:40s} {r.get('http_ms')}ms "
                  f"egress={r.get('egress_ip')}")


if __name__ == "__main__":
    main()
