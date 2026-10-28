"""Custom widgets for the window: the dashed drop zone and a small tooltip."""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from theme import Theme


def round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, r: float, **kw) -> int:
    """A rounded rectangle as a smoothed polygon."""
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
              x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kw)


def draw_empty_art(canvas: tk.Canvas, theme: Theme) -> tk.Canvas:
    """Three stacked sheets: the picture shown when the table is empty."""
    p, px = theme.p, theme.px
    w, h = int(canvas["width"]), int(canvas["height"])
    sheet_w, sheet_h = px(40), px(50)
    for i, (dx, tint) in enumerate(((px(-18), p["header_bg"]), (px(0), "#E9ECF4"), (px(18), p["accent_soft"]))):
        x1 = (w - sheet_w) / 2 + dx
        y1 = (h - sheet_h) / 2 + (px(3) if i != 1 else 0) + (px(3) if i == 2 else 0)
        round_rect(canvas, x1, y1, x1 + sheet_w, y1 + sheet_h, px(6), fill=tint, outline=p["dash"], width=1)
        if i == 2:
            for k in range(3):
                y = y1 + px(14) + k * px(10)
                canvas.create_line(x1 + px(9), y, x1 + sheet_w - px(9) - (px(9) if k == 2 else 0), y,
                                   fill=p["accent"], width=max(2, px(2)), capstyle="round")
    return canvas


class DropZone(tk.Canvas):
    """A dashed, rounded drop target: a plus badge, a title and a hint on the left,
    the add/clear buttons on the right. Lights up while something is dragged over it."""

    def __init__(self, master: tk.Misc, theme: Theme, height: int = 92) -> None:
        super().__init__(master, height=theme.px(height), highlightthickness=0, bd=0, background=theme.p["bg"])
        self.theme = theme
        self.title = ""
        self.hint = ""
        self.release = ""
        self.active = False
        self.buttons: tk.Misc | None = None
        self.bind("<Configure>", lambda event: self.redraw())

    def attach_buttons(self, frame: tk.Misc) -> None:
        self.buttons = frame

    def set_text(self, title: str, hint: str, release: str) -> None:
        self.title, self.hint, self.release = title, hint, release
        self.redraw()

    def set_active(self, active: bool) -> None:
        if active != self.active:
            self.active = active
            self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 40 or height < 20:
            return
        t = self.theme
        p = t.p
        fill = p["accent_soft"] if self.active else p["card"]
        outline = p["accent"] if self.active else p["dash"]
        round_rect(self, 1, 1, width - 2, height - 2, t.px(14), fill=fill, outline=outline,
                   width=2 if self.active else 1, dash=() if self.active else (5, 4))

        badge = t.px(46)
        left = t.px(26)
        cx, cy = left + badge / 2, height / 2
        self.create_oval(cx - badge / 2, cy - badge / 2, cx + badge / 2, cy + badge / 2,
                         fill="#FFFFFF" if self.active else p["accent_soft"], outline="")
        arm, line = t.px(9), max(2, t.px(2))
        self.create_line(cx - arm, cy, cx + arm, cy, fill=p["accent"], width=line, capstyle="round")
        self.create_line(cx, cy - arm, cx, cy + arm, fill=p["accent"], width=line, capstyle="round")

        x = left + badge + t.px(18)
        buttons_width = self.buttons.winfo_reqwidth() if self.buttons is not None else 0
        text_width = max(t.px(120), width - x - buttons_width - t.px(44))
        title = self.release if self.active and self.release else self.title
        self.create_text(x, cy - t.px(11), text=title, anchor="w", font="EbrLead",
                         fill=p["accent"] if self.active else p["text"], width=text_width)
        if self.hint:
            self.create_text(x, cy + t.px(13), text=self.hint, anchor="w", font="EbrSmall", fill=p["muted"],
                             width=text_width)
        if self.buttons is not None:
            try:
                self.buttons.configure(background=fill)            # the gap between the buttons follows the fill
            except tk.TclError:
                pass
            self.create_window(width - t.px(22), cy, window=self.buttons, anchor="e")


class Tooltip:
    """A small note under a widget while the pointer rests on it: shown DELAY_MS after the
    pointer comes in, gone when it leaves or clicks. It stays inside the window and the
    screen. `text` is asked each time it is shown, and refresh() rewrites a note that is up,
    so a language switch reaches it too."""

    DELAY_MS = 450

    def __init__(self, widget: tk.Misc, theme: Theme, text: Callable[[], str]) -> None:
        self.widget, self.theme, self.text = widget, theme, text
        self.tip: tk.Toplevel | None = None
        self.label: tk.Label | None = None
        self._job: str | None = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def _on_enter(self, _event=None) -> None:
        self._cancel()
        self._job = self.widget.after(self.DELAY_MS, self.show)

    def _cancel(self) -> None:
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def shown(self) -> bool:
        return self.tip is not None

    def show(self) -> None:
        self._job = None
        if self.tip is None:
            p, px = self.theme.p, self.theme.px
            # built hidden, so it is measured and placed before it first appears
            self.tip = tk.Toplevel(self.widget, background=p["text"])
            self.tip.withdraw()
            self.tip.overrideredirect(True)
            self.label = tk.Label(self.tip, background=p["text"], foreground=p["card"], font="EbrSmall",
                                  justify="left", padx=px(8), pady=px(4), bd=0)
            self.label.pack()
        self.refresh()
        self.tip.deiconify()

    def refresh(self) -> None:
        """New words (after a language switch) in a note that is up, placed again for their length."""
        if self.tip is None or self.label is None:
            return
        left, top, right, bottom = self._bounds()
        margin, gap = self.theme.px(6), self.theme.px(4)
        self.label.configure(text=self.text(), wraplength=max(self.theme.px(120), right - left - 2 * margin))
        self.tip.update_idletasks()
        width, height = self.tip.winfo_reqwidth(), self.tip.winfo_reqheight()
        w = self.widget
        x = w.winfo_rootx() + w.winfo_width() - width          # its right edge under the widget's right edge
        y = w.winfo_rooty() + w.winfo_height() + gap
        if y + height > bottom - margin:                        # no room underneath: above the widget
            y = w.winfo_rooty() - gap - height
        x = max(left + margin, min(x, right - margin - width))
        y = max(top + margin, min(y, bottom - margin - height))
        self.tip.geometry(f"+{x}+{y}")

    def _bounds(self) -> tuple[int, int, int, int]:
        """The part of the window that is on the screen (the whole window if none of it is)."""
        top = self.widget.winfo_toplevel()
        win = (top.winfo_rootx(), top.winfo_rooty(), top.winfo_rootx() + top.winfo_width(),
               top.winfo_rooty() + top.winfo_height())
        screen = (0, 0, top.winfo_screenwidth(), top.winfo_screenheight())
        box = (max(win[0], screen[0]), max(win[1], screen[1]), min(win[2], screen[2]), min(win[3], screen[3]))
        return box if box[0] < box[2] and box[1] < box[3] else win

    def hide(self, _event=None) -> None:
        self._cancel()
        if self.tip is not None:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = self.label = None
