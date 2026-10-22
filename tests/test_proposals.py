"""Plan Proposal 模型（§5.3）：解析 / 生成 / 批准 / 拒绝 / 补偿式多文件事务。

全部用临时库；真实库一个字节都不碰。验收点：
- 生成提案后 tasks.org 不存在或未被改动；
- 批准：任务回链 + inbox TASK_CREATED + 提案 APPROVED，全部有审计；
- CAS 过期 → 三个文件逐字节不变（退出码 3）；
- 拒绝 → 正式任务零变化；
- 多文件事务中途失败 → 明确报出 written / notWritten，且重试收敛。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pm import cli, entities, proposals
from pm.layout import Layout
from pm.mcp import capture_text

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=TZ)

SAMPLE = """#+TITLE: 提案

* Proposals

** PROPOSAL 从 inbox-00000000000000000000000000 生成验证任务计划
:PROPERTIES:
:ID: proposal-00000000000000000000000001
:PM_KIND: proposal
:PM_STATUS: PENDING
:PM_SOURCE_INBOX_ID: inbox-00000000000000000000000000
:PM_BASE_REVISION: 1
:PM_PLAN_REVISION: 1
:PM_CREATED_BY: ai
:END:

*** 变更
- 新增 task-00000000000000000000000002：明确输入范围

*** 风险与待确认
- 尚未确认参考模型所在 revision

*** 操作
批准后创建正式任务；拒绝不改变正式任务。
"""

INDENTED = """* Proposals

** PROPOSAL 从 inbox-00000000000000000000000000 生成验证任务计划
   :PROPERTIES:
   :ID: proposal-00000000000000000000000001
   :PM_KIND: proposal
   :PM_STATUS: PENDING
   :PM_SOURCE_INBOX_ID: inbox-00000000000000000000000000
   :PM_BASE_REVISION: 2
   :PM_PLAN_REVISION: 3
   :PM_CREATED_BY: ai
   :PM_REVISION: 1
   :END:
   :LOGBOOK:
   - State "PENDING" from "(created)" [2026-10-12 Mon 12:00] id=proposal-00000000000000000000000001 audit=audit-x at=2026-10-12T12:00:00+08:00 actor=ai rev=1
   :END:

   *** 变更
   - 新增 task-00000000000000000000000002：明确输入范围
   - 修改 task-00000000000000000000000003：把验收改成可复现

   *** 风险与待确认
   - 参考模型 revision 未确认

   *** 操作
   批准后创建正式任务；拒绝不改变正式任务。
"""

LEGACY = """* Proposals

** PROPOSAL 手写的旧提案
   这里没有 :ID: 抽屉，属于 LEGACY_UNTRACKED。
"""


def parse_one(text: str) -> dict:
    rows = proposals.parse_proposals(text)
    assert len(rows) == 1, rows
    return rows[0]


class ParseProposalsTest(unittest.TestCase):
    def test_sample_shape_from_design_5_3(self) -> None:
        row = parse_one(SAMPLE)
        self.assertEqual(row["id"], "proposal-00000000000000000000000001")
        self.assertEqual(row["kind"], "proposal")
        self.assertEqual(row["status"], "PENDING")
        self.assertEqual(row["revision"], 1, "没有 :PM_REVISION: 时按初始 1")
        self.assertEqual(row["title"], "从 inbox-00000000000000000000000000 生成验证任务计划")
        self.assertEqual(row["source_inbox_id"], "inbox-00000000000000000000000000")
        self.assertEqual(row["base_revision"], 1)
        self.assertEqual(row["plan_revision"], 1)
        self.assertEqual(row["created_by"], "ai")
        self.assertEqual(
            row["changes"],
            [{"op": "新增", "task_id": "task-00000000000000000000000002", "title": "明确输入范围",
              "text": "新增 task-00000000000000000000000002：明确输入范围", "criteria": []}],
        )
        self.assertEqual(row["risks"], ["尚未确认参考模型所在 revision"])
        self.assertEqual(row["actions"], ["批准后创建正式任务；拒绝不改变正式任务。"])
        self.assertEqual(row["line"], 5)

    def test_indented_drawer_and_sections_parse_the_same(self) -> None:
        row = parse_one(INDENTED)
        self.assertEqual(row["id"], "proposal-00000000000000000000000001")
        self.assertEqual(row["revision"], 1)
        self.assertEqual(row["base_revision"], 2)
        self.assertEqual(row["plan_revision"], 3)
        self.assertEqual([c["task_id"] for c in row["changes"]],
                         ["task-00000000000000000000000002", "task-00000000000000000000000003"])
        self.assertEqual(row["changes"][1]["op"], "修改")
        self.assertEqual(row["changes"][1]["title"], "把验收改成可复现")
        self.assertEqual(row["risks"], ["参考模型 revision 未确认"])

    def test_legacy_without_id_is_marked(self) -> None:
        row = parse_one(LEGACY)
        self.assertIsNone(row["id"])
        self.assertEqual(row["status"], "LEGACY_UNTRACKED")
        self.assertIsNone(row["revision"])
        self.assertEqual(row["changes"], [])

    def test_empty_text_and_missing_sections(self) -> None:
        self.assertEqual(proposals.parse_proposals(""), [])
        row = parse_one("* Proposals\n\n** PROPOSAL 光杆提案\n:PROPERTIES:\n:ID: proposal-plain\n:END:\n")
        self.assertEqual(row["title"], "光杆提案")
        self.assertEqual(row["status"], "PENDING")
        self.assertEqual((row["changes"], row["risks"], row["actions"]), ([], [], []))

    def test_change_line_variants(self) -> None:
        self.assertEqual(
            proposals._parse_change("新增 task-ABC：标题"),
            {"op": "新增", "task_id": "task-ABC", "title": "标题", "text": "新增 task-ABC：标题"},
        )
        self.assertEqual(proposals._parse_change("新增 task-…")["task_id"], "task-…")
        self.assertEqual(proposals._parse_change("新增：标题"),
                         {"op": "新增", "task_id": None, "title": "标题", "text": "新增：标题"})
        self.assertEqual(proposals._parse_change("新增 task-ABC")["title"], "")
        self.assertEqual(proposals._parse_change("")["op"], "")

    def test_body_lines_are_not_confused_with_other_sections(self) -> None:
        text = "* Proposals\n\n** PROPOSAL p\n:PROPERTIES:\n:ID: proposal-1\n:END:\n\n*** 其它\n- 无关\n\n*** 变更\n- 新增 task-A：x\n"
        row = parse_one(text)
        self.assertEqual([c["task_id"] for c in row["changes"]], ["task-A"])


class ProposalFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.library = self.base / "wm"
        self.library.mkdir()
        self.layout = Layout(self.library)
        self.config = self.base / "pm.toml"
        self.config.write_text('library = "' + str(self.library) + '"\n', encoding="utf-8")

    # ---- helpers ----

    def seed_inbox(self, text: str = "验证外部参考模型", *, project_hint: str | None = None,
                   status: str = "CAPTURED") -> str:
        result = capture_text(self.library, text, source="cli", model="test",
                              project_hint=project_hint, now=NOW)
        if status != "CAPTURED":
            entities.apply_change(self.layout.inbox, result.inbox_id, expected_revision=1,
                                  status=status, headline="Inbox", now=NOW)
        return result.inbox_id

    def make_project(self, key: str = "proj-demo") -> Path:
        tasks = self.layout.tasks_file(key)
        tasks.parent.mkdir(parents=True, exist_ok=True)
        tasks.write_text("#+TITLE: demo\n\n* 任务\n", encoding="utf-8")
        return tasks

    def create(self, inbox_id: str, **overrides) -> proposals.ProposalResult:
        kwargs = {
            "source_inbox_id": inbox_id,
            "changes": [{"op": "新增", "title": "明确输入范围"}],
            "risks": ["尚未确认参考模型所在 revision"],
            "project": "proj-demo",
            "now": NOW,
        }
        kwargs.update(overrides)
        return proposals.create_proposal(self.library, **kwargs)

    def proposals_file(self) -> Path:
        return self.layout.proposals_file

    def bytes_of(self, path: Path) -> bytes | None:
        return path.read_bytes() if path.is_file() else None

    def digest(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def task_blocks(self, path: Path) -> list[str]:
        return [block for block in path.read_text(encoding="utf-8").split("** ") if block.strip()] if path.is_file() else []

    # ---- create ----

    def test_create_writes_only_proposals_org_and_never_touches_tasks(self) -> None:
        inbox_id = self.seed_inbox()
        result = self.create(inbox_id)
        self.assertTrue(self.proposals_file().is_file())
        self.assertFalse((self.library / "projects").exists(), "create 不应新建项目目录")
        self.assertFalse(self.layout.tasks_file("proj-demo").exists(), "提案存在时 tasks.org 不得出现")
        self.assertFalse(self.layout.proposals_dir.exists(), "§5.3 用单文件，不建 proposals/ 目录")
        self.assertEqual(result.entity_id, "proposal-" + result.entity_id.split("-", 1)[1])
        self.assertTrue(result.entity_id.startswith("proposal-"))
        self.assertEqual(result.status, "PENDING")
        self.assertEqual(result.revision, 1)
        self.assertEqual(result.base_revision, 1)
        self.assertEqual(len(result.task_ids), 1)
        self.assertTrue(result.task_ids[0].startswith("task-"))

    def test_create_leaves_existing_tasks_file_byte_identical(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        before = self.digest(tasks)
        self.create(inbox_id)
        self.assertEqual(self.digest(tasks), before, "生成提案不得改动 tasks.org")

    def test_create_marks_source_inbox_task_proposed(self) -> None:
        """§5.1：create 之后源条目必须是 TASK_PROPOSED（不再出现在「待处理」）。"""
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        tasks_before = self.digest(tasks)
        result = self.create(inbox_id)
        self.assertEqual(result.inbox_status, "TASK_PROPOSED")
        self.assertEqual(result.inbox_revision, 2)
        self.assertFalse(result.partial)
        self.assertIsNone(result.hint)
        self.assertEqual(result.extra["written"], ["proposals.org", "inbox.org"])
        self.assertEqual(result.extra["notWritten"], [])
        self.assertEqual([s["name"] for s in result.steps], ["proposal", "inbox"])

        text = self.layout.inbox.read_text(encoding="utf-8")
        self.assertIn(":PM_STATUS: TASK_PROPOSED", text)
        self.assertIn(":PM_REVISION: 2", text)
        self.assertIn(":PM_PROPOSAL_ID: " + result.entity_id, text)
        self.assertIn("op=propose", text, "审计必须标 op=propose")
        self.assertIn("proposalId=" + result.entity_id, text)
        self.assertIn("reason=proposal " + result.entity_id + " created", text)
        self.assertIn('State "TASK_PROPOSED" from "CAPTURED"', text)
        self.assertIn("audit=", text)
        self.assertEqual(self.digest(tasks), tasks_before, "create 仍然不得碰 tasks.org")

    def test_create_duplicate_pending_proposal_rejected_then_allow_duplicate(self) -> None:
        inbox_id = self.seed_inbox()
        first = self.create(inbox_id)
        proposals_before = self.digest(self.proposals_file())
        inbox_before = self.digest(self.layout.inbox)
        with self.assertRaises(proposals.ProposalError) as ctx:
            self.create(inbox_id)
        self.assertEqual(ctx.exception.code, "PROPOSAL_EXISTS_FOR_INBOX")
        self.assertEqual(ctx.exception.extra["existingProposalId"], first.entity_id)
        self.assertEqual(ctx.exception.extra["revision"], 1)
        self.assertEqual(self.digest(self.proposals_file()), proposals_before, "被拒时不写")
        self.assertEqual(self.digest(self.layout.inbox), inbox_before, "被拒时不写")

        second = self.create(inbox_id, allow_duplicate=True)
        self.assertNotEqual(second.entity_id, first.entity_id)
        self.assertEqual(second.inbox_status, "TASK_PROPOSED")
        self.assertEqual(proposals.list_proposals(self.library)["count"], 2)

    def test_create_partial_when_inbox_cas_fails(self) -> None:
        inbox_id = self.seed_inbox()
        inbox_before = self.digest(self.layout.inbox)

        def boom(*args, **kwargs):
            raise entities.EntityError(
                "REVISION_CONFLICT", "模拟 inbox 并发修改", exit_code=3,
                extra={"currentRevision": 9, "expectedRevision": 1},
            )

        with mock.patch.object(proposals, "_mark_inbox_proposed", side_effect=boom):
            with self.assertRaises(proposals.ProposalError) as ctx:
                self.create(inbox_id)
        error = ctx.exception
        self.assertEqual(error.code, "PARTIAL_WRITE")
        self.assertEqual(error.exit_code, 3, "退出码沿用底层映射（冲突 3）")
        self.assertTrue(error.extra["partial"])
        self.assertEqual(error.extra["proposalId"], error.extra["entityId"])
        self.assertEqual(error.extra["written"], ["proposals.org"])
        self.assertEqual(error.extra["notWritten"], ["inbox.org"])
        self.assertIn("pm inbox set-status " + inbox_id, error.extra["hint"])
        self.assertIn("--expected-revision 9", error.extra["hint"], "hint 必须带可直接复制的当前 revision")
        self.assertIn("不是假成功", error.message)
        self.assertEqual(self.digest(self.layout.inbox), inbox_before, "inbox 确实没写")
        self.assertEqual(proposals.list_proposals(self.library)["count"], 1, "提案本身仍可 list")

    def test_create_legacy_source_inbox_rejected(self) -> None:
        self.layout.inbox.write_text(
            "#+TITLE: Inbox\n\n* Inbox\n\n** 手写旧条目\n   没有 :ID: 抽屉\n", encoding="utf-8"
        )
        with self.assertRaises(proposals.ProposalError) as ctx:
            self.create("inbox-whatever")
        self.assertEqual(ctx.exception.code, "LEGACY_UNTRACKED")
        self.assertFalse(self.proposals_file().exists(), "被拒时不写提案")

    def test_round_trip_parse_matches_created_result(self) -> None:
        inbox_id = self.seed_inbox()
        result = self.create(inbox_id)
        row = parse_one(self.proposals_file().read_text(encoding="utf-8"))
        self.assertEqual(row["id"], result.entity_id)
        self.assertEqual(row["status"], "PENDING")
        self.assertEqual(row["revision"], 1)
        self.assertEqual(row["source_inbox_id"], inbox_id)
        self.assertEqual(row["base_revision"], 1)
        self.assertEqual(row["plan_revision"], 1)
        self.assertEqual(row["created_by"], "ai")
        self.assertEqual([c["task_id"] for c in row["changes"]], result.task_ids)
        self.assertEqual(row["risks"], ["尚未确认参考模型所在 revision"])
        self.assertIn(":LOGBOOK:", self.proposals_file().read_text(encoding="utf-8"))
        self.assertIn(result.audit_event_id, self.proposals_file().read_text(encoding="utf-8"))

    def test_create_dry_run_writes_nothing(self) -> None:
        inbox_id = self.seed_inbox()
        result = self.create(inbox_id, dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertIsNotNone(result.line)
        self.assertFalse(self.proposals_file().exists())

    def test_create_source_inbox_cas_conflict_writes_nothing(self) -> None:
        inbox_id = self.seed_inbox()
        with self.assertRaises(proposals.ProposalError) as ctx:
            self.create(inbox_id, expected_revision=99)
        self.assertEqual(ctx.exception.code, "REVISION_CONFLICT")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertEqual(ctx.exception.extra["currentRevision"], 1)
        self.assertFalse(self.proposals_file().exists())

    def test_create_unknown_source_inbox_is_rejected(self) -> None:
        self.seed_inbox()
        with self.assertRaises(proposals.ProposalError) as ctx:
            self.create("inbox-does-not-exist")
        self.assertEqual(ctx.exception.code, "NOT_FOUND")
        self.assertFalse(self.proposals_file().exists())

    def test_create_rejects_non_add_changes(self) -> None:
        inbox_id = self.seed_inbox()
        with self.assertRaises(proposals.ProposalError) as ctx:
            self.create(inbox_id, changes=[{"op": "删除", "title": "不再需要"}])
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_CHANGE_OP")
        self.assertFalse(self.proposals_file().exists())

    def test_create_does_not_adopt_project_hint(self) -> None:
        inbox_id = self.seed_inbox(project_hint="demo")
        result = self.create(inbox_id, project=None)
        self.assertIsNone(result.project)
        self.assertEqual(result.extra["projectHint"], "demo")
        row = parse_one(self.proposals_file().read_text(encoding="utf-8"))
        self.assertIsNone(row["project"], "未确认的 hint 不得写进 :PM_PROJECT:")

    def test_create_idempotency_key_replay_appends_nothing(self) -> None:
        inbox_id = self.seed_inbox()
        first = self.create(inbox_id, idempotency_key="ck-1")
        after = self.digest(self.proposals_file())
        second = self.create(inbox_id, idempotency_key="ck-1")
        self.assertTrue(second.idempotent)
        self.assertFalse(second.changed)
        self.assertEqual(second.entity_id, first.entity_id)
        self.assertEqual(second.audit_event_id, first.audit_event_id)
        self.assertEqual(self.digest(self.proposals_file()), after, "重放不得追加第二条提案")
        self.assertEqual(proposals.list_proposals(self.library)["count"], 1)

    def test_create_dry_run_line_matches_real_write(self) -> None:
        inbox_id = self.seed_inbox()
        planned = self.create(inbox_id, dry_run=True)
        real = self.create(inbox_id)
        self.assertEqual(planned.line, real.line)

    def test_proposal_sections_are_real_headlines_and_file_has_title(self) -> None:
        inbox_id = self.seed_inbox()
        self.create(inbox_id)
        lines = self.proposals_file().read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "#+TITLE: Proposals")
        self.assertIn("*** 变更", lines)
        self.assertIn("*** 风险与待确认", lines)
        self.assertIn("*** 操作", lines)
        self.assertNotIn("   *** 变更", lines, "缩进后就不是 org 子标题了（Emacs 里不可折叠）")

    def test_change_criteria_round_trip(self) -> None:
        inbox_id = self.seed_inbox()
        self.create(inbox_id, changes=[{"op": "新增", "title": "t", "criteria": ["a", {"text": "b", "done": True}]}])
        row = parse_one(self.proposals_file().read_text(encoding="utf-8"))
        self.assertEqual(
            row["changes"][0]["criteria"],
            [{"text": "a", "done": False}, {"text": "b", "done": True}],
        )

    # ---- approve happy path ----

    def test_approve_creates_task_marks_inbox_and_approves_proposal(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        task_id = result.task_ids[0]
        tasks = self.layout.tasks_file("proj-demo")

        approved = proposals.approve(self.library, result.entity_id, expected_revision=1,
                                     actor="human", now=NOW)
        self.assertEqual(approved.entity_id, result.entity_id)
        self.assertEqual(approved.status, "APPROVED")
        self.assertEqual(approved.revision, 2)
        self.assertEqual(approved.previous_revision, 1)
        self.assertTrue(approved.changed)
        self.assertEqual(approved.source, "org")
        self.assertEqual(approved.task_ids, [task_id])
        self.assertEqual(approved.project, "proj-demo")
        self.assertEqual(approved.inbox_status, "TASK_CREATED")
        self.assertEqual(approved.inbox_revision, 3)
        self.assertRegex(approved.observed_at or "", r"^\d{4}-\d{2}-\d{2}T")
        self.assertRegex(approved.audit_event_id or "", r"^audit-[0-9A-HJKMNP-TV-Z]{26}$")
        self.assertEqual([s["status"] for s in approved.steps], ["written", "written", "written"])

        task_text = tasks.read_text(encoding="utf-8")
        self.assertIn(task_id, task_text)
        self.assertIn(":PM_KIND: task", task_text)
        self.assertIn(":PM_STATUS: TODO", task_text)
        self.assertIn(":PM_SOURCE_INBOX_ID: " + inbox_id, task_text, "任务必须回链 inbox")
        self.assertIn(":PM_SOURCE_PROPOSAL_ID: " + result.entity_id, task_text, "任务必须回链提案")

        inbox_text = self.layout.inbox.read_text(encoding="utf-8")
        self.assertIn(":PM_STATUS: TASK_CREATED", inbox_text)
        self.assertIn(":PM_REVISION: 3", inbox_text)
        self.assertIn(":PM_PROPOSAL_ID: " + result.entity_id, inbox_text)
        self.assertIn('State "TASK_PROPOSED" from "CAPTURED"', inbox_text, "create 先标 propose")
        self.assertIn('State "TASK_CREATED" from "TASK_PROPOSED"', inbox_text)
        self.assertIn("audit=", inbox_text)

        proposal_text = self.proposals_file().read_text(encoding="utf-8")
        self.assertIn(":PM_STATUS: APPROVED", proposal_text)
        self.assertIn(":PM_REVISION: 2", proposal_text)
        self.assertIn(":PM_TASK_IDS: " + task_id, proposal_text)
        self.assertIn('State "APPROVED" from "PENDING"', proposal_text)
        self.assertIn("audit=" + (approved.audit_event_id or ""), proposal_text)

    def test_approve_uses_proposal_project_without_explicit_flag(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        approved = proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(approved.project, "proj-demo")

    def test_approve_accepts_project_key_without_proj_prefix(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project("proj-demo")
        result = self.create(inbox_id, project=None)
        approved = proposals.approve(self.library, result.entity_id, expected_revision=1,
                                     project="demo", now=NOW)
        self.assertEqual(approved.project, "demo")
        self.assertTrue(self.layout.tasks_file("proj-demo").read_text(encoding="utf-8").count("** TODO ") == 1)

    # ---- CAS ----

    def test_approve_revision_conflict_writes_nothing(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        text = self.proposals_file().read_text(encoding="utf-8")
        self.proposals_file().write_text(text.replace(":PM_REVISION: 1", ":PM_REVISION: 7"), encoding="utf-8")
        digests = [self.digest(self.proposals_file()), self.digest(self.layout.inbox), self.digest(tasks)]

        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "REVISION_CONFLICT")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertEqual(ctx.exception.extra["currentRevision"], 7)
        self.assertEqual(ctx.exception.extra["expectedRevision"], 1)
        self.assertTrue(ctx.exception.extra["diffHint"])
        self.assertEqual(
            digests,
            [self.digest(self.proposals_file()), self.digest(self.layout.inbox), self.digest(tasks)],
            "冲突时三个文件必须逐字节不变",
        )

    def test_reject_revision_conflict_writes_nothing(self) -> None:
        inbox_id = self.seed_inbox()
        result = self.create(inbox_id)
        text = self.proposals_file().read_text(encoding="utf-8")
        self.proposals_file().write_text(text.replace(":PM_REVISION: 1", ":PM_REVISION: 4"), encoding="utf-8")
        before = self.digest(self.proposals_file())
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.reject(self.library, result.entity_id, expected_revision=1, reason="不要")
        self.assertEqual(ctx.exception.code, "REVISION_CONFLICT")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertEqual(self.digest(self.proposals_file()), before)

    # ---- reject ----

    def test_reject_changes_only_proposals_org(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        tasks_before = self.digest(tasks)
        inbox_before = self.digest(self.layout.inbox)

        rejected = proposals.reject(self.library, result.entity_id, expected_revision=1,
                                    reason="计划不完整", actor="human", now=NOW)
        self.assertEqual(rejected.status, "REJECTED")
        self.assertEqual(rejected.revision, 2)
        self.assertTrue(rejected.changed)
        self.assertRegex(rejected.audit_event_id or "", r"^audit-")
        text = self.proposals_file().read_text(encoding="utf-8")
        self.assertIn(":PM_STATUS: REJECTED", text)
        self.assertIn("reason=计划不完整", text)
        self.assertEqual(self.digest(tasks), tasks_before, "拒绝不得创建/改动正式任务")
        self.assertEqual(self.digest(self.layout.inbox), inbox_before, "拒绝不得改动 inbox")

    def test_reject_requires_reason(self) -> None:
        inbox_id = self.seed_inbox()
        result = self.create(inbox_id)
        before = self.digest(self.proposals_file())
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.reject(self.library, result.entity_id, expected_revision=1, reason="   ")
        self.assertEqual(ctx.exception.code, "INVALID_REASON")
        self.assertEqual(self.digest(self.proposals_file()), before)

    def test_reject_is_noop_when_already_rejected(self) -> None:
        inbox_id = self.seed_inbox()
        result = self.create(inbox_id)
        proposals.reject(self.library, result.entity_id, expected_revision=1, reason="第一次", now=NOW)
        after_first = self.digest(self.proposals_file())
        again = proposals.reject(self.library, result.entity_id, expected_revision=2, reason="第二次", now=NOW)
        self.assertFalse(again.changed)
        self.assertEqual(again.revision, 2)
        self.assertEqual(self.digest(self.proposals_file()), after_first)

    def test_reject_approved_proposal_is_refused(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        digests = [self.digest(self.proposals_file()), self.digest(self.layout.inbox), self.digest(tasks)]
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.reject(self.library, result.entity_id, expected_revision=2, reason="反悔")
        self.assertEqual(ctx.exception.code, "PROPOSAL_NOT_PENDING")
        self.assertEqual(digests, [self.digest(self.proposals_file()), self.digest(self.layout.inbox), self.digest(tasks)])

    # ---- approve on non-pending / inbox states ----

    def test_approve_rejected_proposal_is_refused_and_writes_nothing(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        proposals.reject(self.library, result.entity_id, expected_revision=1, reason="不做", now=NOW)
        digests = [self.digest(self.proposals_file()), self.digest(self.layout.inbox), self.digest(tasks)]
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=2, now=NOW)
        self.assertEqual(ctx.exception.code, "PROPOSAL_REJECTED")
        self.assertEqual(digests, [self.digest(self.proposals_file()), self.digest(self.layout.inbox), self.digest(tasks)])

    def test_second_approve_is_refused_without_duplicating_tasks(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        before = self.digest(tasks)
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=2, now=NOW)
        self.assertEqual(ctx.exception.code, "PROPOSAL_NOT_PENDING")
        self.assertEqual(self.digest(tasks), before)
        self.assertEqual(self.layout.tasks_file("proj-demo").read_text(encoding="utf-8").count("** TODO "), 1)

    def test_approve_from_captured_source_historical_proposal(self) -> None:
        """历史提案的源条目仍是 CAPTURED（老版本 create 不标记 inbox）→ approve 必须照常出任务。"""
        inbox_id = self.seed_inbox()  # CAPTURED rev 1
        tasks = self.make_project()
        entities.create_entity(
            self.proposals_file(),
            entity_id="proposal-historical",
            kind=proposals.PROPOSAL_KIND,
            status=proposals.STATUS_PENDING,
            headline=proposals.PROPOSAL_PREFIX + " 历史提案",
            section=proposals.PROPOSALS_SECTION,
            properties={
                "PM_SOURCE_INBOX_ID": inbox_id,
                "PM_BASE_REVISION": "1",
                "PM_PLAN_REVISION": "1",
                "PM_CREATED_BY": "ai",
                "PM_PROJECT": "proj-demo",
            },
            body_lines=proposals.proposal_body_lines(
                [{"op": "新增", "task_id": "task-historical", "title": "历史任务", "criteria": []}], [], None
            ),
            indent_body=False,
            actor="ai",
            now=NOW,
        )
        approved = proposals.approve(self.library, "proposal-historical", expected_revision=1, now=NOW)
        self.assertEqual(approved.status, "APPROVED")
        self.assertEqual(approved.task_ids, ["task-historical"])
        self.assertEqual(approved.inbox_revision, 2)
        inbox_text = self.layout.inbox.read_text(encoding="utf-8")
        self.assertIn(":PM_STATUS: TASK_CREATED", inbox_text)
        self.assertIn('State "TASK_CREATED" from "CAPTURED"', inbox_text, "历史提案直接从 CAPTURED 批准")
        self.assertEqual(tasks.read_text(encoding="utf-8").count("** TODO "), 1)

    def test_approve_refuses_inbox_already_created_by_other_proposal(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=2, status="TASK_CREATED",
                              set_properties={"PM_PROPOSAL_ID": "proposal-other"}, headline="Inbox", now=NOW)
        digests = [self.digest(self.proposals_file()), self.digest(self.layout.inbox), self.digest(tasks)]
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "ALREADY_TASK_CREATED")
        self.assertEqual(digests, [self.digest(self.proposals_file()), self.digest(self.layout.inbox), self.digest(tasks)])

    def test_approve_refuses_terminal_inbox_status(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=2, status="MERGED",
                              headline="Inbox", now=NOW)
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "PROPOSAL_SOURCE_NOT_ACTIONABLE")
        self.assertEqual(self.layout.tasks_file("proj-demo").read_text(encoding="utf-8").count("** TODO "), 0)

    def test_approve_refuses_when_source_inbox_is_gone(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        self.layout.inbox.write_text("* Inbox\n", encoding="utf-8")
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "PROPOSAL_SOURCE_NOT_FOUND")
        self.assertEqual(self.layout.tasks_file("proj-demo").read_text(encoding="utf-8").count("** TODO "), 0)

    # ---- project resolution ----

    def test_approve_project_required_carries_hint(self) -> None:
        inbox_id = self.seed_inbox(project_hint="demo")
        result = self.create(inbox_id, project=None)
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "PROJECT_REQUIRED")
        self.assertEqual(ctx.exception.extra["projectHint"], "demo", "hint 只能预填，不能自动建立关联")

    def test_approve_project_required_without_hint(self) -> None:
        inbox_id = self.seed_inbox()
        result = self.create(inbox_id, project=None)
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "PROJECT_REQUIRED")
        self.assertIsNone(ctx.exception.extra["projectHint"])

    def test_approve_missing_project_dir_writes_nothing(self) -> None:
        inbox_id = self.seed_inbox()
        result = self.create(inbox_id, project="no-such-project")
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "PROJECT_NOT_FOUND")
        text = self.proposals_file().read_text(encoding="utf-8")
        self.assertIn(":PM_STATUS: PENDING", text)

    # ---- dry-run / idempotency ----

    def test_approve_dry_run_writes_nothing(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        digests = [self.digest(self.proposals_file()), self.digest(self.layout.inbox), self.digest(tasks)]
        planned = proposals.approve(self.library, result.entity_id, expected_revision=1, dry_run=True, now=NOW)
        self.assertTrue(planned.dry_run)
        self.assertEqual(planned.status, "APPROVED")
        self.assertEqual(planned.revision, 2)
        self.assertEqual([s["status"] for s in planned.steps], ["planned", "planned", "planned"])
        self.assertEqual(digests, [self.digest(self.proposals_file()), self.digest(self.layout.inbox), self.digest(tasks)])

    def test_approve_idempotency_key_replay_returns_first_audit(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        first = proposals.approve(self.library, result.entity_id, expected_revision=1,
                                  idempotency_key="ak-1", now=NOW)
        after = self.digest(tasks)
        second = proposals.approve(self.library, result.entity_id, expected_revision=2,
                                   idempotency_key="ak-1", now=NOW)
        self.assertTrue(second.idempotent)
        self.assertFalse(second.changed)
        self.assertEqual(second.audit_event_id, first.audit_event_id)
        self.assertEqual(second.observed_at, first.observed_at)
        self.assertEqual(self.digest(tasks), after, "重放不得创建第二个任务")
        self.assertEqual(tasks.read_text(encoding="utf-8").count("** TODO "), 1)

    def test_reject_idempotency_key_replay_returns_first_audit(self) -> None:
        inbox_id = self.seed_inbox()
        result = self.create(inbox_id)
        first = proposals.reject(self.library, result.entity_id, expected_revision=1,
                                 reason="不要", idempotency_key="rk-1", now=NOW)
        after = self.digest(self.proposals_file())
        second = proposals.reject(self.library, result.entity_id, expected_revision=2,
                                  reason="不要", idempotency_key="rk-1", now=NOW)
        self.assertTrue(second.idempotent)
        self.assertEqual(second.audit_event_id, first.audit_event_id)
        self.assertEqual(second.observed_at, first.observed_at)
        self.assertEqual(self.digest(self.proposals_file()), after, "重放不得产生第二次变更")

    # ---- 收敛：断点重试 ----

    def test_retry_converges_when_tasks_and_inbox_already_done(self) -> None:
        """tasks + inbox 已由本提案完成、proposals 未写 → 重跑必须收敛，不报 ALREADY_TASK_CREATED。"""
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        task_id = result.task_ids[0]
        entities.create_entity(
            tasks, entity_id=task_id, kind="task", status="TODO",
            headline="TODO 明确输入范围", section="任务",
            properties={"PM_SOURCE_INBOX_ID": inbox_id, "PM_SOURCE_PROPOSAL_ID": result.entity_id},
            actor="human", now=NOW,
        )
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=2, status="TASK_CREATED",
                              set_properties={"PM_PROPOSAL_ID": result.entity_id}, headline="Inbox", now=NOW)

        approved = proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(approved.status, "APPROVED")
        self.assertEqual([s["status"] for s in approved.steps], ["skipped", "skipped", "written"])
        self.assertEqual(tasks.read_text(encoding="utf-8").count("** TODO "), 1, "不得重复创建任务")
        self.assertIn(":PM_STATUS: APPROVED", self.proposals_file().read_text(encoding="utf-8"))

    def test_partial_write_is_reported_and_then_retry_converges(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        real_apply_change = entities.apply_change

        def fake(path, entity_id, **kwargs):
            if entity_id == result.entity_id and kwargs.get("status") == "APPROVED":
                raise entities.EntityError("BOOM", "模拟 proposals.org 写失败")
            return real_apply_change(path, entity_id, **kwargs)

        with mock.patch.object(entities, "apply_change", side_effect=fake):
            with self.assertRaises(proposals.ProposalError) as ctx:
                proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        error = ctx.exception
        self.assertEqual(error.code, "PARTIAL_WRITE")
        self.assertIn("非原子", error.message)
        self.assertIn("补偿式", error.message)
        self.assertIn("task:" + result.task_ids[0], error.extra["written"])
        self.assertIn("inbox", error.extra["written"])
        self.assertIn("proposal", error.extra["notWritten"])
        self.assertEqual(error.extra["failedStep"], "proposal")
        # 前两步确实落地了：任务在、inbox 已 TASK_CREATED，提案仍是 PENDING
        self.assertIn(result.task_ids[0], tasks.read_text(encoding="utf-8"))
        self.assertIn(":PM_STATUS: TASK_CREATED", self.layout.inbox.read_text(encoding="utf-8"))
        self.assertIn(":PM_STATUS: PENDING", self.proposals_file().read_text(encoding="utf-8"))

        # 重跑：靠回链跳过已完成的两步，收敛到 APPROVED
        approved = proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(approved.status, "APPROVED")
        self.assertEqual([s["status"] for s in approved.steps], ["skipped", "skipped", "written"])
        self.assertEqual(tasks.read_text(encoding="utf-8").count("** TODO "), 1)

    def test_approve_rejects_key_that_was_used_for_a_reject(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        proposals.reject(self.library, result.entity_id, expected_revision=1,
                         reason="不要", idempotency_key="shared-key", now=NOW)
        after = self.digest(self.proposals_file())
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=2,
                              idempotency_key="shared-key", now=NOW)
        self.assertEqual(ctx.exception.code, "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(self.digest(self.proposals_file()), after)

    def test_approve_stale_plan_refused_then_allow_stale_overrides(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)  # create 已把 inbox 标成 TASK_PROPOSED(rev2)，PM_BASE_REVISION = 1
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=2, status="TRIAGE",
                              headline="Inbox", now=NOW)
        digests = [self.digest(self.proposals_file()), self.digest(self.layout.inbox), self.digest(tasks)]
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "STALE_PLAN")
        self.assertEqual(ctx.exception.extra["baseRevision"], 1)
        self.assertEqual(ctx.exception.extra["currentRevision"], 3)
        self.assertEqual(ctx.exception.extra["inboxId"], inbox_id)
        self.assertEqual(
            digests,
            [self.digest(self.proposals_file()), self.digest(self.layout.inbox), self.digest(tasks)],
            "STALE_PLAN 必须一个字节都不写",
        )

        approved = proposals.approve(self.library, result.entity_id, expected_revision=1,
                                     allow_stale=True, now=NOW)
        self.assertEqual(approved.status, "APPROVED")
        self.assertTrue(approved.extra["staleOverride"])
        self.assertEqual(approved.inbox_revision, 4)
        self.assertIn("stale=override", self.proposals_file().read_text(encoding="utf-8"),
                      "覆盖 STALE_PLAN 必须在审计里留痕")

    def test_partial_failure_after_prior_steps_reports_already_done(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        task_id = result.task_ids[0]
        entities.create_entity(
            tasks, entity_id=task_id, kind="task", status="TODO", headline="TODO x", section="任务",
            properties={"PM_SOURCE_PROPOSAL_ID": result.entity_id}, actor="human", now=NOW,
        )
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=2, status="TASK_CREATED",
                              set_properties={"PM_PROPOSAL_ID": result.entity_id}, headline="Inbox", now=NOW)
        real_apply_change = entities.apply_change

        def fake(path, entity_id, **kwargs):
            if entity_id == result.entity_id and kwargs.get("status") == "APPROVED":
                raise entities.EntityError("BOOM", "又失败了")
            return real_apply_change(path, entity_id, **kwargs)

        with mock.patch.object(entities, "apply_change", side_effect=fake):
            with self.assertRaises(proposals.ProposalError) as ctx:
                proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "PARTIAL_WRITE")
        self.assertEqual(ctx.exception.extra["written"], [])
        self.assertEqual(ctx.exception.extra["alreadyDone"], ["task:" + task_id, "inbox"])
        self.assertEqual(ctx.exception.extra["notWritten"], ["proposal"])
        self.assertIn("此前已完成", ctx.exception.message)

    def test_first_step_failure_writes_nothing_and_is_not_partial(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        digest_tasks = self.digest(tasks)
        digest_inbox = self.digest(self.layout.inbox)

        def fake_create(*args, **kwargs):
            raise entities.EntityError("REVISION_CONFLICT", "模拟建任务失败", exit_code=3)

        with mock.patch.object(entities, "create_entity", side_effect=fake_create):
            with self.assertRaises(proposals.ProposalError) as ctx:
                proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        # 第一步（建任务）就失败：不是 PARTIAL，原样抛出 CAS 冲突
        self.assertEqual(ctx.exception.code, "REVISION_CONFLICT")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertEqual(self.digest(tasks), digest_tasks)
        self.assertEqual(self.digest(self.layout.inbox), digest_inbox)
        self.assertIn(":PM_STATUS: PENDING", self.proposals_file().read_text(encoding="utf-8"))

    # ---- 汇编 / 事务元数据 ----

    def test_written_and_not_written_are_exposed_on_success(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        approved = proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(approved.extra["notWritten"], [])
        self.assertEqual(sorted(approved.extra["written"]),
                         sorted(["task:" + result.task_ids[0], "inbox", "proposal"]))

    def test_no_temp_files_left_behind(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        leftovers = [p for p in self.library.rglob("*.pm-tmp")]
        self.assertEqual(leftovers, [], "原子写的临时文件必须清理干净")

    def test_list_proposals_filters_and_reports_legacy(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.proposals_file().write_text(
            self.proposals_file().read_text(encoding="utf-8") + "\n** PROPOSAL 手写旧条目\n",
            encoding="utf-8",
        )
        payload = proposals.list_proposals(self.library)
        statuses = [row["status"] for row in payload["proposals"]]
        self.assertIn("APPROVED", statuses)
        self.assertIn("LEGACY_UNTRACKED", statuses)
        self.assertEqual(payload["count"], len(payload["proposals"]))
        only = proposals.list_proposals(self.library, status="APPROVED")
        self.assertEqual(only["count"], 1)
        self.assertEqual(proposals.list_proposals(self.library / "nope")["count"], 0)

    def test_approved_task_round_trips_through_pm_tasks(self) -> None:
        """跨模块接缝：approve 创建的任务必须能被 pm task list/show 的解析器读出。"""
        from pm import tasks as tasks_mod

        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(
            inbox_id,
            changes=[{"op": "新增", "title": "明确输入范围", "criteria": ["可复现", "有证据"]}],
        )
        approved = proposals.approve(self.library, result.entity_id, expected_revision=1,
                                     actor="ai", now=NOW)
        text = self.layout.tasks_file("proj-demo").read_text(encoding="utf-8")
        records = tasks_mod.parse_tasks(text)
        task = tasks_mod.find_task(records, result.task_ids[0])
        self.assertIsNotNone(task, "approve 创建的任务必须能被 pm.tasks 解析出来")
        self.assertEqual(task["properties"].get("PM_KIND"), "task")
        self.assertEqual(task["status"], "TODO", "任务状态要与 approve 声明的初态一致")
        self.assertFalse(task["status_mismatch"])
        self.assertEqual(task["source_inbox_id"], inbox_id, "回链 inbox 必须保留")
        self.assertEqual(task["properties"].get("PM_SOURCE_PROPOSAL_ID"), result.entity_id,
                         "回链提案必须保留")
        self.assertTrue(task["has_criteria"], "验收标准必须是真正的 *** 子标题")
        self.assertEqual([c["text"] for c in task["criteria"]], ["可复现", "有证据"])
        self.assertEqual(approved.task_ids, [task["id"]])

    # ---- revise：保留 ID / 重挂 base / plan rev +1 / 不碰 inbox 与 tasks ----

    def test_revise_repoints_base_and_replaces_content(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)  # base=1，inbox TASK_PROPOSED rev2
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=2, status="TRIAGE",
                              headline="Inbox", now=NOW)  # 源被外部改到 rev3
        inbox_before = self.digest(self.layout.inbox)
        tasks_before = self.digest(tasks)

        revised = proposals.revise(
            self.library, result.entity_id, expected_revision=1,
            title="改过的计划",
            changes=[{"op": "新增", "title": "新任务", "criteria": ["可复现"]}],
            risks=["新风险"], actions=["新操作"], reason="重挂", actor="human", now=NOW,
        )
        self.assertEqual(revised.status, "PENDING")
        self.assertEqual(revised.revision, 2)
        self.assertEqual(revised.plan_revision, 2)
        self.assertEqual(revised.base_revision, 3)
        self.assertEqual(revised.extra["prevBaseRevision"], 1)
        self.assertEqual(revised.extra["sourceInboxRevision"], 3)
        self.assertEqual(revised.extra["written"], ["proposals.org"])
        self.assertEqual(revised.extra["notWritten"], [])
        self.assertRegex(revised.audit_event_id or "", r"^audit-")
        self.assertEqual(self.digest(self.layout.inbox), inbox_before, "revise 不得改源 inbox")
        self.assertEqual(self.digest(tasks), tasks_before, "revise 不得碰 tasks.org")

        row = parse_one(self.proposals_file().read_text(encoding="utf-8"))
        self.assertEqual(row["id"], result.entity_id, "proposal id 必须保留")
        self.assertEqual(row["title"], "改过的计划")
        self.assertEqual(row["plan_revision"], 2)
        self.assertEqual(row["base_revision"], 3)
        self.assertEqual(row["changes"][0]["title"], "新任务")
        self.assertEqual([c["text"] for c in row["changes"][0]["criteria"]], ["可复现"])
        self.assertEqual(row["risks"], ["新风险"])
        self.assertEqual(row["actions"], ["新操作"])

        audit = self.proposals_file().read_text(encoding="utf-8")
        self.assertIn("op=revise", audit)
        self.assertIn("planRev=2", audit)
        self.assertIn("basedOnInboxRevision=3", audit)
        self.assertIn("prevBaseRevision=1", audit)
        self.assertIn("reason=重挂", audit)

    def test_revise_without_content_keeps_plan(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=2, status="TRIAGE",
                              headline="Inbox", now=NOW)
        proposals.revise(self.library, result.entity_id, expected_revision=1, now=NOW)
        row = parse_one(self.proposals_file().read_text(encoding="utf-8"))
        self.assertEqual(row["changes"][0]["title"], "明确输入范围", "没给 changes 就保持原计划")
        self.assertEqual(row["base_revision"], 3)
        self.assertEqual(row["plan_revision"], 2)

    def test_revise_then_approve_does_not_trigger_stale_plan(self) -> None:
        inbox_id = self.seed_inbox()
        tasks = self.make_project()
        result = self.create(inbox_id)
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=2, status="TRIAGE",
                              headline="Inbox", now=NOW)
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "STALE_PLAN")

        revised = proposals.revise(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(revised.base_revision, 3)
        approved = proposals.approve(self.library, result.entity_id, expected_revision=2, now=NOW)
        self.assertEqual(approved.status, "APPROVED", "revise 之后再 approve 不应触发 STALE_PLAN")
        self.assertEqual(approved.inbox_status, "TASK_CREATED")
        self.assertEqual(approved.task_ids, result.task_ids)
        self.assertEqual(tasks.read_text(encoding="utf-8").count("** TODO "), 1)

    def test_revise_again_after_source_changes_converges(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=2, status="TRIAGE",
                              headline="Inbox", now=NOW)  # rev3
        proposals.revise(self.library, result.entity_id, expected_revision=1, now=NOW)  # base3, rev2
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=3, status="CAPTURED",
                              headline="Inbox", now=NOW)  # rev4
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=2, now=NOW)
        self.assertEqual(ctx.exception.code, "STALE_PLAN")
        revised = proposals.revise(self.library, result.entity_id, expected_revision=2, now=NOW)
        self.assertEqual(revised.base_revision, 4)
        approved = proposals.approve(self.library, result.entity_id, expected_revision=3, now=NOW)
        self.assertEqual(approved.status, "APPROVED")

    def test_revise_terminal_proposal_rejected(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        proposals.reject(self.library, result.entity_id, expected_revision=1, reason="不做", now=NOW)
        before = self.digest(self.proposals_file())
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.revise(self.library, result.entity_id, expected_revision=2, now=NOW)
        self.assertEqual(ctx.exception.code, "PROPOSAL_NOT_REVISABLE")
        self.assertEqual(ctx.exception.extra["status"], "REJECTED")
        self.assertEqual(self.digest(self.proposals_file()), before, "终态被拒时不写")

        other = self.seed_inbox()
        result2 = self.create(other)
        proposals.approve(self.library, result2.entity_id, expected_revision=1, now=NOW)
        with self.assertRaises(proposals.ProposalError) as ctx2:
            proposals.revise(self.library, result2.entity_id, expected_revision=2, now=NOW)
        self.assertEqual(ctx2.exception.code, "PROPOSAL_NOT_REVISABLE")
        self.assertEqual(ctx2.exception.extra["status"], "APPROVED")

    def test_revise_cas_conflict_writes_nothing(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        before = self.digest(self.proposals_file())
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.revise(self.library, result.entity_id, expected_revision=7, now=NOW)
        self.assertEqual(ctx.exception.code, "REVISION_CONFLICT")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertEqual(ctx.exception.extra["currentRevision"], 1)
        self.assertEqual(self.digest(self.proposals_file()), before)

    def test_revise_dry_run_writes_nothing(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        before = self.digest(self.proposals_file())
        revised = proposals.revise(self.library, result.entity_id, expected_revision=1,
                                   title="预演标题", dry_run=True, now=NOW)
        self.assertTrue(revised.dry_run)
        self.assertEqual(revised.extra["written"], [])
        self.assertEqual(self.digest(self.proposals_file()), before)
        self.assertEqual(parse_one(self.proposals_file().read_text(encoding="utf-8"))["plan_revision"], 1)

    def test_revise_idempotency_key_replay(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        first = proposals.revise(self.library, result.entity_id, expected_revision=1,
                                 idempotency_key="rv-1", now=NOW)
        after = self.digest(self.proposals_file())
        second = proposals.revise(self.library, result.entity_id, expected_revision=2,
                                  idempotency_key="rv-1", now=NOW)
        self.assertTrue(second.idempotent)
        self.assertEqual(second.audit_event_id, first.audit_event_id)
        self.assertEqual(second.plan_revision, 2)
        self.assertEqual(self.digest(self.proposals_file()), after, "重放不得第二次变更")

    def test_revise_rejects_illegal_change_op(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        before = self.digest(self.proposals_file())
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.revise(self.library, result.entity_id, expected_revision=1,
                             changes=[{"op": "删除", "title": "x"}], now=NOW)
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_CHANGE_OP")
        self.assertEqual(self.digest(self.proposals_file()), before)

    def test_revise_source_task_created_rejected(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=2, status="TASK_CREATED",
                              headline="Inbox", now=NOW)
        before = self.digest(self.proposals_file())
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.revise(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "ALREADY_TASK_CREATED")
        self.assertEqual(self.digest(self.proposals_file()), before)

    def test_revise_content_without_replace_body_reports_capability_gap(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        before = self.digest(self.proposals_file())
        with mock.patch.object(proposals, "_has_replace_body", return_value=False):
            with self.assertRaises(proposals.ProposalError) as ctx:
                proposals.revise(self.library, result.entity_id, expected_revision=1,
                                 changes=[{"op": "新增", "title": "x"}], now=NOW)
        self.assertEqual(ctx.exception.code, "ENTITY_CAPABILITY_MISSING")
        self.assertEqual(self.digest(self.proposals_file()), before)

    # ---- STALE 判定矩阵（task-60 / docs 06） ----

    def test_matrix_create_then_approve_is_not_stale(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        self.assertEqual(proposals.approve(self.library, result.entity_id, expected_revision=1,
                                           now=NOW).status, "APPROVED")

    def test_matrix_create_source_change_then_approve_is_stale(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=2, status="TRIAGE",
                              headline="Inbox", now=NOW)
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "STALE_PLAN")

    def test_matrix_revise_then_source_change_then_approve_is_stale(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        proposals.revise(self.library, result.entity_id, expected_revision=1, now=NOW)  # base2
        entities.apply_change(self.layout.inbox, inbox_id, expected_revision=2, status="CAPTURED",
                              headline="Inbox", now=NOW)  # rev3
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, result.entity_id, expected_revision=2, now=NOW)
        self.assertEqual(ctx.exception.code, "STALE_PLAN")

    def test_matrix_legacy_marker_recovered_from_audit_line(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        text = self.layout.inbox.read_text(encoding="utf-8")
        self.layout.inbox.write_text(
            "\n".join(line for line in text.split("\n") if "PM_PROPOSED_REVISION" not in line),
            encoding="utf-8",
        )
        approved = proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(approved.status, "APPROVED", "老数据从审计行恢复 marker=2，base=1 不陈旧")

    def test_matrix_without_marker_or_audit_falls_back_to_minus_one(self) -> None:
        inbox_id = self.seed_inbox()
        self.make_project()
        result = self.create(inbox_id)
        text = self.layout.inbox.read_text(encoding="utf-8")
        self.layout.inbox.write_text(
            "\n".join(
                line for line in text.split("\n")
                if "PM_PROPOSED_REVISION" not in line and "op=propose" not in line
            ),
            encoding="utf-8",
        )
        approved = proposals.approve(self.library, result.entity_id, expected_revision=1, now=NOW)
        self.assertEqual(approved.status, "APPROVED", "完全取不到 marker 时回落 base == inbox-1")

    def test_unknown_proposal_is_not_found(self) -> None:
        inbox_id = self.seed_inbox()
        self.create(inbox_id)
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(self.library, "proposal-nope", expected_revision=1, now=NOW)
        self.assertEqual(ctx.exception.code, "NOT_FOUND")


class ProposalCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.library = self.base / "wm"
        self.library.mkdir()
        self.layout = Layout(self.library)
        self.config = self.base / "pm.toml"
        self.config.write_text('library = "' + str(self.library) + '"\n', encoding="utf-8")
        self.tasks = self.layout.tasks_file("proj-demo")
        self.tasks.parent.mkdir(parents=True, exist_ok=True)
        self.tasks.write_text("#+TITLE: demo\n\n* 任务\n", encoding="utf-8")
        self.inbox_id = capture_text(self.library, "验证外部参考模型", source="cli", model="test", now=NOW).inbox_id

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

    def create_via_cli(self, *extra: str) -> dict:
        code, stdout, stderr = self.pm(
            "proposal", "create",
            "--source-inbox", self.inbox_id,
            "--change", "新增：明确输入范围",
            "--project", "proj-demo",
            "--json", *extra,
        )
        self.assertEqual(code, 0, stderr)
        return json.loads(stdout)

    def test_cli_create_list_show_approve(self) -> None:
        payload = self.create_via_cli()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "PENDING")
        self.assertEqual(payload["revision"], 1)
        self.assertEqual(payload["source"], "org")
        self.assertEqual(payload["sourceInboxId"], self.inbox_id)
        self.assertTrue(payload["taskIds"][0].startswith("task-"))
        self.assertRegex(payload["auditEventId"], r"^audit-")
        self.assertEqual(payload["path"], "proposals.org")
        self.assertEqual(payload["written"], ["proposals.org", "inbox.org"])
        self.assertEqual(payload["notWritten"], [])
        self.assertEqual(payload["inbox"]["id"], self.inbox_id)
        self.assertEqual(payload["inbox"]["status"], "TASK_PROPOSED")
        self.assertEqual(payload["inbox"]["revision"], 2)
        self.assertFalse(payload.get("partial", False))

        code, stdout, _ = self.pm("proposal", "list", "--json")
        self.assertEqual(code, 0)
        listing = json.loads(stdout)
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["proposals"][0]["id"], payload["proposalId"])

        code, stdout, _ = self.pm("proposal", "show", payload["proposalId"], "--json")
        self.assertEqual(code, 0)
        shown = json.loads(stdout)["proposal"]
        self.assertEqual(shown["status"], "PENDING")
        self.assertEqual(shown["changes"][0]["title"], "明确输入范围")

        code, stdout, stderr = self.pm(
            "proposal", "approve", payload["proposalId"],
            "--expected-revision", "1", "--actor", "human", "--json",
        )
        self.assertEqual(code, 0, stderr)
        approved = json.loads(stdout)
        self.assertEqual(approved["status"], "APPROVED")
        self.assertEqual(approved["revision"], 2)
        self.assertEqual(approved["entityId"], payload["proposalId"])
        self.assertEqual(approved["taskIds"], payload["taskIds"])
        self.assertIn(":PM_SOURCE_PROPOSAL_ID: " + payload["proposalId"],
                      self.tasks.read_text(encoding="utf-8"))

    def test_cli_create_idempotency_key_replay(self) -> None:
        first = self.create_via_cli("--idempotency-key", "ck-1")
        after = self.layout.proposals_file.read_bytes()
        second = self.create_via_cli("--idempotency-key", "ck-1")
        self.assertTrue(second["idempotent"])
        self.assertEqual(second["proposalId"], first["proposalId"])
        self.assertEqual(second["auditEventId"], first["auditEventId"])
        self.assertEqual(self.layout.proposals_file.read_bytes(), after)

    def test_cli_approve_stale_plan_and_allow_stale(self) -> None:
        payload = self.create_via_cli()
        entities.apply_change(self.layout.inbox, self.inbox_id, expected_revision=2,
                              status="TRIAGE", headline="Inbox", now=NOW)
        code, stdout, _ = self.pm("proposal", "approve", payload["proposalId"],
                                  "--expected-revision", "1", "--json")
        self.assertEqual(code, 2)
        error = json.loads(stdout)
        self.assertEqual(error["error"]["code"], "STALE_PLAN")
        self.assertEqual(error["baseRevision"], 1)
        self.assertEqual(error["currentRevision"], 3)
        code, stdout, stderr = self.pm("proposal", "approve", payload["proposalId"],
                                       "--expected-revision", "1", "--allow-stale", "--json")
        self.assertEqual(code, 0, stderr)
        self.assertTrue(json.loads(stdout)["staleOverride"])

    def test_cli_create_criterion_reaches_the_task(self) -> None:
        from pm import tasks as tasks_mod

        code, stdout, stderr = self.pm(
            "proposal", "create", "--source-inbox", self.inbox_id,
            "--change", "新增：明确输入范围",
            "--criterion", "可复现", "--criterion", "有证据",
            "--project", "proj-demo", "--json",
        )
        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        code, shown, _ = self.pm("proposal", "show", payload["proposalId"], "--json")
        self.assertEqual(code, 0)
        row = json.loads(shown)["proposal"]
        self.assertEqual([c["text"] for c in row["changes"][0]["criteria"]], ["可复现", "有证据"])

        code, stdout, stderr = self.pm("proposal", "approve", payload["proposalId"],
                                       "--expected-revision", "1", "--json")
        self.assertEqual(code, 0, stderr)
        text = self.layout.tasks_file("proj-demo").read_text(encoding="utf-8")
        task = tasks_mod.find_task(tasks_mod.parse_tasks(text), payload["taskIds"][0])
        self.assertEqual([c["text"] for c in task["criteria"]], ["可复现", "有证据"])

    def test_cli_create_criterion_with_multiple_changes_is_rejected(self) -> None:
        code, stdout, _ = self.pm(
            "proposal", "create", "--source-inbox", self.inbox_id,
            "--change", "新增：a", "--change", "新增：b", "--criterion", "x", "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "CRITERION_AMBIGUOUS")
        self.assertFalse(self.layout.proposals_file.exists(), "被拒绝时不得写")

    def test_cli_change_json_object_carries_criteria(self) -> None:
        json_change = '{"op": "新增", "title": "JSON 变更", "criteria": ["a", {"text": "b", "done": true}]}'
        code, stdout, stderr = self.pm(
            "proposal", "create", "--source-inbox", self.inbox_id,
            "--change", json_change, "--project", "proj-demo", "--json",
        )
        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        code, shown, _ = self.pm("proposal", "show", payload["proposalId"], "--json")
        self.assertEqual(code, 0)
        row = json.loads(shown)["proposal"]
        self.assertEqual(row["changes"][0]["title"], "JSON 变更")
        self.assertEqual(
            row["changes"][0]["criteria"],
            [{"text": "a", "done": False}, {"text": "b", "done": True}],
        )

    def test_cli_create_partial_when_inbox_cas_fails(self) -> None:
        before = self.layout.inbox.read_bytes()

        def boom(*args, **kwargs):
            raise entities.EntityError("NOT_FOUND", "模拟条目在 CAS 前消失")

        with mock.patch.object(proposals, "_mark_inbox_proposed", side_effect=boom):
            code, stdout, _ = self.pm(
                "proposal", "create", "--source-inbox", self.inbox_id,
                "--change", "新增：x", "--project", "proj-demo", "--json",
            )
        self.assertEqual(code, 2)
        error = json.loads(stdout)
        self.assertEqual(error["error"]["code"], "PARTIAL_WRITE")
        self.assertTrue(error["partial"])
        self.assertEqual(error["written"], ["proposals.org"])
        self.assertEqual(error["notWritten"], ["inbox.org"])
        self.assertIn("pm inbox set-status", error["hint"])
        self.assertEqual(self.layout.inbox.read_bytes(), before)
        self.assertEqual(proposals.list_proposals(self.library)["count"], 1,
                         "party 失败但提案已落盘，仍可 list/show")

    def test_cli_create_duplicate_rejected_and_allow_duplicate(self) -> None:
        payload = self.create_via_cli()
        code, stdout, _ = self.pm(
            "proposal", "create", "--source-inbox", self.inbox_id,
            "--change", "新增：另一条", "--project", "proj-demo", "--json",
        )
        self.assertEqual(code, 2)
        error = json.loads(stdout)
        self.assertEqual(error["error"]["code"], "PROPOSAL_EXISTS_FOR_INBOX")
        self.assertEqual(error["existingProposalId"], payload["proposalId"])

        code, stdout, stderr = self.pm(
            "proposal", "create", "--source-inbox", self.inbox_id,
            "--change", "新增：另一条", "--project", "proj-demo", "--allow-duplicate", "--json",
        )
        self.assertEqual(code, 0, stderr)
        self.assertNotEqual(json.loads(stdout)["proposalId"], payload["proposalId"])

    def test_cli_revise_shape_content_and_approve(self) -> None:
        payload = self.create_via_cli()
        entities.apply_change(self.layout.inbox, self.inbox_id, expected_revision=2, status="TRIAGE",
                              headline="Inbox", now=NOW)
        code, stdout, stderr = self.pm(
            "proposal", "revise", payload["proposalId"], "--expected-revision", "1",
            "--title", "改过的计划", "--change", "新增：新任务", "--criterion", "可复现",
            "--risk", "新风险", "--action", "新操作", "--json",
        )
        self.assertEqual(code, 0, stderr)
        revised = json.loads(stdout)
        self.assertEqual(revised["proposalId"], payload["proposalId"])
        self.assertEqual(revised["status"], "PENDING")
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["planRevision"], 2)
        self.assertEqual(revised["baseRevision"], 3)
        self.assertEqual(revised["sourceInboxRevision"], 3)
        self.assertEqual(revised["written"], ["proposals.org"])
        self.assertEqual(revised["inbox"]["status"], "TRIAGE", "revise 不改源 inbox 状态，只回报当前值")
        self.assertIn("op=revise", self.layout.proposals_file.read_text(encoding="utf-8"))

        code, stdout, stderr = self.pm("proposal", "approve", payload["proposalId"],
                                       "--expected-revision", "2", "--json")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["status"], "APPROVED", "revise 后 approve 无 STALE_PLAN")

    def test_cli_revise_change_op_flags(self) -> None:
        payload = self.create_via_cli()
        code, stdout, stderr = self.pm(
            "proposal", "revise", payload["proposalId"], "--expected-revision", "1",
            "--change-op", "新增", "--change-title", "来自 flag 的任务", "--json",
        )
        self.assertEqual(code, 0, stderr)
        code, shown, _ = self.pm("proposal", "show", payload["proposalId"], "--json")
        self.assertEqual(code, 0)
        row = json.loads(shown)["proposal"]
        self.assertEqual(row["changes"][0]["title"], "来自 flag 的任务")

    def test_cli_revise_terminal_rejected(self) -> None:
        payload = self.create_via_cli()
        code, _, _ = self.pm("proposal", "reject", payload["proposalId"],
                             "--expected-revision", "1", "--reason", "不做", "--json")
        self.assertEqual(code, 0)
        code, stdout, _ = self.pm("proposal", "revise", payload["proposalId"],
                                  "--expected-revision", "2", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "PROPOSAL_NOT_REVISABLE")

    def test_cli_reject(self) -> None:
        payload = self.create_via_cli()
        code, stdout, stderr = self.pm(
            "proposal", "reject", payload["proposalId"],
            "--expected-revision", "1", "--reason", "计划不完整", "--json",
        )
        self.assertEqual(code, 0, stderr)
        rejected = json.loads(stdout)
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(rejected["revision"], 2)
        self.assertEqual(self.tasks.read_text(encoding="utf-8").count("** TODO "), 0)

    def test_cli_reject_requires_reason(self) -> None:
        payload = self.create_via_cli()
        before = self.layout.proposals_file.read_bytes()
        code, stdout, _ = self.pm("proposal", "reject", payload["proposalId"],
                                  "--expected-revision", "1", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(self.layout.proposals_file.read_bytes(), before)

    def test_cli_approve_conflict_exit_code_3(self) -> None:
        payload = self.create_via_cli()
        text = self.layout.proposals_file.read_text(encoding="utf-8")
        self.layout.proposals_file.write_text(text.replace(":PM_REVISION: 1", ":PM_REVISION: 9"), encoding="utf-8")
        before = self.layout.proposals_file.read_bytes()
        code, stdout, stderr = self.pm("proposal", "approve", payload["proposalId"],
                                       "--expected-revision", "1", "--json")
        self.assertEqual(code, 3)
        error = json.loads(stdout)
        self.assertFalse(error["ok"])
        self.assertEqual(error["error"]["code"], "REVISION_CONFLICT")
        self.assertEqual(error["currentRevision"], 9)
        self.assertEqual(error["expectedRevision"], 1)
        self.assertIn("REVISION_CONFLICT", stderr)
        self.assertEqual(self.layout.proposals_file.read_bytes(), before)

    def test_cli_create_dry_run_writes_nothing(self) -> None:
        code, stdout, stderr = self.pm(
            "proposal", "create", "--source-inbox", self.inbox_id,
            "--change", "新增：明确输入范围", "--project", "proj-demo", "--dry-run", "--json",
        )
        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["dry_run"])
        self.assertFalse(self.layout.proposals_file.exists())

    def test_cli_write_gate_requires_yes_without_explicit_config(self) -> None:
        before = self.inbox_id
        with mock.patch.dict(os.environ, {"PM_CONFIG": str(self.config)}):
            code, stdout, _ = self.run_cli([
                "proposal", "create", "--source-inbox", before,
                "--change", "新增：明确输入范围", "--json",
            ])
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "NEEDS_YES")
        self.assertFalse(self.layout.proposals_file.exists(), "被闸门拒绝时不得写")

    def test_cli_partial_write_reports_written_and_not_written(self) -> None:
        payload = self.create_via_cli()
        real_apply_change = entities.apply_change

        def fake(path, entity_id, **kwargs):
            if entity_id == payload["proposalId"] and kwargs.get("status") == "APPROVED":
                raise entities.EntityError("BOOM", "模拟写 proposals.org 失败")
            return real_apply_change(path, entity_id, **kwargs)

        with mock.patch.object(entities, "apply_change", side_effect=fake):
            code, stdout, _ = self.pm("proposal", "approve", payload["proposalId"],
                                      "--expected-revision", "1", "--json")
        self.assertEqual(code, 2)
        error = json.loads(stdout)
        self.assertEqual(error["error"]["code"], "PARTIAL_WRITE")
        self.assertIn("inbox", error["written"])
        self.assertIn("proposal", error["notWritten"])
        self.assertIn(":PM_STATUS: TASK_CREATED", self.layout.inbox.read_text(encoding="utf-8"))

    def test_cli_registered_subcommands_exist(self) -> None:
        parser = cli.build_parser()
        top = next(action for action in parser._actions if getattr(action, "choices", None))
        self.assertIn("proposal", top.choices)


class PlanFunctionsTest(unittest.TestCase):
    def test_plan_approve_and_reject_are_pure(self) -> None:
        row = parse_one(INDENTED)
        inbox = """* Inbox

** INBOX 验证
   :PROPERTIES:
   :ID: inbox-00000000000000000000000000
   :PM_STATUS: TASK_PROPOSED
   :PM_REVISION: 2
   :END:
"""
        approvable = INDENTED.replace("修改", "新增")  # v1 只支持新增类变更
        plan = proposals.plan_approve(approvable, inbox, "", proposal_id=row["id"],
                                      expected_revision=1, project="proj-demo")
        self.assertEqual(plan["status"], "APPROVED")
        self.assertEqual(plan["revision"], 2)
        self.assertEqual(plan["inboxRevision"], 3)
        self.assertEqual(plan["project"], "proj-demo")
        self.assertEqual(len(plan["tasks"]), 2)
        self.assertFalse(plan["inboxSkipped"])

    def test_plan_reject_validates_reason_and_revision(self) -> None:
        row = parse_one(INDENTED)
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.plan_reject(INDENTED, proposal_id=row["id"], expected_revision=1, reason="")
        self.assertEqual(ctx.exception.code, "INVALID_REASON")
        plan = proposals.plan_reject(INDENTED, proposal_id=row["id"], expected_revision=1, reason="不要")
        self.assertEqual(plan["status"], "REJECTED")
        self.assertEqual(plan["revision"], 2)

    def test_plan_functions_never_write(self) -> None:
        # 纯函数只吃文本：不传任何路径，也不可能落盘
        plan = proposals.plan_reject(SAMPLE, proposal_id="proposal-00000000000000000000000001",
                                     expected_revision=1, reason="不要")
        self.assertTrue(plan["changed"])


if __name__ == "__main__":
    unittest.main()
