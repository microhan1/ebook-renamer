"""Regenerate assets/splash.png, the picture the exe shows while it unpacks (build.bat --splash).

    python tools/make_splash.py

The app icon is drawn by icon.py (no Pillow needed); the text next to it is the English title,
which is the one name all four languages share. Pillow is only needed here, at build time.
"""
import io
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import icon  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
SCALE = 4                                       # drawn large and shrunk for smooth edges
W, H = 300, 104
INK, RULE = "#17202B", "#D9E0E6"
TEXT = "Ebook Renamer"


def main() -> None:
    s = SCALE
    img = Image.new("RGB", (W * s, H * s), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W * s - 1, H * s - 1), outline=RULE, width=s)
    mark = Image.open(io.BytesIO(icon.render_app_icon(56 * s))).convert("RGBA")
    img.paste(mark, (26 * s, (H - 56) // 2 * s), mark)
    size = 30
    while size > 16:                            # the name must fit between the icon and the right edge
        font = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", size * s)
        if d.textlength(TEXT, font=font) <= (W - 98 - 16) * s:
            break
        size -= 1
    d.text((98 * s, 52 * s), TEXT, font=font, fill=INK, anchor="lm")
    out = os.path.join(ROOT, "assets", "splash.png")
    small = img.resize((W, H), Image.LANCZOS).quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    small.save(out, optimize=True)              # 64 colours keep the file a few KB
    print(f"wrote {out} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
