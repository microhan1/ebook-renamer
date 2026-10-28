"""Look and feel: palette, fonts, DPI scaling and ttk styles.

Nothing in here knows about renaming. gui.py asks for styles by name
("Accent.TButton", "Card.TLabel" ...) and for colours by key.
"""
from __future__ import annotations

import base64
import ctypes
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import icon

PALETTE = {
    "bg": "#F4F5F8",            # window
    "card": "#FFFFFF",          # panels
    "border": "#E2E5EC",
    "dash": "#BFC5D2",          # dashed drop outline
    "text": "#1F2430",
    "muted": "#5F6675",
    "faint": "#8A91A0",
    "accent": "#4F46E5",
    "accent_hover": "#4338CA",
    "accent_press": "#3730A3",
    "accent_soft": "#EEF0FF",
    "on_accent": "#FFFFFF",
    "select": "#E6E9FF",        # selected table row
    "header_bg": "#F0F2F7",
    "header_hover": "#E6E9F1",
    "row_alt": "#FAFBFD",
    "warn": "#8A5A00",
    "warn_bg": "#FFF4D6",
    "bad": "#B42318",
    "bad_bg": "#FEEFEC",
    "ok": "#17692F",
    "ok_bg": "#E8F6EC",
    "disabled_bg": "#E6E8ED",
    "disabled_fg": "#9AA0AD",
    "log_bg": "#FAFBFD",
}

MALGUN_GOTHIC_KO = "".join(map(chr, (0xB9D1, 0xC740, 0x20, 0xACE0, 0xB515)))   # Tk lists it by its Korean name there

# first family that is installed wins; the Latin letters of each also look right
FONT_CANDIDATES = {
    "en": ("Segoe UI", "Helvetica", "Arial"),
    "ko": ("Malgun Gothic", MALGUN_GOTHIC_KO, "Segoe UI", "Arial"),
    "zh-CN": ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Arial"),
    "ja": ("Yu Gothic UI", "Meiryo UI", "MS UI Gothic", "Segoe UI", "Arial"),
}
MONO_CANDIDATES = ("Cascadia Mono", "Consolas", "Courier New")
MIN_SCALE, MAX_SCALE = 1.0, 3.0

STATUS_ROW_COLORS = {                      # status -> (foreground key, background key or None for the row's own)
    "ok": ("text", None),
    "nochange": ("muted", None),
    "dup": ("warn", "warn_bg"),
    "nometa": ("faint", None),
    "failed": ("bad", "bad_bg"),
    "done": ("ok", "ok_bg"),
}


def enable_dpi_awareness() -> None:
    """Render at the screen's real resolution instead of letting Windows stretch
    a low-resolution window (blurry text on 125%/150% displays). Call before the
    first Tk window exists; harmless if it is too late or not on Windows."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)      # system DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def clamp_scale(value: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return MIN_SCALE
    if value != value:                                       # NaN
        return MIN_SCALE
    return max(MIN_SCALE, min(MAX_SCALE, value))


def pick_family(lang: str, available, default: str) -> str:
    """First installed family for the language, else `default`."""
    installed = {name.lower(): name for name in available}
    for name in FONT_CANDIDATES.get(lang, FONT_CANDIDATES["en"]):
        if name.lower() in installed:
            return installed[name.lower()]
    return default


def pick_mono(available, default: str) -> str:
    installed = {name.lower(): name for name in available}
    for name in MONO_CANDIDATES:
        if name.lower() in installed:
            return installed[name.lower()]
    return default


def luminance(color: str) -> float:
    def channel(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = icon.hex_rgb(color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio, 1..21. Body text should reach 4.5."""
    a, b = luminance(foreground), luminance(background)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


class Theme:
    def __init__(self, root: tk.Misc, scale: float | None = None, lang: str = "en") -> None:
        self.root = root
        self.p = dict(PALETTE)
        if scale is None:
            try:
                scale = float(root.winfo_fpixels("1i")) / 96.0
            except tk.TclError:
                scale = 1.0
        else:
            root.tk.call("tk", "scaling", clamp_scale(scale) * 96 / 72)   # fonts are in points
        self.scale = clamp_scale(scale)
        self.images: dict[str, tk.PhotoImage] = {}           # keep references: Tk drops unreferenced images
        self.fonts: dict[str, tkfont.Font] = {}
        self._make_fonts(lang)
        self._configure_styles()

    # ----------------------------------------------------------------- units
    def px(self, value: float) -> int:
        return max(1, round(value * self.scale))

    # ----------------------------------------------------------------- fonts
    def _make_fonts(self, lang: str) -> None:
        available = set(tkfont.families(self.root))
        default = tkfont.nametofont("TkDefaultFont").actual("family")
        family = pick_family(lang, available, default)
        mono = pick_mono(available, "TkFixedFont")
        spec = {                                              # name: (points, weight, family)
            "EbrBody": (10, "normal", family), "EbrBold": (10, "bold", family),
            "EbrLead": (11, "bold", family), "EbrSmall": (9, "normal", family),
            "EbrHead": (9, "bold", family), "EbrTitle": (19, "bold", family),
            "EbrSub": (10, "normal", family), "EbrMono": (9, "normal", mono),
        }
        for name, (size, weight, fam) in spec.items():
            if name in self.fonts:
                self.fonts[name].configure(family=fam, size=size, weight=weight)
            else:
                self.fonts[name] = tkfont.Font(root=self.root, name=name, family=fam, size=size, weight=weight)
        for std in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont"):
            tkfont.nametofont(std, root=self.root).configure(family=family, size=10)
        self.family = family

    def set_language(self, lang: str) -> None:
        """Switch to the font that suits the language; every widget follows because styles use named fonts."""
        self._make_fonts(lang)

    # ---------------------------------------------------------------- styles
    def _configure_styles(self) -> None:
        p, px = self.p, self.px
        root = self.root
        style = ttk.Style(root)
        style.theme_use("clam")
        root.configure(background=p["bg"])
        style.configure(".", background=p["bg"], foreground=p["text"], font="EbrBody", bordercolor=p["border"],
                        lightcolor=p["bg"], darkcolor=p["bg"], troughcolor=p["border"], focuscolor=p["bg"],
                        selectbackground=p["select"], selectforeground=p["text"], insertcolor=p["text"])

        style.configure("Card.TFrame", background=p["card"])

        # labels
        style.configure("TLabel", background=p["bg"], foreground=p["text"])
        style.configure("Title.TLabel", font="EbrTitle")
        style.configure("Sub.TLabel", foreground=p["muted"], font="EbrSub")
        style.configure("Small.TLabel", foreground=p["faint"], font="EbrSmall")
        style.configure("Status.TLabel", foreground=p["muted"])
        style.configure("Card.TLabel", background=p["card"])
        style.configure("CardBad.TLabel", background=p["card"], foreground=p["bad"])
        style.configure("CardMuted.TLabel", background=p["card"], foreground=p["muted"], font="EbrSmall")
        style.configure("CardLead.TLabel", background=p["card"], foreground=p["muted"], font="EbrLead")
        style.configure("Pill.TLabel", background=p["accent_soft"], foreground=p["accent"], font="EbrBold",
                        padding=(px(12), px(5)))

        # buttons: flat, one-pixel border, no 3D edges
        def flat_button(name: str, bg: str, fg: str, border: str, hover: str, press: str, pad: tuple, font: str) -> None:
            # relief "solid" is what makes clam draw the one-pixel border; "flat" draws none
            style.configure(name, background=bg, foreground=fg, bordercolor=border, lightcolor=bg, darkcolor=bg,
                            focuscolor=bg, relief="solid", borderwidth=1, padding=pad, font=font, anchor="center")
            style.map(name, relief=[("pressed", "solid"), ("!pressed", "solid")],
                      background=[("disabled", p["disabled_bg"]), ("pressed", press), ("active", hover)],
                      foreground=[("disabled", p["disabled_fg"])],
                      bordercolor=[("disabled", p["disabled_bg"]), ("pressed", press), ("active", hover if hover != bg else border)],
                      lightcolor=[("disabled", p["disabled_bg"]), ("pressed", press), ("active", hover)],
                      darkcolor=[("disabled", p["disabled_bg"]), ("pressed", press), ("active", hover)])

        flat_button("TButton", p["card"], p["text"], p["dash"], p["row_alt"], p["header_bg"], (px(14), px(7)), "EbrBody")
        flat_button("Accent.TButton", p["accent"], p["on_accent"], p["accent"], p["accent_hover"], p["accent_press"],
                    (px(24), px(9)), "EbrBold")
        flat_button("Ghost.TButton", p["bg"], p["text"], p["bg"], p["header_bg"], p["header_hover"], (px(12), px(7)), "EbrBody")
        flat_button("Toggle.TButton", p["card"], p["muted"], p["card"], p["header_bg"], p["header_hover"], (px(12), px(2)), "EbrLead")
        flat_button("Link.TButton", p["card"], p["accent"], p["card"], p["accent_soft"], p["select"], (px(10), px(5)), "EbrBold")
        flat_button("HeadLink.TButton", p["bg"], p["accent"], p["bg"], p["header_bg"], p["header_hover"], (px(8), px(3)), "EbrSmall")
        # reached with Tab: its one-pixel border turns accent (the border is always there, so the size stays)
        style.map("HeadLink.TButton", bordercolor=[("disabled", p["disabled_bg"]), ("focus", p["accent"]),
                                                   ("pressed", p["header_hover"]), ("active", p["header_bg"])])

        # checkbuttons on a card: the same drawn boxes as in the table
        boxes = self.checkbox_images(gap=px(8))               # the gap keeps the label off the box
        style.element_create("Ebr.Check", "image", str(boxes[False]), ("disabled", str(boxes[False])),
                             ("selected", str(boxes[True])), sticky="")
        style.layout("Card.TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("Ebr.Check", {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                ("Checkbutton.label", {"sticky": "nswe"})]})]})])
        style.configure("Card.TCheckbutton", background=p["card"], foreground=p["text"], focuscolor=p["card"],
                        padding=px(3))
        style.map("Card.TCheckbutton", background=[("active", p["card"])],
                  foreground=[("disabled", p["disabled_fg"])])
        # the same box on the window background (the header option)
        style.layout("Plain.TCheckbutton", style.layout("Card.TCheckbutton"))
        style.configure("Plain.TCheckbutton", background=p["bg"], foreground=p["muted"], focuscolor=p["bg"],
                        font="EbrSmall", padding=px(3))
        style.map("Plain.TCheckbutton", background=[("active", p["bg"])],
                  foreground=[("disabled", p["disabled_fg"])])

        # the one-line "new version" strip under the action bar
        style.configure("Notice.TLabel", background=p["accent_soft"], foreground=p["text"])
        flat_button("NoticeUpdate.TButton", p["accent"], p["on_accent"], p["accent"], p["accent_hover"],
                    p["accent_press"], (px(16), px(5)), "EbrBold")
        flat_button("NoticeLater.TButton", p["accent_soft"], p["accent"], p["accent_soft"], p["select"],
                    p["select"], (px(12), px(5)), "EbrBody")

        # combobox
        style.configure("TCombobox", fieldbackground="#FFFFFF", background="#FFFFFF", foreground=p["text"],
                        bordercolor=p["border"], lightcolor="#FFFFFF", darkcolor="#FFFFFF", arrowcolor=p["muted"],
                        padding=(px(8), px(5)), selectbackground="#FFFFFF", selectforeground=p["text"],
                        arrowsize=px(14))
        style.map("TCombobox",
                  fieldbackground=[("disabled", p["bg"]), ("readonly", "#FFFFFF")],
                  bordercolor=[("focus", p["accent"]), ("active", p["faint"])],
                  lightcolor=[("focus", p["accent"])], darkcolor=[("focus", p["accent"])],
                  foreground=[("disabled", p["disabled_fg"])],
                  selectbackground=[("readonly", "#FFFFFF")], selectforeground=[("readonly", p["text"])],
                  arrowcolor=[("disabled", p["disabled_fg"])])
        root.option_add("*TCombobox*Listbox.font", "EbrBody")
        root.option_add("*TCombobox*Listbox.background", "#FFFFFF")
        root.option_add("*TCombobox*Listbox.foreground", p["text"])
        root.option_add("*TCombobox*Listbox.selectBackground", p["accent_soft"])
        root.option_add("*TCombobox*Listbox.selectForeground", p["text"])
        root.option_add("*TCombobox*Listbox.relief", "flat")
        root.option_add("*TCombobox*Listbox.borderWidth", 0)

        # table
        style.configure("Treeview", background=p["card"], fieldbackground=p["card"], foreground=p["text"],
                        rowheight=px(36), borderwidth=0, relief="flat", font="EbrBody", bordercolor=p["card"],
                        lightcolor=p["card"], darkcolor=p["card"])
        style.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["text"])])
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Treeview.Heading", background=p["header_bg"], foreground=p["muted"], font="EbrHead",
                        relief="flat", borderwidth=0, padding=(px(10), px(10)), lightcolor=p["header_bg"],
                        darkcolor=p["header_bg"], bordercolor=p["header_bg"])
        style.map("Treeview.Heading", background=[("active", p["header_hover"])])

        # slim scrollbars without arrow buttons
        for orient, sticky in (("Vertical", "ns"), ("Horizontal", "ew")):
            name = f"Modern.{orient}.TScrollbar"
            style.layout(name, [(f"{orient}.Scrollbar.trough", {"sticky": sticky, "children": [
                (f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
            style.configure(name, troughcolor=p["card"], background="#CDD2DC", bordercolor=p["card"],
                            lightcolor="#CDD2DC", darkcolor="#CDD2DC", relief="flat", gripcount=0, width=px(10))
            style.map(name, background=[("pressed", p["muted"]), ("active", p["faint"])],
                      lightcolor=[("pressed", p["muted"]), ("active", p["faint"])],
                      darkcolor=[("pressed", p["muted"]), ("active", p["faint"])])

        style.configure("Thin.Horizontal.TProgressbar", troughcolor=p["border"], background=p["accent"],
                        bordercolor=p["border"], lightcolor=p["accent"], darkcolor=p["accent"], thickness=px(4))
        style.configure("Idle.Horizontal.TProgressbar", troughcolor=p["bg"], background=p["bg"],
                        bordercolor=p["bg"], lightcolor=p["bg"], darkcolor=p["bg"], thickness=px(4))

    # ---------------------------------------------------------------- pieces
    def card(self, parent: tk.Misc, **kw) -> tk.Frame:
        """A white panel with a one-pixel border."""
        return tk.Frame(parent, bg=self.p["card"], highlightbackground=self.p["border"],
                        highlightcolor=self.p["border"], highlightthickness=1, bd=0, **kw)

    def style_text(self, widget: tk.Text) -> None:
        p = self.p
        widget.configure(font="EbrSmall", background=p["log_bg"], foreground=p["text"], relief="flat", bd=0,
                         highlightthickness=0, padx=self.px(10), pady=self.px(8), selectbackground=p["select"],
                         selectforeground=p["text"], insertbackground=p["text"], spacing1=1, spacing3=1)

    def style_entry(self, widget: tk.Entry) -> None:
        p = self.p
        widget.configure(font="EbrBody", background="#FFFFFF", foreground=p["text"], relief="flat", bd=0,
                         highlightthickness=2, highlightcolor=p["accent"], highlightbackground=p["accent"],
                         insertbackground=p["text"], selectbackground=p["select"], selectforeground=p["text"])

    def row_tags(self, tree: ttk.Treeview) -> None:
        """One tag per (status, odd/even row): Tk does not merge colours from several tags reliably."""
        p = self.p
        for parity, base in (("even", p["card"]), ("odd", p["row_alt"])):
            for status, (fg_key, bg_key) in STATUS_ROW_COLORS.items():
                tree.tag_configure(f"{status}_{parity}", foreground=p[fg_key], background=p[bg_key] if bg_key else base)

    def checkbox_images(self, gap: int = 0) -> dict[bool, tk.PhotoImage]:
        size = self.px(18)
        out: dict[bool, tk.PhotoImage] = {}
        for checked in (True, False):
            key = f"checkbox_{checked}_{size}_{gap}"
            if key not in self.images:
                png = icon.render_checkbox(size, checked, self.p["accent"], self.p["dash"], gap)
                self.images[key] = tk.PhotoImage(master=self.root, data=base64.b64encode(png).decode("ascii"))
            out[checked] = self.images[key]
        return out

    def app_icons(self) -> list[tk.PhotoImage]:
        out = []
        for size in (32, 64):
            key = f"app_icon_{size}"
            if key not in self.images:
                self.images[key] = tk.PhotoImage(master=self.root, data=base64.b64encode(icon.render_app_icon(size)).decode("ascii"))
            out.append(self.images[key])
        return out

    def logo(self) -> tk.PhotoImage:
        size = self.px(44)
        key = f"logo_{size}"
        if key not in self.images:
            self.images[key] = tk.PhotoImage(master=self.root, data=base64.b64encode(icon.render_app_icon(size)).decode("ascii"))
        return self.images[key]
