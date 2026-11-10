"""The splash picture and the PyMuPDF preload (2026-11-10).

    python -m pytest tests/test_startup.py -q

Every test runs in a fresh process: once pymupdf is in sys.modules of the pytest process there
is no way to see "not loaded yet". A slow import is simulated with a finder that sleeps in front
of pymupdf. Settings go to a temporary folder, the network to a dead proxy, and the window tests
need a display.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SAMPLES = os.path.join(ROOT, "samples")

HEAD = r"""
import json, os, sys, threading, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ROOT)
import i18n
i18n.SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")
i18n.init("en")
def loaded():
    return "pymupdf" in sys.modules
class Slow:
    def find_spec(self, name, path=None, target=None):
        if name == "pymupdf":
            time.sleep(1.5)
        return None
class Broken:
    def find_spec(self, name, path=None, target=None):
        if name == "pymupdf":
            raise ImportError("boom pymupdf")
        return None
def out(**kw):
    print("RESULT " + json.dumps(kw, ensure_ascii=False), flush=True)
def fake_splash():
    import types
    mod = types.ModuleType("pyi_splash")
    mod.calls = []
    mod.close = lambda: mod.calls.append(1)
    sys.modules["pyi_splash"] = mod
    return mod
def no_network():
    import urllib.request, urllib.error
    def blocked(*a, **k):
        raise urllib.error.URLError("blocked in test")
    urllib.request.urlopen = blocked
    import update_check
    update_check.fetch.__kwdefaults__["opener"] = blocked
    update_check.check_async.__kwdefaults__["fetcher"] = lambda s, v, **k: None
no_network()
"""


def run(body: str, timeout: int = 120, **values) -> dict:
    tmp = tempfile.mkdtemp(prefix="ebr_startup_test_")
    try:
        script = os.path.join(tmp, "probe.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(f"ROOT = {ROOT!r}\nSETTINGS_DIR = {tmp!r}\n")
            for k, v in values.items():
                f.write(f"{k} = {v!r}\n")
            f.write(HEAD + body)
        env = dict(os.environ, APPDATA=os.path.join(tmp, "appdata"), PYTHONIOENCODING="utf-8",
                   HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9")
        p = subprocess.run([sys.executable, script], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=timeout, cwd=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, f"no result rc={p.returncode}\n{p.stdout[-800:]}\n{p.stderr[-1500:]}"
    assert p.returncode == 0, f"rc={p.returncode}\n{p.stderr[-1500:]}"
    return json.loads(lines[-1][7:])


@pytest.fixture
def pdfs():
    """Copies of two sample PDFs in a writable temporary folder (the samples themselves stay as they are)."""
    tmp = tempfile.mkdtemp(prefix="ebr_startup_pdf_")
    out = []
    for name in ("Document1.pdf", "scan001.pdf"):
        shutil.copy(os.path.join(SAMPLES, name), tmp)
        out.append(os.path.join(tmp, name))
    yield out
    shutil.rmtree(tmp, ignore_errors=True)


def test_importing_the_program_does_not_load_pymupdf():
    r = run("import main, gui\nout(loaded=loaded())\n")
    assert r == {"loaded": False}


def test_window_comes_up_without_pymupdf():
    r = run(r'''
import gui
app = gui.App(scale=1.0, check_updates=False)
app.root.update()
state = loaded()
app.root.destroy()
out(loaded=state)
''')
    assert r == {"loaded": False}


def test_preload_imports_pymupdf_and_swallows_failure():
    r = run(r'''
import meta
before = loaded()
meta.preload()
after = loaded()
out(before=before, after=after)
''')
    assert r == {"before": False, "after": True}
    # a broken PyMuPDF: the preload stays quiet, the real read still raises ImportError as before
    r = run(r'''
sys.meta_path.insert(0, Broken())
import meta
meta.preload()
try:
    meta.read_pdf(PDF)
    kind = "none"
except ImportError:
    kind = "ImportError"
out(kind=kind, loaded=loaded())
''', PDF=os.path.join(SAMPLES, "Document1.pdf"))
    assert r == {"kind": "ImportError", "loaded": False}


@pytest.mark.parametrize("with_preload", [True, False])
def test_pdf_dropped_while_pymupdf_is_still_loading(pdfs, with_preload):
    """Files added right after the window opens, while the import is slow: the window keeps
    ticking and the metadata is the same as a plain read."""
    r = run(r'''
import gui, meta
sys.meta_path.insert(0, Slow())
app = gui.App(scale=1.0, check_updates=False)
app.root.update()
if WITH_PRELOAD:
    threading.Thread(target=meta.preload, daemon=True).start()
dropped_before_load = not loaded()
app.add_paths(PDFS)
ticks = []
def tick():
    ticks.append(time.perf_counter())
    app.root.after(30, tick)
tick()
def watch():
    if app._running or not app.items:
        app.root.after(50, watch)
    else:
        app.root.after(100, app.root.quit)
watch()
app.root.after(60000, app.root.quit)
app.root.mainloop()
gaps = [b - a for a, b in zip(ticks, ticks[1:])]
got = {os.path.basename(i.path): [i.meta.title, i.meta.error] for i in app.items}
app.root.destroy()
plain = {os.path.basename(p): [meta.read_meta(p).title, meta.read_meta(p).error] for p in PDFS}
out(dropped_before_load=dropped_before_load, n_ticks=len(ticks), max_gap=max(gaps), got=got, plain=plain)
''', PDFS=pdfs, WITH_PRELOAD=with_preload)
    assert r["dropped_before_load"] is True
    assert r["got"] == r["plain"]
    assert len(r["got"]) == 2
    assert r["n_ticks"] > 30 and r["max_gap"] < 1.0, "the window froze while waiting for the import"


LAUNCH_WRAP = r'''
import tkinter as tk
import gui
splash = fake_splash()
Real = gui.App
seen = {}
class App(Real):
    def __init__(self, initial_paths=None, **kw):
        kw.setdefault("check_updates", False)
        super().__init__(initial_paths, scale=1.0, **kw)
        seen["app"] = self
        self.root.after(20000, self.root.destroy)     # safety net for a mutation that never closes the splash
gui.App = App
state = {}
def on_close():
    root = seen["app"].root
    try:
        state["viewable"] = bool(root.winfo_viewable())
    except Exception as e:
        state["error"] = repr(e)
    state["loaded_at_close"] = loaded()
    splash.calls.append(1)
    root.after(CLOSE_AFTER, root.destroy)
splash.close = on_close
'''


def test_launch_closes_splash_once_after_the_window_is_drawn():
    r = run("CLOSE_AFTER = 300\n" + LAUNCH_WRAP + r'''
gui.launch()
out(calls=len(splash.calls), **state)
''')
    assert r == {"calls": 1, "viewable": True, "loaded_at_close": False}


def test_launch_starts_the_preload_in_the_background():
    r = run("CLOSE_AFTER = 8000\n" + LAUNCH_WRAP + r'''
def check():
    if loaded():
        state["loaded"] = True
        seen["app"].root.destroy()
    else:
        seen["app"].root.after(50, check)
real_update = tk.Tk.update
def update(self):
    real_update(self)
    self.after(50, check)
    tk.Tk.update = real_update
tk.Tk.update = update
gui.launch()
out(loaded=state.get("loaded", False))
''')
    assert r == {"loaded": True}


def test_splash_is_closed_when_the_window_cannot_be_made():
    r = run(r'''
import gui
splash = fake_splash()
class Bad:
    def __init__(self, *a, **k):
        raise RuntimeError("no window")
gui.App = Bad
try:
    gui.launch()
    kind = "none"
except RuntimeError:
    kind = "RuntimeError"
out(kind=kind, calls=len(splash.calls))
''')
    assert r == {"kind": "RuntimeError", "calls": 1}


def test_cli_paths_close_the_splash():
    r = run(r'''
import main
splash = fake_splash()
try:
    main.main(["--version"])
    version_exit = "none"
except SystemExit:
    version_exit = "SystemExit"
after_version = len(splash.calls)
rc = main.main([EMPTY, "--dry-run"])
out(version_exit=version_exit, after_version=after_version, after_cli=len(splash.calls), rc=rc, loaded=loaded())
''', EMPTY=tempfile.mkdtemp(prefix="ebr_startup_empty_"))
    assert r["version_exit"] == "SystemExit" and r["after_version"] == 1
    assert r["after_cli"] == 2
    assert r["loaded"] is False


def test_close_is_silent_without_pyinstaller_and_on_error():
    r = run(r'''
import splash as sp
sp.close()
mod = fake_splash()
def boom():
    raise ConnectionError("already closed")
mod.close = boom
sp.close()
out(ok=True)
''')
    assert r == {"ok": True}


def test_splash_picture_is_small_and_present():
    path = os.path.join(ROOT, "assets", "splash.png")
    assert os.path.exists(path)
    assert os.path.getsize(path) < 20_000
    with open(path, "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"
    with open(os.path.join(ROOT, "build.bat"), encoding="utf-8") as f:
        assert "--splash assets\\splash.png" in f.read()
