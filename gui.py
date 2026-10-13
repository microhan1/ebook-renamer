"""tkinter GUI for ebook-renamer: a preview table you check, then run."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import i18n
import meta
import namer
import undo
from i18n import t
from namer import Item, Options

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _HAS_DND = True
except Exception:  # pragma: no cover - optional dependency
    _HAS_DND = False

CHECKED, UNCHECKED = chr(0x2611), chr(0x2610)      # ballot box with check / ballot box
COLUMNS = ("current", "author", "title", "new", "status")
COLUMN_WIDTHS = {"current": 220, "author": 130, "title": 210, "new": 270, "status": 130}
PATTERN_DEBOUNCE_MS = 350
TAG_COLORS = {
    namer.DUP: {"background": "#fff3b0"},
    namer.NOMETA: {"foreground": "#999999"},
    namer.NOCHANGE: {"foreground": "#777777"},
    namer.FAILED: {"foreground": "#c0392b"},
    namer.DONE: {"foreground": "#1e7d32"},
}


def _saved_options(settings: dict) -> Options:
    """Options from settings.json, trusting nothing about its types. The file
    sits beside the exe where anyone can edit it; one wrong value must not
    stop the window from opening."""
    raw = settings.get("options")
    raw = raw if isinstance(raw, dict) else {}
    d = Options()
    pattern = raw.get("pattern")
    recursive = raw.get("recursive")
    others = raw.get("others")
    return Options(pattern=pattern if isinstance(pattern, str) else d.pattern,
                   recursive=recursive if isinstance(recursive, bool) else d.recursive,
                   others=others if isinstance(others, bool) else d.others).validated()


class App:
    def __init__(self, initial_paths: list[str] | None = None) -> None:
        self.root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
        self.root.geometry("1100x720")
        self.root.minsize(860, 560)

        self.items: list[Item] = []
        self.sources: list[str] = []            # what the user dropped; re-read on option change
        self.iid_to_item: dict[str, Item] = {}
        self.worker: threading.Thread | None = None
        self.read_gen = 0
        self._texts: list[tuple[tk.Misc, str, str]] = []
        self._status_key = ""
        self._status_kwargs: dict = {}
        self._pattern_job: str | None = None
        self._editor: tk.Entry | None = None
        self._edit_iid: str | None = None
        self._running = False
        self._renaming = False
        self._closing = False

        saved = _saved_options(i18n.load_settings())
        self.var_pattern = tk.StringVar(value=saved.pattern)
        self.var_recursive = tk.BooleanVar(value=saved.recursive)
        self.var_others = tk.BooleanVar(value=saved.others)
        self.var_lang = tk.StringVar(value=i18n.LANG_NAMES[i18n.current_lang()])

        self._build()
        self._apply_texts()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if initial_paths:
            self.root.after(100, lambda: self.add_paths(initial_paths))

    # ------------------------------------------------------------ building
    def _reg(self, widget: tk.Misc, key: str, attr: str = "text") -> tk.Misc:
        self._texts.append((widget, key, attr))
        return widget

    def _build(self) -> None:
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        # ---- header
        head = ttk.Frame(root, padding=(12, 10, 12, 4))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        family = tkfont.nametofont("TkDefaultFont").actual("family")   # the UI font, not a serif fallback
        self._reg(ttk.Label(head, font=(family, 15, "bold")), "app_title").grid(row=0, column=0, sticky="w")
        self._reg(ttk.Label(head), "lbl_language").grid(row=0, column=1, padx=(0, 6))
        self.cmb_lang = ttk.Combobox(head, state="readonly", width=10, textvariable=self.var_lang,
                                     values=[i18n.LANG_NAMES[c] for c in i18n.LANGS])
        self.cmb_lang.grid(row=0, column=2)
        self.cmb_lang.bind("<<ComboboxSelected>>", self._on_lang)

        # ---- drop area + file buttons
        top = ttk.Frame(root, padding=(12, 4))
        top.grid(row=1, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        self.lbl_drop = ttk.Label(top, anchor="center", relief="groove", padding=10, foreground="#555")
        self._reg(self.lbl_drop, "drop_hint")
        self.lbl_drop.grid(row=0, column=0, sticky="ew")
        btns = ttk.Frame(top)
        btns.grid(row=0, column=1, padx=(8, 0))
        self.btn_add = self._reg(ttk.Button(btns, command=self._add_files_dialog), "btn_add_files")
        self.btn_add.pack(side="left")
        self.btn_add_dir = self._reg(ttk.Button(btns, command=self._add_folder_dialog), "btn_add_folder")
        self.btn_add_dir.pack(side="left", padx=4)
        self.btn_clear = self._reg(ttk.Button(btns, command=self.clear), "btn_clear")
        self.btn_clear.pack(side="left")

        # ---- options
        opts = ttk.Frame(root, padding=(12, 4))
        opts.grid(row=2, column=0, sticky="ew")
        opts.columnconfigure(5, weight=1)
        self._reg(ttk.Label(opts), "pattern_label").grid(row=0, column=0, padx=(0, 6))
        self.cmb_pattern = ttk.Combobox(opts, width=28, textvariable=self.var_pattern, values=list(namer.PRESETS))
        self.cmb_pattern.grid(row=0, column=1)
        self.cmb_pattern.bind("<<ComboboxSelected>>", lambda e: self._schedule_replan())
        self.cmb_pattern.bind("<KeyRelease>", lambda e: self._schedule_replan())
        self.chk_recursive = self._reg(ttk.Checkbutton(opts, variable=self.var_recursive,
                                                       command=self._on_recursive), "opt_recursive")
        self.chk_recursive.grid(row=0, column=2, padx=(16, 0))
        self.chk_others = self._reg(ttk.Checkbutton(opts, variable=self.var_others,
                                                    command=self._replan), "opt_others")
        self.chk_others.grid(row=0, column=3, padx=(16, 0))
        self.btn_toggle = self._reg(ttk.Button(opts, command=self._toggle_all), "btn_toggle_all")
        self.btn_toggle.grid(row=0, column=6, sticky="e")
        self.lbl_hint = ttk.Label(opts, foreground="#666")
        self._reg(self.lbl_hint, "hint_edit")
        self.lbl_hint.grid(row=1, column=0, columnspan=7, sticky="w", pady=(4, 0))
        opts.bind("<Configure>", lambda e: self.lbl_hint.configure(wraplength=max(300, e.width - 24)))

        # ---- table
        tbl = ttk.Frame(root, padding=(12, 4))
        tbl.grid(row=3, column=0, sticky="nsew")
        tbl.columnconfigure(0, weight=1)
        tbl.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(tbl, columns=COLUMNS, selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(tbl, command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.column("#0", width=60, minwidth=50, stretch=False, anchor="center")
        for col in COLUMNS:
            self.tree.column(col, width=COLUMN_WIDTHS[col], minwidth=110 if col == "status" else 60,
                             stretch=(col in ("current", "title", "new")))
        for code, style in TAG_COLORS.items():
            self.tree.tag_configure(code, **style)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Double-1>", self._on_tree_double)
        self.tree.bind("<space>", self._on_space)
        if _HAS_DND:
            for w in (root, self.lbl_drop, self.tree):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)

        # ---- log
        logf = self._reg(ttk.LabelFrame(root, padding=4), "lbl_log")
        logf.grid(row=4, column=0, sticky="ew", padx=12, pady=4)
        logf.columnconfigure(0, weight=1)
        self.txt_log = tk.Text(logf, height=4, state="disabled", wrap="none")
        self.txt_log.grid(row=0, column=0, sticky="ew")
        lsb = ttk.Scrollbar(logf, command=self.txt_log.yview)
        lsb.grid(row=0, column=1, sticky="ns")
        self.txt_log.configure(yscrollcommand=lsb.set)

        # ---- bottom
        bot = ttk.Frame(root, padding=(12, 4, 12, 10))
        bot.grid(row=5, column=0, sticky="ew")
        bot.columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(bot, mode="determinate")
        self.progress.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 6))
        self.lbl_status = ttk.Label(bot, anchor="w")
        self.lbl_status.grid(row=1, column=0, sticky="w")
        self.lbl_count = ttk.Label(bot, anchor="e", foreground="#555")
        self.lbl_count.grid(row=1, column=1, sticky="e", padx=(0, 12))
        self.btn_open = self._reg(ttk.Button(bot, command=self._open_folder), "btn_open_folder")
        self.btn_open.grid(row=1, column=2, padx=(0, 6))
        self.btn_undo = self._reg(ttk.Button(bot, command=self._undo), "btn_undo")
        self.btn_undo.grid(row=1, column=3, padx=(0, 6))
        self.btn_run = self._reg(ttk.Button(bot, command=self._run), "btn_run")
        self.btn_run.grid(row=1, column=4)

    def _apply_texts(self) -> None:
        self.root.title(t("app_title"))
        for widget, key, attr in self._texts:
            try:
                widget.configure(**{attr: t(key)})
            except tk.TclError:
                pass
        self.tree.heading("#0", text=t("col_select"))
        for col in COLUMNS:
            self.tree.heading(col, text=t(f"col_{col}"))
        self._refresh_rows()
        self._update_count()
        if self._status_key:
            self._set_status(self._status_key, **self._status_kwargs)

    # ------------------------------------------------------------ helpers
    def _set_status(self, key: str, **kwargs) -> None:
        self._status_key, self._status_kwargs = key, kwargs
        self.lbl_status.configure(text=t(key, **kwargs) if key else "")

    def log(self, key: str, **kwargs) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", t(key, **kwargs) + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def options(self) -> Options:
        return Options(pattern=self.var_pattern.get(), recursive=bool(self.var_recursive.get()),
                       others=bool(self.var_others.get()), others_suffix=t("others_suffix")).validated()

    def _save_options(self) -> None:
        settings = i18n.load_settings()
        o = self.options()
        settings["options"] = {"pattern": o.pattern, "recursive": o.recursive, "others": o.others}
        i18n.save_settings(settings)

    def _set_running(self, running: bool) -> None:
        self._running = running
        state = "disabled" if running else "normal"
        for w in (self.btn_add, self.btn_add_dir, self.btn_clear, self.btn_run, self.btn_undo,
                  self.btn_toggle, self.chk_recursive, self.chk_others):
            w.configure(state=state)
        self.cmb_pattern.configure(state="disabled" if running else "normal")
        self.cmb_lang.configure(state="disabled" if running else "readonly")

    def _on_lang(self, _event=None) -> None:
        index = self.cmb_lang.current()
        if index >= 0:
            i18n.set_lang(i18n.LANGS[index])
        self._replan()
        self._apply_texts()

    # ------------------------------------------------------------ table rows
    def _row_values(self, it: Item) -> tuple:
        return (it.current, it.meta.author, it.meta.title, it.new_name, t(f"status_{it.status}"))

    def _refresh_row(self, iid: str) -> None:
        it = self.iid_to_item[iid]
        tags = (it.status,) if it.status in TAG_COLORS else ()
        self.tree.item(iid, text=CHECKED if it.selected else UNCHECKED, values=self._row_values(it), tags=tags)

    def _refresh_rows(self) -> None:
        for iid in self.iid_to_item:
            self._refresh_row(iid)

    def _update_count(self) -> None:
        total = len(self.items)
        selected = sum(1 for it in self.items if it.selected)
        change = sum(1 for it in self.items
                     if it.selected and it.new_name and it.status in (namer.OK, namer.DUP, namer.FAILED))
        self.lbl_count.configure(text=t("status_count", total=total, selected=selected, change=change) if total else "")

    def _replan(self) -> None:
        if self._running:
            return
        namer.plan(self.items, self.options())
        self._refresh_rows()
        self._update_count()

    def _schedule_replan(self) -> None:
        if self._pattern_job:
            self.root.after_cancel(self._pattern_job)
        self._pattern_job = self.root.after(PATTERN_DEBOUNCE_MS, self._replan_from_pattern)

    def _replan_from_pattern(self) -> None:
        self._pattern_job = None
        self._replan()

    def _on_recursive(self) -> None:
        if self.sources and not self._running:
            self._reload()
        else:
            self._replan()

    def _toggle_all(self) -> None:
        candidates = [it for it in self.items if it.new_name and it.status != namer.DONE]
        if not candidates:
            return
        target = not all(it.selected for it in candidates)
        for it in candidates:
            it.selected = target
        self._replan()

    # ------------------------------------------------------------ adding files
    def _on_drop(self, event) -> None:
        if self._running:
            return
        self.add_paths(list(self.root.tk.splitlist(event.data)))

    def _add_files_dialog(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[(t("file_dialog_ebook"), "*.epub *.pdf *.EPUB *.PDF")])
        if paths:
            self.add_paths(list(paths))

    def _add_folder_dialog(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.add_paths([folder])

    def clear(self) -> None:
        if self._running and self._renaming:
            return                              # never interrupt a rename batch; reading may be abandoned
        self.read_gen += 1                      # any metadata read still in flight is discarded
        self.items = []
        self.sources.clear()
        self.iid_to_item.clear()
        self.tree.delete(*self.tree.get_children())
        self.progress.configure(value=0)
        self._set_running(False)
        self._set_status("status_ready")
        self._update_count()

    def add_paths(self, paths: list[str]) -> None:
        for p in paths:
            if not os.path.exists(p):
                self.log("err_open_failed", name=p)
                continue
            if p not in self.sources:
                self.sources.append(p)
        self._reload()

    def _reload(self) -> None:
        """Re-read every source path. Metadata is read in a worker thread so a
        300-file folder does not freeze the window; rows appear when done."""
        self.read_gen += 1
        gen = self.read_gen
        files = meta.collect_files(self.sources, recursive=bool(self.var_recursive.get()))
        # Rows already on screen keep their state (typed names, unchecked boxes);
        # only files not seen before are read.
        # A renamed (done) row is read again: its file is new, and it must be possible to rename it again.
        known = {os.path.normcase(os.path.abspath(it.path)): it for it in self.items if it.status != namer.DONE}
        self.items = []
        self.iid_to_item.clear()
        self.tree.delete(*self.tree.get_children())
        self._update_count()
        if not files:
            self._set_status("status_ready")
            return
        self._set_running(True)
        self.progress.configure(maximum=len(files), value=0)
        self._set_status("status_reading", done=0, total=len(files))

        def work() -> None:
            items: list[Item] = []
            reused: set[int] = set()
            for idx, path in enumerate(files, 1):
                if gen != self.read_gen:
                    return
                old = known.get(os.path.normcase(os.path.abspath(path)))
                if old is not None:
                    items.append(old)
                    reused.add(id(old))
                else:
                    try:
                        found = meta.read_meta(path)
                    except Exception:           # a reader bug must not freeze the window
                        found = meta.Meta(error="open_failed")
                    items.append(Item(path=path, meta=found))
                if idx % 20 == 0 or idx == len(files):
                    self.root.after(0, self._reading_progress, gen, idx, len(files))
            self.root.after(0, self._reading_done, gen, items, reused)

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _reading_progress(self, gen: int, done: int, total: int) -> None:
        if gen != self.read_gen or self._closing:
            return
        self.progress.configure(value=done)
        self._set_status("status_reading", done=done, total=total)

    def _reading_done(self, gen: int, items: list[Item], reused: set[int] | None = None) -> None:
        if gen != self.read_gen or self._closing:
            return
        reused = reused or set()
        self.items = items
        self._set_running(False)
        namer.plan(self.items, self.options())
        new_items = [it for it in self.items if id(it) not in reused]
        for it in self.items:
            iid = self.tree.insert("", "end", text="", values=self._row_values(it))
            self.iid_to_item[iid] = it
            self._refresh_row(iid)
        for it in new_items:
            if it.meta.error == "password":
                self.log("err_password", name=it.current)
            elif it.meta.error:
                self.log("err_open_failed", name=it.current)
        if new_items:
            nometa = sum(1 for it in new_items if it.status == namer.NOMETA)
            self.log("log_added", count=len(new_items), nometa=nometa)
        self._set_status("status_ready")
        self.progress.configure(value=0)
        self._update_count()

    # ------------------------------------------------------------ table interaction
    def _on_tree_click(self, event) -> None:
        self._commit_edit()
        if self._running:
            return
        if self.tree.identify_region(event.x, event.y) not in ("tree", "cell"):
            return
        if self.tree.identify_column(event.x) != "#0":
            return
        iid = self.tree.identify_row(event.y)
        if iid:
            self._toggle(iid)

    def _on_space(self, _event) -> None:
        if self._running:
            return
        sel = self.tree.selection()
        if sel:
            self._toggle(sel[0])

    def _toggle(self, iid: str) -> None:
        it = self.iid_to_item[iid]
        if it.status == namer.DONE:
            return
        if not it.new_name:               # nothing to rename to: let the user type one
            self._begin_edit(iid)
            return
        it.selected = not it.selected
        self._replan()

    def _on_tree_double(self, event) -> None:
        if self._running:
            return
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        col = self.tree.identify_column(event.x)
        if col != f"#{COLUMNS.index('new') + 1}":
            return
        iid = self.tree.identify_row(event.y)
        if iid and self.iid_to_item[iid].status != namer.DONE:
            self._begin_edit(iid)

    def _begin_edit(self, iid: str) -> None:
        self._commit_edit()
        col = f"#{COLUMNS.index('new') + 1}"
        self.tree.see(iid)
        bbox = self.tree.bbox(iid, col)
        if not bbox:
            return
        x, y, w, h = bbox
        it = self.iid_to_item[iid]
        self._edit_iid = iid
        self._editor = tk.Entry(self.tree)
        self._editor.insert(0, it.new_name or it.current)
        self._editor.select_range(0, "end")
        self._editor.place(x=x, y=y, width=w, height=h)
        self._editor.focus_set()
        self._editor.bind("<Return>", lambda e: self._commit_edit())
        self._editor.bind("<Escape>", lambda e: self._cancel_edit())
        self._editor.bind("<FocusOut>", lambda e: self._commit_edit())

    def _cancel_edit(self) -> None:
        if self._editor is not None:
            self._editor.destroy()
        self._editor, self._edit_iid = None, None

    def _commit_edit(self) -> None:
        if self._editor is None or self._edit_iid is None:
            return
        text = self._editor.get()
        iid = self._edit_iid
        self._cancel_edit()
        it = self.iid_to_item.get(iid)
        if it is None:
            return
        namer.set_manual_name(it, text)
        self._replan()

    # ------------------------------------------------------------ run
    def _run(self) -> None:
        self._commit_edit()
        if self._running:
            return
        if not self.items:
            messagebox.showinfo(t("dlg_confirm"), t("msg_no_files"), parent=self.root)
            return
        namer.plan(self.items, self.options())
        self._refresh_rows()
        todo = [it for it in self.items if it.selected and it.new_name and it.status in (namer.OK, namer.DUP)]
        if not todo:
            messagebox.showinfo(t("dlg_confirm"), t("msg_nothing_selected"), parent=self.root)
            return
        if not messagebox.askyesno(t("dlg_confirm"), t("warn_run", count=len(todo)), parent=self.root):
            return
        self._save_options()
        self._set_running(True)
        self._renaming = True
        self.progress.configure(maximum=len(todo), value=0)
        self._set_status("status_renaming", done=0, total=len(todo))
        items = self.items

        def work() -> None:
            def progress(done: int, total: int) -> None:
                self.root.after(0, self._rename_progress, done, total)

            result = namer.RenameResult()
            try:
                namer.apply(items, progress=progress, result=result)
            except Exception as exc:             # unexpected: still log what was renamed, and unlock the window
                result.failed.append((namer.Item(path=str(exc), meta=meta.Meta()), str(exc)))
            written, log_failed = undo.record_ex(result.renamed)
            self.root.after(0, self._rename_done, result, written, log_failed)

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _rename_progress(self, done: int, total: int) -> None:
        if self._closing:
            return
        self.progress.configure(value=done)
        self._set_status("status_renaming", done=done, total=total)

    def _rename_done(self, result: namer.RenameResult, folders: list[str],
                     log_failed: list[str] | None = None) -> None:
        self._renaming = False
        if self._closing:
            return
        log_failed = log_failed or []
        self._set_running(False)
        for old, new in result.renamed:
            self.log("log_renamed", old=os.path.basename(old), new=os.path.basename(new))
        for it, err in result.failed:
            self.log("err_rename_failed", name=it.current, error=err)
        for folder in folders:
            self.log("log_saved", path=undo.log_path(folder))
        for folder in log_failed:
            self.log("err_log_failed", folder=folder)
        namer.plan(self.items, self.options())
        for it, err in result.failed:                  # plan() resets failures; keep them visible until the next change
            it.status, it.error = namer.FAILED, err
        self._refresh_rows()
        self._update_count()
        self._set_status("msg_done", count=len(result.renamed))
        self.progress.configure(value=0)
        text = t("msg_done", count=len(result.renamed))
        if result.failed:
            text += "\n" + t("msg_failed", count=len(result.failed))
        if log_failed:
            text += "\n" + "\n".join(t("err_log_failed", folder=f) for f in log_failed)
        if result.failed or log_failed:
            messagebox.showwarning(t("dlg_error"), text, parent=self.root)
        else:
            messagebox.showinfo(t("dlg_done"), text, parent=self.root)

    # ------------------------------------------------------------ undo
    def _undo_folders(self) -> list[str]:
        folders: list[str] = []
        for p in self.sources:
            folder = p if os.path.isdir(p) else os.path.dirname(os.path.abspath(p))
            if folder not in folders:
                folders.append(folder)
        for it in self.items:
            if it.folder not in folders:
                folders.append(it.folder)
        return undo.find_logs(folders, recursive=bool(self.var_recursive.get()))

    def _undo(self) -> None:
        self._commit_edit()
        if self._running:
            return
        logs = self._undo_folders()
        if not logs and not self.sources:
            folder = filedialog.askdirectory()
            if not folder:
                return
            logs = undo.find_logs([folder], recursive=bool(self.var_recursive.get()))
            if logs:
                self.sources.append(folder)
        if not logs:
            messagebox.showinfo(t("btn_undo"), t("msg_no_log"), parent=self.root)
            return
        if not messagebox.askyesno(t("dlg_confirm"), t("warn_undo", count=len(logs)), parent=self.root):
            return
        restored: list[tuple[str, str]] = []
        skipped: list[tuple[str, str]] = []
        for folder in logs:
            result = undo.undo(folder)
            restored += result.restored
            skipped += result.skipped
        for src, dst in restored:
            self.log("log_undone", new=os.path.basename(src), old=os.path.basename(dst))
        for path, reason in skipped:
            key = {"missing": "log_undo_missing", "error": "log_undo_error"}.get(reason, "log_undo_skipped")
            self.log(key, name=os.path.basename(path))
        text = t("msg_undo_done", count=len(restored))
        in_use = [os.path.basename(p) for p, r in skipped if r != "missing"]
        if in_use:
            text += "\n\n" + t("msg_undo_skipped", count=len(in_use), names="\n".join(in_use[:20]))
        self._set_status("msg_undo_done", count=len(restored))
        messagebox.showinfo(t("btn_undo"), text, parent=self.root)
        if self.sources:
            self._reload()

    # ------------------------------------------------------------ misc
    def _open_folder(self) -> None:
        target = None
        sel = self.tree.selection()
        if sel:
            target = self.iid_to_item[sel[0]].path
        elif self.items:
            target = self.items[0].path
        elif self.sources:
            target = self.sources[0]
        if not target:
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", target])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(target)])
        except OSError:
            pass

    def _on_close(self) -> None:
        self._closing = True
        self.read_gen += 1
        try:
            self._save_options()
        except Exception:
            pass
        self._close_when_idle()

    def _close_when_idle(self) -> None:
        """Wait for the worker before tearing down: a rename batch that is
        half done must finish and write its log."""
        if self.worker and self.worker.is_alive():
            self.root.after(100, self._close_when_idle)
            return
        self.root.destroy()

    def mainloop(self) -> None:
        self.root.mainloop()


def launch(initial_paths: list[str] | None = None) -> None:
    App(initial_paths).mainloop()
