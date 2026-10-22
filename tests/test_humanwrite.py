from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pm.humanwrite import append_entry, append_under, entry_block, find_section


DOC = """* Inbox
  说明文字

- 用户自己写的一条

* 别的组
  另一个小节的内容
"""


class FindSectionTest(unittest.TestCase):
    def test_locates_section_bounds(self) -> None:
        lines = DOC.split("\n")
        span = find_section(lines, "Inbox")
        assert span is not None
        self.assertEqual(lines[span[0]], "* Inbox")
        self.assertEqual(lines[span[1]], "* 别的组")

    def test_last_section_ends_at_eof(self) -> None:
        span = find_section(DOC.split("\n"), "别的组")
        assert span is not None
        self.assertEqual(span[1], len(DOC.split("\n")))

    def test_missing_returns_none(self) -> None:
        self.assertIsNone(find_section(DOC.split("\n"), "不存在"))


class AppendUnderTest(unittest.TestCase):
    def test_inserts_at_section_end_not_file_end(self) -> None:
        block = "** 新条目\n   正文"
        out, found = append_under(DOC, headline="Inbox", block=block)
        self.assertTrue(found)
        lines = out.split("\n")
        # 新条目必须落在 * Inbox 与 * 别的组 之间
        self.assertLess(lines.index("** 新条目"), lines.index("* 别的组"))

    def test_preserves_existing_content(self) -> None:
        out, _ = append_under(DOC, headline="Inbox", block="** 新条目\n   正文")
        self.assertIn("- 用户自己写的一条", out)
        self.assertIn("另一个小节的内容", out)

    def test_missing_section_appends_to_end_but_still_only_appends(self) -> None:
        out, found = append_under(DOC, headline="不存在", block="** 新条目")
        self.assertFalse(found)
        self.assertIn("- 用户自己写的一条", out)
        self.assertTrue(out.rstrip().endswith("** 新条目"))

    def test_is_idempotent_in_shape(self) -> None:
        once, _ = append_under(DOC, headline="Inbox", block="** A")
        twice, _ = append_under(once, headline="Inbox", block="** B")
        self.assertIn("** A", twice)
        self.assertIn("** B", twice)
        self.assertLess(twice.split("\n").index("** A"), twice.split("\n").index("** B"))


class EntryBlockTest(unittest.TestCase):
    def test_builds_headline_drawer_and_body(self) -> None:
        block = entry_block("正文", title="标题", todo="TODO", properties={"PM_SOURCE": "ai"})
        self.assertIn("** TODO 标题", block)
        self.assertIn(":PM_SOURCE: ai", block)
        self.assertIn("   正文", block)

    def test_sanitizes_newlines_in_values(self) -> None:
        block = entry_block("x", title="a\nb", properties={"K": "v\nw"})
        self.assertEqual(len(block.split("\n")), 5)


class AppendEntryFileTest(unittest.TestCase):
    def test_creates_missing_file_with_headline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.org"
            append_entry(path, headline="任务", block="** 新任务")
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("* 任务"))
            self.assertIn("** 新任务", text)

    def test_appends_without_touching_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inbox.org"
            path.write_text(DOC, encoding="utf-8")
            append_entry(path, headline="Inbox", block="** 新条目")
            text = path.read_text(encoding="utf-8")
            self.assertIn("- 用户自己写的一条", text)
            self.assertIn("** 新条目", text)

    def test_preserves_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inbox.org"
            path.write_bytes(DOC.replace("\n", "\r\n").encode("utf-8"))
            append_entry(path, headline="Inbox", block="** 新条目")
            self.assertIn(b"\r\n", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
