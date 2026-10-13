"""rename_log.json: written next to the renamed files, read back by undo.

Layout (one log per folder; every entry is a bare file name in that folder):
    {"version": 1,
     "sessions": [{"time": "...", "entries": [{"from": "a.epub", "to": "b.epub"}]}]}
Undo restores the newest session first and deletes the log once it is empty.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from meta import is_link_dir

LOG_NAME = "rename_log.json"


def log_path(folder: str) -> str:
    return os.path.join(folder, LOG_NAME)


def _load(folder: str) -> dict:
    try:
        with open(log_path(folder), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"version": 1, "sessions": []}
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
        return {"version": 1, "sessions": []}
    return data


def _backup_unreadable(folder: str) -> None:
    """A log that exists but cannot be understood is moved aside before a new
    one is written, so the old record is never destroyed by a later run."""
    path = log_path(folder)
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("sessions"), list):
            return
    except OSError:
        return                                   # locked or unreadable right now: leave it alone
    except ValueError:
        pass
    n = 0
    while True:
        backup = os.path.join(folder, f"rename_log.broken{n if n else ''}.json")
        if not os.path.exists(backup):
            break
        n += 1
    try:
        os.replace(path, backup)
    except OSError:
        pass


def _save(folder: str, data: dict) -> None:
    path = log_path(folder)
    sessions = [s for s in data.get("sessions", []) if isinstance(s, dict) and s.get("entries")]
    if not sessions:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    data["sessions"] = sessions
    tmp = path + ".part"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)                      # never leave a half-written .part behind
        except OSError:
            pass
        raise


def record_ex(renamed: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """Append (old path, new path) pairs to the log of each folder involved.
    Returns (folders whose log was written, folders where writing failed).
    A failure must reach the user: the files are already renamed, so undo
    would silently not exist."""
    by_folder: dict[str, list[dict]] = {}
    for old, new in renamed:
        folder = os.path.dirname(new)
        by_folder.setdefault(folder, []).append({"from": os.path.basename(old), "to": os.path.basename(new)})
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    written, failed = [], []
    for folder, entries in by_folder.items():
        _backup_unreadable(folder)
        data = _load(folder)
        data["sessions"].append({"time": stamp, "entries": entries})
        try:
            _save(folder, data)
            written.append(folder)
        except (OSError, ValueError):
            failed.append(folder)
    return written, failed


def record(renamed: list[tuple[str, str]]) -> list[str]:
    """Like record_ex, but returns only the folders that were written."""
    return record_ex(renamed)[0]


def has_log(folder: str) -> bool:
    return bool(_load(folder).get("sessions"))


def find_logs(folders: list[str], recursive: bool = False) -> list[str]:
    """Folders among the given ones (and their subfolders when recursive)
    that hold a log with something to undo."""
    out: list[str] = []
    seen: set[str] = set()

    def add(folder: str) -> None:
        key = os.path.normcase(os.path.abspath(folder))
        if key not in seen and has_log(folder):
            seen.add(key)
            out.append(os.path.abspath(folder))

    for folder in folders:
        if not os.path.isdir(folder):
            continue
        add(folder)
        if recursive:
            for root, dirs, _files in os.walk(folder):
                dirs[:] = sorted(d for d in dirs if not is_link_dir(os.path.join(root, d)))
                for d in dirs:
                    add(os.path.join(root, d))
    return out


@dataclass
class UndoResult:
    restored: list[tuple[str, str]] = field(default_factory=list)   # (renamed path, original path)
    skipped: list[tuple[str, str]] = field(default_factory=list)    # (path, reason)
    # reason: "exists" (original name already in use), "missing" (renamed file gone), "error"


def _norm(path: str) -> str:
    return os.path.normcase(path)


class _RealFS:
    exists = staticmethod(os.path.exists)
    rename = staticmethod(os.rename)


class _SimFS:
    """Pretends to rename: used by dry_run so the preview follows exactly the
    same ordering logic as the real undo without touching a file."""

    def __init__(self) -> None:
        self.added: set[str] = set()
        self.removed: set[str] = set()

    def exists(self, path: str) -> bool:
        key = _norm(path)
        return key in self.added or (key not in self.removed and os.path.exists(path))

    def rename(self, src: str, dst: str) -> None:
        self.removed.add(_norm(src))
        self.added.discard(_norm(src))
        self.added.add(_norm(dst))
        self.removed.discard(_norm(dst))


def _temp_name(path: str, fs) -> str:
    n = 0
    while True:
        cand = f"{path}.renaming{n if n else ''}.tmp"
        if not fs.exists(cand):
            return cand
        n += 1


def _safe_name(value) -> str | None:
    """A log entry must be a bare file name inside the log's folder. Anything
    with a path separator, a drive, or '..' is refused: the log is a plain
    JSON file anyone can edit, and undo must never move files elsewhere."""
    if not isinstance(value, str) or not value.strip():
        return None
    if "/" in value or "\\" in value or ":" in value or value in (".", "..") or "\x00" in value:
        return None
    if os.path.basename(value) != value:
        return None
    return value


def undo(folder: str, dry_run: bool = False) -> UndoResult:
    """Put every file in the folder's log back under its original name.

    Newest session first, so a file renamed twice walks back twice. A file
    whose original name is still occupied by another file of the same undo
    (a swap, or a chain) waits for that file to move first; a true cycle is
    broken through a temporary name. A name occupied by a file outside the
    log is left alone and the entry stays in the log for a later retry.

    With dry_run the same decisions are made on a simulated file system and
    nothing on disk (including the log) is touched."""
    fs = _SimFS() if dry_run else _RealFS()
    result = UndoResult()
    data = _load(folder)
    # flatten, newest session first: (session index, entry, current source path, wanted destination)
    pending: list[tuple[int, dict, str, str]] = []
    sessions = [s for s in data.get("sessions", []) if isinstance(s, dict)]
    for si in range(len(sessions) - 1, -1, -1):
        for entry in reversed(sessions[si].get("entries", []) or []):
            if not isinstance(entry, dict):
                continue
            to_name, from_name = _safe_name(entry.get("to")), _safe_name(entry.get("from"))
            if not to_name or not from_name or to_name == from_name:
                continue
            pending.append((si, entry, os.path.join(folder, to_name), os.path.join(folder, from_name)))

    left: dict[int, list[dict]] = {}
    origin: dict[int, str] = {id(e): src for _si, e, src, _dst in pending}
    # names a NEWER session's undo will bring back: (name -> newest producing session)
    produced: dict[str, int] = {}
    for psi, _e, _src, dst in pending:
        produced[_norm(dst)] = max(psi, produced.get(_norm(dst), -1))
    # Decide "missing" before touching anything: a source that is absent now and
    # is not produced by a newer session is gone for good. Checking later would
    # mistake a sibling's freshly restored file (a swap partner) for it.
    for job in list(pending):
        si, entry, src, dst = job
        if not fs.exists(src) and produced.get(_norm(src), -1) <= si:
            pending.remove(job)
            result.skipped.append((src, "missing"))

    while pending:
        # names still to be vacated by files that are really there
        occupied = {_norm(src) for _si, _e, src, _dst in pending if fs.exists(src)}
        progressed = False
        for job in list(pending):
            si, entry, src, dst = job
            if not fs.exists(src):
                if produced.get(_norm(src), -1) > si:
                    continue                               # renamed again later: appears after that undo
                pending.remove(job)                        # same session or none: the file is really gone
                progressed = True
                result.skipped.append((src, "missing"))
                continue
            if _norm(dst) in occupied and _norm(dst) != _norm(src):
                continue                                   # wait for the occupant to move away
            pending.remove(job)
            progressed = True
            if fs.exists(dst) and _norm(src) != _norm(dst):
                result.skipped.append((dst, "exists"))
                left.setdefault(si, []).append(entry)
                continue
            try:
                fs.rename(src, dst)
            except OSError:
                result.skipped.append((src, "error"))
                left.setdefault(si, []).append(entry)
                continue
            result.restored.append((origin[id(entry)], dst))
        if pending and not progressed:
            # Either a cycle (park one file under a temporary name) or jobs waiting
            # for a source that will never appear (drop them as missing).
            present = [j for j in pending if fs.exists(j[2])]
            if not present:
                for si, entry, src, dst in pending:
                    result.skipped.append((src, "missing"))
                pending.clear()
                break
            si, entry, src, dst = present[0]
            pending.remove(present[0])
            tmp = _temp_name(src, fs)
            try:
                fs.rename(src, tmp)
            except OSError:
                result.skipped.append((src, "error"))
                left.setdefault(si, []).append(entry)
                continue
            pending.append((si, entry, tmp, dst))

    remaining = []
    for si, session in enumerate(sessions):
        if si in left:
            remaining.append({"time": session.get("time", ""), "entries": list(reversed(left[si]))})
    data["sessions"] = remaining
    if not dry_run:
        try:
            _save(folder, data)
        except OSError:
            pass
    return result
