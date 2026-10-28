"""Tests for the look of the window: palette, drawn images, fonts and layout.

The layout tests build the real window at several display scales and in every
language, then check that nothing is cut off, hidden, overlapping or taller than
the screen. They need a display and are skipped without one.

    python -m unittest tests.test_ui -v
"""
from __future__ import annotations

import os
import shutil
import struct
import sys
import tempfile
import tkinter as tk
import tkinter.font as tkfont
import unittest
import zlib
from tkinter import messagebox, ttk
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "samples"))

import i18n  # noqa: E402
import icon  # noqa: E402
import make_samples  # noqa: E402
import theme  # noqa: E402
import version  # noqa: E402


def setUpModule() -> None:
    # the user's real settings.json must never be touched by a window test
    i18n.SETTINGS_PATH = os.path.join(tempfile.mkdtemp(prefix="ebr_ui_settings_"), "settings.json")
    i18n.init("en")


def decode_png(data: bytes) -> tuple[int, int, bytes]:
    """Width, height and RGBA bytes of a PNG made by icon.png_bytes (filter type 0 only)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, width, height = 8, b"", 0, 0
    while pos < len(data):
        length, tag = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
        elif tag == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 4
    rows = [raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)] for y in range(height)]
    return width, height, b"".join(rows)


def pixel(rgba: bytes, width: int, x: int, y: int) -> tuple[int, int, int, int]:
    o = (y * width + x) * 4
    return rgba[o], rgba[o + 1], rgba[o + 2], rgba[o + 3]


# ============================================================ palette and fonts (no window needed)
class PaletteTests(unittest.TestCase):
    def test_text_is_readable_on_its_background(self) -> None:
        p = theme.PALETTE
        pairs = {
            "text on card": (p["text"], p["card"], 7.0),
            "text on window": (p["text"], p["bg"], 7.0),
            "text on selected row": (p["text"], p["select"], 7.0),
            "muted on card": (p["muted"], p["card"], 4.5),
            "muted on window": (p["muted"], p["bg"], 4.5),
            "muted on header": (p["muted"], p["header_bg"], 4.5),
            "white on accent button": (p["on_accent"], p["accent"], 4.5),
            "white on hovered accent": (p["on_accent"], p["accent_hover"], 4.5),
            "accent on soft accent (count pill)": (p["accent"], p["accent_soft"], 4.5),
            "accent link on card": (p["accent"], p["card"], 4.5),
            "duplicate row text": (p["warn"], p["warn_bg"], 4.5),
            "failed row text": (p["bad"], p["bad_bg"], 4.5),
            "done row text": (p["ok"], p["ok_bg"], 4.5),
            "failure message on card": (p["bad"], p["card"], 4.5),
            "no-metadata row text": (p["faint"], p["card"], 3.0),
            "no-metadata row text on zebra": (p["faint"], p["row_alt"], 3.0),
        }
        for name, (fg, bg, minimum) in pairs.items():
            self.assertGreaterEqual(theme.contrast_ratio(fg, bg), minimum, f"{name}: {fg} on {bg}")

    def test_contrast_ratio_extremes(self) -> None:
        self.assertAlmostEqual(theme.contrast_ratio("#000000", "#FFFFFF"), 21.0, places=1)
        self.assertAlmostEqual(theme.contrast_ratio("#777777", "#777777"), 1.0, places=3)

    def test_every_status_has_a_row_colour(self) -> None:
        import namer

        for status in (namer.OK, namer.NOCHANGE, namer.DUP, namer.NOMETA, namer.FAILED, namer.DONE):
            self.assertIn(status, theme.STATUS_ROW_COLORS)
        for fg_key, bg_key in theme.STATUS_ROW_COLORS.values():
            self.assertIn(fg_key, theme.PALETTE)
            self.assertTrue(bg_key is None or bg_key in theme.PALETTE)

    def test_all_colours_are_valid_hex(self) -> None:
        for key, value in theme.PALETTE.items():
            self.assertRegex(value, r"^#[0-9A-Fa-f]{6}$", key)


class FontChoiceTests(unittest.TestCase):
    def test_first_installed_candidate_wins(self) -> None:
        self.assertEqual(theme.pick_family("ja", {"Arial", "Yu Gothic UI", "Meiryo UI"}, "X"), "Yu Gothic UI")
        self.assertEqual(theme.pick_family("zh-CN", {"Arial", "Microsoft YaHei"}, "X"), "Microsoft YaHei")

    def test_korean_system_font_listed_by_its_korean_name(self) -> None:
        """On Korean Windows Tk lists Malgun Gothic under its Korean name only."""
        self.assertEqual(theme.pick_family("ko", {theme.MALGUN_GOTHIC_KO, "Arial"}, "X"), theme.MALGUN_GOTHIC_KO)

    def test_fallback_and_unknown_language(self) -> None:
        self.assertEqual(theme.pick_family("ko", set(), "Fallback"), "Fallback")
        self.assertEqual(theme.pick_family("xx", {"Segoe UI"}, "Fallback"), "Segoe UI")

    def test_case_insensitive_match_returns_the_installed_spelling(self) -> None:
        self.assertEqual(theme.pick_family("en", {"segoe ui"}, "X"), "segoe ui")

    def test_mono_choice(self) -> None:
        self.assertEqual(theme.pick_mono({"Consolas", "Arial"}, "X"), "Consolas")
        self.assertEqual(theme.pick_mono(set(), "Fixed"), "Fixed")


class ScaleTests(unittest.TestCase):
    def test_clamp(self) -> None:
        self.assertEqual(theme.clamp_scale(0.5), theme.MIN_SCALE)
        self.assertEqual(theme.clamp_scale(1.5), 1.5)
        self.assertEqual(theme.clamp_scale(9), theme.MAX_SCALE)
        for bad in (float("nan"), "wide", None, -3):
            self.assertGreaterEqual(theme.clamp_scale(bad), theme.MIN_SCALE)
            self.assertLessEqual(theme.clamp_scale(bad), theme.MAX_SCALE)

    def test_dpi_awareness_never_raises(self) -> None:
        theme.enable_dpi_awareness()
        theme.enable_dpi_awareness()                      # a second call is a harmless no-op


# ============================================================ drawn images (no window needed)
class IconTests(unittest.TestCase):
    def test_app_icon_png(self) -> None:
        width, height, rgba = decode_png(icon.render_app_icon(64))
        self.assertEqual((width, height), (64, 64))
        self.assertEqual(pixel(rgba, 64, 0, 0)[3], 0)                       # rounded corner is transparent
        self.assertEqual(pixel(rgba, 64, 32, 20), (255, 255, 255, 255))     # the ribbon is white
        r, g, b, a = pixel(rgba, 64, 12, 32)                                # the tile around it is indigo
        self.assertEqual(a, 255)
        self.assertGreater(b, r)
        self.assertGreater(b, g)

    def test_checkbox_images_differ_and_have_the_right_size(self) -> None:
        on = decode_png(icon.render_checkbox(24, True, "#4F46E5", "#BFC5D2"))
        off = decode_png(icon.render_checkbox(24, False, "#4F46E5", "#BFC5D2"))
        self.assertEqual(on[:2], (24, 24))
        self.assertNotEqual(on[2], off[2])
        self.assertEqual(pixel(on[2], 24, 12, 3)[:3], (79, 70, 229))        # filled with the accent colour
        self.assertEqual(pixel(off[2], 24, 12, 12), (255, 255, 255, 255))   # empty box is white inside

    def test_gap_adds_transparent_room_on_the_right(self) -> None:
        width, height, rgba = decode_png(icon.render_checkbox(20, True, "#4F46E5", "#BFC5D2", gap=9))
        self.assertEqual((width, height), (29, 20))
        for x in range(21, 29):
            for y in range(20):
                self.assertEqual(pixel(rgba, width, x, y)[3], 0, (x, y))

    def test_ico_is_a_valid_icon_file(self) -> None:
        data = icon.ico_bytes((16, 32, 256))
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind, count), (0, 1, 3))
        sizes = []
        for i in range(count):
            w, h, _c, _r, _planes, bits, length, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
            sizes.append(w or 256)
            png_w, png_h, _ = decode_png(data[offset:offset + length])
            self.assertEqual((png_w, png_h), (w or 256, h or 256))
            self.assertEqual(bits, 32)
        self.assertEqual(sizes, [16, 32, 256])

    def test_committed_icon_matches_the_generator(self) -> None:
        path = os.path.join(ROOT, "assets", "icon.ico")
        self.assertTrue(os.path.exists(path), "run tools/make_icon.py")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), icon.ico_bytes())

    def test_degenerate_polyline_and_polygon_inputs(self) -> None:
        self.assertTrue(icon._near_polyline(0.5, 0.5, [(0.5, 0.5), (0.5, 0.5)], 0.01))   # zero-length segment
        self.assertFalse(icon._in_polygon(0.5, 0.5, []))


class VersionTests(unittest.TestCase):
    def test_version_format(self) -> None:
        self.assertRegex(version.__version__, r"^\d+\.\d+\.\d+$")

    def test_cli_prints_it(self) -> None:
        import subprocess

        r = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), "--version"], capture_output=True,
                           text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), f"ebook-renamer {version.__version__}")


# ============================================================ the real window
def have_display() -> bool:
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


class FakeEvent:
    def __init__(self, data: str = "", action: str = "copy") -> None:
        self.data, self.action = data, action


@unittest.skipUnless(have_display(), "needs a display")
class WindowTests(unittest.TestCase):
    SCALES = (1.0, 1.25, 1.5, 2.0)

    def setUp(self) -> None:
        import gui

        self.gui = gui
        self.work = tempfile.mkdtemp(prefix="ebr_ui_")
        for name in ("a", "b"):
            make_samples.make_epub(os.path.join(self.work, f"{name}.epub"), 1, "en", "Same", ["Ann"], None)
        make_samples.make_epub(os.path.join(self.work, "c.epub"), 2, "en", None, [], None)
        make_samples.make_epub(os.path.join(self.work, "d.epub"), 3, "ko", "T", ["A"], None)
        patcher = mock.patch.multiple(messagebox, showinfo=mock.Mock(), showwarning=mock.Mock(),
                                      askyesno=mock.Mock(return_value=True))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.apps: list = []
        i18n.set_lang("en", persist=False)

    def tearDown(self) -> None:
        from tests import _netguard

        tried = _netguard.take()
        self.assertEqual(tried, [], "a window test tried to reach the production server")
        for app in self.apps:
            app.read_gen += 1                                  # a read still in flight stops at its next file
            if app.worker is not None:
                app.worker.join(5)
            try:
                app.root.destroy()
            except tk.TclError:
                pass
        self.apps.clear()
        import gc

        gc.collect()
        shutil.rmtree(self.work, ignore_errors=True)
        i18n.set_lang("en", persist=False)

    def make(self, scale: float | None = None, check_updates: bool = False):
        # a window test never talks to the real server unless it fakes the answer itself
        app = self.gui.App(scale=scale, check_updates=check_updates)
        self.apps.append(app)
        return app

    def settle(self, app, done) -> None:
        """Run the real event loop (worker threads need it) until `done()` or about six seconds."""
        state = {"ticks": 0}

        def check() -> None:
            state["ticks"] += 1
            if done() or state["ticks"] > 200:
                app.root.quit()
            else:
                app.root.after(30, check)

        app.root.after(30, check)
        app.root.mainloop()
        app.root.update()

    def load(self, app) -> None:
        """Add the sample folder and wait until the read is finished."""
        app.add_paths([self.work])
        self.settle(app, lambda: not app._running and bool(app.items))
        self.assertEqual(len(app.items), 4)

    def screen_allows(self, app, scale: float) -> bool:
        return (app.theme.px(self.gui.MIN_WINDOW_SIZE[0]) <= app.root.winfo_screenwidth() * 0.94
                and app.theme.px(self.gui.MIN_WINDOW_SIZE[1]) <= app.root.winfo_screenheight() * 0.88)

    # ------------------------------------------------------------ layout
    def check_layout(self, app, label: str) -> None:
        root = app.root
        root.update_idletasks()
        root.update()
        win = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(),
               root.winfo_rooty() + root.winfo_height())

        def box(w):
            return w.winfo_rootx(), w.winfo_rooty(), w.winfo_rootx() + w.winfo_width(), w.winfo_rooty() + w.winfo_height()

        must_show = {"drop zone": app.zone, "add files": app.btn_add, "add folder": app.btn_add_dir,
                     "clear": app.btn_clear, "pattern": app.cmb_pattern, "recursive": app.chk_recursive,
                     "others": app.chk_others, "select all": app.btn_toggle, "table": app.tree, "open folder": app.btn_open,
                     "undo": app.btn_undo, "rename": app.btn_run, "language": app.cmb_lang, "status": app.lbl_status,
                     "update check": app.chk_update, "send feedback": app.btn_feedback}
        for name, widget in must_show.items():
            self.assertTrue(widget.winfo_ismapped(), f"{label}: {name} is not shown")
            left, top, right, bottom = box(widget)
            self.assertGreaterEqual(left, win[0] - 1, f"{label}: {name} sticks out on the left")
            self.assertGreaterEqual(top, win[1] - 1, f"{label}: {name} sticks out at the top")
            self.assertLessEqual(right, win[2] + 1, f"{label}: {name} sticks out on the right")
            self.assertLessEqual(bottom, win[3] + 1, f"{label}: {name} sticks out at the bottom")

        # nothing with a text label is clipped
        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, (ttk.Label, ttk.Button, ttk.Checkbutton)) and child.winfo_ismapped():
                    if child not in (app.lbl_hint, app.lbl_last) and child.winfo_width() + 1 < child.winfo_reqwidth():
                        self.fail(f"{label}: {child.cget('text')!r} is clipped ({child.winfo_width()} < {child.winfo_reqwidth()})")
                walk(child)

        walk(root)

        # the three footer buttons never overlap one another
        footer = sorted((box(b) for b in (app.btn_open, app.btn_undo, app.btn_run)), key=lambda b: b[0])
        for first, second in zip(footer, footer[1:]):
            self.assertLessEqual(first[2], second[0], f"{label}: footer buttons overlap")

        # the drop zone's text stays clear of its buttons
        zone = app.zone
        buttons_left = app.btn_add.winfo_rootx()
        for item in zone.find_all():
            if zone.type(item) == "text":
                x1, y1, x2, y2 = zone.bbox(item)
                self.assertLessEqual(zone.winfo_rootx() + x2, buttons_left + 1, f"{label}: drop text runs under the buttons")
                self.assertGreaterEqual(y1, 0, f"{label}: drop text above the zone")
                self.assertLessEqual(y2, zone.winfo_height(), f"{label}: drop text below the zone")

        # every column, the last (status) included, lies inside the table
        total = sum(int(app.tree.column(c, "width")) for c in ("#0",) + self.gui.COLUMNS)
        self.assertLessEqual(total, app.tree.winfo_width() + 2, f"{label}: columns are wider than the table")
        for status_text in ("No metadata", i18n.t("status_nometa")):
            font = tkfont.nametofont("EbrBody", root=app.root)
            self.assertLessEqual(font.measure(i18n.t("status_nometa")) + app.theme.px(16),
                                 int(app.tree.column("status", "width")), f"{label}: status text clipped")

        # the table keeps room for a useful number of rows
        rowheight = app.theme.px(36)
        self.assertGreaterEqual(app.tree.winfo_height(), 4 * rowheight, f"{label}: table too short")

    def test_layout_in_every_language_at_every_scale(self) -> None:
        checked = 0
        for scale in self.SCALES:
            app = self.make(scale)
            if not self.screen_allows(app, scale):
                continue
            app.root.geometry(f"{app.root.winfo_width()}x{app.root.winfo_height()}")
            self.load(app)
            for lang in i18n.LANGS:
                app.cmb_lang.current(i18n.LANGS.index(lang))
                app._on_lang()
                self.check_layout(app, f"scale {scale} {lang} loaded")
                checked += 1
            app._toggle_log(True)
            self.check_layout(app, f"scale {scale} log open")
            app.clear()
            self.check_layout(app, f"scale {scale} empty")
            app.root.destroy()
            self.apps.remove(app)
        self.assertGreater(checked, 0)

    def test_layout_at_the_smallest_allowed_window(self) -> None:
        app = self.make(1.0)
        app.root.geometry(f"{app.root.minsize()[0]}x{app.root.minsize()[1]}")
        self.load(app)
        for lang in i18n.LANGS:
            app.cmb_lang.current(i18n.LANGS.index(lang))
            app._on_lang()
            self.check_layout(app, f"minimum size {lang}")

    def test_window_never_opens_larger_than_the_screen(self) -> None:
        for scale in (1.0, 2.0, 3.0):
            app = self.make(scale)
            app.root.update()
            self.assertLessEqual(app.root.winfo_width(), app.root.winfo_screenwidth())
            self.assertLessEqual(app.root.winfo_height(), app.root.winfo_screenheight())
            minw, minh = app.root.minsize()
            self.assertLessEqual(minw, app.root.winfo_width())
            self.assertLessEqual(minh, app.root.winfo_height())

    def test_real_screen_scale_is_detected_without_an_override(self) -> None:
        app = self.make(None)
        self.assertGreaterEqual(app.theme.scale, 1.0)
        self.assertLessEqual(app.theme.scale, 3.0)

    # ------------------------------------------------------------ rows
    def test_rows_get_status_tags_zebra_stripes_and_checkbox_images(self) -> None:
        app = self.make(1.0)
        self.load(app)
        rows = app.tree.get_children()
        tags = [app.tree.item(iid, "tags")[0] for iid in rows]
        self.assertEqual([t.rsplit("_", 1)[1] for t in tags], ["even", "odd", "even", "odd"])
        by_name = {app.iid_to_item[iid].current: iid for iid in rows}
        self.assertTrue(app.tree.item(by_name["c.epub"], "tags")[0].startswith("nometa_"))
        self.assertTrue(app.tree.item(by_name["b.epub"], "tags")[0].startswith("dup_"))
        checked = str(app.tree.item(by_name["a.epub"], "image")[0])
        unchecked = str(app.tree.item(by_name["c.epub"], "image")[0])              # no metadata: unticked
        self.assertNotEqual(checked, unchecked)
        app._toggle(by_name["a.epub"])
        self.assertEqual(str(app.tree.item(by_name["a.epub"], "image")[0]), unchecked)

    def test_every_status_text_fits_the_status_column(self) -> None:
        """"No metadata" in Korean was once cut to a few letters."""
        import namer

        for scale in (1.0, 1.5):
            app = self.make(scale)
            for lang in i18n.LANGS:
                app.cmb_lang.current(i18n.LANGS.index(lang))
                app._on_lang()
                font = tkfont.nametofont("EbrBody", root=app.root)
                room = int(app.tree.column("status", "minwidth")) - app.theme.px(16)     # cell padding
                for status in (namer.OK, namer.NOCHANGE, namer.DUP, namer.NOMETA, namer.FAILED, namer.DONE):
                    text = i18n.t(f"status_{status}")
                    self.assertLessEqual(font.measure(text), room, f"scale {scale} {lang}: {text!r}")
            app.root.destroy()
            self.apps.remove(app)

    def test_every_column_heading_fits_its_column(self) -> None:
        for lang in i18n.LANGS:
            app = self.make(1.0)
            app.cmb_lang.current(i18n.LANGS.index(lang))
            app._on_lang()
            font = tkfont.nametofont("EbrHead", root=app.root)
            for col in self.gui.COLUMNS:
                text = app.tree.heading(col, "text")
                self.assertLessEqual(font.measure(text) + app.theme.px(24), int(app.tree.column(col, "minwidth")) + 60,
                                     f"{lang}: heading {text!r}")
            app.root.destroy()
            self.apps.remove(app)

    def test_every_row_tag_is_configured_with_colours(self) -> None:
        app = self.make(1.0)
        import namer

        for status in (namer.OK, namer.NOCHANGE, namer.DUP, namer.NOMETA, namer.FAILED, namer.DONE):
            for parity in ("even", "odd"):
                tag = f"{status}_{parity}"
                self.assertTrue(app.tree.tag_configure(tag, "foreground"), tag)
                self.assertTrue(app.tree.tag_configure(tag, "background"), tag)

    def test_failed_row_stays_marked_after_a_run(self) -> None:
        import namer

        app = self.make(1.0)
        self.load(app)
        locked = open(os.path.join(self.work, "d.epub"), "rb")
        try:
            app._run()
            self.settle(app, lambda: not app._running and not app._renaming)
        finally:
            locked.close()
        iid = next(i for i, it in app.iid_to_item.items() if it.current == "d.epub")
        self.assertEqual(app.iid_to_item[iid].status, namer.FAILED)
        self.assertTrue(app.tree.item(iid, "tags")[0].startswith("failed_"))

    # ------------------------------------------------------------ empty state and drop zone
    def test_empty_hint_shows_only_while_the_table_is_empty(self) -> None:
        app = self.make(1.0)
        app.root.update()
        self.assertTrue(app.empty.winfo_ismapped())
        self.load(app)
        self.assertFalse(app.empty.winfo_ismapped())
        app.clear()
        app.root.update()
        self.assertTrue(app.empty.winfo_ismapped())

    def test_drag_handlers_light_up_the_zone_and_hand_back_the_action(self) -> None:
        app = self.make(1.0)
        self.assertFalse(app.zone.active)
        self.assertEqual(app._on_drop_enter(FakeEvent()), "copy")
        self.assertTrue(app.zone.active)
        self.assertEqual(app._on_drop_leave(FakeEvent()), "copy")
        self.assertFalse(app.zone.active)
        app._on_drop_enter(FakeEvent())
        spaced = self.work                                                    # a path with spaces arrives in braces
        self.assertEqual(app._on_drop(FakeEvent("{" + spaced + "}")), "copy")
        self.assertFalse(app.zone.active)
        self.assertIn(spaced, app.sources)
        self.settle(app, lambda: not app._running and bool(app.items))      # let the worker finish before teardown
        self.assertEqual(len(app.items), 4)

    def test_drag_over_is_ignored_while_working(self) -> None:
        app = self.make(1.0)
        app._running = True
        app._on_drop_enter(FakeEvent())
        self.assertFalse(app.zone.active)
        self.assertEqual(app._on_drop(FakeEvent(self.work)), "copy")
        self.assertEqual(app.sources, [])
        app._running = False

    def test_zone_text_changes_while_dragging(self) -> None:
        app = self.make(1.0)
        app.root.update()

        def texts() -> list[str]:
            return [app.zone.itemcget(i, "text") for i in app.zone.find_all() if app.zone.type(i) == "text"]

        self.assertIn(i18n.t("drop_hint"), texts())
        app.zone.set_active(True)
        self.assertIn(i18n.t("drop_release"), texts())
        self.assertNotIn(i18n.t("drop_hint"), texts())
        app.zone.set_active(False)
        self.assertIn(i18n.t("drop_hint"), texts())

    # ------------------------------------------------------------ log panel
    def test_log_is_closed_until_something_fails(self) -> None:
        app = self.make(1.0)
        app.root.update()
        self.assertFalse(app.log_open)
        self.assertFalse(app.log_body.winfo_ismapped())
        app.log("log_added", count=3, nometa=1)
        app.log("err_password", name="locked.pdf")                # a load-time problem: shown in red, panel stays shut
        self.assertFalse(app.log_open)
        self.assertEqual(str(app.lbl_last.cget("style")), "CardBad.TLabel")
        self.assertIn("locked.pdf", app.lbl_last.cget("text"))
        app.log("err_rename_failed", name="x.epub", error="locked")   # a failed rename opens it
        app.root.update()
        self.assertTrue(app.log_open)
        self.assertTrue(app.log_body.winfo_ismapped())
        self.assertEqual(app.btn_log.cget("text"), self.gui.LOG_OPEN)

    def test_log_toggle_button(self) -> None:
        app = self.make(1.0)
        app.log("log_added", count=1, nometa=0)
        app._toggle_log()
        self.assertTrue(app.log_open)
        app._toggle_log()
        self.assertFalse(app.log_open)
        self.assertEqual(app.btn_log.cget("text"), self.gui.LOG_CLOSED)
        self.assertIn("1", app.txt_log.get("1.0", "end"))          # the text is kept while hidden

    def log_text(self, app) -> str:
        return app.txt_log.get("1.0", "end")

    def test_log_ends_with_how_many_were_renamed_and_then_how_many_were_restored(self) -> None:
        """After an undo the table is read again; that must not be logged as 'Added: N files'."""
        app = self.make(1.0)
        self.load(app)
        self.assertEqual(self.log_text(app).count("Added:"), 1)
        app._run()
        self.settle(app, lambda: not app._running and not app._renaming)
        renamed = i18n.t("msg_done", count=3)                                # a, b and d; c has no metadata
        self.assertEqual(app.lbl_last.cget("text"), renamed)
        self.assertEqual(self.log_text(app).strip().splitlines()[-1], renamed)
        self.assertEqual(app.lbl_status.cget("text"), renamed)

        app._undo()
        self.settle(app, lambda: not app._running and len(app.items) == 4)
        restored = i18n.t("msg_undo_done", count=3)
        lines = self.log_text(app).strip().splitlines()
        self.assertEqual(lines[-1], restored)                                # the last line is the count
        self.assertEqual(app.lbl_last.cget("text"), restored)
        self.assertEqual(app.lbl_status.cget("text"), restored)              # not 'Ready', not 'Reading ...'
        self.assertEqual(self.log_text(app).count("Added:"), 1)              # the re-read is not "new files"
        self.assertEqual([l for l in lines if l.startswith(i18n.t("msg_undo_done", count=0)[:9])], [restored])
        self.assertTrue(all(it.status != "done" for it in app.items))        # and the rows are ready to rename again

    def test_a_normal_read_is_still_announced(self) -> None:
        app = self.make(1.0)
        self.load(app)
        other = os.path.join(self.work, "more")
        os.makedirs(other)
        make_samples.make_epub(os.path.join(other, "z.epub"), 9, "en", "Zed", ["Zoe"], None)
        app.add_paths([other])
        self.settle(app, lambda: not app._running and len(app.items) == 5)
        self.assertEqual(self.log_text(app).count("Added:"), 2)
        self.assertEqual(app.lbl_status.cget("text"), i18n.t("status_ready"))
        self.assertIn("Added: 1 files", self.log_text(app))                  # only the new file is counted

    def test_undo_that_restores_nothing_says_so(self) -> None:
        app = self.make(1.0)
        self.load(app)
        app._run()
        self.settle(app, lambda: not app._running and not app._renaming)
        for name in os.listdir(self.work):                                  # someone re-uses the original names
            if name.startswith("Ann - Same"):
                shutil.copy2(os.path.join(self.work, name), os.path.join(self.work, "a.epub" if name == "Ann - Same.epub" else "b.epub"))
        app._undo()
        self.settle(app, lambda: not app._running and len(app.items) >= 4)
        self.assertIn(i18n.t("msg_undo_done", count=1), self.log_text(app).strip().splitlines()[-1])

    def test_summary_lines_in_every_language(self) -> None:
        for lang in i18n.LANGS:
            i18n.set_lang(lang, persist=False)
            self.assertIn("3", i18n.t("msg_done", count=3))
            self.assertIn("3", i18n.t("msg_undo_done", count=3))
            self.assertNotEqual(i18n.t("msg_done", count=3), i18n.t("msg_undo_done", count=3))
        i18n.set_lang("en", persist=False)

    def test_a_normal_message_restores_the_normal_colour(self) -> None:
        app = self.make(1.0)
        app.log("err_open_failed", name="x")
        app.log("log_added", count=1, nometa=0)
        self.assertEqual(str(app.lbl_last.cget("style")), "Card.TLabel")

    # ------------------------------------------------------------ fonts
    def test_each_language_uses_an_installed_font(self) -> None:
        app = self.make(1.0)
        installed = set(tkfont.families(app.root))
        for lang in i18n.LANGS:
            i18n.set_lang(lang, persist=False)
            app.theme.set_language(lang)
            self.assertIn(app.theme.family, installed, lang)
            for name in ("EbrBody", "EbrBold", "EbrTitle", "EbrSmall"):
                self.assertEqual(tkfont.nametofont(name, root=app.root).actual("family"), app.theme.family, (lang, name))

    def test_font_follows_the_language_switch_in_the_window(self) -> None:
        app = self.make(1.0)
        before = app.theme.family
        for lang in ("ja", "zh-CN", "ko", "en"):
            app.cmb_lang.current(i18n.LANGS.index(lang))
            app._on_lang()
            self.assertEqual(app.theme.family, tkfont.nametofont("EbrBody", root=app.root).actual("family"))
        self.assertEqual(app.theme.family, before)

    # ------------------------------------------------------------ the rest of the chrome
    def test_window_has_the_app_icon_and_a_version_label(self) -> None:
        app = self.make(1.0)
        self.assertEqual(len(app.theme.app_icons()), 2)
        self.assertEqual(app.lbl_version.cget("text"), f"v{version.__version__}")

    def test_count_pill_hides_when_empty(self) -> None:
        app = self.make(1.0)
        app.root.update()
        self.assertFalse(app.lbl_count.winfo_ismapped())
        self.load(app)
        self.assertTrue(app.lbl_count.winfo_ismapped())
        self.assertIn("4", app.lbl_count.cget("text"))

    def test_progress_bar_is_invisible_when_idle(self) -> None:
        app = self.make(1.0)
        self.assertEqual(str(app.progress.cget("style")), "Idle.Horizontal.TProgressbar")
        app._set_running(True)
        self.assertEqual(str(app.progress.cget("style")), "Thin.Horizontal.TProgressbar")
        app._set_running(False)
        self.assertEqual(str(app.progress.cget("style")), "Idle.Horizontal.TProgressbar")

    def test_inline_editor_is_styled_and_commits(self) -> None:
        app = self.make(1.0)
        self.load(app)
        iid = next(i for i, it in app.iid_to_item.items() if it.current == "c.epub")
        app.root.update()
        app._begin_edit(iid)
        self.assertIsNotNone(app._editor)
        self.assertEqual(int(app._editor.cget("highlightthickness")), 2)
        app._editor.delete(0, "end")
        app._editor.insert(0, "Typed")
        app._commit_edit()
        self.assertEqual(app.iid_to_item[iid].new_name, "Typed.epub")

    # ------------------------------------------------------------ new version notice
    def fresh_settings(self, **entries) -> None:
        i18n.save_settings(dict(entries))

    def notice_info(self, latest: str = "9.9.9"):
        import update_check

        return update_check.UpdateInfo(latest, version.__version__,
                                       "https://chaekgalpi.co.kr/tools/ebookrenamer?utm_source=app")

    def test_update_check_box_sits_next_to_the_language_box_and_starts_on(self) -> None:
        self.fresh_settings()
        app = self.make(1.0)
        app.root.update()
        self.assertTrue(app.var_update_check.get())
        self.assertEqual(app.chk_update.cget("text"), i18n.t("opt_update_check"))
        self.assertEqual(app.chk_update.grid_info()["row"], app.cmb_lang.grid_info()["row"])
        self.assertGreater(app.chk_update.winfo_rootx(), app.cmb_lang.winfo_rootx())

    def test_no_notice_until_there_is_one(self) -> None:
        self.fresh_settings()
        app = self.make(1.0)
        app.root.update()
        self.assertFalse(app.notice.winfo_ismapped())
        self.assertIsNone(app._update_info)

    def test_notice_text_and_buttons_in_every_language(self) -> None:
        for code in i18n.LANGS:
            with self.subTest(lang=code):
                self.fresh_settings()
                i18n.set_lang(code, persist=False)
                app = self.make(1.0)
                app._on_update_result(self.notice_info("9.9.9"), True)
                app.root.update()
                self.assertTrue(app.notice.winfo_ismapped())
                text = app.lbl_notice.cget("text")
                self.assertIn("9.9.9", text)
                self.assertIn(version.__version__, text)
                self.assertEqual(app.btn_notice_update.cget("text"), i18n.t("btn_update"))
                self.assertEqual(app.btn_notice_later.cget("text"), i18n.t("btn_later"))
                self.check_layout(app, f"notice/{code}")
                for w in (app.notice, app.btn_notice_update, app.btn_notice_later):
                    self.assertLessEqual(w.winfo_rootx() + w.winfo_width(),
                                         app.root.winfo_rootx() + app.root.winfo_width() + 1)
                    self.assertLessEqual(w.winfo_rooty() + w.winfo_height(),
                                         app.root.winfo_rooty() + app.root.winfo_height() + 1)
        i18n.set_lang("en", persist=False)

    def test_notice_follows_the_language_switch(self) -> None:
        self.fresh_settings()
        app = self.make(1.0)
        app._on_update_result(self.notice_info("9.9.9"), True)
        app.var_lang.set(i18n.LANG_NAMES["ko"])
        app.cmb_lang.current(i18n.LANGS.index("ko"))
        app._on_lang()
        self.assertEqual(app.lbl_notice.cget("text"), i18n.t("update_available", latest="9.9.9", current=version.__version__))
        self.assertEqual(app.btn_notice_later.cget("text"), i18n.t("btn_later"))
        i18n.set_lang("en", persist=False)

    def test_notice_leaves_everything_above_it_where_it_was(self) -> None:
        self.fresh_settings()
        app = self.make(1.0)
        self.load(app)
        app.root.update()
        keep = (app.zone, app.cmb_pattern, app.cmb_lang, app.chk_update, app.tree)     # all above the table's lower edge
        before = [(w.winfo_rootx(), w.winfo_rooty(), w.winfo_width()) for w in keep]
        size_before = (app.root.winfo_width(), app.root.winfo_height())
        app._on_update_result(self.notice_info(), True)
        app.root.update()
        after = [(w.winfo_rootx(), w.winfo_rooty(), w.winfo_width()) for w in keep]
        self.assertEqual(before, after)
        self.assertEqual(size_before, (app.root.winfo_width(), app.root.winfo_height()))
        self.assertGreaterEqual(app.tree.winfo_height(), 4 * app.theme.px(36))      # the table gave the room, not the window
        self.assertGreater(app.notice.winfo_rooty(), app.btn_run.winfo_rooty())     # a line under the bottom bar
        app._update_later()
        app.root.update()
        self.assertEqual(before, [(w.winfo_rootx(), w.winfo_rooty(), w.winfo_width()) for w in keep])

    def test_later_remembers_the_version_and_hides_the_notice(self) -> None:
        self.fresh_settings(lang="en")
        app = self.make(1.0)
        app._on_update_result(self.notice_info("9.9.9"), True)
        app._update_later()
        app.root.update()
        self.assertFalse(app.notice.winfo_ismapped())
        saved = i18n.load_settings()
        self.assertEqual(saved["update_check_skipped"], "9.9.9")
        self.assertEqual(saved["lang"], "en")                      # the other entries stay

    def test_update_button_opens_only_the_tools_site(self) -> None:
        self.fresh_settings()
        app = self.make(1.0)
        app._on_update_result(self.notice_info(), True)
        with mock.patch("webbrowser.open") as opened:
            app._update_open()
        opened.assert_called_once_with("https://chaekgalpi.co.kr/tools/ebookrenamer?utm_source=app")
        self.assertFalse(app.notice.winfo_ismapped())
        app = self.make(1.0)
        import update_check

        app._update_info = update_check.UpdateInfo("9.9.9", version.__version__, "https://example.com/x")
        with mock.patch("webbrowser.open") as opened:
            app._update_open()
        opened.assert_not_called()

    def test_update_button_opens_the_page_in_the_screen_language(self) -> None:
        import update_check

        ko = "https://chaekgalpi.co.kr/tools/ebookrenamer?utm_source=app"
        en = "https://chaekgalpi.co.kr/en/tools/ebookrenamer?utm_source=app"
        cases = [("ko", en, ko), ("en", en, en), ("ja", en, en), ("zh-CN", en, en),
                 ("en", "", ko), ("en", "https://evil.example/en", ko)]
        for lang, url_en, expected in cases:
            with self.subTest(lang=lang, url_en=url_en):
                self.fresh_settings()
                i18n.set_lang(lang, persist=False)
                app = self.make(1.0)
                app._on_update_result(update_check.UpdateInfo("9.9.9", version.__version__, ko, url_en), True)
                with mock.patch("webbrowser.open") as opened:
                    app._update_open()
                opened.assert_called_once_with(expected)
        i18n.set_lang("en", persist=False)

    def test_switching_the_check_off_saves_it_and_hides_the_notice(self) -> None:
        self.fresh_settings()
        app = self.make(1.0)
        app._on_update_result(self.notice_info(), True)
        app.var_update_check.set(False)
        app._on_update_toggle()
        app.root.update()
        self.assertFalse(app.notice.winfo_ismapped())
        self.assertIs(i18n.load_settings()["update_check"], False)
        app.var_update_check.set(True)
        app._on_update_toggle()
        self.assertIs(i18n.load_settings()["update_check"], True)

    def test_no_notice_when_the_box_was_switched_off_meanwhile(self) -> None:
        self.fresh_settings()
        app = self.make(1.0)
        app.var_update_check.set(False)
        app._on_update_result(self.notice_info(), True)
        self.assertIsNone(app._update_info)

    def test_the_day_is_recorded_only_when_the_server_answered(self) -> None:
        import update_check

        self.fresh_settings()
        app = self.make(1.0)
        app._on_update_result(None, False)
        self.assertNotIn("update_check_last", i18n.load_settings())
        app._on_update_result(None, True)
        self.assertEqual(i18n.load_settings()["update_check_last"], update_check.today())
        self.assertFalse(app.notice.winfo_ismapped())

    def test_window_asks_once_after_start_and_not_again_the_same_day(self) -> None:
        import update_check

        answer = {"latest": "9.9.9", "updateAvailable": True,
                  "url": "https://chaekgalpi.co.kr/tools/ebookrenamer?utm_source=app"}
        calls: list = []

        def fake(slug, ver, **kw):
            calls.append((slug, ver))
            return answer

        self.fresh_settings()
        with mock.patch.object(update_check, "fetch", fake):
            app = self.make(1.0, check_updates=True)
            self.settle(app, lambda: app._update_info is not None)
            self.assertEqual(calls, [("ebookrenamer", version.__version__)])
            self.assertTrue(app.notice.winfo_ismapped())
            self.assertEqual(i18n.load_settings()["update_check_last"], update_check.today())
            second = self.make(1.0, check_updates=True)
            second.root.update()
            self.assertEqual(len(calls), 1)                         # already asked today

    def test_a_window_with_the_check_switched_off_never_asks(self) -> None:
        import update_check

        calls: list = []
        self.fresh_settings(update_check=False)
        with mock.patch.object(update_check, "fetch", lambda *a, **k: calls.append(a) or None):
            app = self.make(1.0, check_updates=True)
            self.assertFalse(app.var_update_check.get())
            app.root.after(2200, app.root.quit)                    # well past the 1.5 s delay
            app.root.mainloop()
        self.assertEqual(calls, [])

    # ------------------------------------------------------------ send feedback
    def no_network(self):
        """Record (and refuse) every way out to the network while the block runs."""
        import socket
        import urllib.request
        from contextlib import ExitStack

        calls: list = []

        def refuse(*a, **k):
            calls.append(a)
            raise OSError("no network in this test")

        stack = ExitStack()
        for target, name in ((socket.socket, "connect"), (socket.socket, "connect_ex"), (socket, "create_connection"),
                             (socket, "getaddrinfo"), (urllib.request, "urlopen")):
            stack.enter_context(mock.patch.object(target, name, refuse))
        return stack, calls

    def expected_feedback_url(self, lang: str) -> str:
        page = "tools" if lang == "ko" else "en/tools"
        return (f"https://chaekgalpi.co.kr/{page}/ebookrenamer?utm_source=app&utm_medium=feedback"
                f"&v={version.__version__}#feedback")

    def switch_lang(self, app, code: str) -> None:
        app.var_lang.set(i18n.LANG_NAMES[code])
        app.cmb_lang.current(i18n.LANGS.index(code))
        app._on_lang()

    def test_feedback_button_sits_under_the_update_check_box(self) -> None:
        self.fresh_settings()
        app = self.make(1.0)
        app.root.update()
        self.assertEqual(app.btn_feedback.cget("text"), i18n.t("btn_feedback"))
        self.assertEqual(app.btn_feedback.master, app.chk_update.master)
        self.assertGreaterEqual(app.btn_feedback.winfo_rooty(), app.chk_update.winfo_rooty() + app.chk_update.winfo_height() - 1)
        right = app.chk_update.winfo_rootx() + app.chk_update.winfo_width()
        self.assertAlmostEqual(app.btn_feedback.winfo_rootx() + app.btn_feedback.winfo_width(), right, delta=2)
        head = app.lbl_subtitle.master
        self.assertLessEqual(app.btn_feedback.winfo_rooty() + app.btn_feedback.winfo_height(),
                             head.winfo_rooty() + head.winfo_height())               # inside the header, not below it
        self.assertEqual(str(app.btn_feedback.cget("style")), "HeadLink.TButton")
        self.assertGreaterEqual(theme.contrast_ratio(theme.PALETTE["accent"], theme.PALETTE["bg"]), 4.5)

    def test_feedback_opens_the_page_once_in_every_language(self) -> None:
        stack, net = self.no_network()
        with stack:
            for code in i18n.LANGS:
                with self.subTest(lang=code):
                    self.fresh_settings()
                    i18n.set_lang(code, persist=False)
                    app = self.make(1.0)
                    with mock.patch("webbrowser.open", return_value=True) as opened:
                        app.btn_feedback.invoke()
                    opened.assert_called_once_with(self.expected_feedback_url(code))
                    messagebox.showwarning.assert_not_called()
                    self.assertEqual(app.txt_log.get("1.0", "end").strip(), "")
                    self.assertFalse(app.log_open)
        self.assertEqual(net, [])
        i18n.set_lang("en", persist=False)

    def test_feedback_follows_the_language_switch(self) -> None:
        stack, net = self.no_network()
        with stack:
            self.fresh_settings()
            i18n.set_lang("ko", persist=False)
            app = self.make(1.0)
            seen = []
            for code in ("ko", "en", "ja", "zh-CN", "ko"):
                self.switch_lang(app, code)
                self.assertEqual(app.btn_feedback.cget("text"), i18n.t("btn_feedback"))
                with mock.patch("webbrowser.open", return_value=True) as opened:
                    app._send_feedback()
                opened.assert_called_once()
                seen.append(opened.call_args.args[0])
            self.assertEqual(seen, [self.expected_feedback_url(c) for c in ("ko", "en", "ja", "zh-CN", "ko")])
            words = set()
            for code in i18n.LANGS:
                self.switch_lang(app, code)
                words.add(app.btn_feedback.cget("text"))
            self.assertEqual(len(words), 4)                       # each language has its own words on the button
        self.assertEqual(net, [])
        i18n.set_lang("en", persist=False)

    def test_feedback_without_a_browser_shows_the_address_and_changes_nothing(self) -> None:
        import webbrowser

        failures = {"returns False": dict(return_value=False),
                    "webbrowser.Error": dict(side_effect=webbrowser.Error("no runnable browser")),
                    "OSError": dict(side_effect=OSError("access denied")),
                    "RuntimeError": dict(side_effect=RuntimeError("odd"))}
        stack, net = self.no_network()
        with stack:
            for code in ("ko", "en"):
                for name, behaviour in failures.items():
                    with self.subTest(lang=code, failure=name):
                        self.fresh_settings(lang=code, update_check=True)
                        i18n.set_lang(code, persist=False)
                        app = self.make(1.0)
                        self.load(app)
                        app.root.update()
                        settings_before = i18n.load_settings()
                        state_before = ([(it.path, it.new_name, it.selected, it.status) for it in app.items],
                                        app.lbl_status.cget("text"), app.var_pattern.get(), app.var_update_check.get(),
                                        app._update_info, list(app.sources), str(app.btn_run.cget("state")))
                        messagebox.showwarning.reset_mock()
                        with mock.patch("webbrowser.open", **behaviour) as opened:
                            app.btn_feedback.invoke()                 # must not raise
                        opened.assert_called_once()
                        address = self.expected_feedback_url(code)
                        messagebox.showwarning.assert_called_once()
                        title, text = messagebox.showwarning.call_args.args[:2]
                        self.assertEqual(title, i18n.t("btn_feedback"))
                        self.assertEqual(text, i18n.t("err_feedback_open", url=address))
                        self.assertTrue(text.endswith("\n" + address))
                        self.assertIn(address, app.txt_log.get("1.0", "end"))     # kept where it can be selected and copied
                        self.assertTrue(app.log_open)
                        self.assertTrue(app.root.winfo_exists())
                        state_after = ([(it.path, it.new_name, it.selected, it.status) for it in app.items],
                                       app.lbl_status.cget("text"), app.var_pattern.get(), app.var_update_check.get(),
                                       app._update_info, list(app.sources), str(app.btn_run.cget("state")))
                        self.assertEqual(state_before, state_after)
                        self.assertEqual(settings_before, i18n.load_settings())
                        self.assertFalse(app._running)
                        with mock.patch("webbrowser.open", return_value=True) as opened:   # works again afterwards
                            app.btn_feedback.invoke()
                        opened.assert_called_once_with(address)
        self.assertEqual(net, [])
        i18n.set_lang("en", persist=False)

    def test_feedback_leaves_the_update_check_alone(self) -> None:
        import update_check

        calls: list = []

        def fake(slug, ver, **kw):
            calls.append((slug, ver))
            return None

        stack, net = self.no_network()
        with stack, mock.patch.object(update_check, "fetch", fake):
            self.fresh_settings()
            app = self.make(1.0, check_updates=True)
            with mock.patch("webbrowser.open", return_value=True):
                app._send_feedback()
            self.settle(app, lambda: bool(calls))                  # past the update check's 1.5 s delay
            app.root.after(300, app.root.quit)
            app.root.mainloop()
            self.assertEqual(calls, [("ebookrenamer", version.__version__)])     # the one usual check, nothing more
            self.assertTrue(app.var_update_check.get())
            self.assertEqual(i18n.load_settings(), {})
            app._on_update_result(self.notice_info("9.9.9"), True)   # the notice still works as before
            with mock.patch("webbrowser.open", return_value=True) as opened:
                app._send_feedback()
            app.root.update()
            self.assertTrue(app.notice.winfo_ismapped())
            self.assertEqual(app._update_info.latest, "9.9.9")
            opened.assert_called_once_with(self.expected_feedback_url("en"))
            with mock.patch("webbrowser.open") as opened:
                app._update_open()
            opened.assert_called_once_with("https://chaekgalpi.co.kr/tools/ebookrenamer?utm_source=app")
        self.assertEqual(net, [])

    # ------------------------------------------------------------ send feedback: keyboard
    def press(self, widget, keysym: str, char: str = "") -> None:
        """Run what Tk runs for a key press on `widget`, binding tag by binding tag, without
        sending a real key: nothing reaches the keyboard of whoever is using the computer."""
        import re

        # what Tk would put in for each %-field of a key press; quoted the way Tk quotes them ("\r" is one value)
        values = {"#": "1", "b": "0", "f": "1", "h": "0", "k": "0", "s": "0", "t": "0", "w": "0", "x": "1", "y": "1",
                  "A": char, "E": "0", "K": keysym, "N": "0", "W": str(widget), "T": "2", "X": "1", "Y": "1", "D": "0"}
        values = {key: value if re.fullmatch(r"[\w.!:-]+", value) else "{" + value + "}" for key, value in values.items()}
        values["%"] = "%"
        errors: list = []
        root = widget._root()
        root.report_callback_exception = lambda *exc: errors.append(exc[1])   # a Python binding that fails says so
        for tag in widget.bindtags():
            script = ""
            for sequence in (f"<KeyPress-{keysym}>", "<KeyPress>"):      # (<1> alone would be a mouse button)
                script = str(widget.tk.call("bind", tag, sequence))
                if script:
                    break
            if not script:
                continue
            script = re.sub(r"%(.)", lambda m: values.get(m.group(1), "{}"), script)
            code = int(widget.tk.call("catch", script, "ebr_press_result"))
            self.assertIn(code, (0, 3), f"{keysym} on {tag}: {widget.tk.getvar('ebr_press_result')}")   # 3: "break"
            if code == 3:
                break
        widget.update()                  # ttk's Space presses the button and invokes it once idle
        widget.update_idletasks()
        del root.report_callback_exception
        self.assertEqual(errors, [], f"{keysym}: a binding raised")

    def test_tab_reaches_send_feedback_after_the_update_check_box(self) -> None:
        self.fresh_settings()
        for lang in i18n.LANGS:
            with self.subTest(lang=lang):
                i18n.set_lang(lang, persist=False)
                app = self.make(1.0)
                app.root.update()
                self.assertEqual(app.chk_update.tk_focusNext(), app.btn_feedback)       # Tab
                self.assertEqual(app.btn_feedback.tk_focusPrev(), app.chk_update)       # Shift+Tab
                after = app.btn_feedback.tk_focusNext()
                self.assertEqual(after, app.btn_add)                                    # and on into the window
                self.assertEqual(after.tk_focusPrev(), app.btn_feedback)
                self.assertTrue(app.btn_feedback.instate(["!disabled"]))
                self.assertNotIn(str(app.btn_feedback.cget("takefocus")), ("0", "False"))
        i18n.set_lang("en", persist=False)

    def test_enter_and_space_open_the_page_once_each(self) -> None:
        stack, net = self.no_network()
        with stack:
            self.fresh_settings()
            app = self.make(1.0)
            app.root.update()
            for keysym, char in (("Return", "\r"), ("KP_Enter", "\r"), ("space", " ")):
                with self.subTest(key=keysym), mock.patch("webbrowser.open", return_value=True) as opened:
                    self.press(app.btn_feedback, keysym, char)
                    app.root.update()
                    opened.assert_called_once_with(self.expected_feedback_url("en"))
        self.assertEqual(net, [])

    def test_other_keys_do_nothing(self) -> None:
        stack, net = self.no_network()
        with stack:
            self.fresh_settings()
            app = self.make(1.0)
            app.root.update()
            keys = [("a", "a"), ("x", "x"), ("1", "1"), ("Escape", "\x1b"), ("BackSpace", "\b"), ("Delete", ""),
                    ("Up", ""), ("Down", ""), ("Left", ""), ("Right", ""), ("F1", ""), ("Home", ""), ("Shift_L", ""),
                    ("Control_L", ""), ("Alt_L", "")]
            with mock.patch("webbrowser.open", return_value=True) as opened:
                for keysym, char in keys:
                    with self.subTest(key=keysym):
                        self.press(app.btn_feedback, keysym, char)
                app.root.update()
            opened.assert_not_called()
            messagebox.showwarning.assert_not_called()
            self.assertEqual(app.txt_log.get("1.0", "end").strip(), "")
        self.assertEqual(net, [])

    def test_focus_shows_without_changing_the_size(self) -> None:
        self.fresh_settings()
        app = self.make(1.0)
        app.root.update()
        style = ttk.Style(app.root)
        name = str(app.btn_feedback.cget("style"))
        accent, bg = theme.PALETTE["accent"], theme.PALETTE["bg"]
        self.assertEqual(style.lookup(name, "bordercolor", ["!focus"]), bg)             # no frame while not focused
        for state in (["focus"], ["focus", "active"], ["focus", "pressed"]):
            with self.subTest(state=state):
                self.assertEqual(style.lookup(name, "bordercolor", state), accent)
        self.assertGreaterEqual(theme.contrast_ratio(accent, bg), 3.0)                   # a frame that can be seen
        before = (app.btn_feedback.winfo_reqwidth(), app.btn_feedback.winfo_reqheight(),
                  app.btn_feedback.winfo_width(), app.btn_feedback.winfo_height())
        for on in (True, False, True):
            app.btn_feedback.state(["focus"] if on else ["!focus"])
            app.root.update()
            self.assertEqual(app.btn_feedback.instate(["focus"]), on)
            self.assertEqual((app.btn_feedback.winfo_reqwidth(), app.btn_feedback.winfo_reqheight(),
                              app.btn_feedback.winfo_width(), app.btn_feedback.winfo_height()), before)
        app.btn_feedback.state(["!focus"])
        self.assertEqual(style.lookup("TButton", "bordercolor", ["focus"]), style.lookup("TButton", "bordercolor"))  # others as before

    # ------------------------------------------------------------ send feedback: tooltip
    TIPS = {"ko": bytes.fromhex("ec958820eb9098eb8a9420eab283c2b7ebb688ed8eb8ed959c20eab283c2b7ebb094eb9dbceb8a9420eab8b0"
                                "eb8aa5ec9d8420ec958ceba0a420eca3bcec84b8ec9a9428ebb88ceb9dbcec9ab0eca080eab08020ec97b4eb"
                                "a6bdeb8b88eb8ba429").decode(),
            "en": "Tell us what's broken or missing (opens your browser)",
            "ja": bytes.fromhex("e4b88de585b7e59088e383bbe38194e8a681e69c9be38292e3818ae79fa5e38289e3819be3818fe381a0e381"
                                "95e38184efbc88e38396e383a9e382a6e382b6e3818ce9968be3818de381bee38199efbc89").decode(),
            "zh-CN": bytes.fromhex("e5918ae8af89e68891e4bbace997aee9a298e68896e5bbbae8aeaeefbc88e5b086e68993e5bc80e6b58f"
                                   "e8a788e599a8efbc89").decode()}

    def wait(self, app, ms: int) -> None:
        """Let the real event loop run for `ms` milliseconds."""
        app.root.after(ms, app.root.quit)
        app.root.mainloop()
        app.root.update()

    def hover(self, app, ms: int | None = None) -> None:
        app.btn_feedback.event_generate("<Enter>")
        self.wait(app, app.tip_feedback.DELAY_MS + 250 if ms is None else ms)

    def tip_box(self, app) -> tuple[int, int, int, int]:
        tip = app.tip_feedback.tip
        tip.update_idletasks()
        return tip.winfo_rootx(), tip.winfo_rooty(), tip.winfo_rootx() + tip.winfo_width(), tip.winfo_rooty() + tip.winfo_height()

    def test_tooltip_words_in_every_language(self) -> None:
        for lang in i18n.LANGS:
            with self.subTest(lang=lang):
                with open(os.path.join(ROOT, "lang", f"{lang}.json"), encoding="utf-8") as f:
                    import json

                    words = json.load(f)["tip_feedback"]
                self.assertEqual(words, self.TIPS[lang])
                self.assertTrue(words.strip())
        self.assertEqual(len(set(self.TIPS.values())), 4)
        self.assertEqual(set(self.TIPS), set(i18n.LANGS))

    def test_tooltip_shows_after_a_short_rest_and_goes_when_the_pointer_leaves(self) -> None:
        self.fresh_settings()
        app = self.make(1.0)
        app.root.update()
        tip = app.tip_feedback
        self.assertTrue(400 <= tip.DELAY_MS <= 500)
        self.assertFalse(tip.shown())
        app.btn_feedback.event_generate("<Enter>")
        self.wait(app, 250)
        self.assertFalse(tip.shown())                                    # not yet
        self.wait(app, tip.DELAY_MS)
        self.assertTrue(tip.shown())
        self.assertTrue(tip.tip.winfo_ismapped())
        self.assertEqual(tip.label.cget("text"), self.TIPS["en"])
        self.assertEqual(tip.tip.master, app.btn_feedback)               # goes with the window
        self.assertTrue(tip.tip.overrideredirect())                      # no title bar, no taskbar entry
        app.btn_feedback.event_generate("<Leave>")
        app.root.update()
        self.assertFalse(tip.shown())
        self.wait(app, tip.DELAY_MS + 200)
        self.assertFalse(tip.shown())                                    # and does not come back by itself
        self.hover(app)
        self.assertTrue(tip.shown())                                     # again on the next visit

    def test_tooltip_does_not_show_when_the_pointer_passes_quickly(self) -> None:
        self.fresh_settings()
        app = self.make(1.0)
        app.root.update()
        tip = app.tip_feedback
        for stay in (0, 50, 200, tip.DELAY_MS - 150):
            with self.subTest(stay=stay):
                app.btn_feedback.event_generate("<Enter>")
                self.wait(app, max(1, stay))
                app.btn_feedback.event_generate("<Leave>")
                self.wait(app, tip.DELAY_MS + 200)
                self.assertFalse(tip.shown())
                self.assertIsNone(tip._job)
        for _ in range(5):                                               # in and out many times: still at most one note
            app.btn_feedback.event_generate("<Enter>")
            self.wait(app, 30)
        self.wait(app, tip.DELAY_MS + 200)
        self.assertTrue(tip.shown())
        tops = [w for w in app.btn_feedback.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertEqual(len(tops), 1)

    def test_clicking_hides_the_tooltip_and_opens_the_page_once(self) -> None:
        stack, net = self.no_network()
        with stack:
            self.fresh_settings()
            app = self.make(1.0)
            app.root.update()
            with mock.patch("webbrowser.open", return_value=True) as opened:
                self.hover(app)
                self.assertTrue(app.tip_feedback.shown())
                app.btn_feedback.event_generate("<ButtonPress-1>")
                app.root.update()
                self.assertFalse(app.tip_feedback.shown())
                app.btn_feedback.event_generate("<ButtonRelease-1>")
                app.root.update()
                self.wait(app, app.tip_feedback.DELAY_MS + 200)
                self.assertFalse(app.tip_feedback.shown())               # the click does not bring it back
            opened.assert_called_once_with(self.expected_feedback_url("en"))
        self.assertEqual(net, [])

    def test_tooltip_follows_a_language_switch_while_it_is_up(self) -> None:
        self.fresh_settings()
        app = self.make(1.0)
        app.root.update()
        self.hover(app)
        seen = []
        for code in ("ko", "ja", "zh-CN", "en", "ko"):
            self.switch_lang(app, code)
            app.root.update()
            self.assertTrue(app.tip_feedback.shown())
            seen.append(app.tip_feedback.label.cget("text"))
            self.assertEqual(seen[-1], self.TIPS[code])
            self.assertEqual(seen[-1], i18n.t("tip_feedback"))
        self.assertEqual(len(set(seen)), 4)
        app.btn_feedback.event_generate("<Leave>")
        self.switch_lang(app, "en")                                     # switching with no note up shows none
        app.root.update()
        self.assertFalse(app.tip_feedback.shown())
        i18n.set_lang("en", persist=False)

    def test_tooltip_stays_inside_the_window_and_the_screen(self) -> None:
        """The smallest window (the English subtitle is the one that gets cut there) at the
        left and the right edge of the screen, and half off the screen, in every language."""
        self.fresh_settings()
        for scale in (1.0, 1.5):
            app = self.make(scale)
            if not self.screen_allows(app, scale):
                continue
            root = app.root
            width, height = root.minsize()
            screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
            places = {"left edge": f"+0+40", "right edge": f"-0+40", "past the right edge": f"+{screen_w - width + 160}+40"}
            for place, position in places.items():
                root.geometry(f"{width}x{height}{position}")
                root.update()
                for lang in ("en",) + tuple(c for c in i18n.LANGS if c != "en"):
                    with self.subTest(scale=scale, place=place, lang=lang):
                        self.switch_lang(app, lang)
                        app.tip_feedback.hide()
                        self.hover(app)
                        self.assertTrue(app.tip_feedback.shown())
                        left, top, right, bottom = self.tip_box(app)
                        win = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(),
                               root.winfo_rooty() + root.winfo_height())
                        self.assertGreaterEqual(left, max(win[0], 0))
                        self.assertLessEqual(right, min(win[2], screen_w))
                        self.assertGreaterEqual(top, max(win[1], 0))
                        self.assertLessEqual(bottom, min(win[3], screen_h))
                        self.assertGreater(right - left, 20)
                        label = app.tip_feedback.label
                        self.assertGreaterEqual(label.winfo_width() + 1, label.winfo_reqwidth())   # its words are not cut
                        button_bottom = app.btn_feedback.winfo_rooty() + app.btn_feedback.winfo_height()
                        self.assertGreaterEqual(top, button_bottom)                  # under the button, not over it
            root.destroy()
            self.apps.remove(app)
        i18n.set_lang("en", persist=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
