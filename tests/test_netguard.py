"""The guard itself: no test can reach the production server through the update check.

    python -m unittest tests.test_netguard -v
"""
from __future__ import annotations

import os
import sys
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests import _netguard  # noqa: E402
import update_check  # noqa: E402


class NetGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        _netguard.install()
        _netguard.take()

    def tearDown(self) -> None:
        _netguard.take()        # the attempts below are made on purpose

    def test_defaults_are_the_guard(self) -> None:
        self.assertIs(urllib.request.urlopen, _netguard.guarded_urlopen)
        self.assertIs(update_check.fetch.__kwdefaults__["opener"], _netguard.guarded_urlopen)
        self.assertIs(update_check.check_async.__kwdefaults__["fetcher"], _netguard.null_fetcher)
        self.assertIsNone(update_check.check_async.__kwdefaults__["fetcher"]("ebookrenamer", "0.0.0"))

    def test_fetch_without_an_opener_is_recorded_and_returns_none(self) -> None:
        self.assertIsNone(update_check.fetch("ebookrenamer", "0.0.0"))
        tried = _netguard.take()
        self.assertEqual(len(tried), 1)
        self.assertTrue(tried[0].startswith("https://chaekgalpi.co.kr/api/tools/ebookrenamer/latest?"), tried)

    def test_urlopen_refuses_the_site_and_its_subdomains_only(self) -> None:
        for url in ("https://chaekgalpi.co.kr/api/tools/ebookrenamer/latest", "http://CHAEKGALPI.co.kr/",
                    "https://www.chaekgalpi.co.kr/x", urllib.request.Request("https://chaekgalpi.co.kr/en/tools/x")):
            with self.subTest(url=getattr(url, "full_url", url)):
                with self.assertRaises(urllib.error.URLError):
                    urllib.request.urlopen(url, timeout=1)
        self.assertEqual(len(_netguard.take()), 4)
        self.assertFalse(_netguard._is_production("https://chaekgalpi.co.kr.evil.example/"))
        self.assertFalse(_netguard._is_production("https://example.com/?u=chaekgalpi.co.kr"))

    def test_install_twice_is_harmless(self) -> None:
        _netguard.install()
        _netguard.install()
        self.assertIs(urllib.request.urlopen, _netguard.guarded_urlopen)
        self.assertIsNot(_netguard._real_urlopen, _netguard.guarded_urlopen)


if __name__ == "__main__":
    unittest.main(verbosity=2)
