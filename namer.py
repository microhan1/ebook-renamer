"""Naming rules: apply a pattern, sanitise the file name, resolve duplicates,
and carry out the renames. Shared by the GUI and the CLI."""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field

from meta import Meta

PRESETS = ("{author} - {title}", "{title} - {author}", "{title}")
DEFAULT_PATTERN = PRESETS[0]
PLACEHOLDERS = ("author", "title", "year")
MAX_STEM = 200
MAX_PATH_CHARS = 259                  # classic Windows MAX_PATH minus the terminating NUL
FIT_PATH = os.name == "nt"            # shorten names to keep the full path under MAX_PATH
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = ({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
             | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
             | {f"COM{c}" for c in map(chr, (0xB9, 0xB2, 0xB3))} | {f"LPT{c}" for c in map(chr, (0xB9, 0xB2, 0xB3))})
_SEPARATORS = "-_,;:|" + chr(0x2013) + chr(0x2014) + chr(0xB7)   # plus en dash, em dash, middle dot

# statuses shown in the table; each has a status_<code> key in the lang files
OK, NOCHANGE, DUP, NOMETA, FAILED, DONE = "ok", "nochange", "dup", "nometa", "failed", "done"


@dataclass
class Options:
    pattern: str = DEFAULT_PATTERN
    recursive: bool = False
    others: bool = False              # append "et al." style suffix for co-authors
    others_suffix: str = ""           # translated text with {n} from the lang file (others_suffix)

    def validated(self) -> "Options":
        pattern = self.pattern if isinstance(self.pattern, str) else DEFAULT_PATTERN
        pattern = pattern.strip()
        if not pattern or not any("{%s}" % p in pattern for p in PLACEHOLDERS):
            pattern = DEFAULT_PATTERN
        suffix = self.others_suffix if isinstance(self.others_suffix, str) else ""
        return Options(pattern=pattern, recursive=bool(self.recursive), others=bool(self.others),
                       others_suffix=suffix)


@dataclass
class Item:
    path: str
    meta: Meta
    new_name: str = ""               # full file name with extension, "" when nothing to do
    manual: bool = False             # user typed the new name; the pattern no longer applies
    typed: str = ""                  # what the user typed (new_name may carry a " (2)" on top of it)
    selected: bool = True
    status: str = OK
    error: str = ""
    original: str = ""               # path before apply() moved it (set on DONE)

    @property
    def current(self) -> str:
        return os.path.basename(self.path)

    @property
    def folder(self) -> str:
        return os.path.dirname(self.path)

    @property
    def ext(self) -> str:
        return os.path.splitext(self.path)[1].lower()


# ---------------------------------------------------------------- names
def sanitize(stem: str) -> str:
    """Strip characters no OS allows, collapse spaces, cap the length."""
    stem = unicodedata.normalize("NFC", stem or "")
    stem = _FORBIDDEN.sub("", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    stem = stem.rstrip(". ")                      # Windows drops trailing dots and spaces
    if len(stem) > MAX_STEM:
        stem = stem[:MAX_STEM].rstrip(". ")
    # Windows treats the part before the FIRST dot as the device name:
    # "CON", "con.x" and "COM1.Title" are all reserved, "CON (2)" is not.
    base, dot, rest = stem.partition(".")
    if base.strip().upper() in _RESERVED:
        stem = base + "_" + dot + rest
    return stem


def _tidy(text: str) -> str:
    """After empty placeholders were substituted, remove the separators they
    left behind: "() - Title", "Title - ", "[]" ..."""
    sep = re.escape(_SEPARATORS)
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"[\(\[\{]\s*[\)\]\}]", " ", text)                       # empty brackets
        text = re.sub(r"(\s*[%s]\s*){2,}" % sep, lambda m: m.group(1), text)   # doubled separators
        text = text.strip()
        text = re.sub(r"^[\s%s.]+|[\s%s]+$" % (sep, sep), "", text)
    return re.sub(r"\s+", " ", text).strip()


def author_text(meta: Meta, opts: Options) -> str:
    if not meta.authors:
        return ""
    text = meta.authors[0]
    n = len(meta.authors) - 1
    if n > 0 and opts.others and opts.others_suffix:
        try:
            text = f"{text} {opts.others_suffix.format(n=n)}".strip()
        except (KeyError, IndexError, ValueError):
            pass
    return text


def build_stem(meta: Meta, opts: Options) -> str:
    """Pattern applied to one file's metadata. Empty when nothing usable."""
    if meta.error or meta.empty:
        return ""
    values = {"author": author_text(meta, opts), "title": meta.title, "year": meta.year}
    text = opts.pattern
    for key in PLACEHOLDERS:
        text = text.replace("{%s}" % key, values[key])
    text = re.sub(r"\{[A-Za-z_][A-Za-z0-9_]*\}", "", text)     # unknown placeholders vanish
    text = _tidy(sanitize(_tidy(text)))
    if not text:  # the pattern only used placeholders this file lacks, e.g. "{title}" with no title
        text = _tidy(sanitize(_tidy(" - ".join(v for v in (values["author"], values["title"]) if v))))
    return sanitize(text)


# ---------------------------------------------------------------- plan
def _key(name: str) -> str:
    return os.path.normcase(unicodedata.normalize("NFC", name))


def plan(items: list[Item], opts: Options) -> None:
    """Fill new_name and status for every item. Pure: touches no file.

    Duplicates get " (2)", " (3)" ... The first of a group keeps the plain
    name. A name already used on disk by a file that is not being renamed
    away also counts as taken. Names differing only by case count as equal."""
    opts = opts.validated()
    for it in items:
        if it.status == DONE:
            continue
        if it.status == FAILED:
            it.status = OK
        if it.manual:
            it.new_name = _fit_name(it.folder, it.typed or it.new_name)   # the typed name, not last plan's " (2)"
            it.status = OK
            continue
        if it.meta.error or it.meta.empty:
            it.new_name, it.status, it.selected = "", NOMETA, False
            continue
        stem = build_stem(it.meta, opts)
        it.new_name = _fit_name(it.folder, stem + it.ext) if stem else ""
        if not it.new_name:
            it.status, it.selected = NOMETA, False
        else:
            it.status = OK

    active = [it for it in items if it.selected and it.new_name and it.status != DONE]
    # names taken on disk, per folder, minus the files that are being placed anew
    taken: dict[str, set[str]] = {}
    for it in active:
        if it.folder not in taken:
            try:
                taken[it.folder] = {_key(n) for n in os.listdir(it.folder)}
            except OSError:
                taken[it.folder] = set()
    for it in active:
        taken[it.folder].discard(_key(it.current))

    # Pass 1: a file that already holds the plain name, or "name (N)" for its own
    # group, keeps it. Running the tool twice must not shuffle the numbers.
    placed: set[int] = set()
    for it in active:
        stem, ext = os.path.splitext(it.new_name)
        held = _held_number(it.current, stem, ext)
        if held is None:
            continue
        name = stem + ext if held == 1 else f"{stem} ({held}){ext}"
        if _key(name) in taken[it.folder]:
            continue
        taken[it.folder].add(_key(name))
        it.new_name = name
        it.status = NOCHANGE if name == it.current else (OK if held == 1 else DUP)
        placed.add(id(it))

    # Pass 2: everyone else takes the lowest free name: plain, then " (2)", " (3)" ...
    for it in active:
        if id(it) in placed:
            continue
        stem, ext = os.path.splitext(it.new_name)
        candidate, n = it.new_name, 1
        while _key(candidate) in taken[it.folder]:
            n += 1
            candidate = f"{stem} ({n}){ext}"
        taken[it.folder].add(_key(candidate))
        it.new_name = candidate
        it.status = DUP if n > 1 else OK


def _held_number(current: str, stem: str, ext: str) -> int | None:
    """1 when `current` is the plain name, N>=2 when it is "stem (N)ext", else None.
    Compared the way the file system compares (NFC, case-insensitive on Windows)."""
    cur, want_stem, want_ext = _key(current), _key(stem), _key(ext)
    if cur == want_stem + want_ext:
        return 1
    m = re.fullmatch(re.escape(want_stem) + r" \(([2-9]|[1-9][0-9]+)\)" + re.escape(want_ext), cur)
    return int(m.group(1)) if m else None


def _fit_name(folder: str, name: str) -> str:
    """Shorten the name so the full path stays inside the classic Windows
    MAX_PATH. Without long-path support a longer path makes the rename fail
    with a confusing "file not found". Leaves a little room for " (NN)"."""
    if not FIT_PATH:
        return name
    stem, ext = os.path.splitext(name)
    room = MAX_PATH_CHARS - len(folder) - 1 - len(ext) - 6
    if room < 20 or len(stem) <= room:                # folder already absurdly deep: do not mangle
        return name
    return sanitize(stem[:room]) + ext


def set_manual_name(item: Item, name: str) -> None:
    """The user typed a name into the table. Keep the extension, sanitise,
    and include the file; an empty name goes back to the pattern."""
    from meta import EXTENSIONS

    stem = os.path.splitext(name)[0] if name.lower().endswith(EXTENSIONS) else name
    stem = _tidy(sanitize(stem))
    if not stem:
        item.manual = False
        item.typed = ""
        item.new_name = ""
        return
    item.manual = True
    item.selected = True
    item.typed = stem + item.ext
    item.new_name = item.typed
    item.status = OK


# -------------------------------------------------------------- apply
@dataclass
class RenameResult:
    renamed: list[tuple[str, str]] = field(default_factory=list)   # (old path, new path)
    failed: list[tuple[Item, str]] = field(default_factory=list)   # (item, error text)
    skipped: int = 0                                               # "no change" items


def _rename(src: str, dst: str) -> None:
    if os.path.exists(dst) and _key(src) != _key(dst):
        raise FileExistsError(2, "File exists", dst)
    os.rename(src, dst)


def _temp_name(path: str) -> str:
    n = 0
    while True:
        cand = f"{path}.renaming{n if n else ''}.tmp"
        if not os.path.exists(cand):
            return cand
        n += 1


def _oserror_text(exc: Exception) -> str:
    return getattr(exc, "strerror", None) or str(exc) or exc.__class__.__name__


def apply(items: list[Item], progress=None, result: RenameResult | None = None) -> RenameResult:
    """Rename the selected items. One failure never stops the batch.

    A target that is currently occupied by another file of the same batch
    (A->B while B->C, or a swap A<->B) is handled by renaming in dependency
    order and breaking cycles through a temporary name.

    Pass your own `result` to keep what was done even if the call is cut short
    (Ctrl-C): it is filled in as each file is renamed."""
    result = result if result is not None else RenameResult()
    todo = [it for it in items if it.selected and it.new_name and it.status in (OK, DUP)]
    pending: dict[str, Item] = {_key(it.path): it for it in todo}
    origin: dict[int, str] = {id(it): it.path for it in todo}
    done_count, total = 0, len(todo)
    inflight: Item | None = None

    def finish(it: Item, ok: bool, err: str = "") -> None:
        nonlocal done_count
        done_count += 1
        if ok:
            result.renamed.append((origin[id(it)], it.path))
        else:
            it.status, it.error = FAILED, err
            result.failed.append((it, err))
        if progress:
            progress(done_count, total)

    try:
        while pending:
            progressed = False
            for key, it in list(pending.items()):
                dst = os.path.join(it.folder, it.new_name)
                if _key(dst) in pending and _key(dst) != key:
                    continue                       # wait for the occupant to move away
                del pending[key]
                progressed = True
                inflight = it
                try:
                    _rename(it.path, dst)
                except Exception as exc:         # one bad name must never end the batch
                    if it.path != origin[id(it)]:  # parked under a temp name: put it back
                        try:
                            os.rename(it.path, origin[id(it)])
                            it.path = origin[id(it)]
                        except Exception:
                            pass
                    finish(it, False, _oserror_text(exc))
                else:
                    it.original, it.path = origin[id(it)], dst
                    it.new_name, it.status, it.manual, it.error = "", DONE, False, ""
                    finish(it, True)
                inflight = None
            if pending and not progressed:         # a cycle: park one file under a temporary name
                key, it = next(iter(pending.items()))
                tmp = _temp_name(it.path)
                del pending[key]
                inflight = it
                try:
                    os.rename(it.path, tmp)
                except Exception as exc:         # one bad name must never end the batch
                    finish(it, False, _oserror_text(exc))
                    inflight = None
                    continue
                it.path = tmp
                pending[_key(tmp)] = it
                inflight = None
    except BaseException:                      # Ctrl-C and friends: never leave a file under a temp name
        stranded = list(pending.values()) + ([inflight] if inflight is not None else [])
        for it in stranded:
            if it.path == origin[id(it)] or it.status == DONE:
                continue
            dst = os.path.join(it.folder, it.new_name)
            try:                                   # finish the rename if its target is free ...
                _rename(it.path, dst)
            except Exception:
                try:                               # ... otherwise put the file back
                    os.rename(it.path, origin[id(it)])
                    it.path = origin[id(it)]
                except Exception:
                    pass
            else:
                result.renamed.append((origin[id(it)], dst))
                it.original, it.path = origin[id(it)], dst
                it.new_name, it.status, it.manual, it.error = "", DONE, False, ""
        raise
    result.skipped = sum(1 for it in items if it.status == NOCHANGE)
    return result
