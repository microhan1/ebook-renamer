"""Generate the sample EPUB/PDF files in this folder.

    python samples/make_samples.py [out_dir]

Every sample carries only public-domain titles and authors plus a one-line
body written for this project, so nothing here is under copyright. Use them
to try the tool: drop the samples folder onto the window.
"""
from __future__ import annotations

import os
import sys
import zipfile
from xml.sax.saxutils import escape

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:opf="http://www.idpf.org/2007/opf" unique-identifier="id" version="2.0">
  <metadata>
    <dc:identifier id="id">urn:uuid:sample-{n}</dc:identifier>
    <dc:language>{lang}</dc:language>
{fields}
  </metadata>
  <manifest><item id="c" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="c"/></spine>
</package>"""

XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head>
<body><h1>{title}</h1><p>Sample file for ebook-renamer. The body is not the original text.</p></body></html>"""


def make_epub(path: str, n: int, lang: str, title: str | None, authors: list[str], date: str | None) -> None:
    fields = []
    if title:
        fields.append(f"    <dc:title>{escape(title)}</dc:title>")
    for a in authors:
        fields.append(f'    <dc:creator opf:role="aut">{escape(a)}</dc:creator>')
    if date:
        fields.append(f"    <dc:date>{date}</dc:date>")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/content.opf", OPF.format(n=n, lang=lang, fields="\n".join(fields)),
                    compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/chapter.xhtml", XHTML.format(title=escape(title or "Untitled")),
                    compress_type=zipfile.ZIP_DEFLATED)


def make_pdf(path: str, title: str | None, author: str | None, date: str | None, password: str | None = None) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Sample file for ebook-renamer.", fontsize=12)
    md = {"title": title or "", "author": author or "", "creationDate": date or ""}
    doc.set_metadata(md)
    if password:
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    else:
        doc.save(path)
    doc.close()


def main(out: str) -> None:
    os.makedirs(out, exist_ok=True)
    make_epub(os.path.join(out, "book_v3.epub"), 1, "ko", "홍길동전", ["허균"], "1612")
    make_epub(os.path.join(out, "final(2).epub"), 2, "en", "Pride and Prejudice", ["Jane Austen"], "1813-01-28")
    make_epub(os.path.join(out, "download.epub"), 3, "ja", "吾輩は猫である",
              ["夏目漱石"], "1905")
    make_epub(os.path.join(out, "untitled_1.epub"), 4, "zh", "狂人日记", ["鲁迅"], "1918")
    make_epub(os.path.join(out, "coauthors.epub"), 5, "en", "Lyrical Ballads",
              ["William Wordsworth", "Samuel Taylor Coleridge"], "1798")
    make_epub(os.path.join(out, "title_only.epub"), 6, "en", "Beowulf", [], None)
    make_epub(os.path.join(out, "no_metadata.epub"), 7, "en", None, [], None)
    make_epub(os.path.join(out, "bad_chars.epub"), 8, "en", 'What: Is "Art"? <Part 1/2>', ["Anonymous"], None)
    make_pdf(os.path.join(out, "scan001.pdf"), "용미인언", "정약용", "D:18190101000000")
    make_pdf(os.path.join(out, "Document1.pdf"), "The Art of War", "Sun Tzu", "D:20200101120000")
    make_pdf(os.path.join(out, "empty_meta.pdf"), None, None, None)
    make_pdf(os.path.join(out, "locked.pdf"), "Locked Book", "Nobody", None, password="secret")
    print("samples written to", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
