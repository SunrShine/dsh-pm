"""inbox v2 解析：稳定 ID / status / 文本无损（设计 §5.1、§9、§11）。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pm.inbox import LEGACY_STATUS, parse_entries, read_inbox
from pm.mcp import capture_block

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 12, 10, 45, 0, tzinfo=TZ)
ID = "inbox-01M4Q0000000000000000000AA"


def doc_for(text: str, **kwargs: object) -> str:
    return "* Inbox\n  随手记\n\n" + capture_block(text, inbox_id=ID, now=NOW, **kwargs) + "\n"


class InboxV2Test(unittest.TestCase):
    def test_multiline_text_roundtrips_losslessly(self) -> None:
        text = "第一行 * 敏感 | 字符\n第二行\n\n第四行 中文 ✓"
        entries = parse_entries(doc_for(text))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["text"], text, "多行 / 中文 / org 敏感字符必须无损取回")
        self.assertEqual(entries[0]["id"], ID)
        self.assertEqual(entries[0]["status"], "CAPTURED")

    def test_single_line_is_stored_exactly_once(self) -> None:
        doc = doc_for("只有一行")
        entries = parse_entries(doc)
        self.assertEqual(entries[0]["text"], "只有一行")
        self.assertEqual(doc.count("只有一行"), 1, "标题与正文不得重复同一段文本")

    def test_first_line_in_headline_rest_in_body(self) -> None:
        doc = doc_for("标题行\n正文一\n正文二")
        lines = doc.split("\n")
        self.assertIn("** INBOX 标题行", lines)
        self.assertIn("   正文一", lines)
        self.assertIn("   正文二", lines)

    def test_following_bullet_is_not_absorbed_into_body(self) -> None:
        doc = doc_for("一条 capture") + "\n- 人工写的条目\n"
        entries = parse_entries(doc)
        self.assertEqual([e["text"] for e in entries], ["一条 capture", "人工写的条目"])
        self.assertEqual(entries[0]["id"], ID)
        self.assertIsNone(entries[1]["id"])
        self.assertEqual(entries[1]["status"], LEGACY_STATUS)

    def test_status_property_is_honoured(self) -> None:
        doc = (
            "* Inbox\n** INBOX 分流过的\n"
            "   :ID: inbox-X\n   :PM_STATUS: TRIAGE\n   :END:\n   正文\n"
        )
        entries = parse_entries(doc)
        self.assertEqual(entries[0]["id"], "inbox-X")
        self.assertEqual(entries[0]["status"], "TRIAGE")
        self.assertEqual(entries[0]["text"], "分流过的\n正文")

    def test_title_mode_keeps_full_text_exactly_once(self) -> None:
        text = "正文第一行\n正文第二行"
        doc = doc_for(text, title="自定义标题")
        entries = parse_entries(doc)
        self.assertEqual(entries[0]["text"], text)
        self.assertEqual(doc.count("正文第一行"), 1)

    def test_legacy_headline_without_id(self) -> None:
        doc = "* Inbox\n** 旧标题\n   :PM_SOURCE: ai\n   :END:\n   旧正文\n"
        self.assertEqual(
            parse_entries(doc),
            [{"text": "旧标题", "line": 2, "id": None, "status": LEGACY_STATUS, "capturedAt": None, "source": "ai", "projectHint": None, "annotationCount": None, "revisionCount": None, "lastAnnotationText": None, "pinned": False}],
        )

    def test_read_inbox_shape_unchanged_with_new_entry_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inbox.org").write_text(doc_for("一条"), encoding="utf-8")
            payload = read_inbox(root)
        assert payload is not None
        self.assertEqual(set(payload), {"path", "count", "entries"})
        self.assertEqual(
            set(payload["entries"][0]),
            {
                "text", "line", "id", "status", "capturedAt", "source", "projectHint",
                "annotationCount", "revisionCount", "lastAnnotationText", "pinned",
            },
        )
        self.assertEqual(payload["count"], 1)


    def test_entry_exposes_capture_metadata(self) -> None:
        doc = doc_for("带元数据", project_hint="demo")
        entry = parse_entries(doc)[0]
        self.assertEqual(entry["capturedAt"], NOW.isoformat(timespec="seconds"))
        self.assertEqual(entry["source"], "cli")
        self.assertEqual(entry["projectHint"], "demo")
        self.assertEqual(entry["annotationCount"], 0, "没有补充就是 0（与旧条目的 null 可区分）")
        self.assertEqual(entry["revisionCount"], 0)
        self.assertIsNone(entry["lastAnnotationText"])
        self.assertIs(entry["pinned"], False, "缺 :PM_PIN: = False（不是 null）")
        self.assertNotIn("annotations", entry, "ui-cards 投影保持精简")

    def test_legacy_entries_have_null_metadata(self) -> None:
        doc = "* Inbox\n\n- 旧列表项\n** 旧标题\n   旧正文\n"
        for entry in parse_entries(doc):
            self.assertIsNone(entry["capturedAt"], entry)
            self.assertIsNone(entry["source"], entry)
            self.assertIsNone(entry["projectHint"], entry)


if __name__ == "__main__":
    unittest.main()
