"""Tests for ebook-renamer. Run from the repository root:

    python -m unittest discover -s tests -v

Every test works on a fresh temporary copy of generated files; the samples
folder itself is never touched.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "samples"))

import i18n  # noqa: E402
import main  # noqa: E402
import make_samples  # noqa: E402
import meta  # noqa: E402
import namer  # noqa: E402
import undo  # noqa: E402

i18n.init("ko")


def opts(**kw) -> namer.Options:
    base = dict(others_suffix="\uc678 {n}\uba85")     # the Korean others_suffix, fixed so test order does not matter
    base.update(kw)
    return namer.Options(**base).validated()


def items_for(folder: str, recursive: bool = False) -> list[namer.Item]:
    return [namer.Item(path=p, meta=meta.read_meta(p)) for p in meta.collect_files([folder], recursive)]


class TempFolder(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="ebr_")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def names(self) -> set[str]:
        return {n for n in os.listdir(self.dir) if not n.endswith(".json")}


class SanitizeTests(unittest.TestCase):
    def test_forbidden_chars_and_spaces(self) -> None:
        self.assertEqual(namer.sanitize('  a\\b/c:d*e?f"g<h>i|j   k  '), "abcdefghij k")

    def test_length_and_trailing_dots(self) -> None:
        self.assertEqual(len(namer.sanitize("x" * 300)), namer.MAX_STEM)
        self.assertEqual(namer.sanitize("name. "), "name")

    def test_reserved_windows_names(self) -> None:
        self.assertEqual(namer.sanitize("CON"), "CON_")

    def test_nfc(self) -> None:
        import unicodedata

        nfd = unicodedata.normalize("NFD", "\ud64d\uae38\ub3d9")
        self.assertEqual(namer.sanitize(nfd), "\ud64d\uae38\ub3d9")

    def test_pattern_with_missing_parts(self) -> None:
        m = meta.Meta(title="Only Title")
        self.assertEqual(namer.build_stem(m, opts()), "Only Title")
        self.assertEqual(namer.build_stem(m, opts(pattern="{title} ({year}) - {author}")), "Only Title")
        m = meta.Meta(authors=["Only Author"])
        self.assertEqual(namer.build_stem(m, opts(pattern="{title}")), "Only Author")
        self.assertEqual(namer.build_stem(meta.Meta(), opts()), "")

    def test_others_suffix(self) -> None:
        m = meta.Meta(title="T", authors=["A", "B", "C"])
        self.assertEqual(namer.build_stem(m, opts()), "A - T")
        self.assertEqual(namer.build_stem(m, opts(others=True)), "A \uc678 2\uba85 - T")

    def test_options_validated(self) -> None:
        self.assertEqual(namer.Options(pattern="no placeholders").validated().pattern, namer.DEFAULT_PATTERN)
        self.assertEqual(namer.Options(pattern=None, recursive="yes").validated().recursive, True)  # type: ignore


class MetaTests(TempFolder):
    def test_epub_and_pdf(self) -> None:
        make_samples.main(self.dir)
        m = meta.read_meta(os.path.join(self.dir, "book_v3.epub"))
        self.assertEqual((m.title, m.author, m.year), ("\ud64d\uae38\ub3d9\uc804", "\ud5c8\uade0", "1612"))
        m = meta.read_meta(os.path.join(self.dir, "coauthors.epub"))
        self.assertEqual(len(m.authors), 2)
        m = meta.read_meta(os.path.join(self.dir, "Document1.pdf"))
        self.assertEqual((m.title, m.author, m.year), ("The Art of War", "Sun Tzu", "2020"))
        m = meta.read_meta(os.path.join(self.dir, "bad_chars.epub"))
        self.assertEqual(m.title, 'What: Is "Art"? <Part 1/2>')

    def test_failures_are_not_exceptions(self) -> None:
        make_samples.main(self.dir)
        self.assertEqual(meta.read_meta(os.path.join(self.dir, "locked.pdf")).error, "password")
        self.assertTrue(meta.read_meta(os.path.join(self.dir, "no_metadata.epub")).empty)
        self.assertTrue(meta.read_meta(os.path.join(self.dir, "empty_meta.pdf")).empty)
        for name, content in (("zero.epub", b""), ("text.pdf", b"hello"), ("bad.epub", b"PK\x03\x04junk")):
            with open(os.path.join(self.dir, name), "wb") as f:
                f.write(content)
            self.assertEqual(meta.read_meta(os.path.join(self.dir, name)).error, "open_failed", name)

    def test_collect(self) -> None:
        sub = os.path.join(self.dir, "sub")
        os.makedirs(sub)
        for name in ("a.EPUB", "b.pdf", "c.txt"):
            open(os.path.join(self.dir, name), "wb").close()
        open(os.path.join(sub, "d.Pdf"), "wb").close()
        flat = [os.path.basename(p) for p in meta.collect_files([self.dir])]
        self.assertEqual(flat, ["a.EPUB", "b.pdf"])
        deep = [os.path.basename(p) for p in meta.collect_files([self.dir], recursive=True)]
        self.assertEqual(deep, ["a.EPUB", "b.pdf", "d.Pdf"])
        # a file given twice appears once
        self.assertEqual(len(meta.collect_files([os.path.join(self.dir, "b.pdf")] * 2)), 1)


class PlanApplyUndoTests(TempFolder):
    def test_full_cycle(self) -> None:
        make_samples.main(self.dir)
        before = self.names()
        items = items_for(self.dir)
        namer.plan(items, opts())
        nometa = {it.current for it in items if it.status == namer.NOMETA}
        self.assertEqual(nometa, {"empty_meta.pdf", "locked.pdf", "no_metadata.epub"})
        self.assertTrue(all(not it.selected for it in items if it.status == namer.NOMETA))

        result = namer.apply(items)
        self.assertEqual(result.failed, [])
        self.assertEqual(len(result.renamed), len(items) - len(nometa))
        self.assertTrue(nometa <= self.names())                      # never touched
        self.assertIn("\ud5c8\uade0 - \ud64d\uae38\ub3d9\uc804.epub", self.names())
        self.assertIn("Anonymous - What Is Art Part 12.epub", self.names())
        self.assertEqual(undo.record(result.renamed), [self.dir])
        self.assertTrue(os.path.exists(undo.log_path(self.dir)))

        res = undo.undo(self.dir)
        self.assertEqual(res.skipped, [])
        self.assertEqual(self.names(), before)
        self.assertFalse(os.path.exists(undo.log_path(self.dir)))    # empty log is removed

    def test_duplicates_get_numbers(self) -> None:
        for i in range(3):
            make_samples.make_epub(os.path.join(self.dir, f"copy{i}.epub"), i, "en", "Same", ["Author"], None)
        make_samples.make_epub(os.path.join(self.dir, "Author - Same.epub"), 9, "en", "Same", ["Author"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        by = {it.current: it for it in items}
        self.assertEqual(by["Author - Same.epub"].status, namer.NOCHANGE)
        news = sorted(it.new_name for it in items if it.status == namer.DUP)
        self.assertEqual(news, ["Author - Same (2).epub", "Author - Same (3).epub", "Author - Same (4).epub"])
        namer.apply(items)
        self.assertEqual(self.names(), {"Author - Same.epub", "Author - Same (2).epub",
                                        "Author - Same (3).epub", "Author - Same (4).epub"})

    def test_swap_cycle(self) -> None:
        make_samples.make_epub(os.path.join(self.dir, "B - A.epub"), 1, "en", "B", ["A"], None)
        make_samples.make_epub(os.path.join(self.dir, "A - B.epub"), 2, "en", "A", ["B"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        self.assertEqual({it.status for it in items}, {namer.OK})
        result = namer.apply(items)
        self.assertEqual(result.failed, [])
        self.assertEqual(self.names(), {"A - B.epub", "B - A.epub"})
        self.assertEqual(meta.read_meta(os.path.join(self.dir, "A - B.epub")).title, "B")
        self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(self.dir)))
        undo.record(result.renamed)
        undo.undo(self.dir)
        self.assertEqual(meta.read_meta(os.path.join(self.dir, "A - B.epub")).title, "A")

    def test_manual_name_includes_nometa_file(self) -> None:
        make_samples.make_epub(os.path.join(self.dir, "x.epub"), 1, "en", None, [], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        self.assertFalse(items[0].selected)
        namer.set_manual_name(items[0], 'Typed: "Name".epub')
        namer.plan(items, opts())
        self.assertTrue(items[0].selected)
        self.assertEqual(items[0].new_name, "Typed Name.epub")
        namer.set_manual_name(items[0], "")
        namer.plan(items, opts())
        self.assertEqual(items[0].status, namer.NOMETA)

    def test_locked_file_fails_alone(self) -> None:
        make_samples.make_epub(os.path.join(self.dir, "a.epub"), 1, "en", "One", ["X"], None)
        make_samples.make_epub(os.path.join(self.dir, "b.epub"), 2, "en", "Two", ["X"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        with open(os.path.join(self.dir, "a.epub"), "rb"):
            result = namer.apply(items)
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(result.failed[0][0].current, "a.epub")
        self.assertEqual(result.failed[0][0].status, namer.FAILED)
        self.assertEqual([os.path.basename(n) for _, n in result.renamed], ["X - Two.epub"])
        undo.record(result.renamed)
        with open(undo.log_path(self.dir), encoding="utf-8") as f:
            log = json.load(f)
        self.assertEqual(log["sessions"][0]["entries"], [{"from": "b.epub", "to": "X - Two.epub"}])

    def test_undo_skips_when_original_name_taken(self) -> None:
        make_samples.make_epub(os.path.join(self.dir, "a.epub"), 1, "en", "One", ["X"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        undo.record(namer.apply(items).renamed)
        open(os.path.join(self.dir, "a.epub"), "wb").close()    # someone re-used the old name
        res = undo.undo(self.dir)
        self.assertEqual([r for _, r in res.skipped], ["exists"])
        self.assertIn("X - One.epub", self.names())
        self.assertTrue(undo.has_log(self.dir))                 # kept for a retry
        os.remove(os.path.join(self.dir, "a.epub"))
        res = undo.undo(self.dir)
        self.assertEqual(res.skipped, [])
        self.assertEqual(self.names(), {"a.epub"})

    def test_undo_without_log(self) -> None:
        self.assertEqual(undo.find_logs([self.dir]), [])
        self.assertEqual(undo.undo(self.dir).restored, [])

    def test_broken_log_is_ignored(self) -> None:
        with open(undo.log_path(self.dir), "w") as f:
            f.write("{not json")
        self.assertFalse(undo.has_log(self.dir))
        with open(undo.log_path(self.dir), "w") as f:
            json.dump({"sessions": "oops"}, f)
        self.assertFalse(undo.has_log(self.dir))

    def test_recursive_logs_per_folder(self) -> None:
        sub = os.path.join(self.dir, "sub")
        os.makedirs(sub)
        make_samples.make_epub(os.path.join(self.dir, "a.epub"), 1, "en", "One", ["X"], None)
        make_samples.make_epub(os.path.join(sub, "b.epub"), 2, "en", "Two", ["Y"], None)
        items = items_for(self.dir, recursive=True)
        namer.plan(items, opts())
        folders = undo.record(namer.apply(items).renamed)
        self.assertEqual(sorted(folders), sorted([self.dir, sub]))
        self.assertEqual(len(undo.find_logs([self.dir], recursive=True)), 2)
        self.assertEqual(len(undo.find_logs([self.dir])), 1)


class PerformanceTests(TempFolder):
    def test_300_files_under_5_seconds_and_full_undo(self) -> None:
        for i in range(150):
            make_samples.make_epub(os.path.join(self.dir, f"e{i:03}.epub"), i, "ko",
                                   f"\uc81c\ubaa9 {i}", [f"\uc800\uc790 {i % 40}"], "2020")
        import pymupdf

        for i in range(150):
            doc = pymupdf.open()
            doc.new_page()
            doc.set_metadata({"title": f"Title {i}", "author": f"Author {i % 40}"})
            doc.save(os.path.join(self.dir, f"p{i:03}.pdf"))
            doc.close()
        before = self.names()
        t0 = time.perf_counter()
        items = items_for(self.dir)
        namer.plan(items, opts())
        elapsed = time.perf_counter() - t0
        print(f"\n  300 files read + planned in {elapsed:.2f}s")
        self.assertLess(elapsed, 5.0)
        result = namer.apply(items)
        self.assertEqual(result.failed, [])
        self.assertEqual(len(result.renamed), 300)
        undo.record(result.renamed)
        res = undo.undo(self.dir)
        self.assertEqual(len(res.restored), 300)
        self.assertEqual(self.names(), before)


class CliTests(TempFolder):
    def test_dry_run_changes_nothing(self) -> None:
        make_samples.main(self.dir)
        before = self.names()
        code = main.main([self.dir, "--dry-run", "--lang", "en"])
        self.assertEqual(code, 0)
        self.assertEqual(self.names(), before)
        self.assertFalse(os.path.exists(undo.log_path(self.dir)))

    def test_run_and_undo(self) -> None:
        make_samples.main(self.dir)
        before = self.names()
        code = main.main([self.dir, "--pattern", "{title} - {author}", "-y", "--lang", "en"])
        self.assertEqual(code, 0)
        self.assertIn("Pride and Prejudice - Jane Austen.epub", self.names())
        self.assertEqual(main.main([self.dir, "--undo", "--lang", "en"]), 0)
        self.assertEqual(self.names(), before)
        self.assertEqual(main.main([self.dir, "--undo", "--lang", "en"]), 2)   # nothing to undo

    def test_no_input(self) -> None:
        self.assertEqual(main.main([os.path.join(self.dir, "missing"), "--lang", "en"]), 2)


class SettingsTests(unittest.TestCase):
    def test_broken_settings_fall_back(self) -> None:
        import gui

        self.assertEqual(gui._saved_options({}).pattern, namer.DEFAULT_PATTERN)
        o = gui._saved_options({"options": {"pattern": 5, "recursive": "yes", "others": 1}})
        self.assertEqual((o.pattern, o.recursive, o.others), (namer.DEFAULT_PATTERN, False, False))
        o = gui._saved_options({"options": "garbage"})
        self.assertEqual(o.pattern, namer.DEFAULT_PATTERN)


if __name__ == "__main__":
    unittest.main(verbosity=2)
