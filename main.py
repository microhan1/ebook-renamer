"""Entry point for ebook-renamer.

    python main.py                                   -> GUI
    python main.py ./books --pattern "{author} - {title}" [--recursive] [--dry-run]
    python main.py ./books --undo
"""
from __future__ import annotations

import argparse
import os
import sys

import i18n
import meta
import namer
import undo
from i18n import t
from version import __version__


def _preselect_lang(argv: list[str]) -> str | None:
    """--lang has to be known before the parser is built, so help is translated."""
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
    return None


def _localize_argparse() -> None:
    """argparse's own labels go through gettext; route them to lang files."""
    table = {
        "usage: ": t("cli_usage"),
        "positional arguments": t("cli_positional"),
        "options": t("cli_options"),
        "show this help message and exit": t("cli_help"),
    }
    argparse._ = lambda s: table.get(s, s)  # type: ignore[attr-defined]


def build_parser() -> argparse.ArgumentParser:
    _localize_argparse()
    p = argparse.ArgumentParser(prog="ebook-renamer", description=t("cli_desc"))
    p.add_argument("inputs", nargs="*", help=t("cli_inputs"))
    p.add_argument("--pattern", default=None, help=t("cli_pattern").replace("%", "%%"))
    p.add_argument("--recursive", action="store_true", help=t("cli_recursive"))
    p.add_argument("--dry-run", action="store_true", help=t("cli_dry_run"))
    p.add_argument("--undo", action="store_true", help=t("cli_undo"))
    p.add_argument("--others", action="store_true", help=t("cli_others"))
    p.add_argument("-y", "--yes", action="store_true", help=t("cli_yes"))
    p.add_argument("--lang", choices=i18n.LANGS, help=t("cli_lang"))
    p.add_argument("--gui", action="store_true", help=t("cli_gui"))
    p.add_argument("--version", action="version", version=f"ebook-renamer {__version__}", help=t("cli_version"))
    return p


def _status_text(code: str) -> str:
    return t(f"status_{code}")


def run_undo(args: argparse.Namespace) -> int:
    folders = [p if os.path.isdir(p) else os.path.dirname(os.path.abspath(p)) for p in args.inputs]
    logs = undo.find_logs(folders, recursive=args.recursive)
    if not logs:
        print(t("msg_no_log"))
        return 2
    restored, skipped = 0, 0
    for folder in logs:
        print(t("cli_undo_folder", folder=folder))
        result = undo.undo(folder, dry_run=args.dry_run)
        for src, dst in result.restored:
            print("  " + t("log_undone", new=os.path.basename(src), old=os.path.basename(dst)))
        for path, reason in result.skipped:
            key = {"missing": "log_undo_missing", "error": "log_undo_error"}.get(reason, "log_undo_skipped")
            print("  " + t(key, name=os.path.basename(path)))
        restored += len(result.restored)
        skipped += len(result.skipped)
    if args.dry_run:
        print(t("cli_dry_run_note"))
        return 0
    print(t("msg_undo_done", count=restored))
    return 1 if skipped else 0


def run_cli(args: argparse.Namespace) -> int:
    if args.undo:
        return run_undo(args)
    for p in args.inputs:
        if not os.path.exists(p):
            print(t("err_open_failed", name=p), file=sys.stderr)
    files = meta.collect_files(args.inputs, recursive=args.recursive)
    if not files:
        print(t("cli_no_input"), file=sys.stderr)
        return 2
    opts = namer.Options(pattern=args.pattern or namer.DEFAULT_PATTERN, recursive=args.recursive,
                         others=args.others, others_suffix=t("others_suffix")).validated()
    items = [namer.Item(path=f, meta=meta.read_meta(f)) for f in files]
    namer.plan(items, opts)
    for it in items:
        if it.meta.error == "password":
            print(t("err_password", name=it.current), file=sys.stderr)
        elif it.meta.error:
            print(t("err_open_failed", name=it.current), file=sys.stderr)
        print(t("cli_row", status=_status_text(it.status), current=it.current, new=it.new_name or "-"))
    todo = [it for it in items if it.selected and it.new_name and it.status in (namer.OK, namer.DUP)]
    if args.dry_run:
        print(t("cli_dry_run_note"))
        return 0
    if not todo:
        print(t("msg_nothing_selected"))
        return 0
    if not args.yes and sys.stdin is not None and sys.stdin.isatty():
        try:
            answer = input(t("cli_confirm", count=len(todo)) + t("cli_confirm_hint")).strip().lower()
        except EOFError:
            # Windows reports the NUL device as a tty; nobody is there to answer,
            # and the command was given without --dry-run, so carry on.
            answer = "y"
            print()
        if answer not in ("y", "yes"):
            print(t("cli_cancelled"))
            return 0
    result = namer.RenameResult()
    interrupted = False
    try:
        namer.apply(items, result=result)
    except KeyboardInterrupt:
        interrupted = True          # keep going: what was already renamed must still be logged
    for old, new in result.renamed:
        print(t("log_renamed", old=os.path.basename(old), new=os.path.basename(new)))
    for it, err in result.failed:
        print(t("err_rename_failed", name=it.current, error=err), file=sys.stderr)
    written, log_failed = undo.record_ex(result.renamed)
    for folder in written:
        print(t("log_saved", path=undo.log_path(folder)))
    for folder in log_failed:
        print(t("err_log_failed", folder=folder), file=sys.stderr)
    if interrupted:
        print("\n" + t("cli_cancelled"))
        return 130
    print(t("msg_done", count=len(result.renamed)))
    if result.failed:
        print(t("msg_failed", count=len(result.failed)), file=sys.stderr)
    return 1 if (result.failed or log_failed) else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Windows consoles default to cp949; Chinese/Japanese file names would crash print().
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    i18n.init(_preselect_lang(argv))
    args = build_parser().parse_args(argv)
    if args.lang:
        i18n.set_lang(args.lang, persist=False)
    # A windowed exe has no console, so dropping files on it opens the GUI
    # with those files loaded instead of running the CLI into nowhere.
    headless = getattr(sys, "frozen", False) and sys.stdout is None
    if args.gui or headless or not args.inputs:
        import gui

        gui.launch(args.inputs or None)
        return 0
    return run_cli(args)


if __name__ == "__main__":
    sys.exit(main())
