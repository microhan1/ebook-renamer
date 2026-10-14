# 책갈피 툴 – 전자책 파일명 정리

[English](README.en.md) · [中文](README.zh-CN.md) · [日本語](README.ja.md)

폴더 안의 EPUB·PDF를 파일 속 제목·저자 정보로 읽어 `저자 - 제목.epub` 형식으로 한 번에 바꿔 줍니다. 미리보기 표에서 확인한 뒤 실행하고, 실행 후에도 되돌리기가 남습니다. 서버 없음(새 버전 확인만 예외, 끌 수 있음), 설치 없음, 파일 내용 무수정.

> **되돌리기**: 실행한 폴더에 `rename_log.json`이 생깁니다. 창의 **되돌리기** 버튼을 누르거나 `python main.py ./books --undo`를 실행하면 전부 원래 이름으로 돌아갑니다.

![미리보기 표](docs/before_after.png)

## 다운로드

- **실행 파일**: [최신 릴리스](https://github.com/microhan1/ebook-renamer/releases/latest)에서 `ebook-renamer.exe`를 받거나 [바로 받기](https://github.com/microhan1/ebook-renamer/releases/latest/download/ebook-renamer.exe)를 눌러 더블클릭. 설치 없이 바로 실행됩니다. 서명이 없어 SmartScreen 경고가 뜨면 "추가 정보 → 실행"을 누르세요.
- **소스 실행**:

```bash
pip install -r requirements.txt
python main.py
```

## 사용법

1. 폴더나 EPUB·PDF 파일을 창에 끌어다 놓습니다.
2. 표에서 새 이름을 확인합니다. 이름 규칙(`{author} - {title}`, `{title} - {author}`, `{title}`, 또는 직접 입력, 치환자 `{author}` `{title}` `{year}`)을 바꾸거나, 체크를 풀어 제외하거나, 새 이름 칸을 더블클릭해 손으로 고칩니다.
3. **이름 바꾸기**를 누릅니다. 이름만 바뀌고 파일은 같은 자리에 그대로 있습니다.

- 제목·저자가 모두 없는 파일은 회색으로 표시되고 기본 제외됩니다. 이름을 직접 입력하면 포함됩니다.
- 새 이름이 같은 파일은 두 번째부터 ` (2)`, ` (3)`이 붙고 노란색 "중복"으로 표시됩니다. 이미 붙은 번호는 다시 실행해도 그대로 유지됩니다.
- 저자가 여러 명이면 첫 저자만 쓰고, 옵션으로 "외 N명"을 붙일 수 있습니다.
- 파일명 정리: 금지 문자(`\ / : * ? " < > |`) 제거, 앞뒤 공백 제거, 연속 공백 하나로, 200자 제한.

명령줄로도 쓸 수 있습니다.

```bash
python main.py ./books --pattern "{author} - {title}" --recursive --dry-run
python main.py ./books --pattern "{title} ({year}) - {author}" -y
python main.py ./books --undo --dry-run
python main.py ./books --undo
```

`--dry-run`은 표만 출력하고 아무것도 바꾸지 않습니다. `--undo`와 함께 쓰면 되돌릴 파일 목록만 보여줍니다. `python main.py --help`가 OS 언어(한국어 · English · 中文 · 日本語)로 옵션을 보여줍니다.

## 새 버전 확인

실행할 때 새 버전이 있는지 확인하려고 도구 이름과 버전만 책갈피 서버(chaekgalpi.co.kr)에 보냅니다. 파일은 보내지 않고, 하루 한 번만 확인하며, 설정에서 끌 수 있습니다. 요청에 들어가는 값은 도구 이름, 버전, 윈도 표시(`win`)뿐입니다.

새 버전이 있으면 창 아래에 한 줄로 알려 주고, **업데이트**를 누르면 책갈피 툴 페이지가 열립니다. 끄려면 창 오른쪽 위의 **새 버전 확인** 체크를 풉니다. 인터넷에 연결되지 않았거나 서버가 답하지 않으면 아무 말 없이 넘어갑니다.

## 하지 않는 것

- 메타데이터를 수정하거나 채우지 않습니다. 읽기만 합니다.
- 인터넷에서 책 정보를 검색하지 않습니다 (새 버전 확인만 예외, 끌 수 있음).
- 파일을 다른 폴더로 옮기거나 폴더를 만들지 않습니다. 이름만 바꿉니다.
- 중복 파일 판별은 하지 않습니다.
- EPUB·PDF 외 확장자는 무시합니다.
- 새 버전을 자동으로 내려받거나 바꾸지 않습니다.

## 시리즈

- 책갈피 툴: [스캔 PDF 보정](https://github.com/microhan1/scan-pdf-cleanup) · [두쪽 나누기](https://github.com/microhan1/scan-pdf-split)- 설치 없이 브라우저에서 쓰는 웹판: [펼침면 나누기](https://microhan1.github.io/spread-split/)
- [책갈피 라이브러리](https://chaekgalpi.co.kr/tools/ebookrenamer?utm_source=github&utm_medium=referral&utm_campaign=tool_cta&utm_content=ebookrenamer) — 읽은 책과 독서록을 기록하는 웹 서비스. 정리한 책을 다 읽으면 한 줄 남겨 보세요.

## 라이선스

MIT. [LICENSE](LICENSE) 참조.

Releases의 exe에는 [PyMuPDF](https://github.com/pymupdf/PyMuPDF)(AGPL-3.0)가 함께 들어 있어, exe 전체는 AGPL-3.0 조건을 따릅니다. 해당 소스는 이 저장소와 PyMuPDF 저장소에서 받을 수 있습니다.
