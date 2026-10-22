"""P2a-后端：inbox 分流骨架（archive / snooze）的 CAS / 原子写 / 审计 / 409。

全部用临时库；真实库只由 C15 另行检查，这里一个字节都不碰。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pm import cli, inbox_ops
from pm.inbox import parse_entries

TZ = timezone(timedelta(hours=8))


class InboxOpsCliTest(unittest.TestCase):
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
        except SystemExit as exc:  # argparse 参数错误
            code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def pm(self, *argv: str) -> tuple[int, str, str]:
        return self.run_cli(["--config", str(self.config), *argv])

    def seed(self, text: str = "第一条笔记") -> str:
        code, stdout, _ = self.pm("capture", text, "--json")
        self.assertEqual(code, 0)
        return json.loads(stdout)["inboxId"]

    def list_json(self, *extra: str) -> dict:
        code, stdout, _ = self.pm("inbox", "list", "--json", *extra)
        self.assertEqual(code, 0)
        return json.loads(stdout)

    def row_for(self, inbox_id: str) -> dict:
        return next(row for row in self.list_json()["entries"] if row["id"] == inbox_id)

    # ---- archive 正常路径 ----

    def test_archive_sets_status_bumps_revision_and_writes_audit(self) -> None:
        inbox_id = self.seed()
        self.assertEqual(self.row_for(inbox_id)["revision"], 1)

        code, stdout, _ = self.pm(
            "inbox", "archive", inbox_id,
            "--expected-revision", "1", "--reason", "确认不需要", "--actor", "ai", "--json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["inboxId"], inbox_id)
        self.assertEqual(payload["status"], "ARCHIVED")
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["previousStatus"], "CAPTURED")
        self.assertEqual(payload["previousRevision"], 1)
        self.assertTrue(payload["changed"])

        text = self.inbox.read_text(encoding="utf-8")
        self.assertIn(":PM_STATUS: ARCHIVED", text)
        self.assertIn(":PM_REVISION: 2", text)
        self.assertIn(":LOGBOOK:", text)
        self.assertIn('State "ARCHIVED" from "CAPTURED"', text)
        self.assertIn("id=" + inbox_id, text)
        self.assertIn("actor=ai", text)
        self.assertIn("rev=2", text)
        self.assertIn("reason=确认不需要", text)

        # 状态与审计在同一个文件里（单文件原子），list 立刻能看到
        row = self.row_for(inbox_id)
        self.assertEqual(row["status"], "ARCHIVED")
        self.assertEqual(row["revision"], 2)
        self.assertEqual(self.list_json("--status", "ARCHIVED")["count"], 1)
        self.assertEqual(self.list_json("--status", "CAPTURED")["count"], 0)

    def test_archived_entry_text_is_still_lossless(self) -> None:
        inbox_id = self.seed("多行第一行 * 星号 | 竖线")
        self.pm("inbox", "archive", inbox_id, "--expected-revision", "1", "--json")
        entries = parse_entries(self.inbox.read_text(encoding="utf-8"))
        self.assertEqual(entries[0]["text"], "多行第一行 * 星号 | 竖线", "LOGBOOK 不得混进正文")

    def test_write_response_carries_design_section_5_fields(self) -> None:
        inbox_id = self.seed()
        code, stdout, _ = self.pm(
            "inbox", "archive", inbox_id, "--expected-revision", "1", "--json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["entityId"], inbox_id, "entityId 与 inboxId 等值")
        self.assertEqual(payload["inboxId"], inbox_id)
        self.assertEqual(payload["source"], "org")
        self.assertRegex(payload["observedAt"], r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{2}:[0-9]{2}$")
        self.assertRegex(payload["auditEventId"], r"^audit-[0-9A-HJKMNP-TV-Z]{26}$")
        # 审计事件 id 必须能在文件里被引用到
        self.assertIn("audit=" + payload["auditEventId"], self.inbox.read_text(encoding="utf-8"))

    def test_replay_returns_the_original_audit_event(self) -> None:
        inbox_id = self.seed()
        _, first, _ = self.pm(
            "inbox", "archive", inbox_id, "--expected-revision", "1",
            "--idempotency-key", "rk-1", "--json",
        )
        first_payload = json.loads(first)
        _, second, _ = self.pm(
            "inbox", "archive", inbox_id, "--expected-revision", "2",
            "--idempotency-key", "rk-1", "--json",
        )
        second_payload = json.loads(second)
        self.assertEqual(
            second_payload["auditEventId"], first_payload["auditEventId"],
            "重放要指向同一条审计事件，不能凭空造新的",
        )
        self.assertEqual(second_payload["observedAt"], first_payload["observedAt"])
        self.assertTrue(second_payload["idempotent"])

    def test_noop_returns_recorded_audit_event(self) -> None:
        inbox_id = self.seed()
        _, first, _ = self.pm("inbox", "archive", inbox_id, "--expected-revision", "1", "--json")
        first_payload = json.loads(first)
        _, again, _ = self.pm("inbox", "archive", inbox_id, "--expected-revision", "2", "--json")
        again_payload = json.loads(again)
        self.assertFalse(again_payload["changed"])
        self.assertEqual(again_payload["auditEventId"], first_payload["auditEventId"])
        self.assertEqual(again_payload["observedAt"], first_payload["observedAt"])

    def test_dry_run_carries_planned_audit_event(self) -> None:
        inbox_id = self.seed()
        code, stdout, _ = self.pm(
            "inbox", "archive", inbox_id, "--expected-revision", "1", "--dry-run", "--json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["source"], "org")
        self.assertRegex(payload["auditEventId"], r"^audit-[0-9A-HJKMNP-TV-Z]{26}$")
        self.assertTrue(payload["observedAt"].startswith("2"))

    def test_list_exposes_capture_metadata(self) -> None:
        """回归：前端要显示的捕获时间/来源/项目提示（原来没暴露，界面只能写「未记录」）。"""
        code, stdout, _ = self.pm("capture", "带元数据的记录", "--project", "demo", "--json")
        self.assertEqual(code, 0)
        inbox_id = json.loads(stdout)["inboxId"]
        row = self.row_for(inbox_id)
        self.assertTrue(row["capturedAt"])
        self.assertEqual(row["source"], "cli")
        self.assertEqual(row["projectHint"], "demo")

    def test_list_legacy_entry_metadata_is_null(self) -> None:
        self.inbox.write_text("#+TITLE: Inbox\n\n* Inbox\n\n- 旧条目\n", encoding="utf-8")
        row = self.list_json()["entries"][0]
        self.assertIsNone(row["capturedAt"])
        self.assertIsNone(row["source"])
        self.assertIsNone(row["projectHint"])

    # ---- 并发模拟：最重要的验收 ----

    def test_concurrent_edit_returns_409_and_writes_nothing(self) -> None:
        inbox_id = self.seed()
        # 外部编辑器改动该条目的 revision（模拟并发写）
        text = self.inbox.read_text(encoding="utf-8")
        self.inbox.write_text(text.replace(":PM_REVISION: 1", ":PM_REVISION: 7"), encoding="utf-8")
        before = self.inbox.read_bytes()

        code, stdout, stderr = self.pm(
            "inbox", "archive", inbox_id, "--expected-revision", "1", "--json"
        )
        self.assertEqual(code, 3, "冲突用专用退出码 3（2 留给输入错误）")
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "REVISION_CONFLICT")
        self.assertEqual(payload["currentRevision"], 7)
        self.assertEqual(payload["expectedRevision"], 1)
        self.assertTrue(payload["diffHint"])
        self.assertIn("REVISION_CONFLICT", stderr)
        self.assertEqual(self.inbox.read_bytes(), before, "冲突时文件必须逐字节不变")

    # ---- snooze ----

    def test_snooze_sets_status_and_until_and_filters(self) -> None:
        inbox_id = self.seed()
        code, stdout, _ = self.pm(
            "inbox", "snooze", inbox_id,
            "--until", "2026-10-20", "--expected-revision", "1", "--reason", "等版本", "--json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "SNOOZED")
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["snoozeUntil"], "2026-10-20")
        text = self.inbox.read_text(encoding="utf-8")
        self.assertIn(":PM_STATUS: SNOOZED", text)
        self.assertIn(":PM_SNOOZE_UNTIL: 2026-10-20", text)

        snoozed = self.list_json("--status", "SNOOZED")
        self.assertEqual(snoozed["count"], 1)
        self.assertEqual(snoozed["entries"][0]["snoozeUntil"], "2026-10-20")
        self.assertEqual(self.list_json("--status", "CAPTURED")["count"], 0)

    def test_snooze_accepts_iso8601_and_normalises(self) -> None:
        inbox_id = self.seed()
        code, stdout, _ = self.pm(
            "inbox", "snooze", inbox_id, "--until", "2026-10-20T09:30:00+08:00",
            "--expected-revision", "1", "--json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["snoozeUntil"], "2026-10-20T09:30:00+08:00")

    def test_invalid_until_rejected_without_writing(self) -> None:
        inbox_id = self.seed()
        before = self.inbox.read_bytes()
        code, stdout, _ = self.pm(
            "inbox", "snooze", inbox_id, "--until", "下周三", "--expected-revision", "1", "--json"
        )
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "INVALID_UNTIL")
        self.assertEqual(self.inbox.read_bytes(), before)

    # ---- idempotency ----

    def test_idempotency_key_prevents_second_change(self) -> None:
        inbox_id = self.seed()
        code, first, _ = self.pm(
            "inbox", "archive", inbox_id, "--expected-revision", "1",
            "--idempotency-key", "k-1", "--json",
        )
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(first)["changed"])
        after_first = self.inbox.read_bytes()

        # 重放同一 key（即使带上新的 expected-revision）：不得再改一次
        code, second, _ = self.pm(
            "inbox", "archive", inbox_id, "--expected-revision", "2",
            "--idempotency-key", "k-1", "--json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(second)
        self.assertTrue(payload["idempotent"])
        self.assertFalse(payload["changed"])
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(self.inbox.read_bytes(), after_first, "重放不得产生第二次变更")

    def test_idempotency_key_reuse_on_other_entry_is_rejected(self) -> None:
        first_id = self.seed("第一条")
        second_id = self.seed("第二条")
        self.pm("inbox", "archive", first_id, "--expected-revision", "1",
                "--idempotency-key", "shared", "--json")
        before = self.inbox.read_bytes()
        code, stdout, _ = self.pm(
            "inbox", "archive", second_id, "--expected-revision", "1",
            "--idempotency-key", "shared", "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(self.inbox.read_bytes(), before)

    # ---- dry-run ----

    def test_dry_run_writes_nothing(self) -> None:
        inbox_id = self.seed()
        import hashlib

        before = hashlib.sha256(self.inbox.read_bytes()).hexdigest()
        code, stdout, _ = self.pm(
            "inbox", "archive", inbox_id, "--expected-revision", "1", "--dry-run", "--json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["status"], "ARCHIVED")
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(hashlib.sha256(self.inbox.read_bytes()).hexdigest(), before)
        self.assertEqual(self.row_for(inbox_id)["status"], "CAPTURED")

    # ---- legacy / not found ----

    def test_legacy_entry_is_rejected_and_file_untouched(self) -> None:
        self.inbox.write_text("#+TITLE: Inbox\n\n* Inbox\n  随手记\n\n- 旧条目\n", encoding="utf-8")
        before = self.inbox.read_bytes()
        code, stdout, _ = self.pm(
            "inbox", "archive", "inbox-whatever", "--expected-revision", "1", "--json"
        )
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "LEGACY_UNTRACKED")
        self.assertIn(":ID:", payload["error"]["message"])
        self.assertEqual(self.inbox.read_bytes(), before)

    def test_unknown_id_without_legacy_is_not_found(self) -> None:
        self.seed()
        before = self.inbox.read_bytes()
        code, stdout, _ = self.pm(
            "inbox", "archive", "inbox-does-not-exist", "--expected-revision", "1", "--json"
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "NOT_FOUND")
        self.assertEqual(self.inbox.read_bytes(), before)

    # ---- 闸门 / 原子性 / list 形状 ----

    def test_write_gate_requires_yes_without_explicit_config(self) -> None:
        inbox_id = self.seed()
        before = self.inbox.read_bytes()
        with mock.patch.dict(os.environ, {"PM_CONFIG": str(self.config)}):
            code, stdout, _ = self.run_cli(
                ["inbox", "archive", inbox_id, "--expected-revision", "1", "--json"]
            )
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "NEEDS_YES")
        self.assertIn(str(self.library.resolve()), payload["error"]["message"])
        self.assertEqual(self.inbox.read_bytes(), before, "被闸门拒绝时不得写")

    def test_no_temp_file_left_behind(self) -> None:
        inbox_id = self.seed()
        self.pm("inbox", "archive", inbox_id, "--expected-revision", "1", "--json")
        leftovers = list(self.library.glob("*.pm-tmp"))
        self.assertEqual(leftovers, [], "原子写的临时文件必须清理干净")

    def test_list_json_exposes_legacy_rows_without_revision(self) -> None:
        self.seed("一条记录")
        self.inbox.write_text(
            self.inbox.read_text(encoding="utf-8") + "\n- 手写旧条目\n",
            encoding="utf-8",
        )
        payload = self.list_json()
        statuses = {row["status"] for row in payload["entries"]}
        self.assertIn("CAPTURED", statuses)
        self.assertIn("LEGACY_UNTRACKED", statuses)
        legacy = next(row for row in payload["entries"] if row["status"] == "LEGACY_UNTRACKED")
        self.assertIsNone(legacy["id"])
        self.assertIsNone(legacy["revision"])
        self.assertEqual(payload["count"], len(payload["entries"]))

    def test_archive_already_archived_is_noop(self) -> None:
        inbox_id = self.seed()
        self.pm("inbox", "archive", inbox_id, "--expected-revision", "1", "--json")
        after_first = self.inbox.read_bytes()
        code, stdout, _ = self.pm(
            "inbox", "archive", inbox_id, "--expected-revision", "2", "--json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertFalse(payload["changed"])
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(self.inbox.read_bytes(), after_first)


class InboxP2bTest(unittest.TestCase):
    """P2b-后端：merge / note / dismiss / set-status + 状态机 + 幂等（临时库）。"""

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

    def seed(self, text: str = "一条记录", *extra: str) -> str:
        code, stdout, _ = self.pm("capture", text, *extra, "--json")
        self.assertEqual(code, 0)
        return json.loads(stdout)["inboxId"]

    def revision(self, inbox_id: str) -> int:
        code, stdout, _ = self.pm("inbox", "list", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        row = next(r for r in payload["entries"] if r["id"] == inbox_id)
        return row["revision"]

    def text_of(self, inbox_id: str) -> str:
        for entry in parse_entries(self.inbox.read_text(encoding="utf-8")):
            if entry["id"] == inbox_id:
                return entry["text"]
        raise AssertionError("entry not found: " + inbox_id)

    # ---- merge ----

    def test_merge_marks_source_and_links_primary(self) -> None:
        primary = self.seed("主记录")
        source = self.seed("重复记录")
        code, stdout, _ = self.pm(
            "inbox", "merge", source, "--into", primary,
            "--expected-revision", "1", "--reason", "重复", "--json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "MERGED")
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["mergedInto"], primary)

        text = self.inbox.read_text(encoding="utf-8")
        self.assertIn(":PM_STATUS: MERGED", text)
        self.assertIn(":PM_MERGED_INTO: " + primary, text)
        self.assertIn("into=" + primary, text)
        # 两条记录都还在（不删历史）
        self.assertEqual(self.text_of(primary), "主记录")
        self.assertEqual(self.text_of(source), "重复记录")
        code, stdout, _ = self.pm("inbox", "list", "--status", "MERGED", "--json")
        self.assertEqual(json.loads(stdout)["count"], 1)

    def test_merge_into_self_rejected(self) -> None:
        inbox_id = self.seed()
        before = self.inbox.read_bytes()
        code, stdout, _ = self.pm(
            "inbox", "merge", inbox_id, "--into", inbox_id, "--expected-revision", "1", "--json"
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "INVALID_TARGET")
        self.assertEqual(self.inbox.read_bytes(), before)

    # ---- note ----

    def test_note_writes_memory_candidate_and_marks_source(self) -> None:
        inbox_id = self.seed("值得留档的结论", "--project", "demo")
        code, stdout, _ = self.pm(
            "inbox", "note", inbox_id, "--expected-revision", "1", "--reason", "留档", "--json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "NOTE")
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["notePath"], "memory-candidates.org")
        self.assertRegex(payload["noteId"], r"^memory-[0-9A-HJKMNP-TV-Z]{26}$")
        self.assertIn(":PM_NOTE_ID: " + payload["noteId"], self.inbox.read_text(encoding="utf-8"))

        candidate = self.library / "memory-candidates.org"
        self.assertTrue(candidate.is_file(), "note 必须写入 memory 候选区")
        text = candidate.read_text(encoding="utf-8")
        self.assertIn(":ID: " + payload["noteId"], text)
        self.assertIn(":PM_KIND: memory", text)
        self.assertIn(":PM_STATUS: CANDIDATE", text)
        self.assertIn(":PM_SOURCE_INBOX_ID: " + inbox_id, text)
        self.assertIn(":PM_SCOPE: demo", text)
        self.assertIn("值得留档的结论", text)
        # note 不创建任务
        self.assertFalse((self.library / "projects").exists())

    def test_note_dry_run_writes_nothing(self) -> None:
        inbox_id = self.seed("预演留档")
        before = self.inbox.read_bytes()
        code, stdout, _ = self.pm(
            "inbox", "note", inbox_id, "--expected-revision", "1", "--dry-run", "--json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["dry_run"])
        self.assertRegex(payload["noteId"], r"^memory-")
        self.assertEqual(self.inbox.read_bytes(), before)
        self.assertFalse((self.library / "memory-candidates.org").exists(), "dry-run 不得建候选文件")

    # ---- dismiss ----

    def test_dismiss_requires_reason(self) -> None:
        inbox_id = self.seed()
        before = self.inbox.read_bytes()
        code, stdout, _ = self.pm(
            "inbox", "dismiss", inbox_id, "--expected-revision", "1", "--json"
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "REASON_REQUIRED")
        self.assertEqual(self.inbox.read_bytes(), before)

        code, stdout, _ = self.pm(
            "inbox", "dismiss", inbox_id, "--expected-revision", "1",
            "--reason", "信息已过期", "--json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "DISMISSED")
        self.assertEqual(payload["revision"], 2)
        text = self.inbox.read_text(encoding="utf-8")
        self.assertIn('- State "DISMISSED" from "CAPTURED"', text)
        self.assertIn("reason=信息已过期", text)

    # ---- set-status 与状态机 ----

    def test_set_status_captured_to_triage(self) -> None:
        inbox_id = self.seed()
        code, stdout, _ = self.pm(
            "inbox", "set-status", inbox_id, "--status", "TRIAGE",
            "--expected-revision", "1", "--json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "TRIAGE")
        self.assertIn('- State "TRIAGE" from "CAPTURED"', self.inbox.read_text(encoding="utf-8"))

    def test_unknown_status_rejected(self) -> None:
        inbox_id = self.seed()
        before = self.inbox.read_bytes()
        code, stdout, _ = self.pm(
            "inbox", "set-status", inbox_id, "--status", "NOPE",
            "--expected-revision", "1", "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "UNKNOWN_STATUS")
        self.assertEqual(self.inbox.read_bytes(), before)

    def test_illegal_transitions_rejected_and_file_unchanged(self) -> None:
        # 1) ARCHIVED → SNOOZED
        a = self.seed("甲")
        self.pm("inbox", "archive", a, "--expected-revision", "1", "--json")
        # 2) MERGED → DISMISSED
        b = self.seed("乙")
        primary = self.seed("丙")
        self.pm("inbox", "merge", b, "--into", primary, "--expected-revision", "1", "--json")
        # 3) DISMISSED → ARCHIVED
        c = self.seed("丁")
        self.pm("inbox", "dismiss", c, "--expected-revision", "1", "--reason", "过期", "--json")
        # 4) TRIAGE → CAPTURED（回退）
        d = self.seed("戊")
        self.pm("inbox", "set-status", d, "--status", "TRIAGE", "--expected-revision", "1", "--json")

        cases = [
            (["inbox", "snooze", a, "--until", "2026-11-01", "--expected-revision", "2"], "ARCHIVED"),
            (["inbox", "dismiss", b, "--expected-revision", "2", "--reason", "x"], "MERGED"),
            (["inbox", "archive", c, "--expected-revision", "2"], "DISMISSED"),
            (["inbox", "set-status", d, "--status", "CAPTURED", "--expected-revision", "2"], "TRIAGE"),
        ]
        for argv, terminal in cases:
            before = self.inbox.read_bytes()
            code, stdout, _ = self.pm(*argv, "--json")
            self.assertEqual(code, 2, argv)
            payload = json.loads(stdout)
            self.assertEqual(payload["error"]["code"], "ILLEGAL_TRANSITION", argv)
            self.assertEqual(payload["currentStatus"], terminal, argv)
            self.assertEqual(self.inbox.read_bytes(), before, argv)

    # ---- 幂等 & legacy ----

    def test_idempotency_on_merge_and_note(self) -> None:
        primary = self.seed("主")
        source = self.seed("源")
        code, first, _ = self.pm(
            "inbox", "merge", source, "--into", primary, "--expected-revision", "1",
            "--idempotency-key", "mk-1", "--json",
        )
        self.assertEqual(code, 0)
        after_first = self.inbox.read_bytes()
        code, replay, _ = self.pm(
            "inbox", "merge", source, "--into", primary, "--expected-revision", "2",
            "--idempotency-key", "mk-1", "--json",
        )
        self.assertEqual(code, 0)
        replay_payload = json.loads(replay)
        self.assertTrue(replay_payload["idempotent"])
        self.assertEqual(replay_payload["auditEventId"], json.loads(first)["auditEventId"])
        self.assertEqual(self.inbox.read_bytes(), after_first)

        target = self.seed("待留档")
        self.pm("inbox", "note", target, "--expected-revision", "1",
                "--idempotency-key", "nk-1", "--json")
        candidate = self.library / "memory-candidates.org"
        first_text = candidate.read_text(encoding="utf-8")
        _, replay2, _ = self.pm(
            "inbox", "note", target, "--expected-revision", "2", "--idempotency-key", "nk-1", "--json"
        )
        payload2 = json.loads(replay2)
        self.assertTrue(payload2["idempotent"])
        self.assertRegex(payload2["noteId"], r"^memory-")
        self.assertEqual(candidate.read_text(encoding="utf-8"), first_text, "重放不得建第二个候选")

    def test_legacy_rejected_for_new_actions(self) -> None:
        self.inbox.write_text("#+TITLE: Inbox\n\n* Inbox\n\n- 旧条目\n", encoding="utf-8")
        before = self.inbox.read_bytes()
        for argv in (
            ["inbox", "dismiss", "inbox-nope", "--expected-revision", "1", "--reason", "x"],
            ["inbox", "note", "inbox-nope", "--expected-revision", "1"],
            ["inbox", "merge", "inbox-nope", "--into", "other", "--expected-revision", "1"],
        ):
            code, stdout, _ = self.pm(*argv, "--json")
            self.assertEqual(code, 2, argv)
            self.assertEqual(json.loads(stdout)["error"]["code"], "LEGACY_UNTRACKED", argv)
        self.assertEqual(self.inbox.read_bytes(), before)

    def test_section_5_fields_on_every_action(self) -> None:
        primary = self.seed("主2")
        source = self.seed("源2")
        note_target = self.seed("笔记2")
        actions = [
            ["inbox", "merge", source, "--into", primary, "--expected-revision", "1"],
            ["inbox", "note", note_target, "--expected-revision", "1"],
        ]
        for argv in actions:
            code, stdout, _ = self.pm(*argv, "--json")
            self.assertEqual(code, 0, argv)
            payload = json.loads(stdout)
            self.assertEqual(payload["entityId"], payload["inboxId"])
            self.assertEqual(payload["source"], "org")
            self.assertRegex(payload["auditEventId"], r"^audit-")
            self.assertTrue(payload["observedAt"])


class ParseUntilTest(unittest.TestCase):
    def test_date_and_iso(self) -> None:
        self.assertEqual(inbox_ops.parse_until("2026-10-20"), "2026-10-20")
        self.assertEqual(inbox_ops.parse_until("2026-10-20T09:30:00+08:00"), "2026-10-20T09:30:00+08:00")

    def test_bad_values(self) -> None:
        for bad in ("", "下周三", "2026-13-40", "not-a-date"):
            with self.assertRaises(inbox_ops.InboxOpError) as ctx:
                inbox_ops.parse_until(bad)
            self.assertEqual(ctx.exception.code, "INVALID_UNTIL")


if __name__ == "__main__":
    unittest.main()
