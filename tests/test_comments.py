import json
import unittest
from pathlib import Path

from briefive import comments
from briefive.manuscript import Manuscript
from briefive.nvidia_client import NvidiaAPIError, NvidiaClient

DOC = Manuscript(path=Path("doc.html"), title="테스트 원고", body="본문 내용입니다.")


class FakeClient(NvidiaClient):
    def __init__(self, response: str):
        super().__init__(api_key="test-key")
        self._response = response
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self._response


class ParseTest(unittest.TestCase):
    def test_plain_array(self):
        self.assertEqual(comments.parse_json_array('[{"a": 1}]'), [{"a": 1}])

    def test_code_fence(self):
        raw = '여기 있습니다:\n```json\n[{"a": 1}]\n```'
        self.assertEqual(comments.parse_json_array(raw), [{"a": 1}])

    def test_surrounding_prose(self):
        self.assertEqual(comments.parse_json_array('결과: [{"a": 1}] 끝'), [{"a": 1}])

    def test_non_array_raises(self):
        with self.assertRaises(NvidiaAPIError):
            comments.parse_json_array("배열이 없습니다")


class GenerateTest(unittest.TestCase):
    def test_generate_comments(self):
        payload = json.dumps(
            [
                {"persona": "예비맘", "text": "9월생이라 딱 대상이네요!"},
                {"persona": "직장인 아빠", "text": "소득 구간 표가 제일 도움됐어요."},
                {"persona": "빈 댓글", "text": "   "},
            ],
            ensure_ascii=False,
        )
        client = FakeClient(payload)
        result = comments.generate_comments(client, DOC, count=5, tone="friendly")

        self.assertEqual(len(result), 2)  # 빈 텍스트는 걸러진다
        self.assertEqual(result[0].persona, "예비맘")
        prompt = client.calls[0][0][1].content
        self.assertIn("테스트 원고", prompt)
        self.assertIn(comments.TONES["friendly"], prompt)

    def test_generate_comments_respects_count(self):
        payload = json.dumps([{"persona": "p", "text": f"댓글 {i}"} for i in range(8)])
        result = comments.generate_comments(FakeClient(payload), DOC, count=3)
        self.assertEqual(len(result), 3)

    def test_draft_replies(self):
        payload = json.dumps(
            [{"comment": "신청은 언제부터인가요?", "reply": "2027년 하반기 예정이에요."}],
            ensure_ascii=False,
        )
        result = comments.draft_replies(FakeClient(payload), DOC, ["신청은 언제부터인가요?"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].reply, "2027년 하반기 예정이에요.")

    def test_draft_replies_without_input_skips_api_call(self):
        client = FakeClient("[]")
        self.assertEqual(comments.draft_replies(client, DOC, ["  ", ""]), [])
        self.assertEqual(client.calls, [])

    def test_reply_falls_back_to_original_comment_text(self):
        payload = json.dumps([{"reply": "확인해서 알려드릴게요."}], ensure_ascii=False)
        result = comments.draft_replies(FakeClient(payload), DOC, ["언제 시작하나요?"])
        self.assertEqual(result[0].comment, "언제 시작하나요?")


if __name__ == "__main__":
    unittest.main()
