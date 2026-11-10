"""The picture the exe shows while it unpacks (PyInstaller --splash, see build.bat).

The bootloader puts it up before Python starts; the program only has to take it down once
the window is drawn, or before any text goes to the console. Run from source there is no
pyi_splash module and close() does nothing.
"""
from __future__ import annotations


def close() -> None:
    try:
        import pyi_splash  # type: ignore[import-not-found]

        pyi_splash.close()
    except Exception:          # not an exe, already closed, or the splash was never shown
        pass
