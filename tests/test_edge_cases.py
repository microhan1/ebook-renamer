"""Edge-case tests for ebook-renamer: odd metadata, odd names, collisions,
rename ordering, undo safety, CLI behaviour. Run from the repository root:

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "samples"))

import i18n  # noqa: E402
import main  # noqa: E402
import make_samples  # noqa: E402
import meta  # noqa: E402
import namer  # noqa: E402
import undo  # noqa: E402

i18n.init("en")

OPF_NS = 'xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/"'


def opts(**kw) -> namer.Options:
    base = dict(others_suffix="and {n} more")
    base.update(kw)
    return namer.Options(**base).validated()


def items_for(folder: str, recursive: bool = False) -> list[namer.Item]:
    return [namer.Item(path=p, meta=meta.read_meta(p)) for p in meta.collect_files([folder], recursive)]


def write_epub(path: str, opf_xml: str, container: str | None = make_samples.CONTAINER,
               opf_name: str = "OEBPS/content.opf") -> str:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        if container is not None:
            zf.writestr("META-INF/container.xml", container.replace("OEBPS/content.opf", opf_name))
        zf.writestr(opf_name, opf_xml)
    return path


def write_pdf(path: str, title=None, author=None, date=None, **save_kw) -> str:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()
    md = {}
    if title is not None:
        md["title"] = title
    if author is not None:
        md["author"] = author
    if date is not None:
        md["creationDate"] = date
    if md:
        doc.set_metadata(md)
    doc.save(path, **save_kw)
    doc.close()
    return path


class TempFolder(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="ebr_edge_")

    def tearDown(self) -> None:
        for root, dirs, files in os.walk(self.dir):
            for n in files:
                try:
                    os.chmod(os.path.join(root, n), stat.S_IWRITE)
                except OSError:
                    pass
        shutil.rmtree(self.dir, ignore_errors=True)

    def p(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def names(self) -> set[str]:
        return {n for n in os.listdir(self.dir) if n != undo.LOG_NAME}


# =============================================================== metadata
class EpubMetadataEdgeTests(TempFolder):
    def test_epub3_refines_roles(self) -> None:
        """EPUB 3 puts the role in a <meta refines>; illustrators and editors
        are not authors. Subtitles (title-type) are not the main title."""
        opf = f"""<package {OPF_NS} version="3.0" unique-identifier="u">
          <metadata>
            <dc:identifier id="u">x</dc:identifier>
            <dc:title id="t1">Main Title</dc:title>
            <dc:title id="t2">A Subtitle</dc:title>
            <meta refines="#t2" property="title-type">subtitle</meta>
            <dc:creator id="c1">Ill Ustrator</dc:creator>
            <meta refines="#c1" property="role" scheme="marc:relators">ill</meta>
            <dc:creator id="c2">Real Author</dc:creator>
            <meta refines="#c2" property="role" scheme="marc:relators">aut</meta>
            <dc:creator id="c3">Ed Itor</dc:creator>
            <meta refines="#c3" property="role" scheme="marc:relators">edt</meta>
            <dc:date>2019-05-01T00:00:00Z</dc:date>
          </metadata></package>"""
        m = meta.read_meta(write_epub(self.p("e3.epub"), opf))
        self.assertEqual(m.title, "Main Title")
        self.assertEqual(m.authors, ["Real Author"])
        self.assertEqual(m.year, "2019")

    def test_epub3_main_title_marked_second(self) -> None:
        opf = f"""<package {OPF_NS} version="3.0"><metadata>
            <dc:title id="t1">Series Name</dc:title>
            <meta refines="#t1" property="title-type">collection</meta>
            <dc:title id="t2">The Book</dc:title>
            <meta refines="#t2" property="title-type">main</meta>
            <dc:creator>Someone</dc:creator>
          </metadata></package>"""
        m = meta.read_meta(write_epub(self.p("e3b.epub"), opf))
        self.assertEqual(m.title, "The Book")

    def test_only_non_author_roles_fall_back(self) -> None:
        """A book with only an editor still gets a name rather than 'no metadata'."""
        opf = f"""<package {OPF_NS} version="2.0"><metadata xmlns:opf="http://www.idpf.org/2007/opf">
            <dc:title>Anthology</dc:title>
            <dc:creator opf:role="edt">Some Editor</dc:creator>
          </metadata></package>"""
        m = meta.read_meta(write_epub(self.p("edt.epub"), opf))
        self.assertEqual(m.authors, ["Some Editor"])

    def test_legacy_oeb_opf(self) -> None:
        """Old Open eBook 1.x packages: dc-metadata, capitalised tags, DC 1.0 namespace."""
        opf = """<?xml version="1.0"?>
        <package unique-identifier="id">
          <metadata>
            <dc-metadata xmlns:dc="http://purl.org/dc/elements/1.0/" xmlns:oebpackage="http://openebook.org/namespaces/oeb-package/1.0/">
              <dc:Title>Old Format Book</dc:Title>
              <dc:Creator role="aut">Old Author</dc:Creator>
              <dc:Date>1999</dc:Date>
            </dc-metadata>
          </metadata></package>"""
        m = meta.read_meta(write_epub(self.p("old.epub"), opf))
        self.assertEqual((m.title, m.authors, m.year), ("Old Format Book", ["Old Author"], "1999"))

    def test_missing_container_falls_back_to_any_opf(self) -> None:
        opf = f'<package {OPF_NS}><metadata><dc:title>No Container</dc:title><dc:creator>A</dc:creator></metadata></package>'
        m = meta.read_meta(write_epub(self.p("nocont.epub"), opf, container=None, opf_name="weird/place/book.opf"))
        self.assertEqual(m.title, "No Container")

    def test_container_points_to_missing_opf(self) -> None:
        with zipfile.ZipFile(self.p("dangling.epub"), "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("META-INF/container.xml", make_samples.CONTAINER)
        self.assertEqual(meta.read_meta(self.p("dangling.epub")).error, "open_failed")

    def test_opf_path_with_spaces_and_percent_encoding(self) -> None:
        opf = f'<package {OPF_NS}><metadata><dc:title>Spaced</dc:title><dc:creator>A</dc:creator></metadata></package>'
        write_epub(self.p("sp.epub"), opf, opf_name="My Book/content.opf")
        self.assertEqual(meta.read_meta(self.p("sp.epub")).title, "Spaced")
        cont = make_samples.CONTAINER.replace("OEBPS/content.opf", "My%20Book/content.opf")
        with zipfile.ZipFile(self.p("pct.epub"), "w") as zf:
            zf.writestr("META-INF/container.xml", cont)
            zf.writestr("My Book/content.opf", opf)
        self.assertEqual(meta.read_meta(self.p("pct.epub")).title, "Spaced")

    def test_whitespace_entities_and_empty_first_title(self) -> None:
        opf = f"""<package {OPF_NS}><metadata>
            <dc:title>   </dc:title>
            <dc:title>
               Tom &amp; Jerry:
               the   Return
            </dc:title>
            <dc:creator>  Hanna   Barbera </dc:creator>
          </metadata></package>"""
        m = meta.read_meta(write_epub(self.p("ws.epub"), opf))
        self.assertEqual(m.title, "Tom & Jerry: the Return")
        self.assertEqual(m.authors, ["Hanna Barbera"])

    def test_invisible_characters_are_dropped(self) -> None:
        opf = f"""<package {OPF_NS}><metadata>
            <dc:title>Zero\u200bWidth\u200e Title\ufeff</dc:title>
            <dc:creator>Au\u00adthor</dc:creator>
          </metadata></package>"""
        m = meta.read_meta(write_epub(self.p("zw.epub"), opf))
        self.assertEqual(m.title, "ZeroWidth Title")
        self.assertEqual(m.authors, ["Author"])

    def test_author_separators(self) -> None:
        """'Last, First' must stay one author; ';', '&' and ' and ' separate."""
        cases = {
            "Doe, John": ["Doe, John"],
            "A; B": ["A", "B"],
            "A & B": ["A", "B"],
            "Simon and Garfunkel": ["Simon", "Garfunkel"],
            "Anderson": ["Anderson"],
            "A & A": ["A"],
        }
        from xml.sax.saxutils import escape

        for n, (raw, want) in enumerate(cases.items()):
            opf = f'<package {OPF_NS}><metadata><dc:title>T</dc:title><dc:creator>{escape(raw)}</dc:creator></metadata></package>'
            m = meta.read_meta(write_epub(self.p(f"sep{n}.epub"), opf))
            self.assertEqual(m.authors, want, raw)

    def test_date_formats(self) -> None:
        for n, (raw, want) in enumerate({"2020-01-01T00:00:00Z": "2020", "20200101": "2020", "c. 1850": "1850",
                                          "January 2, 1999": "1999", "n.d.": "", "": ""}.items()):
            opf = f'<package {OPF_NS}><metadata><dc:title>T</dc:title><dc:date>{raw}</dc:date></metadata></package>'
            self.assertEqual(meta.read_meta(write_epub(self.p(f"d{n}.epub"), opf)).year, want, raw)

    def test_malformed_opf_xml(self) -> None:
        self.assertEqual(meta.read_meta(write_epub(self.p("bad.epub"), "<package><metadata>")).error, "open_failed")

    def test_epub_is_a_zip_with_no_opf_at_all(self) -> None:
        with zipfile.ZipFile(self.p("noopf.epub"), "w") as zf:
            zf.writestr("hello.txt", "hi")
        self.assertEqual(meta.read_meta(self.p("noopf.epub")).error, "open_failed")

    def test_directory_named_like_an_ebook_is_ignored(self) -> None:
        os.makedirs(self.p("folder.epub"))
        make_samples.make_epub(self.p("real.epub"), 1, "en", "Real", ["A"], None)
        self.assertEqual([os.path.basename(p) for p in meta.collect_files([self.dir])], ["real.epub"])
        # given directly it is a folder, so its contents (none) are listed
        self.assertEqual(meta.collect_files([self.p("folder.epub")]), [])


class PdfMetadataEdgeTests(TempFolder):
    def test_owner_password_only_is_readable(self) -> None:
        import pymupdf

        write_pdf(self.p("owner.pdf"), "Owner Locked", "A", encryption=pymupdf.PDF_ENCRYPT_AES_256,
                  owner_pw="owner", user_pw="")
        m = meta.read_meta(self.p("owner.pdf"))
        self.assertEqual(m.error, "")
        self.assertEqual(m.title, "Owner Locked")

    def test_xmp_only_metadata(self) -> None:
        """Some producers write XMP but leave the Info dictionary empty."""
        import pymupdf

        write_pdf(self.p("xmp.pdf"))
        doc = pymupdf.open(self.p("xmp.pdf"))
        doc.set_metadata({})
        xmp = """<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
        <x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
          <rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:xmp="http://ns.adobe.com/xap/1.0/">
            <dc:title><rdf:Alt><rdf:li xml:lang="x-default">XMP Title</rdf:li></rdf:Alt></dc:title>
            <dc:creator><rdf:Seq><rdf:li>First Writer</rdf:li><rdf:li>Second Writer</rdf:li></rdf:Seq></dc:creator>
            <xmp:CreateDate>2011-07-04T10:00:00Z</xmp:CreateDate>
          </rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>"""
        doc.set_xml_metadata(xmp)
        doc.save(self.p("xmp2.pdf"))
        doc.close()
        m = meta.read_meta(self.p("xmp2.pdf"))
        self.assertEqual(m.title, "XMP Title")
        self.assertEqual(m.authors, ["First Writer", "Second Writer"])
        self.assertEqual(m.year, "2011")

    def test_info_dict_wins_over_xmp(self) -> None:
        import pymupdf

        write_pdf(self.p("both.pdf"), "Info Title", "Info Author")
        doc = pymupdf.open(self.p("both.pdf"))
        doc.set_xml_metadata('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                             '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                             '<dc:title><rdf:Alt><rdf:li>XMP Title</rdf:li></rdf:Alt></dc:title>'
                             '</rdf:Description></rdf:RDF></x:xmpmeta>')
        doc.save(self.p("both2.pdf"))
        doc.close()
        self.assertEqual(meta.read_meta(self.p("both2.pdf")).title, "Info Title")

    def test_whitespace_only_and_control_chars(self) -> None:
        write_pdf(self.p("ws.pdf"), "  \t ", "Line\r\nBreak\tAuthor")
        m = meta.read_meta(self.p("ws.pdf"))
        self.assertEqual(m.title, "")
        self.assertEqual(m.authors, ["Line Break Author"])
        self.assertFalse(m.empty)

    def test_zero_page_pdf_is_not_an_exception(self) -> None:
        raw = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
               b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
               b"3 0 obj<</Title(Zero Pages)/Author(Nobody)>>endobj\n"
               b"trailer<</Root 1 0 R/Info 3 0 R>>\n%%EOF\n")
        with open(self.p("zero.pdf"), "wb") as f:
            f.write(raw)
        m = meta.read_meta(self.p("zero.pdf"))
        self.assertIn(m.error, ("", "open_failed"))
        if not m.error:
            self.assertEqual(m.title, "Zero Pages")

    def test_truncated_pdf(self) -> None:
        write_pdf(self.p("full.pdf"), "Cut Off", "A")
        data = open(self.p("full.pdf"), "rb").read()
        with open(self.p("cut.pdf"), "wb") as f:
            f.write(data[: len(data) // 2])
        m = meta.read_meta(self.p("cut.pdf"))      # repaired or refused, never raised
        self.assertIsInstance(m, meta.Meta)

    def test_epub_bytes_with_pdf_extension(self) -> None:
        make_samples.make_epub(self.p("really_epub.pdf"), 1, "en", "T", ["A"], None)
        self.assertEqual(meta.read_meta(self.p("really_epub.pdf")).error, "open_failed")


# =============================================================== naming
class NamingEdgeTests(unittest.TestCase):
    def test_title_made_only_of_forbidden_chars(self) -> None:
        m = meta.Meta(title="???", authors=["A"])
        self.assertEqual(namer.build_stem(m, opts()), "A")
        m = meta.Meta(title="***", authors=[])
        self.assertEqual(namer.build_stem(m, opts()), "")
        it = namer.Item(path="x.epub", meta=m)
        namer.plan([it], opts())
        self.assertEqual(it.status, namer.NOMETA)

    def test_unknown_placeholder_is_dropped(self) -> None:
        m = meta.Meta(title="T", authors=["A"])
        self.assertEqual(namer.build_stem(m, opts(pattern="{author} - {title} [{isbn}]")), "A - T")
        self.assertEqual(namer.build_stem(m, opts(pattern="{title} {series}")), "T")

    def test_pattern_without_separator(self) -> None:
        m = meta.Meta(title="T", authors=["A"])
        self.assertEqual(namer.build_stem(m, opts(pattern="{author}{title}")), "AT")
        self.assertEqual(namer.build_stem(m, opts(pattern="{author}/{title}")), "AT")

    def test_year_only_pattern_uses_fallback_without_year(self) -> None:
        m = meta.Meta(title="T", authors=["A"], year="")
        self.assertEqual(namer.build_stem(m, opts(pattern="{year}")), "A - T")
        m.year = "2001"
        self.assertEqual(namer.build_stem(m, opts(pattern="{year}")), "2001")

    def test_brackets_and_separators_around_missing_parts(self) -> None:
        m = meta.Meta(title="T", authors=[], year="")
        self.assertEqual(namer.build_stem(m, opts(pattern="[{year}] {author} - {title} ({year})")), "T")
        self.assertEqual(namer.build_stem(m, opts(pattern="{title} - {author} - {year}")), "T")
        self.assertEqual(namer.build_stem(m, opts(pattern="{author}_{title}")), "T")

    def test_dash_inside_title_survives(self) -> None:
        m = meta.Meta(title="Spider-Man - Volume 2", authors=["A - B"])
        self.assertEqual(namer.build_stem(m, opts()), "A - B - Spider-Man - Volume 2")

    def test_long_cjk_title_is_capped(self) -> None:
        m = meta.Meta(title="\u5b57" * 500, authors=["\u4f5c\u8005"])
        stem = namer.build_stem(m, opts())
        self.assertEqual(len(stem), namer.MAX_STEM)
        self.assertTrue(stem.startswith("\u4f5c\u8005 - "))

    def test_reserved_name_case_and_extension(self) -> None:
        self.assertEqual(namer.sanitize("con"), "con_")
        self.assertEqual(namer.sanitize("LPT1"), "LPT1_")
        self.assertEqual(namer.sanitize("CONTINUE"), "CONTINUE")

    def test_leading_dots_and_spaces(self) -> None:
        m = meta.Meta(title=".hidden", authors=[])
        self.assertEqual(namer.build_stem(m, opts(pattern="{title}")), "hidden")
        self.assertEqual(namer.sanitize("   x   "), "x")
        self.assertEqual(namer.sanitize("x..."), "x")

    def test_nfd_and_nfc_produce_one_name(self) -> None:
        import unicodedata

        a = meta.Meta(title=unicodedata.normalize("NFD", "\ud55c\uae00"), authors=[])
        b = meta.Meta(title=unicodedata.normalize("NFC", "\ud55c\uae00"), authors=[])
        self.assertEqual(namer.build_stem(a, opts()), namer.build_stem(b, opts()))
        self.assertEqual(len(namer.build_stem(a, opts())), 2)

    def test_emoji_and_fullwidth_punctuation_kept(self) -> None:
        m = meta.Meta(title="\U0001F4DA \uff1a\uff0f Book", authors=[])
        self.assertEqual(namer.build_stem(m, opts()), "\U0001F4DA \uff1a\uff0f Book")

    def test_others_suffix_placeholder_variants(self) -> None:
        m = meta.Meta(title="T", authors=["A", "B", "C"])
        self.assertEqual(namer.build_stem(m, opts(others=True, others_suffix="et al.")), "A et al. - T")
        self.assertEqual(namer.build_stem(m, opts(others=True, others_suffix="{bad")), "A - T")
        self.assertEqual(namer.build_stem(m, opts(others=True, others_suffix="")), "A - T")
        m = meta.Meta(title="T", authors=["A"])
        self.assertEqual(namer.build_stem(m, opts(others=True)), "A - T")

    def test_manual_name_strips_any_ebook_extension(self) -> None:
        it = namer.Item(path="D:/x/a.epub", meta=meta.Meta())
        namer.set_manual_name(it, "Typed.pdf")
        self.assertEqual(it.new_name, "Typed.epub")
        namer.set_manual_name(it, "Typed.EPUB")
        self.assertEqual(it.new_name, "Typed.epub")
        namer.set_manual_name(it, "Typed.txt")
        self.assertEqual(it.new_name, "Typed.txt.epub")
        namer.set_manual_name(it, "   ")
        self.assertFalse(it.manual)

    def test_options_validation_variants(self) -> None:
        self.assertEqual(namer.Options(pattern="   ").validated().pattern, namer.DEFAULT_PATTERN)
        self.assertEqual(namer.Options(pattern="{isbn}").validated().pattern, namer.DEFAULT_PATTERN)
        self.assertEqual(namer.Options(pattern=" {title} ").validated().pattern, "{title}")
        self.assertEqual(namer.Options(others_suffix=5).validated().others_suffix, "")  # type: ignore


# =============================================================== collisions
class CollisionTests(TempFolder):
    def test_case_only_rename_is_performed(self) -> None:
        make_samples.make_epub(self.p("author - title.epub"), 1, "en", "Title", ["Author"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        self.assertEqual(items[0].status, namer.OK)
        self.assertEqual(items[0].new_name, "Author - Title.epub")
        result = namer.apply(items)
        self.assertEqual(result.failed, [])
        self.assertEqual(os.listdir(self.dir), ["Author - Title.epub"])
        undo.record(result.renamed)
        undo.undo(self.dir)
        self.assertEqual(os.listdir(self.dir), ["author - title.epub"])

    def test_exact_same_name_is_no_change(self) -> None:
        make_samples.make_epub(self.p("Author - Title.epub"), 1, "en", "Title", ["Author"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        self.assertEqual(items[0].status, namer.NOCHANGE)
        result = namer.apply(items)
        self.assertEqual((result.renamed, result.skipped), ([], 1))

    def test_case_collision_with_other_file_gets_number(self) -> None:
        make_samples.make_epub(self.p("x.epub"), 1, "en", "Title", ["Author"], None)
        make_samples.make_epub(self.p("author - title.epub"), 2, "en", "Other", ["Z"], None)   # stays as is? no: renames away
        make_samples.make_epub(self.p("y.epub"), 3, "en", "Title", ["AUTHOR"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        by = {it.current: it for it in items}
        self.assertEqual(by["x.epub"].new_name, "Author - Title.epub")
        self.assertEqual(by["y.epub"].new_name, "AUTHOR - Title (2).epub")
        self.assertEqual(by["y.epub"].status, namer.DUP)
        self.assertEqual(by["author - title.epub"].new_name, "Z - Other.epub")

    def test_directory_occupying_the_target_name(self) -> None:
        os.makedirs(self.p("Author - Title.epub"))
        make_samples.make_epub(self.p("x.epub"), 1, "en", "Title", ["Author"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        self.assertEqual(items[0].new_name, "Author - Title (2).epub")
        namer.apply(items)
        self.assertTrue(os.path.isdir(self.p("Author - Title.epub")))
        self.assertTrue(os.path.isfile(self.p("Author - Title (2).epub")))

    def test_unselected_item_does_not_reserve_its_name(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "Same", ["X"], None)
        make_samples.make_epub(self.p("b.epub"), 2, "en", "Same", ["X"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        self.assertEqual([it.new_name for it in items], ["X - Same.epub", "X - Same (2).epub"])
        items[0].selected = False
        namer.plan(items, opts())
        self.assertEqual(items[1].new_name, "X - Same.epub")
        self.assertEqual(items[1].status, namer.OK)

    def test_manual_name_colliding_with_planned_name(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "Same", ["X"], None)
        make_samples.make_epub(self.p("b.epub"), 2, "en", None, [], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        namer.set_manual_name(items[1], "X - Same")
        namer.plan(items, opts())
        self.assertEqual(items[1].new_name, "X - Same (2).epub")
        self.assertEqual(items[1].status, namer.DUP)
        self.assertTrue(items[1].manual)                 # still the user's name after re-plan

    def test_same_names_in_different_folders_do_not_collide(self) -> None:
        sub = self.p("sub")
        os.makedirs(sub)
        make_samples.make_epub(self.p("a.epub"), 1, "en", "Same", ["X"], None)
        make_samples.make_epub(os.path.join(sub, "b.epub"), 2, "en", "Same", ["X"], None)
        items = items_for(self.dir, recursive=True)
        namer.plan(items, opts())
        self.assertEqual({it.new_name for it in items}, {"X - Same.epub"})
        self.assertEqual({it.status for it in items}, {namer.OK})

    def test_epub_and_pdf_with_same_stem_do_not_collide(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "Same", ["X"], None)
        write_pdf(self.p("b.pdf"), "Same", "X")
        items = items_for(self.dir)
        namer.plan(items, opts())
        self.assertEqual(sorted(it.new_name for it in items), ["X - Same.epub", "X - Same.pdf"])
        self.assertEqual({it.status for it in items}, {namer.OK})

    def test_uppercase_extension_is_lowercased(self) -> None:
        make_samples.make_epub(self.p("A.EPUB"), 1, "en", "T", ["X"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        self.assertEqual(items[0].new_name, "X - T.epub")

    def test_replan_after_failure_resets_status(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        with open(self.p("a.epub"), "rb"):
            namer.apply(items)
        self.assertEqual(items[0].status, namer.FAILED)
        namer.plan(items, opts())
        self.assertEqual(items[0].status, namer.OK)
        self.assertEqual(namer.apply(items).failed, [])


# =============================================================== apply ordering
class ApplyOrderingTests(TempFolder):
    def _titles(self) -> dict[str, str]:
        return {n: meta.read_meta(self.p(n)).title for n in self.names()}

    def test_chain_a_to_b_to_c(self) -> None:
        make_samples.make_epub(self.p("A.epub"), 1, "en", "B", [], None)     # wants B.epub
        make_samples.make_epub(self.p("B.epub"), 2, "en", "C", [], None)     # wants C.epub
        items = items_for(self.dir)
        namer.plan(items, opts(pattern="{title}"))
        self.assertEqual({it.status for it in items}, {namer.OK})           # no numbering needed
        result = namer.apply(items)
        self.assertEqual(result.failed, [])
        self.assertEqual(self._titles(), {"B.epub": "B", "C.epub": "C"})

    def test_three_cycle(self) -> None:
        make_samples.make_epub(self.p("A.epub"), 1, "en", "B", [], None)
        make_samples.make_epub(self.p("B.epub"), 2, "en", "C", [], None)
        make_samples.make_epub(self.p("C.epub"), 3, "en", "A", [], None)
        items = items_for(self.dir)
        namer.plan(items, opts(pattern="{title}"))
        result = namer.apply(items)
        self.assertEqual(result.failed, [])
        self.assertEqual(self._titles(), {"A.epub": "A", "B.epub": "B", "C.epub": "C"})
        self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(self.dir)))
        self.assertEqual(sorted(os.path.basename(o) for o, _ in result.renamed), ["A.epub", "B.epub", "C.epub"])
        undo.record(result.renamed)
        res = undo.undo(self.dir)
        self.assertEqual(res.skipped, [])
        self.assertEqual(self._titles(), {"A.epub": "B", "B.epub": "C", "C.epub": "A"})

    def test_target_created_after_planning_is_never_overwritten(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        with open(self.p("X - T.epub"), "wb") as f:
            f.write(b"precious")
        result = namer.apply(items)
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(open(self.p("X - T.epub"), "rb").read(), b"precious")
        self.assertTrue(os.path.exists(self.p("a.epub")))

    def test_source_deleted_after_planning(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        make_samples.make_epub(self.p("b.epub"), 2, "en", "U", ["X"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        os.remove(self.p("a.epub"))
        result = namer.apply(items)
        self.assertEqual([it.current for it, _ in result.failed], ["a.epub"])
        self.assertEqual(self.names(), {"X - U.epub"})

    def test_read_only_file_keeps_attribute(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        os.chmod(self.p("a.epub"), stat.S_IREAD)
        items = items_for(self.dir)
        namer.plan(items, opts())
        result = namer.apply(items)
        self.assertEqual(result.failed, [])
        self.assertFalse(os.stat(self.p("X - T.epub")).st_mode & stat.S_IWRITE)

    def test_progress_callback(self) -> None:
        for i in range(3):
            make_samples.make_epub(self.p(f"{i}.epub"), i, "en", f"T{i}", ["X"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        seen = []
        namer.apply(items, progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(seen, [(1, 3), (2, 3), (3, 3)])

    def test_file_contents_unchanged(self) -> None:
        import hashlib

        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        before = hashlib.sha256(open(self.p("a.epub"), "rb").read()).hexdigest()
        items = items_for(self.dir)
        namer.plan(items, opts())
        namer.apply(items)
        after = hashlib.sha256(open(self.p("X - T.epub"), "rb").read()).hexdigest()
        self.assertEqual(before, after)


# =============================================================== undo safety
class UndoEdgeTests(TempFolder):
    def test_two_sessions_unwind_in_order(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        undo.record(namer.apply(items).renamed)                       # a -> X - T
        items = items_for(self.dir)
        namer.plan(items, opts(pattern="{title}"))
        undo.record(namer.apply(items).renamed)                       # X - T -> T
        self.assertEqual(self.names(), {"T.epub"})
        with open(undo.log_path(self.dir), encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["sessions"]), 2)
        res = undo.undo(self.dir)
        self.assertEqual(len(res.restored), 2)
        self.assertEqual(self.names(), {"a.epub"})

    def test_log_entries_cannot_escape_the_folder(self) -> None:
        outside = os.path.join(os.path.dirname(self.dir), "ebr_escape_target.epub")
        make_samples.make_epub(self.p("victim.epub"), 1, "en", "T", ["X"], None)
        log = {"version": 1, "sessions": [{"time": "", "entries": [
            {"from": "..\\ebr_escape_target.epub", "to": "victim.epub"},
            {"from": "sub/deeper.epub", "to": "victim.epub"},
            {"from": "C:\\Windows\\x.epub", "to": "victim.epub"},
        ]}]}
        with open(undo.log_path(self.dir), "w", encoding="utf-8") as f:
            json.dump(log, f)
        try:
            res = undo.undo(self.dir)
            self.assertEqual(res.restored, [])
            self.assertTrue(os.path.exists(self.p("victim.epub")))
            self.assertFalse(os.path.exists(outside))
        finally:
            if os.path.exists(outside):
                os.remove(outside)

    def test_entry_where_from_equals_to(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        with open(undo.log_path(self.dir), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "sessions": [{"entries": [{"from": "a.epub", "to": "a.epub"}]}]}, f)
        res = undo.undo(self.dir)
        self.assertEqual((res.restored, res.skipped), ([], []))
        self.assertTrue(os.path.exists(self.p("a.epub")))

    def test_record_with_nothing_writes_no_log(self) -> None:
        self.assertEqual(undo.record([]), [])
        self.assertFalse(os.path.exists(undo.log_path(self.dir)))

    def test_undo_swap_when_third_file_blocks(self) -> None:
        """A<->B swap logged, but A's original name is now taken by a stranger."""
        make_samples.make_epub(self.p("B - A.epub"), 1, "en", "B", ["A"], None)
        make_samples.make_epub(self.p("A - B.epub"), 2, "en", "A", ["B"], None)
        items = items_for(self.dir)
        namer.plan(items, opts())
        undo.record(namer.apply(items).renamed)
        os.rename(self.p("A - B.epub"), self.p("gone.epub"))         # one of the pair disappears
        res = undo.undo(self.dir)
        self.assertEqual([r for _, r in res.skipped], ["missing"])
        self.assertEqual(len(res.restored), 1)

    def test_log_is_valid_json_with_relative_names_only(self) -> None:
        sub = self.p("sub dir")
        os.makedirs(sub)
        make_samples.make_epub(os.path.join(sub, "a.epub"), 1, "en", "T", ["X"], None)
        items = items_for(self.dir, recursive=True)
        namer.plan(items, opts())
        undo.record(namer.apply(items).renamed)
        with open(undo.log_path(sub), encoding="utf-8") as f:
            data = json.load(f)
        entry = data["sessions"][0]["entries"][0]
        self.assertEqual(entry, {"from": "a.epub", "to": "X - T.epub"})
        self.assertFalse(os.path.exists(undo.log_path(self.dir)))


# =============================================================== CLI
class CliEdgeTests(TempFolder):
    def _run(self, *args: str, **kw) -> subprocess.CompletedProcess:
        kw.setdefault("stdin", subprocess.DEVNULL)
        return subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), *args],
                              capture_output=True, text=True, encoding="utf-8", cwd=ROOT, **kw)

    def test_single_file_input_and_undo_by_file_path(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        make_samples.make_epub(self.p("b.epub"), 2, "en", "U", ["X"], None)
        r = self._run(self.p("a.epub"), "-y", "--lang", "en")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), {"X - T.epub", "b.epub"})
        r = self._run(self.p("X - T.epub"), "--undo", "--lang", "en")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), {"a.epub", "b.epub"})

    def test_missing_input_is_reported_but_batch_continues(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        r = self._run(self.p("nope.epub"), self.dir, "--dry-run", "--lang", "en")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Cannot open file", r.stderr)
        self.assertIn("X - T.epub", r.stdout)

    def test_exit_code_1_on_failure(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        with open(self.p("X - T.epub"), "wb") as f:
            f.write(b"x")
        # planning numbers the collision, so force a runtime failure instead: lock the source
        items = items_for(self.dir)
        namer.plan(items, opts())
        self.assertEqual([it.new_name for it in items if it.current == "a.epub"], ["X - T (2).epub"])
        with open(self.p("a.epub"), "rb"):
            r = self._run(self.dir, "-y", "--lang", "en")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Rename failed", r.stderr)

    def test_cjk_output_on_pipe(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "ja", "\u543e\u8f29\u306f\u732b\u3067\u3042\u308b",
                               ["\u590f\u76ee\u6f31\u77f3"], None)
        r = self._run(self.dir, "--dry-run", "--lang", "zh-CN")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("\u590f\u76ee\u6f31\u77f3 - \u543e\u8f29\u306f\u732b\u3067\u3042\u308b.epub", r.stdout)

    def test_no_confirmation_prompt_when_not_a_tty(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        r = self._run(self.dir, "--lang", "en", stdin=subprocess.DEVNULL)   # no -y, stdin is not a tty
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), {"X - T.epub"})

    def test_pattern_without_placeholders_falls_back(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        r = self._run(self.dir, "--dry-run", "--pattern", "nothing", "--lang", "en")
        self.assertIn("X - T.epub", r.stdout)

    def test_recursive_undo_covers_subfolders(self) -> None:
        sub = self.p("sub")
        os.makedirs(sub)
        make_samples.make_epub(self.p("a.epub"), 1, "en", "T", ["X"], None)
        make_samples.make_epub(os.path.join(sub, "b.epub"), 2, "en", "U", ["Y"], None)
        self.assertEqual(main.main([self.dir, "--recursive", "-y", "--lang", "en"]), 0)
        self.assertEqual(main.main([self.dir, "--undo", "--lang", "en"]), 0)           # top folder only
        self.assertTrue(os.path.exists(os.path.join(sub, "Y - U.epub")))
        self.assertEqual(main.main([self.dir, "--undo", "--recursive", "--lang", "en"]), 0)
        self.assertTrue(os.path.exists(os.path.join(sub, "b.epub")))

    def test_dry_run_with_only_nometa_files(self) -> None:
        make_samples.make_epub(self.p("a.epub"), 1, "en", None, [], None)
        r = self._run(self.dir, "--lang", "en", "-y")
        self.assertEqual(r.returncode, 0)
        self.assertIn("No files to rename", r.stdout)
        self.assertEqual(self.names(), {"a.epub"})


# =============================================================== settings / i18n
class SettingsI18nTests(unittest.TestCase):
    def test_settings_file_variants(self) -> None:
        import gui

        original = i18n.SETTINGS_PATH
        tmp = tempfile.mkdtemp(prefix="ebr_set_")
        try:
            i18n.SETTINGS_PATH = os.path.join(tmp, "settings.json")
            for content in ("[1, 2]", "null", "{bad", "", '{"lang": 42, "options": {"pattern": ["x"]}}'):
                with open(i18n.SETTINGS_PATH, "w", encoding="utf-8") as f:
                    f.write(content)
                settings = i18n.load_settings()
                self.assertIsInstance(settings, dict)
                self.assertEqual(gui._saved_options(settings).pattern, namer.DEFAULT_PATTERN)
                self.assertIn(i18n.init(), i18n.LANGS)
            with open(i18n.SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump({"lang": "ja", "options": {"pattern": "{title}", "recursive": True, "others": True}}, f)
            self.assertEqual(i18n.init(), "ja")
            o = gui._saved_options(i18n.load_settings())
            self.assertEqual((o.pattern, o.recursive, o.others), ("{title}", True, True))
        finally:
            i18n.SETTINGS_PATH = original
            i18n.init("en")
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_key_and_bad_format(self) -> None:
        missing = "no_such" + "_key"                 # built at runtime so check_i18n does not see a key literal
        self.assertEqual(i18n.t(missing), missing)
        self.assertEqual(i18n.t("msg_done"), i18n.t("msg_done", wrong="x"))
        self.assertEqual(i18n.t("msg_done", count=3), "Done: 3 files renamed")

    def test_every_language_has_every_status(self) -> None:
        for lang in i18n.LANGS:
            i18n.set_lang(lang, persist=False)
            for code in (namer.OK, namer.NOCHANGE, namer.DUP, namer.NOMETA, namer.FAILED, namer.DONE):
                self.assertNotEqual(i18n.t(f"status_{code}"), f"status_{code}", (lang, code))
        i18n.set_lang("en", persist=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
