#!/usr/bin/env python3
"""Spike: dump raw text around the relay script to see exact call format."""
import re
import sys

html = open(sys.argv[1] if len(sys.argv) > 1 else "pin.html", encoding="utf-8").read()
i = html.find("__PWS_RELAY_REGISTER_COMPLETED_REQUEST__")
print("first call at byte", i)
print(repr(html[i - 200 : i + 600]))
