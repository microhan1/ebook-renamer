"""Keep every test away from the production server.

The update check asks https://chaekgalpi.co.kr/api/tools/ebookrenamer/latest once a day, and
each such request is counted on the site as a real start of the tool. A test that opens a
window with the check switched on, or calls fetch() with its default opener, would inflate that
count. Patching ``update_check.fetch`` is not enough: ``fetch(opener=urllib.request.urlopen)``
and ``check_async(fetcher=fetch)`` bind their defaults when the module is defined, so the
defaults themselves are replaced here, and ``urllib.request.urlopen`` too.

A blocked attempt raises URLError before any connection is made and is recorded in
``attempts``; the test that made it is then failed (conftest.py under pytest, the window
tests' tearDown under unittest).
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import update_check  # noqa: E402

HOST = "chaekgalpi.co.kr"
attempts: list[str] = []
_real_urlopen = urllib.request.urlopen


def _is_production(url) -> bool:
    full = getattr(url, "full_url", url)
    try:
        host = (urllib.parse.urlsplit(str(full)).hostname or "").lower()
    except ValueError:
        return False
    return host == HOST or host.endswith("." + HOST)


def guarded_urlopen(url, *args, **kwargs):
    """urlopen that refuses the production server and remembers who tried."""
    if _is_production(url):
        attempts.append(str(getattr(url, "full_url", url)))
        raise urllib.error.URLError("blocked in tests: no request to the production server")
    return _real_urlopen(url, *args, **kwargs)


def null_fetcher(slug, version, **kwargs):
    """check_async's default fetcher in tests: no answer, as if offline."""
    return None


def install() -> None:
    """Idempotent: safe to call before every test."""
    urllib.request.urlopen = guarded_urlopen
    update_check.fetch.__kwdefaults__["opener"] = guarded_urlopen
    update_check.check_async.__kwdefaults__["fetcher"] = null_fetcher


def take() -> list[str]:
    """The attempts so far, and forget them."""
    got = list(attempts)
    attempts.clear()
    return got


install()
