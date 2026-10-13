"""Read title / author / year from EPUB and PDF files. Read only, never write.

EPUB: META-INF/container.xml -> the OPF package -> dc:title, dc:creator, dc:date.
      EPUB 2 (opf:role attributes), EPUB 3 (<meta refines> role and title-type)
      and legacy OEB 1.x packages (dc-metadata, DC 1.0 namespace) are handled.
PDF:  document Info dictionary (Title, Author, CreationDate) via PyMuPDF, with
      the XMP packet as a fallback when the Info dictionary is empty.
"""
from __future__ import annotations

import os
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field

EXTENSIONS = (".epub", ".pdf")

_NS_CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"
_AUTHOR_ROLES = {"aut", "author", "creator"}          # anything else (ill, edt, trl ...) is not an author
_MAIN_TITLE_TYPES = {"main"}
_SIDE_TITLE_TYPES = {"subtitle", "short", "collection", "edition", "expanded"}


@dataclass
class Meta:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    error: str = ""          # "password" | "open_failed" | "" ; the file is excluded when set

    @property
    def author(self) -> str:
        return self.authors[0] if self.authors else ""

    @property
    def empty(self) -> bool:
        return not self.title and not self.authors


# ------------------------------------------------------------- helpers
# Invisible formatting characters that only cause trouble in a file name: zero-width
# space, bidi marks and overrides (an RLO can disguise an extension), word joiner,
# soft hyphen, BOM. ZWJ (200D) and ZWNJ (200C) stay: emoji sequences and several
# scripts need them.
_DROP_FORMAT = {0x00AD, 0x061C, 0x180E, 0x200B, 0x200E, 0x200F, 0xFEFF} \
    | set(range(0x202A, 0x202F)) | set(range(0x2060, 0x2065)) | set(range(0x2066, 0x206A))


_LINE_BREAKS = "\t\n\r\x0b\x0c" + chr(0x2028) + chr(0x2029)       # become a plain space


def _clean(text: str | None) -> str:
    """Collapse whitespace, drop control characters, lone surrogates (they
    cannot be encoded and would crash a rename) and invisible formatting
    characters, normalise to NFC so Korean typed on macOS (NFD) and Windows
    (NFC) produce the same file name."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", str(text))
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in _LINE_BREAKS:
            out.append(" ")
        elif cat in ("Cc", "Cs") or ord(ch) in _DROP_FORMAT:
            continue
        else:
            out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _year(text: str | None) -> str:
    m = re.search(r"(?<!\d)(\d{4})(?!\d)", text or "")
    if not m:
        m = re.search(r"(\d{4})", text or "")            # "20200101" style
    return m.group(1) if m else ""


def _split_authors(values: list[str]) -> list[str]:
    """One creator field may hold several names joined by ';', '&' or ' and '.
    A comma is NOT a separator: "Doe, John" is one person."""
    out: list[str] = []
    for v in values:
        for part in re.split(r"\s*(?:;|&|\band\b)\s*", v or ""):
            part = _clean(part)
            if part and part not in out:
                out.append(part)
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _is_dc(el: ET.Element, name: str) -> bool:
    """dc:title / dc:creator / dc:date in any Dublin Core namespace version,
    case-insensitive (OEB 1.x wrote dc:Title)."""
    return _local(el.tag) == name and "purl.org/dc/elements" in _ns(el.tag)


def _attr(el: ET.Element, name: str) -> str:
    for k, v in el.attrib.items():
        if _local(k) == name:
            return v or ""
    return ""


# ---------------------------------------------------------------- EPUB
MAX_XML_BYTES = 32 * 1024 * 1024        # real OPF files are well under 1 MB; a zip bomb is not


def _read_member(zf: zipfile.ZipFile, name: str) -> bytes:
    """Read a zip member, refusing one that claims to be huge. A few KB of
    deflate can expand to gigabytes, and the whole thing would be held in memory."""
    if zf.getinfo(name).file_size > MAX_XML_BYTES:
        raise ValueError("member too large")
    return zf.read(name)


def read_epub(path: str) -> Meta:
    try:
        with zipfile.ZipFile(path) as zf:
            opf_name = _find_opf(zf)
            if not opf_name:
                return Meta(error="open_failed")
            root = ET.fromstring(_read_member(zf, opf_name))
    except (zipfile.BadZipFile, OSError, KeyError, ET.ParseError, ValueError, RuntimeError, IndexError,
            zipfile.LargeZipFile, NotImplementedError, EOFError, UnicodeError):
        return Meta(error="open_failed")
    return _parse_opf(root)


def _parse_opf(root: ET.Element) -> Meta:
    elements = list(root.iter())
    # EPUB 3: <meta refines="#id" property="role|title-type">value</meta>
    refines: dict[str, dict[str, str]] = {}
    for el in elements:
        if _local(el.tag) == "meta":
            target = el.get("refines", "").lstrip("#")
            prop = _local(el.get("property", "") or "")
            if target and prop:
                refines.setdefault(target, {})[prop] = _clean(el.text).lower()

    titles: list[tuple[str, str]] = []          # (title-type, text)
    for el in elements:
        if _is_dc(el, "title"):
            text = _clean(el.text)
            if text:
                titles.append((refines.get(el.get("id", ""), {}).get("title-type", ""), text))
    title = ""
    for ttype, text in titles:
        if ttype in _MAIN_TITLE_TYPES:
            title = text
            break
    if not title:
        for ttype, text in titles:
            if ttype not in _SIDE_TITLE_TYPES:
                title = text
                break
    if not title and titles:
        title = titles[0][1]

    creators, others = [], []
    for el in elements:
        if _is_dc(el, "creator"):
            name = _clean(el.text)
            if not name:
                continue
            role = (_attr(el, "role") or refines.get(el.get("id", ""), {}).get("role", "")).lower()
            (creators if role == "" or role in _AUTHOR_ROLES else others).append(name)
    authors = _split_authors(creators or others)

    year = ""
    for el in elements:
        if _is_dc(el, "date"):
            year = _year(el.text)
            if year:
                break
    return Meta(title=title, authors=authors, year=year)


def _find_opf(zf: zipfile.ZipFile) -> str | None:
    names = zf.namelist()
    try:
        cont = ET.fromstring(_read_member(zf, "META-INF/container.xml"))
        for rf in cont.iter():
            if _local(rf.tag) != "rootfile":
                continue
            p = rf.get("full-path") or ""
            for cand in (p, urllib.parse.unquote(p)):
                if cand in names:
                    return cand
    except (KeyError, ET.ParseError, ValueError):
        pass
    for name in names:             # broken or missing container.xml: take any .opf
        if name.lower().endswith(".opf"):
            return name
    return None


# ----------------------------------------------------------------- PDF
def _pymupdf():
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf  # type: ignore
    return pymupdf


_quiet = False


def read_pdf(path: str) -> Meta:
    global _quiet
    pymupdf = _pymupdf()
    if not _quiet:                       # MuPDF prints repair notices to stderr for damaged files
        try:
            pymupdf.TOOLS.mupdf_display_errors(False)
            pymupdf.TOOLS.mupdf_display_warnings(False)
        except Exception:
            pass
        _quiet = True
    try:
        doc = pymupdf.open(path, filetype="pdf")   # MuPDF also opens EPUB/XPS; insist on PDF
    except Exception:
        return Meta(error="open_failed")
    try:
        if not doc.is_pdf:                        # an EPUB/XPS/image wearing a .pdf extension
            return Meta(error="open_failed")
        if doc.needs_pass:
            return Meta(error="password")
        info = doc.metadata or {}
        title = _clean(info.get("title"))
        authors = _split_authors([_clean(info.get("author"))])
        year = _year(info.get("creationDate") or info.get("modDate"))
        if not title or not authors or not year:
            xmp = _read_xmp(doc)
            title = title or xmp.title
            authors = authors or xmp.authors
            year = year or xmp.year
    except Exception:
        return Meta(error="open_failed")
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return Meta(title=title, authors=authors, year=year)


def _read_xmp(doc) -> Meta:
    """dc:title / dc:creator / xmp:CreateDate from the XMP packet, if any."""
    try:
        xml = doc.get_xml_metadata()
    except Exception:
        return Meta()
    if not xml or not xml.strip():
        return Meta()
    try:
        root = ET.fromstring(xml.strip())
    except ET.ParseError:
        return Meta()
    title, creators, year = "", [], ""
    for el in root.iter():
        name = _local(el.tag)
        if _is_dc(el, "title") and not title:
            title = _first_li(el)
        elif _is_dc(el, "creator") and not creators:
            creators = [t for t in _all_li(el) if t]
        elif name in ("createdate", "date") and not year:
            year = _year(_first_li(el))
    return Meta(title=title, authors=_split_authors(creators), year=year)


def _all_li(el: ET.Element) -> list[str]:
    lis = [_clean(li.text) for li in el.iter() if _local(li.tag) == "li"]
    return lis or [_clean(el.text)]


def _first_li(el: ET.Element) -> str:
    for text in _all_li(el):
        if text:
            return text
    return ""


# ------------------------------------------------------------- generic
def read_meta(path: str) -> Meta:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".epub":
        return read_epub(path)
    if ext == ".pdf":
        return read_pdf(path)
    return Meta(error="open_failed")


def is_ebook(path: str) -> bool:
    return path.lower().endswith(EXTENSIONS)


def is_link_dir(path: str) -> bool:
    """Symlink, junction or any other reparse point. Following one can loop
    forever or list the same file under several paths."""
    try:
        if os.path.islink(path):
            return True
        isjunction = getattr(os.path, "isjunction", None)
        if isjunction is not None and isjunction(path):
            return True
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
        return bool(attrs & 0x400)                  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return True


def collect_files(paths: list[str], recursive: bool = False) -> list[str]:
    """Expand folders (one level, or fully with recursive) into EPUB/PDF
    paths. Order is stable and duplicates are removed. Linked folders found
    while walking are not entered."""
    out: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen:
            seen.add(key)
            out.append(os.path.abspath(p))

    for p in paths:
        if os.path.isdir(p):
            if recursive:
                for root, dirs, files in os.walk(p):
                    dirs[:] = sorted(d for d in dirs if not is_link_dir(os.path.join(root, d)))
                    for name in sorted(files):
                        if is_ebook(name):
                            add(os.path.join(root, name))
            else:
                try:
                    names = sorted(os.listdir(p))
                except OSError:
                    continue
                for name in names:
                    full = os.path.join(p, name)
                    if is_ebook(name) and os.path.isfile(full):
                        add(full)
        elif os.path.isfile(p) and is_ebook(p):
            add(p)
    return out
