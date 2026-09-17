#!/usr/bin/env python3
"""Spike: inspect payload 1 structure of the cheesecake pin (carousel hunt)."""
import re

from extractor import _fetch, extract_relay_payloads

html = _fetch("https://www.pinterest.com/pin/easy-nobake-creme-egg-cheesecake-recipe--1098033952905607765/")
print("carousel mentions in raw html:", len(re.findall(r"carousel", html, re.I)))

payloads = extract_relay_payloads(html)
print("payloads:", len(payloads))


def walk(n, d=0):
    if d > 3:
        return
    if isinstance(n, dict):
        for k, v in list(n.items())[:20]:
            print("  " * d + f"{k} ({type(v).__name__})")
            if isinstance(v, (dict, list)):
                walk(v, d + 1)
    elif isinstance(n, list) and n:
        walk(n[0], d)


walk(payloads[1])
