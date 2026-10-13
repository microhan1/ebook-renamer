"""Randomised scenario tests. Many small folders are built from awkward
metadata and awkward starting names, then planned, renamed and undone. Every
run checks the same invariants, so a single failing seed reproduces exactly:

    python -m unittest tests.test_fuzz -v

Invariants
  plan   every new name is a legal Windows file name, keeps its extension,
         and no two files end up with the same name (case-insensitive), nor
         with a file that stays where it is
  apply  nothing fails, nothing is lost, file contents are untouched,
         files without metadata are never renamed
  repeat running again with everything selected changes nothing
  undo   the folder returns to exactly what it was, with no temp files
"""
from __future__ import annotations

import hashlib
import os
import random
import re
import shutil
import sys
import tempfile
import unicodedata
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "samples"))

import i18n  # noqa: E402
import make_samples  # noqa: E402
import meta  # noqa: E402
import namer  # noqa: E402
import undo  # noqa: E402

i18n.init("en")

TITLES = [
    "", "Title", "title", "TITLE ", "T" * 300, "A: B?", "***", "CON", "con.Title", "x.", " lead", ".hidden",
    "\ud55c\uae00 \uc81c\ubaa9", "\u6f22\u5b57\u304b\u306a", "\u72c2\u4eba\u65e5\u8bb0", "\U0001F4DA book", "a/b\\c", "..", "NUL",
    "title (2)", "Title (3)", "Spider-Man - Vol. 2", "Tom & Jerry", "100%", "#1 hit", "a  b   c", "trailing...",
    unicodedata.normalize("NFD", "\ud55c\uae00"), "\uff76\uff80\uff76\uff85", "Caf\xe9", "Cafe\u0301", "<b>bold</b>",
    "same", "SAME", "Same Title", "same title",
]
AUTHORS = [[], ["Ann"], ["ann"], ["Ann", "Bob"], ["Doe, John"], ["\uae00\uc4f4\uc774"], ["A" * 250], ["X & Y"], ["Anonymous"],
           ["Ann", "Bob", "Cy", "Di"], ["  "], ["CON"]]
PATTERNS = ["{author} - {title}", "{title} - {author}", "{title}", "{title} ({year}) - {author}", "[{year}] {title}",
            "{author}{title}", "{author}"]
RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
FORBIDDEN = set('\\/:*?"<>|')


def key(name: str) -> str:
    return os.path.normcase(unicodedata.normalize("NFC", name))


def digest(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def snapshot(folder: str) -> dict[str, str]:
    """relative path -> content hash, for every file except the undo log."""
    out = {}
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if name.startswith("rename_log"):
                continue
            full = os.path.join(root, name)
            out[os.path.relpath(full, folder)] = digest(full)
    return out


def legal_windows_name(name: str) -> str | None:
    """Return a complaint, or None when the name is fine."""
    stem, ext = os.path.splitext(name)
    if not stem:
        return "empty stem"
    if any(c in FORBIDDEN or ord(c) < 32 for c in name):
        return "forbidden character"
    if stem != stem.strip() or stem.endswith(".") or name.endswith((" ", ".")):
        return "leading/trailing space or dot"
    if stem.partition(".")[0].strip().upper() in RESERVED:
        return "reserved device name"
    if len(stem) > namer.MAX_STEM + 12:
        return f"stem too long ({len(stem)})"
    if unicodedata.normalize("NFC", name) != name:
        return "not NFC"
    if any(0xD800 <= ord(c) <= 0xDFFF for c in name):
        return "surrogate"
    return None


class FuzzBase(unittest.TestCase):
    def build(self, rnd: random.Random, folder: str, count: int, subfolder: bool) -> None:
        """Create files whose starting names are adversarial: some already equal the
        name another file is about to get, so chains and swaps happen."""
        specs = []
        for i in range(count):
            title = rnd.choice(TITLES)
            authors = rnd.choice(AUTHORS)
            specs.append((title, authors, rnd.choice(["", "", "1999", "2020-05-01", "n.d."]), rnd.random() < 0.15))
        planned = []
        for title, authors, date, _pdf in specs:
            m = meta.Meta(title=meta._clean(title), authors=meta._split_authors([meta._clean(a) for a in authors]),
                          year=meta._year(date))
            planned.append(namer.build_stem(m, namer.Options().validated()) or f"f{len(planned)}")
        used: set[str] = set()
        for i, (title, authors, date, is_pdf) in enumerate(specs):
            ext = ".pdf" if is_pdf else rnd.choice([".epub", ".epub", ".EPUB"])
            if is_pdf:
                ext = rnd.choice([".pdf", ".PDF"])
            roll = rnd.random()
            if roll < 0.35:
                stem = planned[rnd.randrange(len(planned))]            # collide with someone's target
            elif roll < 0.5:
                stem = planned[i] + f" ({rnd.randint(2, 6)})"
            elif roll < 0.6:
                stem = planned[i].swapcase()
            else:
                stem = f"file{i}"
            name = stem + ext
            while key(name) in used:
                name = f"{stem} x{rnd.randint(0, 999)}{ext}"
            used.add(key(name))
            target = folder
            if subfolder and rnd.random() < 0.4:
                target = os.path.join(folder, "sub dir")
                os.makedirs(target, exist_ok=True)
            path = os.path.join(target, name)
            if is_pdf:
                make_samples.make_pdf(path, title or None, ", ".join(authors) or None, None)
            else:
                make_samples.make_epub(path, i, "en", title or None, authors, date or None)
        # decoys: other extensions and a folder squatting on a likely target name
        with open(os.path.join(folder, "notes.txt"), "w") as f:
            f.write("keep")
        decoy = os.path.join(folder, planned[0] + ".epub") if planned else ""
        if decoy and rnd.random() < 0.5 and not os.path.exists(decoy):
            os.makedirs(decoy)

    def rotate(self, folder: str, recursive: bool, options: namer.Options) -> None:
        """Give every file the planned name of the next file of the same kind, so
        each target is another file's current name: swaps and longer cycles."""
        items = [namer.Item(path=p, meta=meta.read_meta(p)) for p in meta.collect_files([folder], recursive)]
        namer.plan(items, options)
        groups: dict[tuple[str, str], list[namer.Item]] = {}
        for it in items:
            if it.status in (namer.OK, namer.DUP):
                groups.setdefault((it.folder, it.ext), []).append(it)
        for group in groups.values():
            if len(group) < 2:
                continue
            names = [it.new_name for it in group]
            moves = []
            for it, new in zip(group, names[1:] + names[:1]):
                parked = it.path + ".rot"
                os.rename(it.path, parked)
                moves.append((parked, os.path.join(it.folder, new)))
            for parked, dst in moves:
                os.rename(parked, dst)

    def check_plan(self, items: list[namer.Item]) -> None:
        by_folder: dict[str, list[namer.Item]] = {}
        for it in items:
            if it.selected and it.new_name and it.status != namer.DONE:
                by_folder.setdefault(it.folder, []).append(it)
        for it in items:
            if it.meta.error or it.meta.empty:
                if not it.manual:
                    self.assertEqual(it.status, namer.NOMETA, it.current)
                    self.assertFalse(it.selected, it.current)
        for folder, active in by_folder.items():
            finals = [key(it.new_name) for it in active]
            self.assertEqual(len(finals), len(set(finals)), [it.new_name for it in active])
            staying = {key(n) for n in os.listdir(folder)} - {key(it.current) for it in active}
            self.assertFalse(set(finals) & staying, (set(finals) & staying))
            for it in active:
                self.assertEqual(os.path.splitext(it.new_name)[1], it.ext, it.new_name)
                complaint = legal_windows_name(it.new_name)
                self.assertIsNone(complaint, (complaint, it.new_name))

    def scenario(self, seed: int, select_all: bool) -> None:
        rnd = random.Random(seed)
        folder = tempfile.mkdtemp(prefix=f"ebr_fz{seed}_")
        try:
            subfolder = rnd.random() < 0.4
            self.build(rnd, folder, rnd.randint(1, 18), subfolder)
            options = namer.Options(pattern=rnd.choice(PATTERNS), others=rnd.random() < 0.3,
                                    others_suffix="and {n} more").validated()
            if rnd.random() < 0.5:
                self.rotate(folder, subfolder, options)          # make rename cycles certain
            initial = snapshot(folder)
            initial_dirs = sorted(os.path.relpath(os.path.join(r, d), folder) for r, ds, _ in os.walk(folder) for d in ds)

            items = [namer.Item(path=p, meta=meta.read_meta(p)) for p in meta.collect_files([folder], subfolder)]
            if not select_all:
                for it in items:
                    if rnd.random() < 0.2:
                        it.selected = False
            namer.plan(items, options)
            self.check_plan(items)

            result = namer.apply(items)
            self.assertEqual(result.failed, [], f"seed {seed}")
            written, failed = undo.record_ex(result.renamed)
            self.assertEqual(failed, [])

            # nothing lost, nothing altered, metadata-less files untouched
            after = snapshot(folder)
            self.assertEqual(sorted(after.values()), sorted(initial.values()), f"seed {seed}: contents changed")
            for it in items:
                if it.status == namer.NOMETA and not it.manual:
                    self.assertTrue(os.path.exists(it.path), it.current)
                    self.assertEqual(os.path.basename(it.path), it.current)
            self.assertFalse(any(n.endswith(".tmp") for r, _, fs in os.walk(folder) for n in fs))
            with open(os.path.join(folder, "notes.txt")) as note:
                self.assertEqual(note.read(), "keep")

            if select_all:
                again = [namer.Item(path=p, meta=meta.read_meta(p)) for p in meta.collect_files([folder], subfolder)]
                namer.plan(again, options)
                self.check_plan(again)
                changing = [(it.current, it.new_name) for it in again if it.status in (namer.OK, namer.DUP)]
                self.assertEqual(changing, [], f"seed {seed}: second run is not a no-op")

            for log_folder in undo.find_logs([folder], recursive=True):
                res = undo.undo(log_folder)
                self.assertEqual(res.skipped, [], f"seed {seed}")
            self.assertEqual(snapshot(folder), initial, f"seed {seed}: undo did not restore")
            self.assertEqual(sorted(os.path.relpath(os.path.join(r, d), folder) for r, ds, _ in os.walk(folder) for d in ds),
                             initial_dirs)
            self.assertFalse(any(n.startswith("rename_log") for r, _, fs in os.walk(folder) for n in fs))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class FuzzAllSelected(FuzzBase):
    def test_seeds(self) -> None:
        for seed in range(80):
            with self.subTest(seed=seed):
                self.scenario(seed, select_all=True)


class FuzzRandomSelection(FuzzBase):
    def test_seeds(self) -> None:
        for seed in range(1000, 1060):
            with self.subTest(seed=seed):
                self.scenario(seed, select_all=False)


class FuzzTwoSessions(FuzzBase):
    """Two different patterns in a row, then undo twice over."""

    def test_seeds(self) -> None:
        for seed in range(2000, 2030):
            with self.subTest(seed=seed):
                rnd = random.Random(seed)
                folder = tempfile.mkdtemp(prefix=f"ebr_fz2_{seed}_")
                try:
                    self.build(rnd, folder, rnd.randint(2, 14), False)
                    initial = snapshot(folder)
                    for pattern in rnd.sample(PATTERNS, 2):
                        items = [namer.Item(path=p, meta=meta.read_meta(p)) for p in meta.collect_files([folder])]
                        namer.plan(items, namer.Options(pattern=pattern).validated())
                        self.check_plan(items)
                        result = namer.apply(items)
                        self.assertEqual(result.failed, [])
                        undo.record(result.renamed)
                    res = undo.undo(folder)
                    self.assertEqual(res.skipped, [], f"seed {seed}")
                    self.assertEqual(snapshot(folder), initial, f"seed {seed}")
                finally:
                    shutil.rmtree(folder, ignore_errors=True)


class FuzzUndoOfDryRun(FuzzBase):
    def test_dry_run_matches_real(self) -> None:
        for seed in range(3000, 3025):
            with self.subTest(seed=seed):
                rnd = random.Random(seed)
                folder = tempfile.mkdtemp(prefix=f"ebr_fz3_{seed}_")
                try:
                    self.build(rnd, folder, rnd.randint(2, 12), False)
                    for pattern in rnd.sample(PATTERNS, 2):
                        items = [namer.Item(path=p, meta=meta.read_meta(p)) for p in meta.collect_files([folder])]
                        namer.plan(items, namer.Options(pattern=pattern).validated())
                        undo.record(namer.apply(items).renamed)
                    if not undo.has_log(folder):
                        continue
                    before = snapshot(folder)
                    names_before = sorted(os.listdir(folder))
                    dry = undo.undo(folder, dry_run=True)
                    self.assertEqual(sorted(os.listdir(folder)), names_before)
                    real = undo.undo(folder)
                    self.assertEqual(sorted(dry.restored), sorted(real.restored))
                    self.assertEqual(sorted(dry.skipped), sorted(real.skipped))
                    self.assertEqual(sorted(snapshot(folder).values()), sorted(before.values()))
                finally:
                    shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
