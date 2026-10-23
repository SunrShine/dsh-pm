"""多文件 inbox（2026-10-22 用户设计）的后端测试。

真源按来源/周期轮转：
  inbox-human-<period>.org（默认 weekly） / inbox-ai-<period>.org（默认 monthly）
inbox.org 是生成视图（只读）；旧单文件由 pm inbox migrate 拆分。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from pm import inbox_files
from pm.mcp import capture_text

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 22, 19, 30, tzinfo=TZ)


def legacy_inbox() -> str:
    return (
        "#+TITLE: Inbox\n"
        "#+TODO: INBOX(i) TODO(t) | DONE(d!)\n"
        "\n"
        "* Inbox\n"
        "  人工随手记：整理时再变成项目任务。\n"
        "- 旧的手写 bullet 一条\n"
        "\n"
        "** INBOX 人类条目 A\n"
        "   :PROPERTIES:\n"
        "   :ID: inbox-manual-0001\n"
        "   :PM_KIND: inbox\n"
        "   :PM_STATUS: CAPTURED\n"
        "   :PM_SOURCE: cli\n"
        "   :PM_ADDED_BY: cli\n"
        "   :PM_CAPTURED_AT: 2026-10-20T10:00:00+08:00\n"
        "   :END:\n"
        "   人写的正文\n"
        "\n"
        "** INBOX AI 条目 B\n"
        "   :PROPERTIES:\n"
        "   :ID: inbox-ai-0002\n"
        "   :PM_KIND: inbox\n"
        "   :PM_STATUS: ARCHIVED\n"
        "   :PM_SOURCE: mcp\n"
        "   :PM_ADDED_BY: deepseek-v4.1-flash\n"
        "   :PM_CAPTURED_AT: 2026-10-02T09:00:00+08:00\n"
        "   :END:\n"
        "   AI 写的正文\n"
    )


class MultiFileLayoutTest(unittest.TestCase):
    def test_period_suffix_modes(self) -> None:
        self.assertEqual(inbox_files.period_suffix("weekly", NOW), "2026-W43")
        self.assertEqual(inbox_files.period_suffix("monthly", NOW), "2026-10")
        self.assertEqual(inbox_files.period_suffix("quarterly", NOW), "2026-Q4")
        self.assertEqual(inbox_files.period_suffix("yearly", NOW), "2026")
        self.assertEqual(inbox_files.period_suffix("single", NOW), "")
        self.assertTrue(inbox_files.period_suffix("per-entry", NOW).startswith("20261022-"))

    def test_human_and_ai_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            modes = inbox_files.InboxModes(human="weekly", ai="monthly")
            self.assertEqual(inbox_files.human_path(root, NOW, modes).name, "inbox-human-2026-W43.org")
            self.assertEqual(inbox_files.ai_path(root, NOW, modes).name, "inbox-ai-2026-10.org")
            single = inbox_files.InboxModes(human="single", ai="single")
            self.assertEqual(inbox_files.human_path(root, NOW, single).name, "inbox.org")
            self.assertEqual(inbox_files.ai_path(root, NOW, single).name, "inbox.org")


class MultiFileCaptureTest(unittest.TestCase):
    def test_capture_routes_human_and_ai_and_writes_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            modes = inbox_files.InboxModes(human="weekly", ai="monthly")
            human = capture_text(root, "人工记录", source="cli", model="cli",
                                 now=NOW, inbox_modes=modes)
            ai = capture_text(root, "AI 记录", source="mcp", model="deepseek",
                              now=NOW, inbox_modes=modes)
            self.assertEqual(human.path.name, "inbox-human-2026-W43.org")
            self.assertEqual(ai.path.name, "inbox-ai-2026-10.org")
            human_text = human.path.read_text(encoding="utf-8")
            self.assertIn("手动条目模板", human_text)
            self.assertIn("人工记录", human_text)
            ai_text = ai.path.read_text(encoding="utf-8")
            self.assertIn("不要手改", ai_text)
            self.assertIn("AI 记录", ai_text)

    def test_dry_run_does_not_create_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from pm.mcp import plan_capture
            modes = inbox_files.InboxModes(human="weekly", ai="monthly")
            plan = plan_capture(root, "预演", source="cli", model="cli", now=NOW, inbox_modes=modes)
            self.assertEqual(plan.path.name, "inbox-human-2026-W43.org")
            self.assertFalse(plan.path.exists(), "dry-run 不得创建文件")

    def test_single_mode_keeps_legacy_inbox_org(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = capture_text(root, "兼容单文件", source="cli", model="cli", now=NOW)
            self.assertEqual(result.path.name, "inbox.org")
            self.assertIn("兼容单文件", (root / "inbox.org").read_text(encoding="utf-8"))


class MultiFileAggregateTest(unittest.TestCase):
    def test_aggregate_reads_all_files_with_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            modes = inbox_files.InboxModes(human="weekly", ai="monthly")
            capture_text(root, "人工 A", source="cli", model="cli", now=NOW, inbox_modes=modes)
            capture_text(root, "AI B", source="mcp", model="deepseek", now=NOW, inbox_modes=modes)
            payload = inbox_files.read_entries(root)
            self.assertEqual(payload["count"], 2)
            self.assertEqual(payload["counts"], {"human": 1, "ai": 1})
            by_text = {entry["text"]: entry for entry in payload["entries"]}
            self.assertEqual(by_text["人工 A"]["origin"], "human")
            self.assertEqual(by_text["人工 A"]["file"], "inbox-human-2026-W43.org")
            self.assertEqual(by_text["AI B"]["origin"], "ai")
            self.assertEqual(by_text["AI B"]["file"], "inbox-ai-2026-10.org")

    def test_aggregate_includes_legacy_single_file_until_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inbox.org").write_text(legacy_inbox(), encoding="utf-8")
            payload = inbox_files.read_entries(root)
            self.assertEqual(payload["count"], 3)  # 2 条 + 1 个 legacy bullet
            by_prefix = {(entry["text"] or "").splitlines()[0]: entry for entry in payload["entries"]}
            self.assertEqual(by_prefix["人类条目 A"]["origin"], "human")
            self.assertEqual(by_prefix["AI 条目 B"]["origin"], "human")  # 旧文件在迁移前统一按 human 文件读


class MultiFileRenderTest(unittest.TestCase):
    def test_render_inlines_current_files_and_skips_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            modes = inbox_files.InboxModes(human="weekly", ai="monthly")
            capture_text(root, "人工 A", source="cli", model="cli", now=NOW, inbox_modes=modes)
            capture_text(root, "AI B", source="mcp", model="deepseek", now=NOW, inbox_modes=modes)
            result = inbox_files.render(root, modes)
            self.assertTrue(result["written"])
            text = (root / "inbox.org").read_text(encoding="utf-8")
            self.assertIn("人工 A", text)
            self.assertIn("AI B", text)
            self.assertIn(inbox_files.GENERATED_MARKER, text)
            self.assertNotIn("[[file:inbox.org][inbox.org]]", text, "生成视图不得把自己列进历史")
            self.assertFalse(inbox_files.render(root, modes, check=True)["changed"])

    def test_render_is_skipped_in_single_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = inbox_files.render(root, inbox_files.InboxModes(human="single", ai="single"))
            self.assertTrue(result.get("skipped"))
            self.assertFalse((root / "inbox.org").exists())


class MultiFileOpsTest(unittest.TestCase):
    def test_ops_find_entry_across_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            modes = inbox_files.InboxModes(human="weekly", ai="monthly")
            ai = capture_text(root, "AI 待置顶", source="mcp", model="deepseek", now=NOW, inbox_modes=modes)
            from pm import inbox_ops
            result = inbox_ops.pin(root, ai.inbox_id, expected_revision=1)
            self.assertTrue(result.changed)
            text = ai.path.read_text(encoding="utf-8")
            self.assertIn(":PM_PIN: t", text)
            self.assertIn(":PM_REVISION: 2", text)


class MigrateTest(unittest.TestCase):
    def test_migrate_splits_by_origin_and_rewrites_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inbox.org").write_text(legacy_inbox(), encoding="utf-8")
            modes = inbox_files.InboxModes(human="weekly", ai="monthly")
            dry = inbox_files.migrate(root, modes, dry_run=True, now=NOW)
            self.assertTrue(dry["dry_run"])
            self.assertTrue((root / "inbox.org").read_text(encoding="utf-8").startswith("#+TITLE"))
            self.assertFalse(any(root.glob("inbox-human-*.org")))
            done = inbox_files.migrate(root, modes, dry_run=False, now=NOW)
            self.assertIn("backup", done)
            human_file = root / "inbox-human-2026-W43.org"
            ai_file = root / "inbox-ai-2026-10.org"
            self.assertTrue(human_file.is_file())
            self.assertTrue(ai_file.is_file())
            self.assertIn("人类条目 A", human_file.read_text(encoding="utf-8"))
            self.assertIn("旧的手写 bullet 一条", human_file.read_text(encoding="utf-8"))
            self.assertIn("AI 条目 B", ai_file.read_text(encoding="utf-8"))
            rendered = (root / "inbox.org").read_text(encoding="utf-8")
            self.assertIn(inbox_files.GENERATED_MARKER, rendered)
            self.assertTrue(any(root.glob("inbox.org.bak.*")))
            again = inbox_files.migrate(root, modes, dry_run=True, now=NOW)
            self.assertIn("已是生成视图", again.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
