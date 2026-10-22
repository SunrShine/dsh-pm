"""丢弃候选（task-163）：pm memory discard = 只从 CANDIDATE 标 DEPRECATED，必填 --reason、一条审计、幂等。

状态集不新增 DISCARDED（复用 DEPRECATED）；已 VERIFIED 的走既有 pm memory deprecate。
全部用临时库（继承 tests.test_memory 的脚手架），真实库一个字节都不碰。
"""

from __future__ import annotations

import json
import unittest

from pm import entities, memory

# bin/test 把 tests/ 放进 PYTHONPATH → 直接按顶层模块名导入；不复制脚手架（一处定义）
from test_memory import NOW, MemoryBaseTest


class DiscardTest(MemoryBaseTest):
    # ---------------- 领域函数 ----------------

    def test_discard_candidate_marks_deprecated_with_audit(self) -> None:
        entry = self.add_candidate("这条候选不要了")
        result = memory.discard(
            self.library, entry.id, expected_revision=1, reason="重复候选", now=NOW
        )
        self.assertTrue(result.changed)
        self.assertEqual(result.status, memory.STATUS_DEPRECATED)
        self.assertEqual(result.previous_status, memory.STATUS_CANDIDATE)
        self.assertEqual(result.revision, 2)
        self.assertTrue(result.extra["discarded"])
        self.assertEqual(result.extra["wasStatus"], memory.STATUS_CANDIDATE)

        after = memory.parse_candidates(self.library)[0]
        self.assertEqual(after.status, memory.STATUS_DEPRECATED)
        self.assertIsNotNone(after.deprecated_at)
        text = self.candidates.read_text(encoding="utf-8")
        self.assertIn('State "DEPRECATED" from "CANDIDATE"', text)
        self.assertIn("op=discard", text, "审计要留下是丢弃动作")
        self.assertIn("reason=重复候选", text)
        self.assertIn(":PM_DEPRECATED_AT:", text)

    def test_verified_entry_is_rejected_and_untouched(self) -> None:
        entry = self.add_candidate("已确认的记忆")
        memory.verify(self.library, entry.id, expected_revision=1, actor="human", now=NOW)
        before = self.candidates.read_bytes()
        with self.assertRaises(memory.MemoryError) as raised:
            memory.discard(self.library, entry.id, expected_revision=2, reason="想丢", now=NOW)
        self.assertEqual(raised.exception.code, "NOT_A_CANDIDATE")
        self.assertEqual(raised.exception.exit_code, 2)
        self.assertIn("VERIFIED", str(raised.exception))
        self.assertEqual(self.candidates.read_bytes(), before, "拒绝时零写入")
        self.assertEqual(memory.parse_candidates(self.library)[0].status, memory.STATUS_VERIFIED)

    def test_second_discard_is_idempotent_and_adds_no_audit(self) -> None:
        entry = self.add_candidate("丢两次")
        first = memory.discard(self.library, entry.id, expected_revision=1, reason="不要了", now=NOW)
        before = self.candidates.read_bytes()
        audits_before = before.count(b"audit=")
        second = memory.discard(
            self.library, entry.id, expected_revision=first.revision, reason="不要了（重复提交）", now=NOW
        )
        self.assertFalse(second.changed)
        self.assertEqual(second.revision, first.revision)
        self.assertEqual(second.audit_event_id, first.audit_event_id, "幂等时不产生新审计")
        self.assertFalse(second.extra["discarded"])
        self.assertEqual(second.extra["wasStatus"], memory.STATUS_DEPRECATED)
        after = self.candidates.read_bytes()
        self.assertEqual(after, before, "幂等时一个字节都不写")
        self.assertEqual(after.count(b"audit="), audits_before)

    def test_missing_or_blank_reason_is_rejected(self) -> None:
        entry = self.add_candidate("没给理由")
        for reason in ("", "   \n  "):
            with self.assertRaises(memory.MemoryError) as raised:
                memory.discard(self.library, entry.id, expected_revision=1, reason=reason, now=NOW)
            self.assertEqual(raised.exception.code, "REASON_REQUIRED")
            self.assertEqual(raised.exception.exit_code, 2)
        self.assertEqual(memory.parse_candidates(self.library)[0].status, memory.STATUS_CANDIDATE)

    def test_stale_revision_conflicts_without_writing(self) -> None:
        entry = self.add_candidate("CAS")
        before = self.candidates.read_bytes()
        with self.assertRaises(entities.EntityError) as raised:
            memory.discard(self.library, entry.id, expected_revision=99, reason="revision 过期", now=NOW)
        self.assertEqual(raised.exception.code, "REVISION_CONFLICT")
        self.assertEqual(raised.exception.exit_code, 3)
        self.assertEqual(self.candidates.read_bytes(), before)
        self.assertEqual(memory.parse_candidates(self.library)[0].status, memory.STATUS_CANDIDATE)

    def test_dry_run_writes_nothing(self) -> None:
        entry = self.add_candidate("干跑")
        before = self.candidates.read_bytes()
        memory.discard(
            self.library, entry.id, expected_revision=1, reason="只预演", dry_run=True, now=NOW
        )
        self.assertEqual(self.candidates.read_bytes(), before, "--dry-run 必须零写入")
        self.assertEqual(memory.parse_candidates(self.library)[0].status, memory.STATUS_CANDIDATE)

    def test_unknown_id_is_not_found(self) -> None:
        before = self.candidates.read_bytes() if self.candidates.exists() else b""
        with self.assertRaises(entities.EntityError) as raised:
            memory.discard(self.library, "memory-00000000000000000000000000", expected_revision=1,
                           reason="不存在", now=NOW)
        self.assertEqual(raised.exception.code, "NOT_FOUND")
        self.assertEqual(raised.exception.exit_code, 2)
        self.assertEqual(self.candidates.read_bytes() if self.candidates.exists() else b"", before)

    # ---------------- CLI ----------------

    def test_cli_discard_json_ok(self) -> None:
        entry = self.add_candidate("走 CLI")
        code, stdout, stderr = self.pm(
            "memory", "discard", entry.id, "--expected-revision", "1", "--reason", "重复", "--json"
        )
        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["changed"])
        self.assertEqual(payload["status"], memory.STATUS_DEPRECATED)
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["path"], "memory-candidates.org")

    def test_cli_without_reason_exits_2(self) -> None:
        entry = self.add_candidate("CLI 缺 reason")
        before = self.candidates.read_bytes()
        code, stdout, _ = self.pm(
            "memory", "discard", entry.id, "--expected-revision", "1", "--json"
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "REASON_REQUIRED")
        self.assertEqual(self.candidates.read_bytes(), before)

    def test_cli_verified_entry_exits_2(self) -> None:
        entry = self.add_candidate("CLI 拒 VERIFIED")
        memory.verify(self.library, entry.id, expected_revision=1, actor="human", now=NOW)
        code, stdout, _ = self.pm(
            "memory", "discard", entry.id, "--expected-revision", "2", "--reason", "试试", "--json"
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "NOT_A_CANDIDATE")

    def test_cli_conflict_exits_3(self) -> None:
        entry = self.add_candidate("CLI CAS")
        code, _, stderr = self.pm(
            "memory", "discard", entry.id, "--expected-revision", "99", "--reason", "过期"
        )
        self.assertEqual(code, 3)
        self.assertIn("REVISION_CONFLICT", stderr)


if __name__ == "__main__":
    unittest.main()
