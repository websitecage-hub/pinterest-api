"""Inspect what Pinterest returns for a nonexistent pin vs a real pin,
to decide how to map 'not found' to a clean 404."""
import sys, json, re
sys.path.insert(0, 'app')
from extractor import extract_relay_payloads, _find_pin_obj, _fetch

for target in ("999999999999999999", "369858188161092508"):
    print(f"\n===== pin {target} =====")
    try:
        html = _fetch(f"https://www.pinterest.com/pin/{target}/")
        print("html size:", len(html))
        payloads = extract_relay_payloads(html)
        print("relay payloads:", len(payloads))
        pin_found = False
        for p in payloads:
            pin = _find_pin_obj(p)
            if pin is not None:
                pin_found = True
                print("PIN OBJECT FOUND, keys:", sorted(pin.keys())[:20])
                # look for error-ish fields
                for k in pin.keys():
                    if "error" in k.lower() or "message" in k.lower():
                        print("  error field:", k, "=", pin[k])
                break
        if not pin_found:
            print("no pin object in payloads")
            # dump top-level keys of each payload to see what's there
            for i, p in enumerate(payloads):
                print(f"payload[{i}] top keys:", sorted(p.keys())[:10])
    except Exception as e:
        print("FETCH FAILED:", type(e).__name__, e)
