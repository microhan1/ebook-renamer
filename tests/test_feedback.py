"""[Send feedback]: the address it opens, in every language and with odd versions, and the
words on it. The address is built from constants only and nothing is sent anywhere - these
tests also make sure building it touches no socket. The window side (one browser call, what
happens when no browser opens) is in test_ui.WindowTests.

    python -m unittest tests.test_feedback -v
"""
from __future__ import annotations

import json
import os
import socket
import sys
import unittest
import urllib.parse
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import i18n  # noqa: E402
import update_check as uc  # noqa: E402
from version import __version__  # noqa: E402

KO_PAGE = "https://chaekgalpi.co.kr/tools/ebookrenamer"
EN_PAGE = "https://chaekgalpi.co.kr/en/tools/ebookrenamer"
QUERY = "?utm_source=app&utm_medium=feedback"
HANGUL = chr(0xD55C) + chr(0xAE00)          # two Korean syllables, kept out of the source as literals


def url(lang, version="0.2.4") -> str:
    return uc.feedback_url(uc.SLUG, version, lang)


def query_of(address: str) -> dict:
    return urllib.parse.parse_qs(urllib.parse.urlsplit(address).query, keep_blank_values=True, strict_parsing=True)


class AddressTests(unittest.TestCase):
    def test_exact_address_in_each_language(self) -> None:
        expected = {"ko": f"{KO_PAGE}{QUERY}&v=0.2.4#feedback",
                    "en": f"{EN_PAGE}{QUERY}&v=0.2.4#feedback",
                    "ja": f"{EN_PAGE}{QUERY}&v=0.2.4#feedback",        # no Japanese page
                    "zh-CN": f"{EN_PAGE}{QUERY}&v=0.2.4#feedback"}     # no Chinese page
        self.assertEqual(set(expected), set(i18n.LANGS))
        for lang, address in expected.items():
            with self.subTest(lang=lang):
                self.assertEqual(url(lang), address)

    def test_unknown_or_missing_language_gets_the_korean_page(self) -> None:
        for lang in (None, "", "fr", "zh-TW", "zh", "english", " en", 7, ["en"]):
            with self.subTest(lang=lang):
                self.assertEqual(url(lang), f"{KO_PAGE}{QUERY}&v=0.2.4#feedback")

    def test_language_code_case_does_not_matter(self) -> None:
        for lang in ("EN", "En", "JA", "zh-cn", "ZH-CN", "Zh-Cn"):
            with self.subTest(lang=lang):
                self.assertEqual(url(lang), f"{EN_PAGE}{QUERY}&v=0.2.4#feedback")
        self.assertEqual(url("KO"), f"{KO_PAGE}{QUERY}&v=0.2.4#feedback")

    def test_shape_of_every_address(self) -> None:
        for lang in i18n.LANGS + ("xx", None):
            with self.subTest(lang=lang):
                address = url(lang)
                self.assertTrue(address.startswith("https://chaekgalpi.co.kr/"))
                self.assertTrue(address.startswith(uc.SITE))
                self.assertTrue(address.endswith("#feedback"))
                self.assertEqual(address.count("#"), 1)
                parts = urllib.parse.urlsplit(address)
                self.assertEqual((parts.scheme, parts.hostname, parts.fragment), ("https", "chaekgalpi.co.kr", "feedback"))
                self.assertTrue(parts.path.endswith("/tools/ebookrenamer"))
                q = query_of(address)
                self.assertEqual(q["utm_source"], ["app"])
                self.assertEqual(q["utm_medium"], ["feedback"])
                self.assertIn("utm_source=app", address)
                self.assertIn("utm_medium=feedback", address)

    def test_the_app_uses_its_own_slug_and_version(self) -> None:
        address = uc.feedback_url(uc.SLUG, __version__, "ko")
        self.assertEqual(address, f"{KO_PAGE}{QUERY}&v={__version__}#feedback")
        self.assertEqual(uc.SLUG, "ebookrenamer")


class VersionValueTests(unittest.TestCase):
    def test_plain_and_prefixed_versions(self) -> None:
        self.assertEqual(url("ko", "0.2.1"), f"{KO_PAGE}{QUERY}&v=0.2.1#feedback")
        self.assertEqual(url("ko", "v0.2.1"), f"{KO_PAGE}{QUERY}&v=v0.2.1#feedback")

    def test_plus_is_encoded_so_it_does_not_turn_into_a_space(self) -> None:
        address = url("en", "1.0.0-beta+3")
        self.assertEqual(address, f"{EN_PAGE}{QUERY}&v=1.0.0-beta%2B3#feedback")
        self.assertEqual(query_of(address)["v"], ["1.0.0-beta+3"])

    def test_empty_version_leaves_v_out(self) -> None:
        for version in ("", None, "   ", "\t\n"):
            with self.subTest(version=version):
                address = url("ko", version)
                self.assertEqual(address, f"{KO_PAGE}{QUERY}#feedback")
                self.assertNotIn("v", query_of(address))
                self.assertNotIn("&v=", address)

    def test_odd_versions_are_encoded_and_read_back_unchanged(self) -> None:
        odd = ["0.2 beta", "1.0&utm_source=evil", "2.0#top", "3.0?x=1", "a/b", "100%", "x=y", "1.0;2",
               "v" + HANGUL, HANGUL + " 1.0 & #", " 0.2.4 ", "0.2.4\n", "'\"<>", "+" * 5, "%2B", "a" * 300]
        for version in odd:
            for lang in ("ko", "en"):
                with self.subTest(version=version, lang=lang):
                    address = url(lang, version)
                    parts = urllib.parse.urlsplit(address)
                    self.assertEqual(parts.fragment, "feedback")
                    self.assertTrue(parts.path.endswith("/tools/ebookrenamer"))
                    q = query_of(address)
                    self.assertEqual(set(q), {"utm_source", "utm_medium", "v"})
                    self.assertEqual(q["utm_source"], ["app"])
                    self.assertEqual(q["v"], [version])
                    self.assertTrue(address.isascii())
                    self.assertNotIn(" ", address)
                    self.assertEqual(address.count("#"), 1)
                    self.assertEqual(address.count("?"), 1)

    def test_a_non_string_version_is_used_as_text(self) -> None:
        self.assertEqual(query_of(url("ko", 3))["v"], ["3"])


class NoNetworkTests(unittest.TestCase):
    def test_building_the_address_opens_no_connection(self) -> None:
        calls: list = []

        def refuse(*a, **k):
            calls.append(a)
            raise AssertionError("network used")

        with mock.patch.object(socket.socket, "connect", refuse), \
                mock.patch.object(socket, "create_connection", refuse), \
                mock.patch.object(socket, "getaddrinfo", refuse), \
                mock.patch("urllib.request.urlopen", refuse):
            for lang in i18n.LANGS:
                url(lang, __version__)
        self.assertEqual(calls, [])


class WordsTests(unittest.TestCase):
    """The button and the "could not open a browser" message in all four languages."""
    BUTTON = {"ko": bytes.fromhex("ec9d98eab2ac20ebb3b4eb82b4eab8b0").decode(),
              "en": "Send feedback",
              "ja": bytes.fromhex("e38194e6848fe8a68be38292e98081e3828b").decode(),
              "zh-CN": bytes.fromhex("e58f91e98081e58f8de9a688").decode()}

    def load(self, lang: str) -> dict:
        with open(os.path.join(ROOT, "lang", f"{lang}.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_keys_exist_and_are_not_empty_in_every_language(self) -> None:
        for lang in i18n.LANGS:
            data = self.load(lang)
            for key in ("btn_feedback", "err_feedback_open"):
                with self.subTest(lang=lang, key=key):
                    self.assertIsInstance(data.get(key), str)
                    self.assertTrue(data[key].strip())

    def test_button_words_are_the_agreed_ones(self) -> None:
        for lang, words in self.BUTTON.items():
            with self.subTest(lang=lang):
                self.assertEqual(self.load(lang)["btn_feedback"], words)

    def test_failure_message_shows_the_address_on_its_own_line(self) -> None:
        address = url("ko", __version__)
        for lang in i18n.LANGS:
            with self.subTest(lang=lang):
                text = self.load(lang)["err_feedback_open"]
                self.assertEqual(text.count("{url}"), 1)
                self.assertTrue(text.endswith("\n{url}"))
                self.assertTrue(text.format(url=address).endswith("\n" + address))


if __name__ == "__main__":
    unittest.main(verbosity=2)
