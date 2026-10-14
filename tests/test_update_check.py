"""Update check: once a day, off switch, silent failures, what is sent, when a notice shows.
The network is always faked - these tests never reach the real server.

    python -m unittest tests.test_update_check -v
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import unittest
import urllib.error
import urllib.parse
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import update_check as uc  # noqa: E402
from version import __version__  # noqa: E402

DAY = "2026-10-13"
SLUG = "ebookrenamer"
OK = {"slug": SLUG, "latest": "0.3.0", "tag": "v0.3.0", "client": "0.2.2", "updateAvailable": True,
      "url": "https://chaekgalpi.co.kr/tools/ebookrenamer?utm_source=app&utm_medium=update"}


class FakeRoot:
    """after() runs the callback at once and records the delay."""

    def __init__(self) -> None:
        self.delays: list[int] = []

    def after(self, ms, fn):
        self.delays.append(ms)
        fn()


class FakeResp(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200) -> None:
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class InlineThread:
    def __init__(self, target, name=None, daemon=None) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


def counting(answer):
    calls: list = []

    def fetcher(slug, version):
        calls.append((slug, version))
        return answer

    return fetcher, calls


class Base(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(uc.threading, "Thread", InlineThread)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_start(self, prefs, fetcher, day=DAY):
        """One app start: schedule the check; the day is recorded only when answered (as the GUI does)."""
        results: list = []

        def on_result(info, answered):
            results.append(info)
            if answered:
                prefs.update_check_last = day

        root = FakeRoot()
        scheduled = uc.check_async(root, SLUG, "0.2.2", prefs, on_result, fetcher=fetcher, day=day)
        return scheduled, results, root


class HowOftenTests(Base):
    def test_same_day_twice_asks_once(self) -> None:
        p = uc.Prefs()
        fetcher, calls = counting(OK)
        self.run_start(p, fetcher)
        self.run_start(p, fetcher)
        self.assertEqual(len(calls), 1)
        self.run_start(p, fetcher, day="2026-10-14")
        self.assertEqual(len(calls), 2)

    def test_switched_off_never_asks(self) -> None:
        p = uc.Prefs(update_check=False)
        fetcher, calls = counting(OK)
        scheduled, results, root = self.run_start(p, fetcher)
        self.assertFalse(scheduled)
        self.assertEqual((calls, results, root.delays), ([], [], []))

    def test_offline_does_not_use_up_the_day(self) -> None:
        p = uc.Prefs()
        fetcher, calls = counting(None)
        self.run_start(p, fetcher)
        self.run_start(p, fetcher)
        self.assertEqual(len(calls), 2)
        self.assertEqual(p.update_check_last, "")

    def test_waits_one_and_a_half_seconds_first(self) -> None:
        _, _, root = self.run_start(uc.Prefs(), counting(OK)[0])
        self.assertEqual(root.delays[0], 1500)

    def test_a_closed_window_is_not_an_error(self) -> None:
        class Dead:
            def after(self, ms, fn):
                raise RuntimeError("application has been destroyed")

        self.assertFalse(uc.check_async(Dead(), SLUG, "0.2.2", uc.Prefs(), lambda i, a: None,
                                        fetcher=counting(OK)[0], day=DAY))

        class DiesLater:
            n = 0

            def after(self, ms, fn):
                DiesLater.n += 1
                if DiesLater.n == 1:
                    fn()
                else:
                    raise RuntimeError("gone")

        uc.check_async(DiesLater(), SLUG, "0.2.2", uc.Prefs(), lambda i, a: None, fetcher=counting(OK)[0], day=DAY)


class WhatIsSentTests(unittest.TestCase):
    def test_request_carries_only_slug_version_and_os(self) -> None:
        seen = {}

        def opener(req, timeout):
            seen["url"], seen["timeout"] = req.full_url, timeout
            seen["headers"] = {k.lower(): v for k, v in req.header_items()}
            return FakeResp(json.dumps(OK).encode())

        self.assertEqual(uc.fetch(SLUG, "0.2.2", opener=opener), OK)
        url = urllib.parse.urlsplit(seen["url"])
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "chaekgalpi.co.kr", "/api/tools/ebookrenamer/latest"))
        self.assertEqual(urllib.parse.parse_qs(url.query), {"v": ["0.2.2"], "os": ["win"]})
        self.assertEqual(seen["timeout"], 4.0)
        self.assertEqual(seen["headers"]["user-agent"], "chaekgalpi-tool/ebookrenamer/0.2.2")
        self.assertLessEqual(set(seen["headers"]), {"user-agent", "accept"})      # nothing else about the user or machine

    def test_the_slug_and_the_version_are_the_apps_own(self) -> None:
        self.assertEqual(uc.SLUG, "ebookrenamer")
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_failures_are_silent(self) -> None:
        def failing(behaviour):
            def opener(req, timeout):
                if behaviour == "urlerror":
                    raise urllib.error.URLError("offline")
                if behaviour == "timeout":
                    raise socket.timeout("slow")
                if behaviour == "http500":
                    raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)
                if behaviour == "http400":
                    raise urllib.error.HTTPError(req.full_url, 400, "bad v", {}, None)
                if behaviour == "oserror":
                    raise OSError("reset")
                if behaviour == "badjson":
                    return FakeResp(b"<html>not json")
                if behaviour == "badbytes":
                    return FakeResp(b"\xff\xfe\x00")
                if behaviour == "list":
                    return FakeResp(b"[1, 2]")
                return FakeResp(json.dumps(OK).encode(), status=500)
            return opener

        for behaviour in ("urlerror", "timeout", "http500", "http400", "badjson", "badbytes", "list", "status500", "oserror"):
            with self.subTest(behaviour=behaviour):
                self.assertIsNone(uc.fetch(SLUG, "0.2.2", opener=failing(behaviour)))

    def test_a_huge_answer_is_cut_off_not_read_whole(self) -> None:
        big = FakeResp(b'{"latest": "' + b"9" * (uc.MAX_BYTES * 2) + b'"}')
        self.assertIsNone(uc.fetch(SLUG, "0.2.2", opener=lambda req, timeout: big))


class WhenANoticeShowsTests(Base):
    def test_no_notice_unless_the_server_says_true(self) -> None:
        for flag in (False, None, "true", 1, [True], {}):
            with self.subTest(flag=flag):
                self.assertIsNone(uc.interpret(dict(OK, updateAvailable=flag), "0.2.2"))
        no_key = dict(OK)
        del no_key["updateAvailable"]
        self.assertIsNone(uc.interpret(no_key, "0.2.2"))

    def test_notice_once_when_newer(self) -> None:
        p = uc.Prefs()
        _, results, _ = self.run_start(p, counting(OK)[0])
        self.assertEqual(results, [uc.UpdateInfo("0.3.0", "0.2.2", OK["url"])])

    def test_not_a_dict_shows_nothing(self) -> None:
        for data in (None, [], "x", 3):
            self.assertIsNone(uc.interpret(data, "0.2.2"))

    def test_later_hides_that_version_but_not_a_newer_one(self) -> None:
        self.assertIsNone(uc.interpret(OK, "0.2.2", "0.3.0"))
        self.assertEqual(uc.interpret(dict(OK, latest="0.3.1"), "0.2.2", "0.3.0").latest, "0.3.1")

    def test_after_later_the_next_start_does_not_remind_again(self) -> None:
        p = uc.Prefs(update_check_skipped="0.3.0")
        _, results, _ = self.run_start(p, counting(OK)[0])
        self.assertEqual(results, [None])

    def test_only_pages_of_the_tools_site_are_opened(self) -> None:
        for url in ("https://github.com/microhan1/ebook-renamer/releases", "http://chaekgalpi.co.kr/tools/x",
                    "https://chaekgalpi.co.kr.evil.example/", "https://evil.example/https://chaekgalpi.co.kr/",
                    "javascript:alert(1)", "file:///C:/x.exe", "", None, 5):
            with self.subTest(url=url):
                self.assertIsNone(uc.interpret(dict(OK, url=url), "0.2.2"))

    def test_odd_versions_show_nothing(self) -> None:
        for latest in ("", "   ", None, 3, "x" * 40):
            with self.subTest(latest=latest):
                self.assertIsNone(uc.interpret(dict(OK, latest=latest), "0.2.2"))

    def test_the_answer_is_trimmed(self) -> None:
        self.assertEqual(uc.interpret(dict(OK, latest=" 0.3.0 "), "0.2.2").latest, "0.3.0")


class EnglishPageTests(unittest.TestCase):
    """[Update] opens the English tools page on a non-Korean screen when the server gives one."""
    EN = "https://chaekgalpi.co.kr/en/tools/ebookrenamer?utm_source=app&utm_medium=update"

    def info(self, **answer):
        return uc.interpret(dict(OK, **answer), "0.2.2")

    def test_korean_screen_gets_the_korean_page(self) -> None:
        self.assertEqual(uc.page_for(self.info(urlEn=self.EN), "ko"), OK["url"])

    def test_english_screen_gets_the_english_page(self) -> None:
        self.assertEqual(uc.page_for(self.info(urlEn=self.EN), "en"), self.EN)

    def test_japanese_and_chinese_screens_get_the_english_page(self) -> None:
        for lang in ("ja", "zh-CN"):
            with self.subTest(lang=lang):
                self.assertEqual(uc.page_for(self.info(urlEn=self.EN), lang), self.EN)

    def test_english_screen_falls_back_to_the_korean_page(self) -> None:
        no_key = self.info()
        self.assertEqual(uc.page_for(no_key, "en"), OK["url"])
        for bad in (None, "", 5, ["x"], "https://evil.example/en/tools/ebookrenamer",
                    "http://chaekgalpi.co.kr/en/tools/ebookrenamer", "https://chaekgalpi.co.kr.evil.example/en"):
            with self.subTest(urlEn=bad):
                info = self.info(urlEn=bad)
                self.assertEqual(info.url_en, "")
                self.assertEqual(uc.page_for(info, "en"), OK["url"])

    def test_an_english_page_does_not_rescue_a_bad_korean_one(self) -> None:
        self.assertIsNone(uc.interpret(dict(OK, url="https://evil.example/", urlEn=self.EN), "0.2.2"))

    def test_nothing_more_is_sent_to_the_server(self) -> None:
        seen = {}

        def opener(req, timeout):
            seen["url"] = req.full_url
            seen["headers"] = {k.lower() for k, _ in req.header_items()}
            return FakeResp(json.dumps(dict(OK, urlEn=self.EN)).encode())

        uc.fetch(SLUG, "0.2.2", opener=opener)
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(seen["url"]).query), {"v": ["0.2.2"], "os": ["win"]})
        self.assertLessEqual(seen["headers"], {"user-agent", "accept"})


class ThreadHandoffTests(unittest.TestCase):
    def test_the_thread_holds_no_tk_object(self) -> None:
        """The fetch thread must not keep the window alive: if it held the last reference,
        Tk objects would be freed off the main thread and Tcl aborts."""
        captured: dict = {}

        class CaptureThread:
            def __init__(self, target, name=None, daemon=None) -> None:
                captured["target"] = target

            def start(self) -> None:
                pass

        class Root:
            def after(self, ms, fn):
                if ms == uc.DELAY_MS:
                    fn()

        root, on_result = Root(), (lambda info, answered: None)
        with mock.patch.object(uc.threading, "Thread", CaptureThread):
            uc.check_async(root, SLUG, "0.2.2", uc.Prefs(), on_result, fetcher=lambda s, v: OK, day=DAY)
        target = captured["target"]
        held = [c.cell_contents for c in (target.__closure__ or ())] + list(target.__defaults__ or ())
        self.assertFalse(any(x is root or x is on_result for x in held))

    def test_the_answer_reaches_the_tk_side_by_polling(self) -> None:
        """No answer yet: the Tk side looks again after POLL_MS; once it is there, on_result runs once."""
        seen: list = []
        later: list = []

        class Root:
            def after(self, ms, fn):
                later.append((ms, fn))
                if ms == uc.DELAY_MS:
                    fn()

        threads: list = []

        class HeldThread:
            def __init__(self, target, name=None, daemon=None) -> None:
                self.target = target
                threads.append(self)

            def start(self) -> None:
                pass

        with mock.patch.object(uc.threading, "Thread", HeldThread):
            uc.check_async(Root(), SLUG, "0.2.2", uc.Prefs(), lambda i, a: seen.append((i, a)),
                           fetcher=lambda s, v: OK, day=DAY)
        self.assertEqual((seen, [ms for ms, _ in later]), ([], [uc.DELAY_MS, uc.POLL_MS]))
        later[-1][1]()                                  # polled before the thread is done: asks again later
        self.assertEqual((seen, later[-1][0]), ([], uc.POLL_MS))
        threads[0].target()                             # the thread finishes
        later[-1][1]()
        self.assertEqual(seen, [(uc.UpdateInfo("0.3.0", "0.2.2", OK["url"]), True)])

    def test_closing_the_window_while_the_request_is_out_does_not_abort_tcl(self) -> None:
        """Before the fix this died with "Tcl_AsyncDelete: async handler deleted by the wrong thread"."""
        import subprocess
        import tempfile

        script = (CLOSE_WHILE_ASKING.format(root=ROOT))
        with tempfile.TemporaryDirectory(prefix="ebr_close_") as tmp:
            path = os.path.join(tmp, "close_while_asking.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            try:
                p = subprocess.run([sys.executable, "-W", "ignore", path], capture_output=True, timeout=120)
            except Exception as exc:                    # no display (no Tk) is not a failure of this code
                self.skipTest(f"cannot run a window here: {exc}")
        out = (p.stdout + p.stderr).decode("utf-8", "replace")
        if "TclError" in out and "display" in out:
            self.skipTest("no display")
        self.assertTrue(p.returncode == 0 and "survived" in out and "Tcl_AsyncDelete" not in out, out[-800:])


CLOSE_WHILE_ASKING = r'''
import os, sys, tempfile, time
sys.path.insert(0, {root!r})
import i18n
i18n.SETTINGS_PATH = os.path.join(tempfile.mkdtemp(), "settings.json")     # never the user's file
i18n.init("en")
import gui, update_check as uc
def slow(slug, version, **kw):
    time.sleep(1.5)          # the request is still out when the window closes
    return {{"latest": "9.9.9", "updateAvailable": True, "url": "https://chaekgalpi.co.kr/tools/ebookrenamer"}}
uc.fetch = slow
for _ in range(3):
    app = gui.App(scale=1.0)
    app.root.after(1700, app._on_close)      # 0.2 s into the request
    app.root.mainloop()
    del app
    time.sleep(2.0)          # the thread finishes with no window left
print("survived")
'''


class SettingsTests(unittest.TestCase):
    def test_defaults_when_nothing_is_saved(self) -> None:
        self.assertEqual(uc.load_prefs({}), uc.Prefs(True, "", ""))

    def test_settings_are_type_checked(self) -> None:
        p = uc.load_prefs({"update_check": "no", "update_check_last": 20261013, "update_check_skipped": ["0.3.0"]})
        self.assertEqual(p, uc.Prefs(True, "", ""))

    def test_values_are_trimmed_and_capped(self) -> None:
        p = uc.load_prefs({"update_check": False, "update_check_last": " 2026-10-13xxxxxx ", "update_check_skipped": "v" * 80})
        self.assertIs(p.update_check, False)
        self.assertEqual(p.update_check_last, "2026-10-13")
        self.assertEqual(len(p.update_check_skipped), 32)

    def test_storing_keeps_the_other_settings(self) -> None:
        settings = {"lang": "ko", "options": {"pattern": "{title}"}}
        uc.store_prefs(settings, uc.Prefs(False, DAY, "0.3.0"))
        self.assertEqual(settings, {"lang": "ko", "options": {"pattern": "{title}"}, "update_check": False,
                                   "update_check_last": DAY, "update_check_skipped": "0.3.0"})
        self.assertEqual(uc.load_prefs(settings), uc.Prefs(False, DAY, "0.3.0"))

    def test_today_is_an_iso_date(self) -> None:
        self.assertRegex(uc.today(), r"^\d{4}-\d{2}-\d{2}$")

    def test_the_module_uses_the_standard_library_only(self) -> None:
        with open(os.path.join(ROOT, "update_check.py"), encoding="utf-8") as f:
            source = f.read()
        imported = {line.split()[1].split(".")[0] for line in source.splitlines() if line.startswith(("import ", "from "))}
        self.assertLessEqual(imported, {"__future__", "dataclasses", "datetime", "json", "threading", "urllib", "typing"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
