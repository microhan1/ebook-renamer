"""Regenerate assets/icon.ico (used by build.bat for the exe's file icon).

    python tools/make_icon.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import icon  # noqa: E402

start = time.perf_counter()
data = icon.ico_bytes()
out = os.path.join(ROOT, "assets", "icon.ico")
with open(out, "wb") as f:
    f.write(data)
print(f"wrote {out} ({len(data)} bytes) in {time.perf_counter() - start:.1f}s")
