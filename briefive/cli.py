"""briefive-comments 커맨드라인 도구.

사용 예:
    export NVIDIA_API_KEY=nvapi-...
    python3 -m briefive.cli models
    python3 -m briefive.cli comments 우리아이자립펀드_블로그원고.html -n 6
    python3 -m briefive.cli reply 우리아이자립펀드_블로그원고.html -c "신청은 언제부터인가요?"
    python3 -m briefive.cli ask "우리아이자립펀드 한 줄 요약" --stream
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from . import comments as comments_mod
from . import manuscript as manuscript_mod
from .nvidia_client import ChatMessage, NvidiaAPIError, NvidiaClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="briefive",
        description="NVIDIA NIM(integrate.api.nvidia.com) 기반 블로그 댓글 도구",
    )
    parser.add_argument("--model", help="사용할 모델 ID (기본: NVIDIA_MODEL 환경변수)")
    parser.add_argument("--base-url", help="API 베이스 URL (기본: NVIDIA_BASE_URL 환경변수)")
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    sub = parser.add_subparsers(dest="command", required=True)

    p_models = sub.add_parser("models", help="엔드포인트에서 사용 가능한 모델 목록 조회")
    p_models.add_argument("--filter", help="모델 ID 부분 문자열 필터")

    p_comments = sub.add_parser("comments", help="원고에 달릴 법한 댓글 생성")
    p_comments.add_argument("path", help="원고 HTML 경로")
    p_comments.add_argument("-n", "--count", type=int, default=5, help="생성할 댓글 수 (기본 5)")
    p_comments.add_argument(
        "-t", "--tone", choices=sorted(comments_mod.TONES), default="mixed", help="댓글 어조"
    )
    p_comments.add_argument("--temperature", type=float, default=0.9)
    p_comments.add_argument("--dry-run", action="store_true", help="API 호출 없이 프롬프트만 출력")

    p_reply = sub.add_parser("reply", help="받은 댓글에 대한 답글 초안 작성")
    p_reply.add_argument("path", help="원고 HTML 경로")
    p_reply.add_argument("-c", "--comment", action="append", default=[], help="답글을 달 댓글 (반복 가능)")
    p_reply.add_argument("--comments-file", help="댓글이 한 줄에 하나씩 든 텍스트 파일")
    p_reply.add_argument("--temperature", type=float, default=0.6)
    p_reply.add_argument("--dry-run", action="store_true", help="API 호출 없이 프롬프트만 출력")

    p_ask = sub.add_parser("ask", help="임의의 프롬프트를 모델에 그대로 질의")
    p_ask.add_argument("prompt", help="질의 내용")
    p_ask.add_argument("--system", help="시스템 프롬프트")
    p_ask.add_argument("--stream", action="store_true", help="스트리밍 출력")
    p_ask.add_argument("--temperature", type=float, default=0.7)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except NvidiaAPIError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"파일을 찾을 수 없습니다: {exc.filename}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    # --dry-run 은 API 키 없이도 동작해야 하므로 클라이언트 생성을 미룬다.
    if getattr(args, "dry_run", False):
        return _dry_run(args)

    client = NvidiaClient.from_env(model=args.model, base_url=args.base_url)

    if args.command == "models":
        return _cmd_models(client, args)
    if args.command == "comments":
        return _cmd_comments(client, args)
    if args.command == "reply":
        return _cmd_reply(client, args)
    if args.command == "ask":
        return _cmd_ask(client, args)
    raise AssertionError(f"알 수 없는 명령: {args.command}")


def _dry_run(args: argparse.Namespace) -> int:
    doc = manuscript_mod.load(args.path)
    if args.command == "comments":
        messages = comments_mod.build_comment_prompt(doc, args.count, args.tone)
    else:
        messages = comments_mod.build_reply_prompt(doc, _collect_comments(args))
    for message in messages:
        print(f"--- {message.role} ---\n{message.content}\n")
    return 0


def _cmd_models(client: NvidiaClient, args: argparse.Namespace) -> int:
    models = client.list_models()
    if args.filter:
        needle = args.filter.lower()
        models = [m for m in models if needle in str(m.get("id", "")).lower()]
    if args.json:
        _print_json(models)
        return 0
    for model in sorted(models, key=lambda m: str(m.get("id", ""))):
        print(model.get("id", "<unknown>"))
    print(f"\n총 {len(models)}개", file=sys.stderr)
    return 0


def _cmd_comments(client: NvidiaClient, args: argparse.Namespace) -> int:
    doc = manuscript_mod.load(args.path)
    results = comments_mod.generate_comments(
        client,
        doc,
        count=args.count,
        tone=args.tone,
        temperature=args.temperature,
        model=args.model,
    )
    if args.json:
        _print_json([c.to_dict() for c in results])
        return 0
    print(f"# {doc.title} — 댓글 {len(results)}개\n")
    for index, comment in enumerate(results, start=1):
        print(f"{index}. ({comment.persona}) {comment.text}")
    return 0


def _cmd_reply(client: NvidiaClient, args: argparse.Namespace) -> int:
    doc = manuscript_mod.load(args.path)
    incoming = _collect_comments(args)
    if not incoming:
        print("답글을 달 댓글이 없습니다. -c 또는 --comments-file 을 사용하세요.", file=sys.stderr)
        return 2
    results = comments_mod.draft_replies(
        client, doc, incoming, temperature=args.temperature, model=args.model
    )
    if args.json:
        _print_json([r.to_dict() for r in results])
        return 0
    for index, item in enumerate(results, start=1):
        print(f"{index}. 댓글: {item.comment}\n   답글: {item.reply}\n")
    return 0


def _cmd_ask(client: NvidiaClient, args: argparse.Namespace) -> int:
    messages = []
    if args.system:
        messages.append(ChatMessage("system", args.system))
    messages.append(ChatMessage("user", args.prompt))

    if args.stream:
        for piece in client.stream_chat(messages, model=args.model, temperature=args.temperature):
            print(piece, end="", flush=True)
        print()
        return 0

    answer = client.chat(messages, model=args.model, temperature=args.temperature)
    if args.json:
        _print_json({"answer": answer})
    else:
        print(answer)
    return 0


def _collect_comments(args: argparse.Namespace) -> list[str]:
    collected = list(args.comment)
    if getattr(args, "comments_file", None):
        with open(args.comments_file, encoding="utf-8") as handle:
            collected.extend(line.strip() for line in handle if line.strip())
    return collected


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
