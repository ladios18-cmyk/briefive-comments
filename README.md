# briefive-comments

네이버 블로그 원고(HTML)를 읽어 **NVIDIA NIM**(`https://integrate.api.nvidia.com/v1`)의
OpenAI 호환 API로 댓글과 답글 초안을 만드는 도구입니다.

표준 라이브러리만 사용하므로 별도 패키지 설치가 필요 없습니다. (Python 3.10+)

## 설정

```bash
cp .env.example .env      # 값을 채운 뒤
set -a; source .env; set +a
```

| 환경변수 | 설명 | 기본값 |
| --- | --- | --- |
| `NVIDIA_API_KEY` | https://build.nvidia.com 에서 발급한 키 | (필수) |
| `NVIDIA_BASE_URL` | API 베이스 URL | `https://integrate.api.nvidia.com/v1` |
| `NVIDIA_MODEL` | 기본 모델 ID | `meta/llama-3.3-70b-instruct` |

## 사용법

```bash
# 엔드포인트 연결 및 사용 가능한 모델 확인
python3 -m briefive.cli models --filter llama

# 원고에 달릴 법한 댓글 6개 생성
python3 -m briefive.cli comments 우리아이자립펀드_블로그원고.html -n 6 -t friendly

# 받은 댓글에 대한 답글 초안
python3 -m briefive.cli reply 우리아이자립펀드_블로그원고.html \
  -c "신청은 언제부터 가능한가요?" -c "소득 기준이 헷갈려요"

# 임의 프롬프트 질의 (스트리밍)
python3 -m briefive.cli ask "우리아이자립펀드를 한 문장으로 요약해줘" --stream

# API 호출 없이 프롬프트만 확인
python3 -m briefive.cli comments 우리아이자립펀드_블로그원고.html --dry-run
```

공통 옵션: `--model`, `--base-url`, `--json`.
댓글 어조(`-t`)는 `friendly` / `curious` / `grateful` / `mixed` 중에서 고릅니다.

## 구조

| 파일 | 역할 |
| --- | --- |
| `briefive/nvidia_client.py` | `/chat/completions`, `/models` 호출. 재시도·SSE 스트리밍 포함 |
| `briefive/manuscript.py` | 원고 HTML에서 제목과 「▼ 여기부터 복사 ▼」 구간 본문 추출 |
| `briefive/comments.py` | 프롬프트 구성, 응답 JSON 파싱, 댓글·답글 생성 |
| `briefive/cli.py` | 커맨드라인 진입점 |

## 파이썬에서 직접 쓰기

```python
from briefive import manuscript
from briefive.comments import generate_comments
from briefive.nvidia_client import NvidiaClient

client = NvidiaClient.from_env()
doc = manuscript.load("우리아이자립펀드_블로그원고.html")
for c in generate_comments(client, doc, count=5, tone="curious"):
    print(f"({c.persona}) {c.text}")
```

## 테스트

```bash
python3 -m unittest discover -s tests -t .
```

테스트는 HTTP 계층을 스텁으로 대체하므로 API 키 없이 실행됩니다.

## 참고

- 생성된 댓글·답글은 **초안**입니다. 사실관계(금액·시행 시기 등)는 원고와 공식 자료로 확인한 뒤 사용하세요.
- 모델 응답이 JSON 형식을 벗어나면 `NvidiaAPIError` 가 발생합니다. 온도를 낮추거나 다른 모델을 지정해 보세요.
