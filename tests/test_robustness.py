"""Robustness tests: things that went wrong, or could, when the tool meets real
folders. Each class pins one risk found while testing against copies of real
e-books. Run from the repository root:

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "samples"))

import i18n  # noqa: E402
import main  # noqa: E402
import make_samples  # noqa: E402
import meta  # noqa: E402
import namer  # noqa: E402
import undo  # noqa: E402

i18n.init("en")

OPF_NS = 'xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/"'


def opts(**kw) -> namer.Options:
    return namer.Options(others_suffix="and {n} more", **kw).validated()


def items_for(folder: str, recursive: bool = False) -> list[namer.Item]:
    return [namer.Item(path=p, meta=meta.read_meta(p)) for p in meta.collect_files([folder], recursive)]


def epub(path: str, title, author="A", date=None) -> None:
    make_samples.make_epub(path, 1, "en", title, [author] if author else [], date)


class TempFolder(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="ebr_rob_")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def p(self, *parts: str) -> str:
        return os.path.join(self.dir, *parts)

    def names(self, folder: str | None = None) -> set[str]:
        return {n for n in os.listdir(folder or self.dir) if not n.startswith("rename_log")}

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), *args], capture_output=True,
                              text=True, encoding="utf-8", cwd=ROOT, stdin=subprocess.DEVNULL)


# ============================================================ characters
class InvisibleCharacterTests(unittest.TestCase):
    def test_controls_and_lone_surrogates_are_removed(self) -> None:
        raw = "Bad" + chr(0x7F) + "Del" + chr(0x85) + "C1" + chr(0xD800) + "Lone" + chr(0xDFFF) + "End"
        self.assertEqual(meta._clean(raw), "BadDelC1LoneEnd")

    def test_bidi_override_cannot_disguise_the_extension(self) -> None:
        spoof = "invoice" + chr(0x202E) + "fdp.exe"
        self.assertNotIn(chr(0x202E), meta._clean(spoof))
        for c in (0x202A, 0x202B, 0x202C, 0x202D, 0x2066, 0x2067, 0x2068, 0x2069, 0x200E, 0x200F, 0x061C):
            self.assertEqual(meta._clean("a" + chr(c) + "b"), "ab", hex(c))

    def test_emoji_joiner_and_variation_selector_survive(self) -> None:
        family = "\U0001F469" + chr(0x200D) + "\U0001F4BB"
        self.assertEqual(meta._clean(family), family)
        self.assertEqual(meta._clean("\u2764" + chr(0xFE0F)), "\u2764" + chr(0xFE0F))
        self.assertEqual(meta._clean("a" + chr(0x200C) + "b"), "a" + chr(0x200C) + "b")   # ZWNJ is meaningful

    def test_zero_width_and_bom_are_removed(self) -> None:
        self.assertEqual(meta._clean(chr(0xFEFF) + "x" + chr(0x200B) + "y" + chr(0xAD) + "z"), "xyz")

    def test_line_and_paragraph_separators_become_spaces(self) -> None:
        self.assertEqual(meta._clean("a" + chr(0x2028) + "b" + chr(0x2029) + "c\vd\fe"), "a b c d e")

    def test_raw_pdf_with_lone_surrogate_title(self) -> None:
        """A UTF-16BE title holding a lone high surrogate: must not crash, must not
        reach the file name."""
        tmp = tempfile.mkdtemp(prefix="ebr_sur_")
        try:
            raw = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                   b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                   b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]>>endobj\n"
                   b"4 0 obj<</Title<FEFF0041D8000042>/Author<FEFFDC00004300>>>endobj\n"
                   b"trailer<</Root 1 0 R/Info 4 0 R/Size 5>>\n%%EOF\n")
            path = os.path.join(tmp, "s.pdf")
            with open(path, "wb") as f:
                f.write(raw)
            m = meta.read_meta(path)
            for text in [m.title] + m.authors:
                self.assertFalse(any(0xD800 <= ord(c) <= 0xDFFF for c in text), repr(text))
            items = [namer.Item(path=path, meta=m)]
            namer.plan(items, opts())
            if items[0].new_name:
                self.assertEqual(namer.apply(items).failed, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ReservedNameTests(unittest.TestCase):
    def test_device_name_before_first_dot(self) -> None:
        self.assertEqual(namer.sanitize("CON"), "CON_")
        self.assertEqual(namer.sanitize("con.Title"), "con_.Title")
        self.assertEqual(namer.sanitize("COM1.v2"), "COM1_.v2")
        self.assertEqual(namer.sanitize("NUL .x"), "NUL _.x")
        self.assertEqual(namer.sanitize("CONIN$"), "CONIN$_")

    def test_superscript_device_names(self) -> None:
        for name in ("COM" + chr(0xB9), "LPT" + chr(0xB2), "COM" + chr(0xB3)):
            self.assertTrue(namer.sanitize(name).endswith("_"), name)

    def test_names_that_merely_start_with_a_device_name(self) -> None:
        for name in ("CONTINUE", "Console", "COM10", "CON (2)", "A.CON", "NULL"):
            self.assertEqual(namer.sanitize(name), name)

    def test_reserved_title_gets_a_real_file(self) -> None:
        tmp = tempfile.mkdtemp(prefix="ebr_res_")
        try:
            epub(os.path.join(tmp, "a.epub"), "CON.Title", author=None)
            items = items_for(tmp)
            namer.plan(items, opts())
            self.assertEqual(items[0].new_name, "CON_.Title.epub")
            self.assertEqual(namer.apply(items).failed, [])
            self.assertEqual(os.listdir(tmp), ["CON_.Title.epub"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ============================================================ numbering stays put
class IdempotencyTests(TempFolder):
    def run_once(self, **kw) -> list[tuple[str, str]]:
        items = items_for(self.dir)
        namer.plan(items, opts(**kw))
        result = namer.apply(items)
        undo.record(result.renamed)
        return result.renamed

    def test_second_run_changes_nothing(self) -> None:
        for i in range(5):
            epub(self.p(f"copy{i}.epub"), "Same", "X")
        self.assertEqual(len(self.run_once()), 5)
        before = self.names()
        for _ in range(3):
            self.assertEqual(self.run_once(), [])
        self.assertEqual(self.names(), before)

    def test_files_that_already_hold_their_numbers_keep_them(self) -> None:
        """Real case: Battery report.epub and 'Battery report (2)' ... '(20)', all with one title."""
        epub(self.p("Battery report.epub"), "Battery report", None)
        for n in range(2, 21):
            epub(self.p(f"Battery report ({n}).epub"), "Battery report", None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        self.assertEqual({it.status for it in items}, {namer.NOCHANGE})

    def test_gap_in_numbers_is_filled_by_the_newcomer_only(self) -> None:
        epub(self.p("S.epub"), "S", "")
        epub(self.p("S (3).epub"), "S", "")
        epub(self.p("t.epub"), "S", "")
        items = items_for(self.dir)
        namer.plan(items, opts())
        by = {it.current: it for it in items}
        self.assertEqual(by["S.epub"].status, namer.NOCHANGE)
        self.assertEqual(by["S (3).epub"].status, namer.NOCHANGE)
        self.assertEqual((by["t.epub"].new_name, by["t.epub"].status), ("S (2).epub", namer.DUP))

    def test_number_one_is_not_a_held_number(self) -> None:
        """'S (1)' is not what the tool would have written; it takes the plain name."""
        epub(self.p("S (1).epub"), "S", "")
        items = items_for(self.dir)
        namer.plan(items, opts())
        self.assertEqual((items[0].new_name, items[0].status), ("S.epub", namer.OK))

    def test_leading_zero_number_is_not_held(self) -> None:
        epub(self.p("S (02).epub"), "S", "")
        items = items_for(self.dir)
        namer.plan(items, opts())
        self.assertEqual(items[0].new_name, "S.epub")

    def test_held_number_with_wrong_case_is_only_recased(self) -> None:
        epub(self.p("S.epub"), "S", "")
        epub(self.p("s (2).epub"), "S", "")
        items = items_for(self.dir)
        namer.plan(items, opts())
        by = {it.current: it for it in items}
        self.assertEqual(by["S.epub"].status, namer.NOCHANGE)
        self.assertEqual(by["s (2).epub"].new_name, "S (2).epub")
        namer.apply(items)
        self.assertEqual(self.names(), {"S.epub", "S (2).epub"})

    def test_unselected_holder_blocks_its_name(self) -> None:
        epub(self.p("S.epub"), "S", "")
        epub(self.p("n.epub"), "S", "")
        items = items_for(self.dir)
        by = {it.current: it for it in items}
        by["S.epub"].selected = False
        namer.plan(items, opts())
        self.assertEqual(by["n.epub"].new_name, "S (2).epub")
        namer.apply(items)
        self.assertEqual(self.names(), {"S.epub", "S (2).epub"})

    def test_typed_name_is_not_stuck_on_a_stale_number(self) -> None:
        epub(self.p("a.epub"), "Same", "X")
        epub(self.p("b.epub"), "plain", None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        by = {it.current: it for it in items}
        namer.set_manual_name(by["b.epub"], "X - Same")
        namer.plan(items, opts())
        self.assertEqual(by["b.epub"].new_name, "X - Same (2).epub")
        by["a.epub"].selected = False
        namer.plan(items, opts())
        self.assertEqual(by["b.epub"].new_name, "X - Same.epub")            # back to what the user typed

    def test_hundreds_of_duplicates(self) -> None:
        for i in range(300):
            epub(self.p(f"f{i:03}.epub"), "Same", "X")
        items = items_for(self.dir)
        t0 = time.perf_counter()
        namer.plan(items, opts())
        self.assertLess(time.perf_counter() - t0, 5)
        names = [it.new_name for it in items]
        self.assertEqual(len(set(names)), 300)
        self.assertIn("X - Same (300).epub", names)


# ============================================================ interrupted / failing apply
class ApplyFailureTests(TempFolder):
    def test_value_error_on_one_file_does_not_stop_the_batch(self) -> None:
        epub(self.p("a.epub"), "One", "X")
        epub(self.p("b.epub"), "Two", "X")
        items = items_for(self.dir)
        namer.plan(items, opts())
        items[0].new_name = "bad" + chr(0) + "name.epub"
        result = namer.apply(items)
        self.assertEqual([it.current for it, _ in result.failed], ["a.epub"])
        self.assertTrue(result.failed[0][1])                                # a readable message
        self.assertEqual(self.names(), {"a.epub", "X - Two.epub"})

    def test_interrupt_keeps_what_was_done_and_it_is_loggable(self) -> None:
        for i in range(5):
            epub(self.p(f"f{i}.epub"), f"T{i}", "X")
        items = items_for(self.dir)
        namer.plan(items, opts())
        calls = {"n": 0}
        real = namer._rename

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 3:
                raise KeyboardInterrupt
            real(src, dst)

        result = namer.RenameResult()
        with mock.patch.object(namer, "_rename", flaky):
            with self.assertRaises(KeyboardInterrupt):
                namer.apply(items, result=result)
        self.assertEqual(len(result.renamed), 2)
        written, failed = undo.record_ex(result.renamed)
        self.assertEqual((written, failed), ([self.dir], []))
        undo.undo(self.dir)
        self.assertEqual(self.names(), {f"f{i}.epub" for i in range(5)})

    def test_interrupt_in_the_middle_of_a_swap_leaves_no_temp_file(self) -> None:
        epub(self.p("B - A.epub"), "B", "A")
        epub(self.p("A - B.epub"), "A", "B")
        items = items_for(self.dir)
        namer.plan(items, opts())
        real = os.rename
        calls = {"n": 0}

        def flaky(src, dst, *a, **k):
            calls["n"] += 1
            if calls["n"] == 3:                  # park, move partner, then the parked file's final move
                raise KeyboardInterrupt
            return real(src, dst, *a, **k)

        result = namer.RenameResult()
        with mock.patch.object(os, "rename", flaky):
            with self.assertRaises(KeyboardInterrupt):
                namer.apply(items, result=result)
        self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(self.dir)), os.listdir(self.dir))
        for old, new in result.renamed:          # the record matches the disk
            self.assertTrue(os.path.exists(new))
        self.assertEqual(len(os.listdir(self.dir)), 2)

    def test_cli_interrupt_still_writes_the_log(self) -> None:
        for i in range(4):
            epub(self.p(f"f{i}.epub"), f"T{i}", "X")
        real = namer._rename
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 3:
                raise KeyboardInterrupt
            real(src, dst)

        with mock.patch.object(namer, "_rename", flaky):
            code = main.main([self.dir, "-y", "--lang", "en"])
        self.assertEqual(code, 130)
        self.assertTrue(undo.has_log(self.dir))
        undo.undo(self.dir)
        self.assertEqual(self.names(), {f"f{i}.epub" for i in range(4)})


# ============================================================ the undo log itself
class UndoLogTests(TempFolder):
    def test_unwritable_log_is_reported_not_swallowed(self) -> None:
        os.makedirs(self.p("rename_log.json"))                 # a directory sits where the log must go
        epub(self.p("a.epub"), "One", "X")
        r = self.cli(self.dir, "-y", "--lang", "en")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Could not save the undo log", r.stderr)
        self.assertEqual(self.names(), {"X - One.epub"})       # the rename itself still happened
        self.assertEqual(sorted(n for n in os.listdir(self.dir) if n.startswith("rename_log")),
                         ["rename_log.json"])                   # only the squatting directory: no .part left behind

    def test_unwritable_log_message_in_every_language(self) -> None:
        for lang in i18n.LANGS:
            i18n.set_lang(lang, persist=False)
            text = i18n.t("err_log_failed", folder="F")
            self.assertIn("F", text)
            self.assertNotEqual(text, "err_log_failed")
        i18n.set_lang("en", persist=False)

    def test_corrupt_log_is_moved_aside_never_destroyed(self) -> None:
        broken = '{"version": 1, "sessions": [ {"entries": [ BROKEN'
        with open(self.p("rename_log.json"), "w", encoding="utf-8") as f:
            f.write(broken)
        epub(self.p("a.epub"), "One", "X")
        items = items_for(self.dir)
        namer.plan(items, opts())
        undo.record(namer.apply(items).renamed)
        with open(self.p("rename_log.broken.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), broken)
        self.assertTrue(undo.has_log(self.dir))
        # a second corrupt log gets its own backup name
        with open(self.p("rename_log.json"), "w", encoding="utf-8") as f:
            f.write("not json at all")
        epub(self.p("b.epub"), "Two", "X")
        items = items_for(self.dir)
        namer.plan(items, opts())
        undo.record(namer.apply(items).renamed)
        self.assertTrue(os.path.exists(self.p("rename_log.broken1.json")))

    def test_valid_log_is_not_backed_up(self) -> None:
        epub(self.p("a.epub"), "One", "X")
        items = items_for(self.dir)
        namer.plan(items, opts())
        undo.record(namer.apply(items).renamed)
        epub(self.p("b.epub"), "Two", "X")
        items = items_for(self.dir)
        namer.plan(items, opts())
        undo.record(namer.apply(items).renamed)
        self.assertFalse(any("broken" in n for n in os.listdir(self.dir)))

    def test_dry_run_undo_matches_the_real_undo_and_touches_nothing(self) -> None:
        epub(self.p("B - A.epub"), "B", "A")
        epub(self.p("A - B.epub"), "A", "B")
        epub(self.p("c.epub"), "C", "X")
        for pattern in ("{author} - {title}", "{title}"):
            items = items_for(self.dir)
            namer.plan(items, opts(pattern=pattern))
            undo.record(namer.apply(items).renamed)
        state = (self.names(), open(self.p("rename_log.json"), "rb").read())
        dry = undo.undo(self.dir, dry_run=True)
        self.assertEqual((self.names(), open(self.p("rename_log.json"), "rb").read()), state)
        real = undo.undo(self.dir)
        self.assertEqual(dry.restored, real.restored)
        self.assertEqual(dry.skipped, real.skipped)
        self.assertEqual(self.names(), {"B - A.epub", "A - B.epub", "c.epub"})

    def test_cli_undo_dry_run(self) -> None:
        epub(self.p("a.epub"), "One", "X")
        self.assertEqual(self.cli(self.dir, "-y", "--lang", "en").returncode, 0)
        r = self.cli(self.dir, "--undo", "--dry-run", "--lang", "en")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("X - One.epub", r.stdout)
        self.assertIn("no files were changed", r.stdout)
        self.assertEqual(self.names(), {"X - One.epub"})
        self.assertTrue(undo.has_log(self.dir))
        self.assertEqual(self.cli(self.dir, "--undo", "--lang", "en").returncode, 0)
        self.assertEqual(self.names(), {"a.epub"})

    def test_locked_file_is_reported_as_locked_not_as_name_in_use(self) -> None:
        epub(self.p("a.epub"), "One", "X")
        epub(self.p("b.epub"), "Two", "X")
        self.assertEqual(self.cli(self.dir, "-y", "--lang", "en").returncode, 0)
        with open(self.p("X - One.epub"), "rb"):                           # held open: cannot be renamed
            r = self.cli(self.dir, "--undo", "--lang", "en")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Undo skipped (could not rename): X - One.epub", r.stdout)
        self.assertNotIn("name in use", r.stdout)
        self.assertEqual(self.names(), {"X - One.epub", "b.epub"})         # the other file was restored
        self.assertTrue(undo.has_log(self.dir))                            # the locked one stays logged for a retry
        self.assertEqual(self.cli(self.dir, "--undo", "--lang", "en").returncode, 0)
        self.assertEqual(self.names(), {"a.epub", "b.epub"})

    def test_dry_run_reports_blocked_entries(self) -> None:
        epub(self.p("a.epub"), "One", "X")
        items = items_for(self.dir)
        namer.plan(items, opts())
        undo.record(namer.apply(items).renamed)
        open(self.p("a.epub"), "wb").close()
        dry = undo.undo(self.dir, dry_run=True)
        self.assertEqual([r for _, r in dry.skipped], ["exists"])
        self.assertTrue(os.path.exists(self.p("a.epub")))


# ============================================================ path length
class PathLengthTests(TempFolder):
    def test_name_is_shortened_to_fit_max_path(self) -> None:
        deep = self.p("x" * 30)
        os.makedirs(deep)
        epub(os.path.join(deep, "a.epub"), "T" * 300, "Author")
        items = items_for(deep)
        with mock.patch.object(namer, "MAX_PATH_CHARS", len(deep) + 60), mock.patch.object(namer, "FIT_PATH", True):
            namer.plan(items, opts())
        name = items[0].new_name
        self.assertTrue(name.endswith(".epub"))
        self.assertLessEqual(len(deep) + 1 + len(name), len(deep) + 60 - 6)
        self.assertTrue(name.startswith("Author - TTT"))

    def test_numbering_still_fits(self) -> None:
        deep = self.p("y" * 20)
        os.makedirs(deep)
        for i in range(12):
            epub(os.path.join(deep, f"{i}.epub"), "T" * 300, "A")
        items = items_for(deep)
        limit = len(deep) + 60
        with mock.patch.object(namer, "MAX_PATH_CHARS", limit), mock.patch.object(namer, "FIT_PATH", True):
            namer.plan(items, opts())
        self.assertEqual(len({it.new_name for it in items}), 12)
        self.assertLessEqual(max(len(deep) + 1 + len(it.new_name) for it in items), limit)

    def test_absurdly_deep_folder_is_left_alone(self) -> None:
        epub(self.p("a.epub"), "T" * 100, "A")
        items = items_for(self.dir)
        with mock.patch.object(namer, "MAX_PATH_CHARS", len(self.dir) + 5), mock.patch.object(namer, "FIT_PATH", True):
            namer.plan(items, opts())
        self.assertEqual(items[0].new_name, "A - " + "T" * 100 + ".epub")

    def test_fit_can_be_switched_off(self) -> None:
        epub(self.p("a.epub"), "T" * 300, "A")
        items = items_for(self.dir)
        with mock.patch.object(namer, "FIT_PATH", False):
            namer.plan(items, opts())
        self.assertEqual(len(items[0].new_name), namer.MAX_STEM + len(".epub"))


# ============================================================ hostile and odd archives
class ArchiveTests(TempFolder):
    def test_huge_opf_is_refused_without_reading_it(self) -> None:
        path = self.p("bomb.epub")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("META-INF/container.xml", make_samples.CONTAINER)
            zf.writestr("OEBPS/content.opf", "<package " + OPF_NS + "><metadata><dc:title>Bomb</dc:title></metadata>"
                        + " " * (80 * 1024 * 1024) + "</package>")
        self.assertLess(os.path.getsize(path), 1024 * 1024)
        tracemalloc.start()
        t0 = time.perf_counter()
        m = meta.read_meta(path)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        self.assertEqual(m.error, "open_failed")
        self.assertLess(peak, 20 * 1024 * 1024)
        self.assertLess(time.perf_counter() - t0, 2)

    def test_huge_container_is_refused_and_falls_back(self) -> None:
        path = self.p("bomb2.epub")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("META-INF/container.xml", "<container>" + " " * (60 * 1024 * 1024) + "</container>")
            zf.writestr("OEBPS/content.opf", "<package " + OPF_NS + "><metadata><dc:title>Fallback</dc:title></metadata></package>")
        self.assertEqual(meta.read_meta(path).title, "Fallback")      # found by scanning for any .opf

    def test_entity_expansion_bomb(self) -> None:
        lol = '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "lol">'
        for i in range(1, 10):
            prev = "a" if i == 1 else f"e{i - 1}"
            lol += f'<!ENTITY e{i} "' + f"&{prev};" * 10 + '">'
        lol += "]>"
        opf = lol + "<package " + OPF_NS + "><metadata><dc:title>&e9;</dc:title></metadata></package>"
        path = self.p("lol.epub")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("META-INF/container.xml", make_samples.CONTAINER)
            zf.writestr("OEBPS/content.opf", opf)
        t0 = time.perf_counter()
        m = meta.read_meta(path)
        self.assertLess(time.perf_counter() - t0, 3)
        self.assertLess(len(m.title), 10_000)

    def test_encoded_opf_variants(self) -> None:
        body = ('<?xml version="1.0" encoding="UTF-8"?><package ' + OPF_NS +
                '><metadata><dc:title>BOM Title</dc:title><dc:creator>BOM Author</dc:creator></metadata></package>')
        cases = {
            "utf8bom.epub": (b"\xef\xbb\xbf" + body.encode("utf-8"), "BOM Title"),
            "utf16.epub": (body.replace("UTF-8", "UTF-16").encode("utf-16"), "BOM Title"),
            "latin1.epub": (body.replace("UTF-8", "ISO-8859-1").replace("BOM Title", "Caf\u00e9").encode("latin-1"), "Caf\u00e9"),
        }
        for name, (data, title) in cases.items():
            with zipfile.ZipFile(self.p(name), "w") as zf:
                zf.writestr("META-INF/container.xml", make_samples.CONTAINER)
                zf.writestr("OEBPS/content.opf", data)
            m = meta.read_meta(self.p(name))
            self.assertEqual((m.title, m.authors), (title, ["BOM Author"]), name)

    def test_zip_with_directory_entry_named_like_the_opf(self) -> None:
        path = self.p("dir.epub")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("META-INF/container.xml", make_samples.CONTAINER)
            zf.writestr("OEBPS/content.opf/", "")
        self.assertIn(meta.read_meta(path).error, ("open_failed", ""))     # never raises

    def test_epub_with_trailing_garbage_and_prefix(self) -> None:
        path = self.p("prefixed.epub")
        epub(path, "Prefixed", "A")
        data = open(path, "rb").read()
        with open(path, "wb") as f:
            f.write(b"\x00" * 64 + data)                                  # self-extractor style prefix
        self.assertIn(meta.read_meta(path).error, ("", "open_failed"))     # defined result, no exception


class PdfEdgeTests(TempFolder):
    def raw_pdf(self, name: str, info: bytes) -> str:
        raw = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
               b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n4 0 obj<<" + info + b">>endobj\n"
               b"trailer<</Root 1 0 R/Info 4 0 R/Size 5>>\n%%EOF\n")
        path = self.p(name)
        with open(path, "wb") as f:
            f.write(raw)
        return path

    def test_utf16_korean_title_and_pdfdoc_accents(self) -> None:
        title16 = "\ud55c\uae00 \uc81c\ubaa9".encode("utf-16-be").hex().upper().encode()
        path = self.raw_pdf("k.pdf", b"/Title<FEFF" + title16 + b">/Author(Caf\xe9 Auteur)/CreationDate(D:20180305000000+09'00')")
        m = meta.read_meta(path)
        self.assertEqual((m.title, m.authors, m.year), ("\ud55c\uae00 \uc81c\ubaa9", ["Caf\u00e9 Auteur"], "2018"))

    def test_damaged_pdf_does_not_print_mupdf_noise(self) -> None:
        epub_like = self.raw_pdf("d.pdf", b"/Title(Damaged)")
        data = open(epub_like, "rb").read()[:-40]
        with open(self.p("cut.pdf"), "wb") as f:
            f.write(data)
        code = ("import sys; sys.path.insert(0, %r); import meta; meta.read_meta(%r)" % (ROOT, self.p("cut.pdf")))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr.strip(), "")

    def test_huge_author_string(self) -> None:
        path = self.raw_pdf("big.pdf", b"/Title(T)/Author(" + b"A" * 200_000 + b")")
        items = [namer.Item(path=path, meta=meta.read_meta(path))]
        namer.plan(items, opts())
        self.assertLessEqual(len(items[0].new_name), namer.MAX_STEM + 4)
        self.assertEqual(namer.apply(items).failed, [])


# ============================================================ walking folders
@unittest.skipUnless(sys.platform == "win32", "directory junctions are a Windows feature")
class JunctionTests(TempFolder):
    def make_loop(self) -> str:
        sub = self.p("sub")
        os.makedirs(sub)
        epub(os.path.join(sub, "a.epub"), "One", "X")
        loop = os.path.join(sub, "loop")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", loop, self.dir], capture_output=True)
        if r.returncode != 0:
            self.skipTest("cannot create a junction here")
        return loop

    def test_recursive_collect_does_not_follow_a_junction_loop(self) -> None:
        self.make_loop()
        files = meta.collect_files([self.dir], recursive=True)
        self.assertEqual([os.path.basename(f) for f in files], ["a.epub"])

    def test_undo_search_does_not_follow_a_junction_loop(self) -> None:
        self.make_loop()
        items = items_for(self.dir, recursive=True)
        namer.plan(items, opts())
        undo.record(namer.apply(items).renamed)
        self.assertEqual(undo.find_logs([self.dir], recursive=True), [self.p("sub")])

    def test_symlink_to_folder_is_skipped(self) -> None:
        target = self.p("real")
        os.makedirs(target)
        epub(os.path.join(target, "a.epub"), "One", "X")
        try:
            os.symlink(target, self.p("link"), target_is_directory=True)
        except OSError:
            self.skipTest("symlinks need privileges here")
        files = meta.collect_files([self.dir], recursive=True)
        self.assertEqual(len(files), 1)

    def test_a_folder_given_directly_may_itself_be_a_junction(self) -> None:
        loop = self.make_loop()
        self.assertEqual(len(meta.collect_files([loop])), 0 + len(meta.collect_files([self.dir])))


class DropPathTests(unittest.TestCase):
    def test_tk_splitlist_handles_the_drop_formats(self) -> None:
        import tkinter as tk

        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        root.withdraw()
        try:
            cases = {
                "{D:/my books/a b.epub} D:/x/c.epub": ["D:/my books/a b.epub", "D:/x/c.epub"],
                "{D:/x/a{b}.epub}": ["D:/x/a{b}.epub"],
                "{C:/Users/me/\u3042 \u3044.pdf} {C:/x.pdf}": ["C:/Users/me/\u3042 \u3044.pdf", "C:/x.pdf"],
            }
            for raw, want in cases.items():
                self.assertEqual(list(root.tk.splitlist(raw)), want, raw)
        finally:
            root.destroy()


# ============================================================ the command line
class CliPromptTests(TempFolder):
    def answer(self, reply: str) -> tuple[int, int]:
        epub(self.p("a.epub"), "One", "X")
        tty = mock.Mock()
        tty.isatty.return_value = True
        with mock.patch.object(sys, "stdin", tty), mock.patch("builtins.input", return_value=reply) as asked:
            code = main.main([self.dir, "--lang", "en"])
        return code, asked.call_count

    def test_yes_renames(self) -> None:
        for reply in ("y", "Y", " yes "):
            shutil.rmtree(self.dir)
            os.makedirs(self.dir)
            self.assertEqual(self.answer(reply), (0, 1), reply)
            self.assertEqual(self.names(), {"X - One.epub"}, reply)

    def test_anything_else_cancels(self) -> None:
        for reply in ("n", "", "no", "yep", "1"):
            shutil.rmtree(self.dir)
            os.makedirs(self.dir)
            self.assertEqual(self.answer(reply), (0, 1), reply)
            self.assertEqual(self.names(), {"a.epub"}, reply)

    def test_yes_flag_never_asks(self) -> None:
        epub(self.p("a.epub"), "One", "X")
        tty = mock.Mock()
        tty.isatty.return_value = True
        with mock.patch.object(sys, "stdin", tty), mock.patch("builtins.input", side_effect=AssertionError("asked")):
            self.assertEqual(main.main([self.dir, "-y", "--lang", "en"]), 0)
        self.assertEqual(self.names(), {"X - One.epub"})

    def test_dry_run_never_asks(self) -> None:
        epub(self.p("a.epub"), "One", "X")
        with mock.patch("builtins.input", side_effect=AssertionError("asked")):
            self.assertEqual(main.main([self.dir, "--dry-run", "--lang", "en"]), 0)

    def test_bad_option_values_exit_2_without_a_traceback(self) -> None:
        for args in (["--lang", "xx"], ["--bogus"]):
            r = self.cli(self.dir, *args)
            self.assertEqual(r.returncode, 2, args)
            self.assertNotIn("Traceback", r.stderr)

    def test_help_in_every_language_lists_every_option(self) -> None:
        for lang in i18n.LANGS:
            r = self.cli("--help", "--lang", lang)
            self.assertEqual(r.returncode, 0, lang)
            for option in ("--pattern", "--recursive", "--dry-run", "--undo", "--others", "--yes", "--lang", "--gui"):
                self.assertIn(option, r.stdout, (lang, option))
            self.assertNotIn("positional arguments", r.stdout)           # argparse's own English label is translated

    def test_same_folder_given_twice_and_with_its_own_file(self) -> None:
        epub(self.p("a.epub"), "One", "X")
        code = main.main([self.dir, self.dir, self.p("a.epub"), "-y", "--lang", "en"])
        self.assertEqual(code, 0)
        self.assertEqual(self.names(), {"X - One.epub"})
        with open(self.p("rename_log.json"), encoding="utf-8") as f:
            entries = json.load(f)["sessions"][0]["entries"]
        self.assertEqual(len(entries), 1)

    @unittest.skipUnless(sys.platform == "win32", "extended-length paths are a Windows feature")
    def test_extended_length_path_input(self) -> None:
        epub(self.p("a.epub"), "One", "X")
        epub(self.p("b.epub"), "Two", "X")
        prefixed = "\\\\?\\" + self.dir
        self.assertEqual(main.main([prefixed, "-y", "--lang", "en"]), 0)
        self.assertEqual(self.names(), {"X - One.epub", "X - Two.epub"})
        self.assertEqual(main.main([prefixed, "--undo", "--lang", "en"]), 0)
        self.assertEqual(self.names(), {"a.epub", "b.epub"})


# ============================================================ scale
class ScaleTests(TempFolder):
    def test_thousand_files_plan_apply_undo(self) -> None:
        n = 1000
        for i in range(n):
            epub(self.p(f"f{i:04}.epub"), f"Title {i % 250}", f"Author {i % 40}")
        before = self.names()
        t0 = time.perf_counter()
        items = items_for(self.dir)
        namer.plan(items, opts())
        t_plan = time.perf_counter() - t0
        result = namer.apply(items)
        self.assertEqual(result.failed, [])
        undo.record(result.renamed)
        res = undo.undo(self.dir)
        t_all = time.perf_counter() - t0
        print(f"\n  {n} files: read+plan {t_plan:.2f}s, whole cycle {t_all:.2f}s")
        self.assertEqual(len(res.restored), len(result.renamed))
        self.assertEqual(self.names(), before)
        self.assertLess(t_all, 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
