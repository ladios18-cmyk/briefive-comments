import io
import json
import unittest

from briefive.nvidia_client import DEFAULT_BASE_URL, ChatMessage, NvidiaAPIError, NvidiaClient


class FakeResponse(io.BytesIO):
    """with 문과 이터레이션을 지원하는 최소 응답 객체."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False


class StubClient(NvidiaClient):
    """_urlopen 만 바꿔치기해 네트워크 없이 동작을 검증한다."""

    def __init__(self, payload, **kwargs):
        super().__init__(api_key="test-key", **kwargs)
        self._payload = payload
        self.requests = []

    def _urlopen(self, request):
        self.requests.append(request)
        body = self._payload
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        return FakeResponse(body)


def chat_payload(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class ClientTest(unittest.TestCase):
    def test_requires_api_key(self):
        with self.assertRaises(NvidiaAPIError):
            NvidiaClient(api_key="")

    def test_chat_returns_message_content(self):
        client = StubClient(chat_payload("안녕하세요"))
        self.assertEqual(client.chat([ChatMessage("user", "hi")]), "안녕하세요")

    def test_chat_request_shape(self):
        client = StubClient(chat_payload("ok"), model="meta/llama-3.3-70b-instruct")
        client.chat([{"role": "user", "content": "hi"}], temperature=0.3)
        request = client.requests[0]

        self.assertEqual(request.full_url, f"{DEFAULT_BASE_URL}/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")

        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "meta/llama-3.3-70b-instruct")
        self.assertEqual(body["messages"], [{"role": "user", "content": "hi"}])
        self.assertEqual(body["temperature"], 0.3)
        self.assertFalse(body["stream"])

    def test_base_url_trailing_slash_is_normalized(self):
        client = StubClient(chat_payload("ok"), base_url=f"{DEFAULT_BASE_URL}/")
        client.chat([ChatMessage("user", "hi")])
        self.assertEqual(client.requests[0].full_url, f"{DEFAULT_BASE_URL}/chat/completions")

    def test_empty_choices_raise(self):
        with self.assertRaises(NvidiaAPIError):
            StubClient({"choices": []}).chat([ChatMessage("user", "hi")])

    def test_list_models(self):
        client = StubClient({"data": [{"id": "meta/llama-3.3-70b-instruct"}]})
        self.assertEqual(client.list_models()[0]["id"], "meta/llama-3.3-70b-instruct")
        self.assertEqual(client.requests[0].get_method(), "GET")

    def test_stream_chat_parses_sse(self):
        stream = (
            'data: {"choices":[{"delta":{"content":"안"}}]}\n'
            "\n"
            'data: {"choices":[{"delta":{"content":"녕"}}]}\n'
            "data: [DONE]\n"
        ).encode("utf-8")
        client = StubClient(stream)
        self.assertEqual("".join(client.stream_chat([ChatMessage("user", "hi")])), "안녕")


if __name__ == "__main__":
    unittest.main()
