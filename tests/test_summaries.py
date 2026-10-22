from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pm.summaries import (
    AI,
    HUMAN,
    SummaryEntry,
    load_ai,
    load_human,
    parse_summary_blocks,
    render_ai_file,
    resolve,
    upsert_ai_summary,
)

HUMAN_DOC = """#+TITLE: 人工覆盖

* 卡片摘要覆盖
  说明文字

** session-aaa
   :PROPERTIES:
   :PM_SESSION: session-aaa
   :PM_SUMMARY_SOURCE: human
   :END:
   人工摘要 A

* 固定显示（pin）
  # 下面这条在别的小节里，也必须被认到
** session-bbb
   :PROPERTIES:
   :PM_SESSION: session-bbb
   :PM_SOURCE_INSTANCE: dsh-other
   :END:
   人工摘要 B
"""

AI_DOC = """#+TITLE: AI 生成的摘要

* 说明
  本文件由 pm summary set 维护

* AI 摘要
** session-aaa
   :PROPERTIES:
   :PM_IDENTITY: dsh-default/session-aaa
   :PM_SESSION: session-aaa
   :PM_SOURCE_INSTANCE: dsh-default
   :PM_SUMMARY_SOURCE: ai
   :PM_GENERATED_BY: test-model
   :PM_GENERATED_AT: 2026-10-10T12:00:00+0800
   :END:
   AI 摘要 A
"""


class ParseTest(unittest.TestCase):
    def test_human_entries_are_found_anywhere_in_file(self) -> None:
        found = parse_summary_blocks(HUMAN_DOC, source=HUMAN)
        self.assertEqual(found["dsh-default/session-aaa"].text, "人工摘要 A")
        self.assertEqual(found["dsh-other/session-bbb"].text, "人工摘要 B")

    def test_property_drawer_lines_are_not_treated_as_body(self) -> None:
        found = parse_summary_blocks(HUMAN_DOC, source=HUMAN)
        for entry in found.values():
            self.assertNotIn("PROPERTIES", entry.text)
            self.assertNotIn("PM_SESSION", entry.text)

    def test_ai_entry_keeps_provenance(self) -> None:
        found = parse_summary_blocks(AI_DOC, source=AI)
        entry = found["dsh-default/session-aaa"]
        self.assertEqual(entry.source, AI)
        self.assertEqual(entry.generated_by, "test-model")
        self.assertEqual(entry.generated_at, "2026-10-10T12:00:00+0800")

    def test_block_without_session_is_ignored(self) -> None:
        doc = "* 说明\n** 随便写点什么\n   正文\n"
        self.assertEqual(parse_summary_blocks(doc, source=HUMAN), {})

    def test_commented_example_is_ignored(self) -> None:
        doc = "* x\n# ** session-xxx\n#    :PM_SESSION: session-xxx\n#    摘要\n"
        self.assertEqual(parse_summary_blocks(doc, source=HUMAN), {})


class PrecedenceTest(unittest.TestCase):
    def test_human_wins_over_ai(self) -> None:
        human = {"k": SummaryEntry("k", "人工", HUMAN)}
        ai = {"k": SummaryEntry("k", "AI", AI)}
        chosen = resolve("k", human, ai)
        assert chosen is not None
        self.assertEqual(chosen.text, "人工")

    def test_ai_used_when_no_human(self) -> None:
        ai = {"k": SummaryEntry("k", "AI", AI)}
        chosen = resolve("k", {}, ai)
        assert chosen is not None
        self.assertEqual(chosen.source, AI)

    def test_none_when_absent(self) -> None:
        self.assertIsNone(resolve("k", {}, {}))


class RoundTripTest(unittest.TestCase):
    def test_upsert_then_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upsert_ai_summary(root, identity_key="dsh-default/session-a", text="一条摘要", model="m")
            upsert_ai_summary(root, identity_key="dsh-default/session-b", text="另一条", model="m")
            found = load_ai(root)
            self.assertEqual(sorted(found), ["dsh-default/session-a", "dsh-default/session-b"])
            self.assertEqual(found["dsh-default/session-a"].text, "一条摘要")
            self.assertEqual(found["dsh-default/session-a"].generated_by, "m")

    def test_upsert_is_idempotent_for_same_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = upsert_ai_summary(root, identity_key="dsh-default/s", text="t", model="m")
            text_a = first.read_text(encoding="utf-8")
            second = upsert_ai_summary(root, identity_key="dsh-default/s", text="t", model="m")
            self.assertEqual(text_a, second.read_text(encoding="utf-8"))

    def test_whitespace_is_collapsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upsert_ai_summary(root, identity_key="dsh-default/s", text="  多   空格\n换行  ")
            self.assertEqual(load_ai(root)["dsh-default/s"].text, "多 空格 换行")

    def test_missing_files_are_not_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_human(Path(tmp)), {})
            self.assertEqual(load_ai(Path(tmp)), {})

    def test_render_ai_file_is_stable(self) -> None:
        entries = {
            "dsh-default/b": SummaryEntry("dsh-default/b", "B", AI),
            "dsh-default/a": SummaryEntry("dsh-default/a", "A", AI),
        }
        self.assertEqual(render_ai_file(entries), render_ai_file(dict(reversed(list(entries.items())))))


if __name__ == "__main__":
    unittest.main()
