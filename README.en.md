# Chaekgalpi Tools – Ebook Renamer

[한국어](README.md) · [中文](README.zh-CN.md) · [日本語](README.ja.md)

Reads the title and author embedded in EPUB and PDF files in a folder and renames them all to `Author - Title.epub` in one go. Check the preview table first, then run; undo stays available afterwards. No server (the update check is the only exception, and you can turn it off), no install, file contents are never modified.

> **Undo**: a `rename_log.json` is written to the folder you ran on. Press **Undo** in the window or run `python main.py ./books --undo` to restore every original name.

![Preview table](docs/before_after.png)

## Download

- **Executable**: grab `ebook-renamer.exe` from the [latest release](https://github.com/microhan1/ebook-renamer/releases/latest) or use the [direct download](https://github.com/microhan1/ebook-renamer/releases/latest/download/ebook-renamer.exe), then double-click it. Nothing to install. The exe is unsigned; if SmartScreen warns, choose "More info → Run anyway".
- **Run from source**:

```bash
pip install -r requirements.txt
python main.py
```

## Usage

1. Drop a folder or EPUB/PDF files onto the window.
2. Check the new names in the table. Change the naming pattern (`{author} - {title}`, `{title} - {author}`, `{title}`, or type your own with `{author}` `{title}` `{year}`), untick files to exclude them, or double-click a New name cell to fix it by hand.
3. Press **Rename**. Only the names change; the files stay where they are.

- A file with neither title nor author is shown in grey and excluded by default. Type a name to include it.
- Files that would get the same name receive ` (2)`, ` (3)` ... from the second one on and are marked "Duplicate" in yellow. Numbers already in place are kept when you run it again.
- With several authors only the first is used; an option appends "and N more".
- Name cleanup: forbidden characters (`\ / : * ? " < > |`) removed, surrounding spaces trimmed, runs of spaces collapsed, 200-character limit.

It also works from the command line.

```bash
python main.py ./books --pattern "{author} - {title}" --recursive --dry-run
python main.py ./books --pattern "{title} ({year}) - {author}" -y
python main.py ./books --undo --dry-run
python main.py ./books --undo
```

`--dry-run` prints the table and changes nothing; with `--undo` it only lists what would be restored. `python main.py --help` prints the options in your OS language (한국어 · English · 中文 · 日本語).

## Update check

When it starts, it sends only the tool name and version to the Chaekgalpi server (chaekgalpi.co.kr) to see whether a newer version exists. No files are sent, it checks at most once a day, and you can turn it off in the settings. The request contains only the tool name, the version and a Windows marker (`win`).

If a newer version exists, a single line appears at the bottom of the window, and **Update** opens the Chaekgalpi Tools page. To turn it off, untick **Check for updates** at the top right of the window. When you are offline or the server does not answer, nothing is shown.

## What it does not do

- It does not edit or fill in metadata. Read only.
- It does not look up book information on the internet (the update check is the only exception, and you can turn it off).
- It does not move files to other folders or create folders. Names only.
- It does not detect duplicate books.
- Extensions other than EPUB and PDF are ignored.
- It does not download or install a new version by itself.

## Series

- Chaekgalpi Tools: [Scan PDF Cleanup](https://github.com/microhan1/scan-pdf-cleanup) · [Two-page Split](https://github.com/microhan1/scan-pdf-split)- Browser version, nothing to install: [Spread Split](https://microhan1.github.io/spread-split/)
- [Chaekgalpi Library](https://chaekgalpi.co.kr/en/tools/ebookrenamer?utm_source=github&utm_medium=referral&utm_campaign=tool_cta&utm_content=ebookrenamer) — a web service for recording the books you have read and your reviews (tools page in English; the reading-log service itself is in Korean). When you finish a book you have organized, leave a one-line note.

## License

MIT. See [LICENSE](LICENSE).

The exe on Releases bundles [PyMuPDF](https://github.com/pymupdf/PyMuPDF) (AGPL-3.0), so the exe as a whole is distributed under AGPL-3.0 terms. The corresponding source is this repository and the PyMuPDF repository.
