import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from briefive import manuscript

SAMPLE = """<!DOCTYPE html>
<html><head><title>테스트 원고</title><style>p { color: red; }</style></head>
<body>
  <div class="guide">
    <p>「▼ 여기부터 복사 ▼」 ~ 「▲ 여기까지 복사 ▲」 구간만 복사하세요.</p>
  </div>
  <div class="copyline">▼ 여기부터 복사 ▼</div>
  <p>첫 문단입니다.</p>
  <h2>소제목</h2>
  <p>둘째 문단입니다.</p>
  <div class="copyline">▲ 여기까지 복사 ▲</div>
  <p>발행하지 않는 꼬리말.</p>
</body></html>
"""


class ManuscriptTest(unittest.TestCase):
    def _load(self, html: str) -> manuscript.Manuscript:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.html"
            path.write_text(html, encoding="utf-8")
            return manuscript.load(path)

    def test_title_comes_from_title_tag(self):
        self.assertEqual(self._load(SAMPLE).title, "테스트 원고")

    def test_body_is_limited_to_copy_region(self):
        body = self._load(SAMPLE).body
        self.assertIn("첫 문단입니다.", body)
        self.assertIn("둘째 문단입니다.", body)
        self.assertNotIn("꼬리말", body)
        # 상단 사용법 안내의 표식 문구에 속아 빈 본문을 내놓으면 안 된다.
        self.assertNotIn("구간만 복사하세요", body)

    def test_style_and_script_are_dropped(self):
        self.assertNotIn("color: red", self._load(SAMPLE).body)

    def test_falls_back_to_whole_body_without_markers(self):
        body = self._load("<html><body><p>표식 없는 글</p></body></html>").body
        self.assertEqual(body, "표식 없는 글")

    def test_truncate_marks_elision(self):
        self.assertTrue(manuscript.truncate("가" * 50, 10).endswith("…(이하 생략)"))
        self.assertEqual(manuscript.truncate("짧은 글", 100), "짧은 글")


if __name__ == "__main__":
    unittest.main()
