# 书签工具 – 电子书文件重命名

[한국어](README.md) · [English](README.en.md) · [日本語](README.ja.md)

读取文件夹中 EPUB 或 PDF 文件内嵌的书名和作者信息，一次性将文件重命名为 `作者 - 书名.epub`。先在预览表中确认再执行，执行后仍可撤销。无需服务器（仅检查新版本例外，可关闭），无需安装，不修改文件内容。

> **撤销**：执行后会在该文件夹生成 `rename_log.json`。点击窗口中的**撤销**按钮，或运行 `python main.py ./books --undo`，即可全部恢复原文件名。

![预览表](docs/before_after.png)

## 下载

- **可执行文件**：在[最新发布](https://github.com/microhan1/ebook-renamer/releases/latest)下载 `ebook-renamer.exe`，或点击[直接下载](https://github.com/microhan1/ebook-renamer/releases/latest/download/ebook-renamer.exe)，然后双击运行，无需安装。exe 未签名，若 SmartScreen 弹出警告，请选择“更多信息 → 仍要运行”。
- **从源码运行**：

```bash
pip install -r requirements.txt
python main.py
```

## 使用方法

1. 将文件夹或 EPUB/PDF 文件拖到窗口中。
2. 在表格中确认新文件名。可以更改命名规则（`{author} - {title}`、`{title} - {author}`、`{title}`，或用 `{author}` `{title}` `{year}` 自行输入），取消勾选以排除文件，或双击“新文件名”单元格手动修改。
3. 点击**重命名**。只改文件名，文件仍在原处。

- 书名和作者都为空的文件显示为灰色并默认排除。输入名称后即可纳入处理。
- 新文件名相同的文件从第二个起加上 ` (2)`、` (3)`……并以黄色“重复”标示。已有的编号再次运行时保持不变。
- 有多位作者时只使用第一作者，可选附加“及其他N人”。
- 文件名清理：去除禁止字符（`\ / : * ? " < > |`），去掉首尾空格，连续空格合并为一个，长度不超过 200 个字符。

也可以在命令行使用。

```bash
python main.py ./books --pattern "{author} - {title}" --recursive --dry-run
python main.py ./books --pattern "{title} ({year}) - {author}" -y
python main.py ./books --undo --dry-run
python main.py ./books --undo
```

`--dry-run` 只打印表格，不做任何更改；与 `--undo` 一起使用时，只列出将要恢复的文件。`python main.py --help` 会按操作系统语言（한국어 · English · 中文 · 日本語）显示选项。

## 检查新版本

运行时，为了确认是否有新版本，只会把工具名称和版本发送到书签服务器（chaekgalpi.co.kr）。不会发送文件，每天只检查一次，可在设置中关闭。请求中只包含工具名称、版本和 Windows 标记（`win`）。

有新版本时，窗口下方会显示一行提示，点击**更新**会打开书签工具页面。要关闭，请取消窗口右上角的**检查新版本**勾选。未联网或服务器没有响应时，不会有任何提示。

## 反馈

遇到问题、不便之处或想要的功能，可以点击窗口右上角的**发送反馈**，或在[书签工具页面](https://chaekgalpi.co.kr/en/tools/ebookrenamer#feedback)无需登录直接提交。程序只会在浏览器中打开该页面，本身不发送任何内容。也欢迎继续使用 [GitHub Issues](https://github.com/microhan1/ebook-renamer/issues)。

## 不做的事

- 不修改、不补充元数据，只读取。
- 不在互联网上查找图书信息（仅检查新版本例外，可关闭）。
- 不把文件移到其他文件夹，也不创建文件夹，只改名。
- 不判断重复文件。
- 忽略 EPUB 和 PDF 以外的扩展名。
- 不会自动下载或替换为新版本。

## 系列

- 书签工具：[扫描PDF清晰化](https://github.com/microhan1/scan-pdf-cleanup) · [双页拆分](https://github.com/microhan1/scan-pdf-split)- 无需安装、在浏览器中使用的网页版：[跨页拆分](https://microhan1.github.io/spread-split/)
- [书签图书馆（Chaekgalpi Library）](https://chaekgalpi.co.kr/tools/ebookrenamer?utm_source=github&utm_medium=referral&utm_campaign=tool_cta&utm_content=ebookrenamer) — 记录读过的书和读书笔记的网络服务。读完整理好的书后，不妨留下一句感想。

## 许可证

MIT。参见 [LICENSE](LICENSE)。

Releases 中的 exe 包含 [PyMuPDF](https://github.com/pymupdf/PyMuPDF)（AGPL-3.0），因此 exe 整体按 AGPL-3.0 条款分发。对应源代码为本仓库及 PyMuPDF 仓库。
