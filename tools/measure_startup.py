"""Time a built exe from start to the splash picture and to the main window (2026-11-10, splash work).

    python tools/measure_startup.py <exe> [runs=3] [--shot picture.png] [--close]

- The exe is copied to a temporary folder and started from there, so the settings.json it writes
  lands beside the copy, never beside the real exe. APPDATA and TEMP point into the same folder;
  anything a forced kill leaves behind (_MEI*) is removed with it.
- No internet: HTTP(S)_PROXY point at a dead proxy (127.0.0.1:9), so the once-a-day version check
  cannot reach the production server (global rule 8).
- Only windows of this exe's own process tree are looked at. A window with a title bar (WS_CAPTION)
  is the program window; one without is the splash picture.
- Taskbar buttons: visible, unowned windows without WS_EX_TOOLWINDOW. Two would mean the splash
  shows up beside the program.
- --close: once the window is up, send WM_CLOSE (as the user would, while PyMuPDF may still be
  loading in the background) and check the exit code and that no _MEI* folder is left.
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.SetProcessDPIAware()

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION, WS_EX_TOOLWINDOW = 0x00C00000, 0x00000080
GW_OWNER = 4
WM_CLOSE = 0x0010
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindow.restype = wintypes.HWND
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE


def app_titles() -> set[str]:
    out = set()
    for name in os.listdir(os.path.join(ROOT, "lang")):
        if name.endswith(".json"):
            with open(os.path.join(ROOT, "lang", name), encoding="utf-8") as f:
                out.add(json.load(f)["app_title"])
    return out


TITLES = app_titles()


class PE(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


def family(root_pid: int) -> set[int]:
    """root_pid and every descendant (the onefile bootloader starts the real program as a child)."""
    snap = kernel32.CreateToolhelp32Snapshot(2, 0)
    pe = PE()
    pe.dwSize = ctypes.sizeof(PE)
    parents = {}
    ok = kernel32.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        parents[pe.th32ProcessID] = pe.th32ParentProcessID
        ok = kernel32.Process32NextW(snap, ctypes.byref(pe))
    kernel32.CloseHandle(snap)
    found = {root_pid}
    grew = True
    while grew:
        grew = False
        for pid, parent in parents.items():
            if parent in found and pid not in found:
                found.add(pid)
                grew = True
    return found


def windows_of(pids: set[int]) -> list[dict]:
    """Visible top-level windows owned by those processes."""
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            out.append(dict(hwnd=hwnd, title=buf.value, pid=pid.value,
                            caption=bool((style & WS_CAPTION) == WS_CAPTION),
                            taskbar=not (ex & WS_EX_TOOLWINDOW) and not user32.GetWindow(hwnd, GW_OWNER),
                            size=(r.right - r.left, r.bottom - r.top)))
        return True
    user32.EnumWindows(cb, 0)
    return out


def offline_env(base: dict) -> dict:
    env = dict(base)
    env.update(HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9",
               https_proxy="http://127.0.0.1:9", http_proxy="http://127.0.0.1:9", NO_PROXY="", no_proxy="")
    return env


def shot(hwnd, path: str) -> None:
    """What is really on screen (PrintWindow misses the splash's scaling)."""
    from PIL import ImageGrab
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    ImageGrab.grab((r.left, r.top, r.right, r.bottom), all_screens=True).save(path)


def prepare(exe: str) -> str:
    """One copy of the exe in a temporary folder of its own; every run starts that copy, so the
    settings.json it writes lands there. Copying once (not per run) keeps the first-run virus scan
    of a fresh file out of the timings. Remove the folder with cleanup() at the end."""
    home = tempfile.mkdtemp(prefix="ebr_measure_app_")
    exe_copy = os.path.join(home, os.path.basename(exe))
    shutil.copy(exe, exe_copy)
    return exe_copy


def cleanup(exe_copy: str) -> None:
    shutil.rmtree(os.path.dirname(exe_copy), ignore_errors=True)


def measure(exe_copy: str, shot_path: str | None = None, close: bool = False, limit: float = 60) -> dict:
    home = os.path.dirname(exe_copy)
    for leftover in ("settings.json", "rename_log.json"):           # each run starts like a first start
        try:
            os.remove(os.path.join(home, leftover))
        except OSError:
            pass
    root = tempfile.mkdtemp(prefix="ebr_measure_")
    tmp = os.path.join(root, "tmp")
    os.makedirs(tmp)
    env = offline_env(dict(os.environ, APPDATA=os.path.join(root, "appdata"), TEMP=tmp, TMP=tmp))
    res = dict(splash=None, window=None, splash_gone=None, tasks_max=0, tasks_after=None, leftover=None,
               mei=0, close_rc=None, close_took=None, close_left=None)
    t0 = time.perf_counter()
    proc = subprocess.Popen([exe_copy], env=env, cwd=home)
    try:
        pids = family(proc.pid)
        last_family = 0.0
        settled = None
        main_hwnd = None
        while time.perf_counter() - t0 < limit:
            now = time.perf_counter() - t0
            if now - last_family > 0.1:
                pids = family(proc.pid)
                last_family = now
            ws = windows_of(pids)
            plain = [w for w in ws if not w["caption"]]
            main = [w for w in ws if w["caption"] and w["title"] in TITLES]
            res["tasks_max"] = max(res["tasks_max"], sum(w["taskbar"] for w in ws))
            if plain and res["splash"] is None:
                res["splash"] = now
                res["splash_info"] = {k: plain[0][k] for k in ("title", "taskbar", "size")}
                if shot_path:
                    time.sleep(0.15)
                    shot(plain[0]["hwnd"], shot_path)
            if main and res["window"] is None:
                res["window"] = now
                res["window_title"] = main[0]["title"]
                main_hwnd = main[0]["hwnd"]
                settled = now
            if res["window"] is not None and not plain and res["splash_gone"] is None:
                res["splash_gone"] = now
            # the picture 1.5 s after the window came up; a splash still there gets up to 5 s to go away
            # (under heavy load the window takes longer to paint, and the splash is closed only after that)
            if settled is not None and now - settled > 1.5 and (not plain or now - settled > 5.0):
                res["tasks_after"] = sum(w["taskbar"] for w in ws)
                res["leftover"] = len(plain)
                break
            time.sleep(0.01)
        if close and main_hwnd:
            user32.PostMessageW(main_hwnd, WM_CLOSE, 0, 0)
            t1 = time.perf_counter()
            try:
                res["close_rc"] = proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                res["close_rc"] = "timeout"
            res["close_took"] = time.perf_counter() - t1
            time.sleep(0.5)
            res["close_left"] = len([d for d in os.listdir(tmp) if d.startswith("_MEI")])
        res["mei"] = len([d for d in os.listdir(tmp) if d.startswith("_MEI")])
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            time.sleep(1.0)
        shutil.rmtree(root, ignore_errors=True)     # the only _MEI* a forced kill leaves are in here
    return res


def fmt(v) -> str:
    return f"{v:.2f}" if isinstance(v, float) else "-"


def main() -> int:
    args = list(sys.argv[1:])
    shot_path = None
    if "--shot" in args:
        i = args.index("--shot")
        shot_path = args[i + 1]
        del args[i:i + 2]
    close = "--close" in args
    if close:
        args.remove("--close")
    exe = args[0]
    n = int(args[1]) if len(args) > 1 else 3
    print(f"{exe}  ({os.path.getsize(exe) / 1024 / 1024:.1f}MB)")
    exe_copy = prepare(exe)
    try:
        return report(exe_copy, n, shot_path, close)
    finally:
        cleanup(exe_copy)


def report(exe_copy: str, n: int, shot_path: str | None, close: bool) -> int:
    print("run | splash(s) | window(s) | splash gone(s) | taskbar max | taskbar after | splash left | _MEI"
          + (" | close rc | close(s) | _MEI left" if close else ""))
    rows = []
    for k in range(1, n + 1):
        r = measure(exe_copy, shot_path if k == 1 else None, close=close)
        rows.append(r)
        line = (f"{k} | {fmt(r['splash'])} | {fmt(r['window'])} | {fmt(r['splash_gone'])} | {r['tasks_max']} | "
                f"{r['tasks_after']} | {r['leftover']} | {r['mei']}")
        if close:
            line += f" | {r['close_rc']} | {fmt(r['close_took'])} | {r['close_left']}"
        print(line, flush=True)
        if r.get("splash_info"):
            print("   splash window:", r["splash_info"], flush=True)
        if r.get("window_title"):
            print("   program window:", r["window_title"], flush=True)
    win = [r["window"] for r in rows if r["window"]]
    spl = [r["splash"] for r in rows if r["splash"]]
    if win:
        print(f"mean: window {sum(win) / len(win):.2f}s" + (f" · splash {sum(spl) / len(spl):.2f}s" if spl else ""))
    bad = [r for r in rows if r["window"] is None or r["tasks_max"] > 1 or r["leftover"]
           or (close and (r["close_rc"] != 0 or r["close_left"]))]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
