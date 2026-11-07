#!/usr/bin/env python3
"""Prove /session/status distinguishes configured-from-accepted cookies.

Anonymous:  authenticated=false, verified=false
Dummy:      authenticated=true,  verified=false  <- the important case: a
            cookie is present but Pinterest does not accept it, so results are
            silently anonymous unless the API says so.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

print("== anonymous ==")
import searcher  # noqa: E402
print(searcher.session_status())

print("\n== bogus cookie (the case that used to lie) ==")
os.environ["PINTEREST_COOKIE"] = (
    "_pinterest_sess=DUMMYVALUE123; csrftoken=DUMMYCSRF; _auth=1"
)
searcher._reset_session()
st = searcher.session_status()
print(st)
assert st["authenticated"] is True, "a cookie is configured"
assert st["verified"] is False, "Pinterest must reject a bogus cookie"
assert st["hint"], "should explain the fallback"
print("\nOK: configured != verified")