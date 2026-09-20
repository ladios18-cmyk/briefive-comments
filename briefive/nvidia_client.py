"""NVIDIA NIM(https://integrate.api.nvidia.com/v1) OpenAI 호환 API 클라이언트.

표준 라이브러리만 사용한다. 별도 의존성 설치 없이 `python3 -m briefive.cli` 로 바로 동작.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"

# 일시적 장애로 보고 재시도할 상태 코드.
RETRY_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})


class NvidiaAPIError(RuntimeError):
    """NVIDIA API 호출이 실패했을 때 발생."""

    def __init__(self, message: str, *, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class ChatMessage:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class NvidiaClient:
    """`/chat/completions` 와 `/models` 를 감싼 얇은 클라이언트."""

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = 120.0
    max_retries: int = 3
    retry_backoff: float = 2.0
    extra_headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.environ.get("NVIDIA_API_KEY")
        self.base_url = (self.base_url or DEFAULT_BASE_URL).rstrip("/")
        if not self.api_key:
            raise NvidiaAPIError(
                "NVIDIA_API_KEY 가 설정되지 않았습니다. "
                "https://build.nvidia.com 에서 키를 발급받아 환경변수로 지정하세요."
            )

    # ------------------------------------------------------------------ #
    # 팩토리
    # ------------------------------------------------------------------ #
    @classmethod
    def from_env(cls, **overrides: Any) -> "NvidiaClient":
        """환경변수(NVIDIA_API_KEY / NVIDIA_BASE_URL / NVIDIA_MODEL)로 클라이언트 생성."""
        params: dict[str, Any] = {
            "api_key": os.environ.get("NVIDIA_API_KEY"),
            "base_url": os.environ.get("NVIDIA_BASE_URL", DEFAULT_BASE_URL),
            "model": os.environ.get("NVIDIA_MODEL", DEFAULT_MODEL),
        }
        params.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**params)

    # ------------------------------------------------------------------ #
    # 공개 API
    # ------------------------------------------------------------------ #
    def list_models(self) -> list[dict[str, Any]]:
        """엔드포인트에서 사용 가능한 모델 목록을 가져온다."""
        payload = self._request("GET", "/models", None)
        return list(payload.get("data", []))

    def chat(
        self,
        messages: Sequence[ChatMessage | dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        top_p: float = 0.95,
        max_tokens: int = 2048,
        **extra: Any,
    ) -> str:
        """채팅 완성 결과의 본문 텍스트를 반환."""
        body = self._chat_body(
            messages,
            model=model,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=False,
            **extra,
        )
        payload = self._request("POST", "/chat/completions", body)
        choices = payload.get("choices") or []
        if not choices:
            raise NvidiaAPIError(f"응답에 choices 가 없습니다: {payload!r}")
        return choices[0].get("message", {}).get("content", "") or ""

    def stream_chat(
        self,
        messages: Sequence[ChatMessage | dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        top_p: float = 0.95,
        max_tokens: int = 2048,
        **extra: Any,
    ) -> Iterator[str]:
        """SSE 스트리밍으로 토큰 조각을 순서대로 내보낸다."""
        body = self._chat_body(
            messages,
            model=model,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=True,
            **extra,
        )
        request = self._build_request("POST", "/chat/completions", body, stream=True)
        with self._urlopen(request) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for choice in chunk.get("choices", []):
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        yield piece

    # ------------------------------------------------------------------ #
    # 내부 구현
    # ------------------------------------------------------------------ #
    def _chat_body(
        self,
        messages: Sequence[ChatMessage | dict[str, str]],
        *,
        model: str | None,
        stream: bool,
        **params: Any,
    ) -> dict[str, Any]:
        normalized = [m.to_dict() if isinstance(m, ChatMessage) else dict(m) for m in messages]
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": normalized,
            "stream": stream,
        }
        body.update({k: v for k, v in params.items() if v is not None})
        return body

    def _build_request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        *,
        stream: bool = False,
    ) -> urllib.request.Request:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "text/event-stream" if stream else "application/json",
            **self.extra_headers,
        }
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        request = self._build_request(method, path, body)
        with self._urlopen(request) as response:
            raw = response.read().decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise NvidiaAPIError(f"JSON 파싱 실패: {exc}", body=raw) from exc

    def _urlopen(self, request: urllib.request.Request):
        """재시도 로직을 얹은 urlopen. 테스트에서 이 메서드만 바꿔치기하면 된다."""
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return urllib.request.urlopen(request, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")
                if exc.code not in RETRY_STATUSES or attempt == self.max_retries - 1:
                    raise NvidiaAPIError(
                        f"NVIDIA API {exc.code} 오류: {detail[:500]}",
                        status=exc.code,
                        body=detail,
                    ) from exc
                last_error = exc
            except urllib.error.URLError as exc:
                if attempt == self.max_retries - 1:
                    raise NvidiaAPIError(f"NVIDIA API 연결 실패: {exc.reason}") from exc
                last_error = exc
            time.sleep(self.retry_backoff**attempt)
        raise NvidiaAPIError(f"재시도 {self.max_retries}회 모두 실패: {last_error}")
