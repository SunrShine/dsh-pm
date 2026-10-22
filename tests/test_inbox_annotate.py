"""inbox 补充（annotate）/ 修订（edit）/ 历史（history）—— 契约 内部记录/09 §0 §1 §2。

口径：原文只读 + 追加式补充 + 显式修订（记旧值）；都不改状态、不按行号处理 LEGACY。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from pm import cli
from pm import inbox as inbox_module

import fixtures

ORIGINAL = "随手记录再记录的时候只有一句话"
EDITED = "随手记录在记录的时候只有一句话"


class InboxAnnotateBaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.library = self.base / "wm"
        self.library.mkdir()
        self.config = self.base / "pm.toml"
        self.config.write_text('library = "' + str(self.library) + '"\n', encoding="utf-8")
        self.inbox = self.library / "inbox.org"

    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def pm(self, *argv: str) -> tuple[int, str, str]:
        return self.run_cli(["--config", str(self.config), *argv])

    def ok(self, *argv: str) -> dict:
        code, stdout, stderr = self.pm(*argv)
        self.assertEqual(code, 0, "命令失败 %r: %s" % (list(argv), stderr))
        return json.loads(stdout)

    def seed(self, text: str = ORIGINAL) -> str:
        return self.ok("capture", text, "--json")["inboxId"]

    def sha(self) -> str:
        return hashlib.sha256(self.inbox.read_bytes()).hexdigest()

    def entry_text(self, inbox_id: str) -> str:
        payload = self.ok("inbox", "list", "--json")
        return next(row for row in payload["entries"] if row["id"] == inbox_id)["text"]


class AnnotateTest(InboxAnnotateBaseTest):
    def test_appends_block_and_audit_without_touching_original(self) -> None:
        inbox_id = self.seed()
        payload = self.ok(
            "inbox", "annotate", inbox_id,
            "--text", "回顾时补充第一行\n补充第二行",
            "--actor", "human", "--expected-revision", "1", "--json",
        )
        for key in ("entityId", "revision", "source", "observedAt", "auditEventId"):
            self.assertIn(key, payload)
        self.assertEqual(payload["op"], "annotate")
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["status"], "CAPTURED", "补充不改状态")
        self.assertEqual(payload["previousStatus"], "CAPTURED")

        text = self.inbox.read_text(encoding="utf-8")
        self.assertIn("** INBOX " + ORIGINAL, text, "原文 headline 不动")
        self.assertIn("补充 [", text)
        self.assertIn("actor=human rev=2", text)
        self.assertIn("   补充 [", text, "补充块 3 空格缩进")
        self.assertIn("   回顾时补充第一行", text)
        self.assertIn("   补充第二行", text)
        self.assertIn("op=annotate", text)
        self.assertIn("audit=" + payload["auditEventId"], text)
        self.assertEqual(text.count(":LOGBOOK:"), 1, "LOGBOOK 只能有一个")
        # 补充内容不复制进任务/记忆
        self.assertFalse((self.library / "projects").exists())
        # 条目 text 仍是原文（补充走 history）
        self.assertEqual(self.entry_text(inbox_id), ORIGINAL)

    def test_requires_text(self) -> None:
        inbox_id = self.seed()
        before = self.sha()
        code, stdout, _ = self.pm(
            "inbox", "annotate", inbox_id, "--text", "   ", "--expected-revision", "1", "--json"
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "REQUIRED_TEXT")
        self.assertEqual(self.sha(), before)

    def test_legacy_entry_rejected(self) -> None:
        self.inbox.write_text("#+TITLE: Inbox\n\n* Inbox\n\n- 旧条目\n", encoding="utf-8")
        before = self.sha()
        code, stdout, _ = self.pm(
            "inbox", "annotate", "inbox-nope", "--text", "x", "--expected-revision", "1", "--json"
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "LEGACY_UNTRACKED")
        self.assertEqual(self.sha(), before)

    def test_conflict_exit_3_and_unchanged(self) -> None:
        inbox_id = self.seed()
        before = self.sha()
        code, stdout, _ = self.pm(
            "inbox", "annotate", inbox_id, "--text", "x", "--expected-revision", "9", "--json"
        )
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(stdout)["error"]["code"], "REVISION_CONFLICT")
        self.assertEqual(self.sha(), before)

    def test_dry_run_writes_nothing(self) -> None:
        inbox_id = self.seed()
        before = self.sha()
        payload = self.ok(
            "inbox", "annotate", inbox_id, "--text", "预演补充",
            "--expected-revision", "1", "--dry-run", "--json",
        )
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(self.sha(), before)
        self.assertNotIn("预演补充", self.inbox.read_text(encoding="utf-8"))

    def test_idempotency_key(self) -> None:
        inbox_id = self.seed()
        first = self.ok(
            "inbox", "annotate", inbox_id, "--text", "补充一次",
            "--expected-revision", "1", "--idempotency-key", "an-1", "--json",
        )
        after = self.sha()
        replay = self.ok(
            "inbox", "annotate", inbox_id, "--text", "补充一次",
            "--expected-revision", "2", "--idempotency-key", "an-1", "--json",
        )
        self.assertTrue(replay["idempotent"])
        self.assertEqual(replay["auditEventId"], first["auditEventId"])
        self.assertEqual(self.sha(), after)
        self.assertEqual(self.inbox.read_text(encoding="utf-8").count("补充一次"), 1)


class EditTest(InboxAnnotateBaseTest):
    def test_rewrites_headline_and_keeps_old_value(self) -> None:
        inbox_id = self.seed()
        payload = self.ok(
            "inbox", "edit", inbox_id,
            "--text", EDITED, "--reason", "原文有错别字",
            "--actor", "human", "--expected-revision", "1", "--json",
        )
        self.assertEqual(payload["op"], "edit")
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["status"], "CAPTURED", "修订不改状态")

        text = self.inbox.read_text(encoding="utf-8")
        self.assertIn("** INBOX " + EDITED, text)
        self.assertNotIn("** INBOX " + ORIGINAL, text)
        # 旧值逐字留在条目里
        self.assertIn("   修订 [", text)
        self.assertIn("   原因：原文有错别字", text)
        self.assertIn("   旧值：" + ORIGINAL, text)
        self.assertIn("   新值：" + EDITED, text)
        # 审计
        self.assertIn("op=edit", text)
        self.assertIn("oldText=" + ORIGINAL.replace(" ", " "), text)
        self.assertIn("newText=" + EDITED, text)
        self.assertIn("oldsha=" + hashlib.sha256(ORIGINAL.encode()).hexdigest()[:12], text)
        self.assertIn("oldlen=" + str(len(ORIGINAL)), text)
        self.assertIn("audit=" + payload["auditEventId"], text)
        self.assertEqual(self.entry_text(inbox_id), EDITED)

    def test_requires_reason(self) -> None:
        inbox_id = self.seed()
        before = self.sha()
        code, stdout, _ = self.pm(
            "inbox", "edit", inbox_id, "--text", EDITED,
            "--expected-revision", "1", "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "REASON_REQUIRED")
        self.assertEqual(self.sha(), before)

    def test_rejects_multiline_text(self) -> None:
        inbox_id = self.seed()
        before = self.sha()
        code, stdout, _ = self.pm(
            "inbox", "edit", inbox_id, "--text", "第一行\n第二行", "--reason", "r",
            "--expected-revision", "1", "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "INVALID_HEADLINE")
        self.assertEqual(self.sha(), before)

    def test_legacy_entry_rejected(self) -> None:
        self.inbox.write_text("#+TITLE: Inbox\n\n* Inbox\n\n- 旧条目\n", encoding="utf-8")
        before = self.sha()
        code, stdout, _ = self.pm(
            "inbox", "edit", "inbox-nope", "--text", "x", "--reason", "r",
            "--expected-revision", "1", "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "LEGACY_UNTRACKED")
        self.assertEqual(self.sha(), before)

    def test_conflict_exit_3_and_unchanged(self) -> None:
        inbox_id = self.seed()
        before = self.sha()
        code, _stdout, _ = self.pm(
            "inbox", "edit", inbox_id, "--text", EDITED, "--reason", "r",
            "--expected-revision", "5", "--json",
        )
        self.assertEqual(code, 3)
        self.assertEqual(self.sha(), before)


class AppendPlacementTest(InboxAnnotateBaseTest):
    """回归：追加块不能被顶到条目尾部空行之后（真机第一次 annotate 就踩到了）。"""

    def lines(self) -> list[str]:
        return self.inbox.read_text(encoding="utf-8").splitlines()

    def marker_index(self) -> int:
        for index, line in enumerate(self.lines()):
            if line.strip().startswith("补充 ["):
                return index
        self.fail("没有找到补充块")

    def test_entry_followed_by_blanks_then_eof(self) -> None:
        inbox_id = self.seed()
        with self.inbox.open("a", encoding="utf-8") as handle:
            handle.write("\n" * 4)  # 条目尾部 4 个空行（真机的样子）
        self.ok("inbox", "annotate", inbox_id, "--text", "补充内容",
                "--expected-revision", "1", "--json")

        lines = self.lines()
        index = self.marker_index()
        self.assertTrue(lines[index - 1].strip(), "补充块前面必须是内容行，不能是空行")
        self.assertTrue(lines[index - 1].strip().startswith(":END:"), lines[index - 1])
        self.assertEqual(lines[index + 1], "   补充内容")
        self.assertEqual(self.inbox.read_text(encoding="utf-8").count(":LOGBOOK:"), 1)
        # 解析仍然正确：原文不变，补充进 history
        self.assertEqual(self.entry_text(inbox_id), ORIGINAL)
        payload = self.ok("inbox", "history", inbox_id, "--json")
        self.assertEqual([row["text"] for row in payload["annotations"]], ["补充内容"])

    def test_entry_followed_by_blanks_then_next_entry(self) -> None:
        first = self.seed("第一条原文")
        with self.inbox.open("a", encoding="utf-8") as handle:
            handle.write("\n" * 4)
        second = self.seed("第二条原文")  # capture 追加在小节末尾，落在空行之后

        # 写入前：第一条内容结束后的所有行（空行 + 第二条），必须原样留在追加块之后
        before_lines = self.lines()
        second_line = before_lines.index("** INBOX 第二条原文")
        content_end = max(i for i in range(second_line) if before_lines[i].strip())
        tail_before = before_lines[content_end + 1 :]
        self.assertTrue(tail_before[0].strip() == "", "第二条之前应当有空行分隔")

        before_second = self.entry_text(second)
        self.ok("inbox", "annotate", first, "--text", "给第一条的补充",
                "--expected-revision", "1", "--json")

        lines = self.lines()
        index = self.marker_index()
        self.assertEqual(lines[index - 1], before_lines[content_end], "插在最后一行内容之后")
        self.assertTrue(lines[index - 1].strip().startswith(":END:"), lines[index - 1])
        self.assertEqual(lines[index + 1], "   给第一条的补充")
        self.assertEqual(lines[index + 2 :], tail_before, "空行与下一条必须原样留在块之后")
        self.assertEqual(self.inbox.read_text(encoding="utf-8").count(":LOGBOOK:"), 2)
        # 另一条没被动过
        self.assertEqual(self.entry_text(second), before_second)
        second_payload = self.ok("inbox", "history", second, "--json")
        self.assertEqual(second_payload["annotations"], [])
        self.assertEqual(second_payload["revision"], 1)

    def test_insert_after_last_body_line_not_before_it(self) -> None:
        inbox_id = self.seed("标题行\n正文第一行\n正文第二行")
        with self.inbox.open("a", encoding="utf-8") as handle:
            handle.write("\n" * 3)
        self.ok("inbox", "annotate", inbox_id, "--text", "补充",
                "--expected-revision", "1", "--json")

        lines = self.lines()
        index = self.marker_index()
        self.assertEqual(lines[index - 1], "   正文第二行", "必须插在最后一行正文之后")
        self.assertEqual(lines[index - 2], "   正文第一行")
        payload = self.ok("inbox", "history", inbox_id, "--json")
        self.assertEqual(payload["text"], "标题行\n正文第一行\n正文第二行")

    def test_edit_block_placement_after_blanks(self) -> None:
        inbox_id = self.seed()
        with self.inbox.open("a", encoding="utf-8") as handle:
            handle.write("\n" * 3)
        self.ok("inbox", "edit", inbox_id, "--text", EDITED, "--reason", "修一下",
                "--expected-revision", "1", "--json")

        lines = self.lines()
        marker = next(i for i, line in enumerate(lines) if line.strip().startswith("修订 ["))
        self.assertTrue(lines[marker - 1].strip().startswith(":END:"), lines[marker - 1])
        self.assertEqual(lines[marker + 1], "   原因：修一下")
        self.assertEqual(self.inbox.read_text(encoding="utf-8").count(":LOGBOOK:"), 1)


class HistoryTest(InboxAnnotateBaseTest):
    def test_history_shape_and_order(self) -> None:
        inbox_id = self.seed("第一行原文\n第二行原文")
        self.ok("inbox", "annotate", inbox_id, "--text", "补充内容",
                "--expected-revision", "1", "--json")
        self.ok("inbox", "edit", inbox_id, "--text", EDITED, "--reason", "改一下",
                "--expected-revision", "2", "--json")

        payload = self.ok("inbox", "history", inbox_id, "--json")
        self.assertEqual(
            set(payload), {"ok", "id", "revision", "status", "text", "annotations", "revisions"}
        )
        self.assertEqual(payload["id"], inbox_id)
        self.assertEqual(payload["revision"], 3)
        self.assertEqual(payload["status"], "CAPTURED")
        self.assertEqual(payload["text"], EDITED + "\n第二行原文", "原文 = 当前 headline + 未改的正文")
        self.assertEqual(len(payload["annotations"]), 1)
        self.assertEqual(len(payload["revisions"]), 1)
        annotation = payload["annotations"][0]
        self.assertEqual(set(annotation), {"at", "actor", "revision", "text"})
        self.assertEqual(annotation["actor"], "human")
        self.assertEqual(annotation["revision"], 2)
        self.assertEqual(annotation["text"], "补充内容")
        revision = payload["revisions"][0]
        self.assertEqual(
            set(revision), {"at", "actor", "revision", "reason", "oldText", "newText"}
        )
        self.assertEqual(revision["reason"], "改一下")
        self.assertEqual(revision["oldText"], "第一行原文")
        self.assertEqual(revision["newText"], EDITED)
        self.assertEqual(revision["revision"], 3)

    def test_history_is_read_only(self) -> None:
        inbox_id = self.seed()
        self.ok("inbox", "annotate", inbox_id, "--text", "补充", "--expected-revision", "1", "--json")
        before = self.sha()
        self.ok("inbox", "history", inbox_id, "--json")
        self.assertEqual(self.sha(), before)

    def test_history_unknown_and_legacy(self) -> None:
        self.seed()
        code, stdout, _ = self.pm("inbox", "history", "inbox-nope", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "NOT_FOUND")

        self.inbox.write_text("#+TITLE: Inbox\n\n* Inbox\n\n- 旧条目\n", encoding="utf-8")
        code, stdout, _ = self.pm("inbox", "history", "inbox-nope", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "LEGACY_UNTRACKED")


class RegistrationTest(unittest.TestCase):
    def test_inbox_subcommands_registered(self) -> None:
        import argparse

        parser = cli.build_parser()
        root = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)][0]
        inbox_parser = root.choices["inbox"]
        sub = [a for a in inbox_parser._actions if isinstance(a, argparse._SubParsersAction)][0]
        for name in ("annotate", "edit", "history"):
            self.assertIn(name, sub.choices)


class ListProjectionTest(InboxAnnotateBaseTest):
    """task-40：inbox list 的 entries[] 暴露补充/修订计数、最后一条补充与补充块全文。"""

    def rows(self) -> dict:
        payload = self.ok("inbox", "list", "--json")
        return {row["id"]: row for row in payload["entries"]}

    def stamp(self, value: str) -> None:
        self.assertIsInstance(value, str)
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2} \w{3} \d{2}:\d{2}$", value)

    def test_no_annotations_is_zero_not_null(self) -> None:
        inbox_id = self.seed()
        row = self.rows()[inbox_id]
        self.assertEqual(row["annotationCount"], 0)
        self.assertEqual(row["revisionCount"], 0)
        self.assertIsNone(row["lastAnnotationText"])
        self.assertEqual(row["annotations"], [])

    def test_single_annotation(self) -> None:
        inbox_id = self.seed()
        self.ok("inbox", "annotate", inbox_id, "--text", "唯一一条补充",
                "--expected-revision", "1", "--json")
        row = self.rows()[inbox_id]
        self.assertEqual(row["annotationCount"], 1)
        self.assertEqual(row["revisionCount"], 0)
        self.assertEqual(row["lastAnnotationText"], "唯一一条补充")
        self.assertEqual(len(row["annotations"]), 1)
        annotation = row["annotations"][0]
        self.assertEqual(set(annotation), {"at", "actor", "revision", "text"})
        self.assertEqual(annotation["actor"], "human")
        self.assertEqual(annotation["revision"], 2)
        self.assertEqual(annotation["text"], "唯一一条补充")
        self.stamp(annotation["at"])

    def test_multiple_annotations_and_revision_verbatim_order(self) -> None:
        inbox_id = self.seed()
        self.ok("inbox", "annotate", inbox_id, "--text", "第一条补充",
                "--expected-revision", "1", "--json")
        self.ok("inbox", "annotate", inbox_id, "--text", "第二条补充\n第二行原文",
                "--expected-revision", "2", "--json")
        self.ok("inbox", "edit", inbox_id, "--text", EDITED, "--reason", "插入一次修订",
                "--expected-revision", "3", "--json")
        self.ok("inbox", "annotate", inbox_id, "--text", "第三条补充",
                "--expected-revision", "4", "--json")

        row = self.rows()[inbox_id]
        self.assertEqual(row["annotationCount"], 3)
        self.assertEqual(row["revisionCount"], 1)
        self.assertEqual(row["lastAnnotationText"], "第三条补充")
        self.assertEqual(
            [item["text"] for item in row["annotations"]],
            ["第一条补充", "第二条补充\n第二行原文", "第三条补充"],
            "顺序按文件顺序，文本逐字一致",
        )
        self.assertEqual([item["revision"] for item in row["annotations"]], [2, 3, 5])

    def test_legacy_counts_are_null(self) -> None:
        self.inbox.write_text("#+TITLE: Inbox\n\n* Inbox\n\n- 旧条目\n", encoding="utf-8")
        legacy = self.ok("inbox", "list", "--json")["entries"][0]
        self.assertEqual(legacy["status"], "LEGACY_UNTRACKED")
        self.assertIsNone(legacy["annotationCount"], "旧条目是「不知道」，不能用 0 冒充")
        self.assertIsNone(legacy["revisionCount"])
        self.assertIsNone(legacy["lastAnnotationText"])
        self.assertEqual(legacy["annotations"], [])

        # 对照：新捕获、没有补充的条目是 0（可区分）
        fresh = self.seed("新的一条")
        row = self.rows()[fresh]
        self.assertEqual(row["annotationCount"], 0)
        self.assertIsNone(row["lastAnnotationText"])

    def test_next_entry_counters_not_contaminated(self) -> None:
        first = self.seed("第一条")
        second = self.seed("第二条")
        self.ok("inbox", "annotate", first, "--text", "只给第一条的补充",
                "--expected-revision", "1", "--json")
        rows = self.rows()
        self.assertEqual(rows[first]["annotationCount"], 1)
        self.assertEqual(rows[first]["lastAnnotationText"], "只给第一条的补充")
        self.assertEqual(rows[second]["annotationCount"], 0)
        self.assertEqual(rows[second]["annotations"], [])
        self.assertIsNone(rows[second]["lastAnnotationText"])
        self.assertEqual(rows[second]["revision"], 1, "另一条没被写过")

    def test_ui_cards_projection_stays_lean(self) -> None:
        inbox_id = self.seed()
        self.ok("inbox", "annotate", inbox_id, "--text", "补充内容",
                "--expected-revision", "1", "--json")
        payload = inbox_module.read_inbox(self.library)
        row = payload["entries"][0]
        self.assertEqual(row["annotationCount"], 1)
        self.assertEqual(row["revisionCount"], 0)
        self.assertEqual(row["lastAnnotationText"], "补充内容")
        self.assertNotIn("annotations", row, "ui-cards 的侧边栏投影不放大块全文")

    def test_ui_cards_cli_payload(self) -> None:
        home = fixtures.build_dsh_home(self.base / "dsh")
        config = self.base / "with_dsh.toml"
        config.write_text(
            fixtures.fixture_config_toml(library=str(self.library)).replace("REPLACED", str(home)),
            encoding="utf-8",
        )
        inbox_id = self.seed()
        self.ok("inbox", "annotate", inbox_id, "--text", "补充内容",
                "--expected-revision", "1", "--json")
        code, stdout, stderr = self.run_cli(
            ["--config", str(config), "ui-cards", "--dsh-home", str(home)]
        )
        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["schemaVersion"], "ui-cards-v1", "新增字段是增量的，不升版本")
        row = payload["inbox"]["entries"][0]
        self.assertEqual(row["annotationCount"], 1)
        self.assertEqual(row["lastAnnotationText"], "补充内容")
        self.assertNotIn("annotations", row)


if __name__ == "__main__":
    unittest.main()
