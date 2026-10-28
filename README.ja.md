# しおりツール – 電子書籍ファイル名整理

[한국어](README.md) · [English](README.en.md) · [中文](README.zh-CN.md)

フォルダ内の EPUB・PDF に埋め込まれたタイトル・著者情報を読み取り、`著者 - タイトル.epub` の形式に一括で変更します。プレビュー表で確認してから実行し、実行後も元に戻せます。サーバーなし（新しいバージョンの確認のみ例外、オフにできます）、インストール不要、ファイル内容は変更しません。

> **元に戻す**：実行したフォルダに `rename_log.json` が作られます。ウィンドウの**元に戻す**ボタンを押すか `python main.py ./books --undo` を実行すると、すべて元の名前に戻ります。

![プレビュー表](docs/before_after.png)

## ダウンロード

- **実行ファイル**：[最新リリース](https://github.com/microhan1/ebook-renamer/releases/latest)から `ebook-renamer.exe` をダウンロードするか、[直接ダウンロード](https://github.com/microhan1/ebook-renamer/releases/latest/download/ebook-renamer.exe)してダブルクリック。インストール不要です。exe は未署名のため SmartScreen の警告が出たら「詳細情報 → 実行」を選んでください。
- **ソースから実行**：

```bash
pip install -r requirements.txt
python main.py
```

## 使い方

1. フォルダまたは EPUB・PDF ファイルをウィンドウにドロップします。
2. 表で新しい名前を確認します。命名ルール（`{author} - {title}`、`{title} - {author}`、`{title}`、または `{author}` `{title}` `{year}` で自由入力）を変えたり、チェックを外して除外したり、「新しい名前」のセルをダブルクリックして直接編集できます。
3. **名前を変更**を押します。名前だけが変わり、ファイルは同じ場所に残ります。

- タイトルも著者もないファイルは灰色で表示され、既定で除外されます。名前を入力すると対象になります。
- 新しい名前が重なるファイルは 2 つ目から ` (2)`、` (3)`… が付き、黄色の「重複」で表示されます。すでに付いた番号は再実行しても変わりません。
- 著者が複数いる場合は第一著者だけを使い、オプションで「他N名」を付けられます。
- ファイル名の整理：禁止文字（`\ / : * ? " < > |`）を除去、前後の空白を削除、連続する空白は 1 つに、200 文字まで。

コマンドラインでも使えます。

```bash
python main.py ./books --pattern "{author} - {title}" --recursive --dry-run
python main.py ./books --pattern "{title} ({year}) - {author}" -y
python main.py ./books --undo --dry-run
python main.py ./books --undo
```

`--dry-run` は表を出力するだけで何も変更しません。`--undo` と併用すると、元に戻すファイルの一覧だけを表示します。`python main.py --help` が OS の言語（한국어 · English · 中文 · 日本語）でオプションを表示します。

## 新しいバージョンの確認

起動時に新しいバージョンがあるか確認するため、ツール名とバージョンだけをしおりサーバー（chaekgalpi.co.kr）に送ります。ファイルは送らず、確認は 1 日 1 回だけで、設定でオフにできます。リクエストに含まれるのは、ツール名、バージョン、Windows を示す印（`win`）だけです。

新しいバージョンがあるとウィンドウの下に 1 行で知らせ、**更新**を押すとしおりツールのページが開きます。オフにするには、ウィンドウ右上の**新しいバージョンを確認**のチェックを外します。オフラインのときやサーバーが応答しないときは、何も表示しません。

## ご意見・ご要望

不具合・使いにくい点・ほしい機能は、ウィンドウ右上の**ご意見を送る**を押すか、[しおりツールのページ](https://chaekgalpi.co.kr/en/tools/ebookrenamer#feedback)からログインなしで送れます。プログラムはそのページをブラウザで開くだけで、自分では何も送りません。[GitHub Issues](https://github.com/microhan1/ebook-renamer/issues) もこれまでどおり受け付けています。

## しないこと

- メタデータの修正や補完はしません。読み取りのみです。
- インターネットで書籍情報を検索しません（新しいバージョンの確認のみ例外、オフにできます）。
- ファイルを別フォルダへ移動したりフォルダを作ったりしません。名前だけ変えます。
- 重複ファイルの判定はしません。
- EPUB・PDF 以外の拡張子は無視します。
- 新しいバージョンを自動でダウンロードしたり置き換えたりしません。

## シリーズ

- しおりツール：[スキャンPDF補正](https://github.com/microhan1/scan-pdf-cleanup) · [見開き分割](https://github.com/microhan1/scan-pdf-split)- インストール不要、ブラウザーで使える Web 版：[見開き分割](https://microhan1.github.io/spread-split/)
- [しおりライブラリ（Chaekgalpi Library）](https://chaekgalpi.co.kr/en/tools/ebookrenamer?utm_source=github&utm_medium=referral&utm_campaign=tool_cta&utm_content=ebookrenamer) — 読んだ本と読書録を記録するウェブサービス。整理した本を読み終えたら、ひと言残してみてください。

## ライセンス

MIT。[LICENSE](LICENSE) を参照。

Releases の exe には [PyMuPDF](https://github.com/pymupdf/PyMuPDF)（AGPL-3.0）が同梱されているため、exe 全体は AGPL-3.0 の条件で配布されます。対応するソースはこのリポジトリと PyMuPDF のリポジトリです。
