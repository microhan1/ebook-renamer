# 书签工具 – 电子书文件重命名

[한국어](README.md) · [English](README.en.md) · [日本語](README.ja.md)

读取文件夹中 EPUB·PDF 内嵌的书名和作者信息，一次性将文件重命名为 `作者 - 书名.epub`。先在预览表中确认再执行，执行后仍可撤销。无服务器，无需安装，不修改文件内容。

> **撤销**：执行后会在该文件夹生成 `rename_log.json`。点击窗口中的**撤销**按钮，或运行 `python main.py ./books --undo`，即可全部恢复原文件名。

![预览表](docs/before_after.png)

## 下载

- **可执行文件**：在 [Releases](https://github.com/microhan1/ebook-renamer/releases) 下载 `ebook-renamer.exe` 并双击运行，无需安装。exe 未签名，若 SmartScreen 弹出警告，请选择"更多信息 → 仍要运行"。
- **从源码运行**：

```bash
pip install -r requirements.txt
python main.py
```

## 使用方法

1. 将文件夹或 EPUB·PDF 文件拖到窗口中。
2. 在表格中确认新文件名。可以更改命名规则（`{author} - {title}`、`{title} - {author}`、`{title}`，或用 `{author}` `{title}` `{year}` 自行输入），取消勾选以排除文件，或双击"新文件名"单元格手动修改。
3. 点击**重命名**。只改名字，文件仍在原处。

- 书名和作者都为空的文件显示为灰色并默认排除。输入名称后即可包含。
- 新文件名相同的文件从第二个起加上 ` (2)`、` (3)`……并以黄色"重复"标示。已有的编号再次运行时保持不变。
- 有多位作者时只使用第一作者，可选附加"等N人"。
- 文件名清理：去除禁止字符（`\ / : * ? " < > |`），去掉首尾空格，连续空格合并为一个，限制 200 字。

也可以在命令行使用。

```bash
python main.py ./books --pattern "{author} - {title}" --recursive --dry-run
python main.py ./books --pattern "{title} ({year}) - {author}" -y
python main.py ./books --undo --dry-run
python main.py ./books --undo
```

`--dry-run` 只打印表格，不做任何更改；与 `--undo` 一起使用时，只列出将要恢复的文件。`python main.py --help` 会用操作系统语言（한국어 · English · 中文 · 日本語）显示选项。

## 不做的事

- 不修改、不补充元数据，只读取。
- 不在互联网上查找图书信息。
- 不把文件移到其他文件夹，也不创建文件夹，只改名。
- 不判断重复的图书。
- 忽略 EPUB·PDF 以外的扩展名。

## 系列

- 书签工具：[扫描PDF清晰化](https://github.com/microhan1/scan-pdf-cleanup) · [双页拆分](https://github.com/microhan1/scan-pdf-split) · [边距裁剪](https://github.com/microhan1/scan-pdf-crop)
- 无需安装、在浏览器中使用的网页版：[跨页拆分](https://microhan1.github.io/spread-split/)
- [书签图书馆（Chaekgalpi Library）](https://github.com/microhan1/chaekgalpi)

## 许可证

MIT。参见 [LICENSE](LICENSE)。

Releases 中的 exe 包含 [PyMuPDF](https://github.com/pymupdf/PyMuPDF)（AGPL-3.0），因此 exe 整体按 AGPL-3.0 条款分发。对应源代码为本仓库及 PyMuPDF 仓库。
