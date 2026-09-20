"""원고를 읽고 NVIDIA NIM 모델로 블로그 댓글/답글을 만든다."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

from .manuscript import Manuscript
from .nvidia_client import ChatMessage, NvidiaAPIError, NvidiaClient

# 댓글 어조 프리셋. --tone 으로 고른다.
TONES: dict[str, str] = {
    "friendly": "이웃 블로거끼리 나누는 편안한 반말체 없는 존댓말, 이모지는 최대 1개",
    "curious": "글을 읽고 생긴 실제 궁금증을 구체적으로 묻는 질문형",
    "grateful": "정보가 도움이 됐다는 감사 표현 중심, 짧고 담백하게",
    "mixed": "감사·질문·경험 공유가 자연스럽게 섞이도록 댓글마다 다르게",
}

SYSTEM_PROMPT = """너는 한국 네이버 블로그 이웃들의 댓글을 쓰는 사람이다.
규칙:
- 실제 사람이 쓴 것처럼 자연스러운 한국어 구어체로 쓴다.
- 글에 실제로 나온 내용을 근거로 쓴다. 글에 없는 사실을 지어내지 않는다.
- 광고, 홍보 링크, 상호명, 연락처는 절대 넣지 않는다.
- 댓글마다 길이·말투·관심사를 다르게 해서 복사된 느낌이 나지 않게 한다.
- 한 댓글은 1~3문장, 120자 내외로 짧게 쓴다.
- 출력은 반드시 지정된 JSON 형식만, 다른 설명 없이 내보낸다."""


@dataclass
class Comment:
    """생성된 댓글 한 개."""

    persona: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class Reply:
    """받은 댓글에 대한 블로거 답글 초안."""

    comment: str
    reply: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def build_comment_prompt(manuscript: Manuscript, count: int, tone: str) -> list[ChatMessage]:
    tone_hint = TONES.get(tone, TONES["mixed"])
    user = f"""아래는 네이버 블로그에 발행할 글이다.

# 제목
{manuscript.title}

# 본문
{manuscript.excerpt}

이 글에 달릴 법한 댓글 {count}개를 만들어라.
어조: {tone_hint}
persona 는 댓글 작성자를 한 줄로 설명한 값이다(예: "9월 출산 예정인 예비맘").

출력 형식(JSON 배열만):
[{{"persona": "...", "text": "..."}}]"""
    return [ChatMessage("system", SYSTEM_PROMPT), ChatMessage("user", user)]


def build_reply_prompt(manuscript: Manuscript, incoming: Sequence[str]) -> list[ChatMessage]:
    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(incoming, start=1))
    user = f"""아래 글을 쓴 블로거 입장에서 독자 댓글에 답글을 달아라.

# 제목
{manuscript.title}

# 본문
{manuscript.excerpt}

# 받은 댓글
{numbered}

규칙:
- 댓글 하나당 답글 하나, 순서를 유지한다.
- 본문에서 확인되는 내용만 근거로 답한다. 확정되지 않은 제도는 "아직 확정 전"임을 분명히 한다.
- 본문에 없는 질문에는 아는 척하지 말고 확인해서 알려주겠다고 답한다.

출력 형식(JSON 배열만):
[{{"comment": "원문 댓글", "reply": "답글"}}]"""
    return [ChatMessage("system", SYSTEM_PROMPT), ChatMessage("user", user)]


def parse_json_array(raw: str) -> list[dict[str, Any]]:
    """모델 출력에서 JSON 배열을 끄집어낸다. ```json 펜스와 잡설을 견딘다."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("["):
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            raise NvidiaAPIError(f"모델 응답에서 JSON 배열을 찾지 못했습니다: {raw[:300]}")
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NvidiaAPIError(f"모델 응답 JSON 파싱 실패: {exc}: {raw[:300]}") from exc
    if not isinstance(parsed, list):
        raise NvidiaAPIError(f"JSON 배열이 아닙니다: {raw[:300]}")
    return [item for item in parsed if isinstance(item, dict)]


def generate_comments(
    client: NvidiaClient,
    manuscript: Manuscript,
    *,
    count: int = 5,
    tone: str = "mixed",
    temperature: float = 0.9,
    model: str | None = None,
) -> list[Comment]:
    raw = client.chat(
        build_comment_prompt(manuscript, count, tone),
        model=model,
        temperature=temperature,
        max_tokens=2048,
    )
    comments = [
        Comment(persona=str(item.get("persona", "독자")).strip(), text=str(item.get("text", "")).strip())
        for item in parse_json_array(raw)
    ]
    return [c for c in comments if c.text][:count]


def draft_replies(
    client: NvidiaClient,
    manuscript: Manuscript,
    incoming: Iterable[str],
    *,
    temperature: float = 0.6,
    model: str | None = None,
) -> list[Reply]:
    comments = [c.strip() for c in incoming if c.strip()]
    if not comments:
        return []
    raw = client.chat(
        build_reply_prompt(manuscript, comments),
        model=model,
        temperature=temperature,
        max_tokens=2048,
    )
    parsed = parse_json_array(raw)
    replies: list[Reply] = []
    for index, item in enumerate(parsed):
        original = str(item.get("comment", "")).strip() or (
            comments[index] if index < len(comments) else ""
        )
        reply_text = str(item.get("reply", "")).strip()
        if reply_text:
            replies.append(Reply(comment=original, reply=reply_text))
    return replies
