"""블로그 원고 HTML에서 제목과 본문 텍스트를 뽑아낸다.

이 저장소의 원고는 「▼ 여기부터 복사 ▼」 ~ 「▲ 여기까지 복사 ▲」 사이가 실제 발행 본문이다.
해당 표식이 없으면 <body> 전체를 본문으로 본다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

COPY_START = "여기부터 복사"
COPY_END = "여기까지 복사"

# 텍스트를 추출하지 않는 태그.
SKIP_TAGS = frozenset({"style", "script", "head"})
# 앞뒤로 줄바꿈을 넣어 문단을 분리할 태그.
BLOCK_TAGS = frozenset(
    {"p", "div", "h1", "h2", "h3", "h4", "li", "tr", "br", "table", "ul", "ol", "blockquote"}
)


@dataclass
class Manuscript:
    """원고 한 편."""

    path: Path
    title: str
    body: str

    @property
    def excerpt(self) -> str:
        """프롬프트에 넣기 좋은 길이로 자른 본문."""
        return truncate(self.body, 6000)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in BLOCK_TAGS:
            self._chunks.append("\n")
        if tag in {"td", "th"}:
            self._chunks.append(" | ")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._skip_depth:
            return
        self._chunks.append(data)

    @property
    def text(self) -> str:
        return normalize_whitespace("".join(self._chunks))

    @property
    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())


def normalize_whitespace(text: str) -> str:
    """줄 단위 공백을 정리하고 빈 줄이 3개 이상 이어지지 않게 만든다."""
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    joined = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "\n…(이하 생략)"


def extract_copy_region(text: str) -> str:
    """복사 구간 표식이 있으면 그 사이만, 없으면 원문 전체를 돌려준다.

    표식 문구는 상단 사용법 안내에도 등장하므로, 마지막 종료 표식과 그 앞의
    가장 가까운 시작 표식을 실제 구간으로 본다.
    """
    end = text.rfind(COPY_END)
    if end == -1:
        return text
    start = text.rfind(COPY_START, 0, end)
    if start == -1:
        return text
    line_end = text.find("\n", start)
    if line_end == -1 or line_end >= end:
        return text
    region = text[line_end + 1 : end]
    # 표식 줄에 붙어 있던 ▲/▼ 기호 제거.
    return normalize_whitespace(region.strip("▲▼ \n"))


def load(path: str | Path) -> Manuscript:
    """HTML 원고 파일을 읽어 Manuscript 로 만든다."""
    file_path = Path(path)
    parser = _TextExtractor()
    parser.feed(file_path.read_text(encoding="utf-8"))
    parser.close()

    body = extract_copy_region(parser.text)
    title = parser.title or _first_heading(body) or file_path.stem
    return Manuscript(path=file_path, title=title, body=body)


def _first_heading(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return ""
