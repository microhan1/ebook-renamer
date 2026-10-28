"""Once a day after start: ask the 책갈피 tools site whether a newer version exists.

Only the tool's slug, its version and "win" are sent - no file, path, device or user
information. The request runs on a background thread 1.5 s after the window is shown and
never blocks the UI; any failure (offline, timeout, HTTP error, bad JSON) is silent. The
server decides whether the version is older (`updateAvailable`); null means "cannot
compare" and shows nothing. Nothing is downloaded or replaced: the notice only opens the
tool's page on the site. Standard library only.
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import threading
import urllib.parse
import urllib.request
from typing import Callable

SLUG = "ebookrenamer"
API = "https://chaekgalpi.co.kr/api/tools/{slug}/latest"
SITE = "https://chaekgalpi.co.kr/"  # the notice only ever opens a page on this site
TIMEOUT = 4.0
DELAY_MS = 1500
POLL_MS = 100                       # how often the Tk thread looks for the answer
MAX_BYTES = 64 * 1024
DEFAULT_LANG = "en"                 # i18n.DEFAULT_LANG (a test keeps them equal): the screen with no language
KEYS = ("update_check", "update_check_last", "update_check_skipped")   # the three entries kept in settings.json


@dataclasses.dataclass
class UpdateInfo:
    latest: str
    current: str
    url: str
    url_en: str = ""      # the English tools page (server answers "urlEn"); "" when absent or not on the site


def page_lang(lang) -> str:
    """Which page of the site a screen language reads: "ko" when the code's first part is
    ko (ko, KO, ko-KR, ko_KR), "en" for every other code, known or not (the site has no
    Japanese or Chinese page). No language (None, "", blanks, not text) counts as the
    tool's default screen language. The one rule for [Send feedback] and [Update]."""
    if not isinstance(lang, str) or not lang.strip():
        lang = DEFAULT_LANG
    return "ko" if lang.strip().replace("_", "-").split("-")[0].lower() == "ko" else "en"


def page_for(info: UpdateInfo, lang) -> str:
    """The page [Update] opens: the Korean page on a Korean screen, otherwise the English
    page when the server gave one on the tools site, else the Korean page."""
    if page_lang(lang) == "en" and isinstance(info.url_en, str) and info.url_en.startswith(SITE):
        return info.url_en
    return info.url


FEEDBACK_PAGES = {"ko": SITE + "tools/{slug}", "en": SITE + "en/tools/{slug}"}


def feedback_url(slug: str, version, lang) -> str:
    """The feedback box on the tool's page ([Send feedback] only opens it in the browser).
    Built from constants alone; the version is the one value that varies, so it is encoded
    and left out when empty. utm_source=app marks it as coming from the program."""
    page = page_lang(lang)
    query = "utm_source=app&utm_medium=feedback"
    version = "" if version is None else str(version)
    if version.strip():
        query += "&v=" + urllib.parse.quote(version, safe="")
    return f"{FEEDBACK_PAGES[page].format(slug=slug)}?{query}#feedback"


@dataclasses.dataclass
class Prefs:
    update_check: bool = True         # on by default; the check box turns it off
    update_check_last: str = ""       # YYYY-MM-DD of the last check the server answered
    update_check_skipped: str = ""    # "Later" was pressed for this version: do not show it again


def load_prefs(settings: dict) -> Prefs:
    """Prefs from settings.json, trusting nothing about its types (the file can be edited by hand)."""
    on, last, skipped = (settings.get(k) for k in KEYS)
    return Prefs(update_check=on if isinstance(on, bool) else True,
                 update_check_last=last.strip()[:10] if isinstance(last, str) else "",
                 update_check_skipped=skipped.strip()[:32] if isinstance(skipped, str) else "")


def store_prefs(settings: dict, prefs: Prefs) -> dict:
    """Put the three entries into `settings` (other entries, like the language, stay) and return it."""
    settings.update(dataclasses.asdict(prefs))
    return settings


def today() -> str:
    return datetime.date.today().isoformat()


def should_check(prefs, day: str) -> bool:
    """Checking is on and has not been done today."""
    return bool(getattr(prefs, "update_check", True)) and getattr(prefs, "update_check_last", "") != day


def fetch(slug: str, version: str, *, opener: Callable = urllib.request.urlopen) -> dict | None:
    """The server's answer, or None on any failure."""
    query = urllib.parse.urlencode({"v": version, "os": "win"})
    req = urllib.request.Request(f"{API.format(slug=slug)}?{query}",
                                 headers={"User-Agent": f"chaekgalpi-tool/{slug}/{version}",
                                          "Accept": "application/json"})
    try:
        with opener(req, timeout=TIMEOUT) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            data = json.loads(resp.read(MAX_BYTES).decode("utf-8"))
    except Exception:  # offline, timeout, HTTP error, bad JSON: say nothing
        return None
    return data if isinstance(data, dict) else None


def interpret(data: dict | None, version: str, skipped: str = "") -> UpdateInfo | None:
    """An UpdateInfo only when the server says a newer version exists, it is not the
    version the user chose to skip, and the link points at the tools site."""
    if not isinstance(data, dict) or data.get("updateAvailable") is not True:
        return None
    latest, url = data.get("latest"), data.get("url")
    if not isinstance(latest, str) or not latest.strip() or len(latest) > 32:
        return None
    if not isinstance(url, str) or not url.startswith(SITE):
        return None
    latest = latest.strip()
    if latest == (skipped or "").strip():
        return None
    url_en = data.get("urlEn")
    url_en = url_en if isinstance(url_en, str) and url_en.startswith(SITE) else ""
    return UpdateInfo(latest, version, url, url_en)


def check_async(root, slug: str, version: str, prefs, on_result: Callable[[UpdateInfo | None, bool], None], *,
                fetcher: Callable = fetch, day: str | None = None) -> bool:
    """Schedule one check DELAY_MS after now. on_result(info, answered) runs on the Tk
    thread: `answered` is True when the server replied (the caller records the day then),
    `info` is set only when a notice should be shown. Returns False when no check is due."""
    if not should_check(prefs, day or today()):
        return False
    skipped = getattr(prefs, "update_check_skipped", "")
    box: dict = {}

    # The thread only fetches into `box` and holds no Tk object. Handing the result over with
    # root.after(..., on_result) from the thread left it holding the last reference to the App
    # when the window was closed during the request: the Tk variables were then freed off the
    # main thread and Tcl aborted ("Tcl_AsyncDelete: async handler deleted by the wrong thread").
    # The Tk thread polls for the answer instead.
    def work(box=box) -> None:
        box["data"] = fetcher(slug, version)

    def poll() -> None:
        if "data" not in box:
            root.after(POLL_MS, poll)
            return
        data = box["data"]
        on_result(interpret(data, version, skipped), data is not None)

    def start() -> None:
        threading.Thread(target=work, name="update-check", daemon=True).start()
        poll()

    try:
        root.after(DELAY_MS, start)
    except Exception:
        return False
    return True
