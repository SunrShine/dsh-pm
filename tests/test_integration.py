"""task-23 跨模块集成测试：**只测模块之间的接缝**。

三个领域模块（Task / Proposal / Memory）各自的单测已经很足，
这里专门盯"A 模块写出去的东西，B 模块能不能正确读回来"，
以及跨域统一契约（§5 写返回五字段、CAS 退出码 3、终态不可迁出、
「DONE 只能由人写」「AI 不能 verify」在各入口是否都成立）。

约定：
- **一律临时库**；真实库一个字节都不碰（用例自带 working dir，tearDown 清理）。
- 断言全部**自己派生**：读 JSON 的键集合、读 org 原文的属性、重算状态，
  不引用实现者写在文档里的说法。
- 发现实现与预期不符时，不在这里"改到绿"：用 @unittest.expectedFailure
  明确登记为已知缺陷，并写清缺陷编号，避免悄悄把断言放宽。

已知缺陷登记（详见 内部记录（未随仓库发布））：
- D1: MCP 工具 task_add 的 todo 参数未校验，可写入 DONE / CANCELLED，
      绕过 DONE_REQUIRES_HUMAN（DONE 只能由人写）——见 McpTaskAddGateTest。
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fixtures
from pm import cli, memory, mcp, tasks

TODO_LINE = (
    "#+TODO: INBOX(i) TODO(t) NEXT(n) DOING(s) WAITING(w@) "
    "BLOCKED(b@) REVIEW(r) | DONE(d!) CANCELLED(c@)"
)
PROJECT = "demo01"
PROJECT_ID = "proj-demo01"

#: §5 冻结的写返回五字段（本项目自定义的 entities.OpResult 对外形状）。
SECTION5 = ("entityId", "revision", "source", "observedAt", "auditEventId")


class IntegrationBaseTest(unittest.TestCase):
    """每个用例一个临时库。"""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="pm-int-")
        self.base = Path(self._tmp)
        self.library = self.base / "lib"
        self._write(self.library / "inbox.org", "#+TITLE: Inbox\n" + TODO_LINE + "\n\n* Inbox\n")
        self._write(self.library / "proposals.org", "* Proposals\n")
        self._write(self.library / "memory-candidates.org", "* Memory 候选\n")
        self._write(
            self.library / "projects" / PROJECT_ID / "tasks.org",
            "#+TITLE: " + PROJECT + " — 任务\n" + TODO_LINE + "\n#+FILETAGS: :pm:tasks:\n\n* 任务\n",
        )
        (self.base / "dsh").mkdir(parents=True, exist_ok=True)
        self.config = self.base / "pm.toml"
        self._write(
            self.config,
            "\n".join(
                [
                    'library = "' + str(self.library) + '"',
                    'dsh_home = "' + str(self.base / "dsh") + '"',
                    "active_days = 14",
                    "active_hours = 24",
                    "row_limit = 8",
                    "",
                ]
            ),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    # ---------------------------------------------------------------- 驱动 CLI

    def pm(self, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["--config", str(self.config), *argv])
        except SystemExit as exc:  # argparse 参数错误
            code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def run_ok(self, *argv: str) -> dict:
        code, out, err = self.pm(*argv)
        self.assertEqual(code, 0, "命令失败 %r -> exit %s\n%s" % (list(argv), code, err))
        return json.loads(out)

    def run_err(self, *argv: str):
        code, out, err = self.pm(*argv)
        self.assertNotEqual(code, 0, "本应失败却成功: %r\n%s" % (list(argv), out))
        payload = json.loads(out) if out.strip() else {}
        return code, payload, err

    # ---------------------------------------------------------------- 断言助手

    def tree_hash(self) -> str:
        """整个库的逐字节指纹（用于「一字节不写」断言）。"""
        digest = hashlib.sha256()
        for path in sorted(self.library.rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(self.library)).encode("utf-8"))
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def assert_section5(self, payload: dict, *, domain_id: str, where: str) -> None:
        """§5：五个键齐全、类型正确，且 entityId 等于该域的主 id。"""
        missing = [key for key in SECTION5 if key not in payload]
        self.assertEqual(missing, [], "%s 缺少 §5 字段 %s（实际键 %s）" % (where, missing, sorted(payload)))
        self.assertTrue(payload.get("ok") is True, "%s ok 不为 true: %r" % (where, payload.get("ok")))
        self.assertIsInstance(payload["entityId"], str)
        self.assertEqual(payload["entityId"], domain_id, "%s 的 entityId 与域内 id 不一致" % where)
        self.assertIsInstance(payload["revision"], int)
        self.assertEqual(payload["source"], "org")
        self.assertIsInstance(payload["observedAt"], str)
        self.assertIsInstance(payload["auditEventId"], str)
        self.assertTrue(payload["auditEventId"], "%s 的 auditEventId 为空" % where)

    # ---------------------------------------------------------------- 造数据

    def capture(self, text: str) -> str:
        return self.run_ok("capture", text, "--json")["inboxId"]

    def make_proposal(self, *, project: str = PROJECT, change: str = "新增：明确输入范围", inbox_id=None) -> dict:
        source = inbox_id or self.capture("提案来源 " + change)
        return self.run_ok(
            "proposal", "create",
            "--source-inbox", source,
            "--change", change,
            "--project", project,
            "--json",
        )

    def make_task(self, *, title: str = "任务", criterion=None) -> dict:
        argv = ["task", "create", "--project", PROJECT, "--title", title]
        for item in criterion or ():
            argv += ["--criterion", item]
        argv.append("--json")
        return self.run_ok(*argv)

    def make_task_at(self, status: str) -> tuple[str, int]:
        """建一个任务并推进到 status；返回 (task_id, revision)。"""
        task_id = self.make_task(title="推进到 " + status)["entityId"]
        revision = 1
        for step in ("NEXT", "DOING", "REVIEW", "DONE"):
            payload = self.run_ok(
                "task", "transition", task_id,
                "--project", PROJECT, "--to", step,
                "--actor", "human", "--expected-revision", str(revision), "--json",
            )
            revision = payload["revision"]
            if step == status:
                return task_id, revision
        raise AssertionError("不支持的目标状态 " + status)

    def task_file(self) -> Path:
        return self.library / "projects" / PROJECT_ID / "tasks.org"

    def read_tasks_row(self, task_id: str) -> dict:
        rows = tasks.parse_tasks(self.task_file().read_text(encoding="utf-8"))
        for row in rows:
            if row.get("id") == task_id:
                return row
        self.fail("tasks.parse_tasks 解析不到 " + task_id)


class IntegrationBaseWithProjectTest(IntegrationBaseTest):
    """需要一个能被 MCP Service 解析到的项目（走 DSH fixture）。"""

    def setUp(self) -> None:
        super().setUp()
        self.home = fixtures.build_dsh_home(self.base / "dsh")
        self.config.write_text(
            fixtures.fixture_config_toml(library=str(self.library)).replace("REPLACED", str(self.home)),
            encoding="utf-8",
        )
        self.merged_project = "alpha_beta"
        self.merged_task_file = self.library / "projects" / "proj-alpha_beta" / "tasks.org"
        self._write(
            self.merged_task_file,
            "#+TITLE: Alpha Beta — 任务\n" + TODO_LINE + "\n#+FILETAGS: :pm:tasks:\n\n* 任务\n",
        )


# ================================================================ 接缝 1：proposal.approve → task


class ProposalApproveToTaskTest(IntegrationBaseTest):
    """proposal.approve 建出的任务，pm.tasks 必须能按同一套形状解析回来。"""

    def test_approve_task_parses_with_kind_status_and_backlinks(self) -> None:
        inbox_id = self.capture("要被提案接管的条目")
        proposal = self.make_proposal(inbox_id=inbox_id, change="新增：明确输入范围")
        task_id = proposal["taskIds"][0]

        approved = self.run_ok(
            "proposal", "approve", proposal["entityId"],
            "--expected-revision", "1", "--project", PROJECT, "--json",
        )
        self.assertEqual(approved["status"], "APPROVED")

        # 用 Task 模块自己的解析器读 Proposal 模块写出来的东西。
        row = self.read_tasks_row(task_id)
        props = row["properties"]
        self.assertEqual(props.get("PM_KIND"), "task")
        self.assertEqual(tasks.resolve_status(row), "TODO")
        self.assertEqual(props.get("PM_SOURCE_PROPOSAL_ID"), proposal["entityId"])
        self.assertEqual(props.get("PM_SOURCE_INBOX_ID"), inbox_id)

    def test_approve_marks_inbox_task_created(self) -> None:
        inbox_id = self.capture("状态要变成 TASK_CREATED 的条目")
        proposal = self.make_proposal(inbox_id=inbox_id)
        self.run_ok(
            "proposal", "approve", proposal["entityId"],
            "--expected-revision", "1", "--project", PROJECT, "--json",
        )
        listed = self.run_ok("inbox", "list", "--json")
        entry = next(item for item in listed["entries"] if item["id"] == inbox_id)
        self.assertEqual(entry["status"], "TASK_CREATED")

    def test_approve_status_is_always_todo_even_when_change_mentions_done(self) -> None:
        """提案文本里写完成态也不能绕出 DONE：approve 建的任务恒为 TODO。"""
        proposal = self.make_proposal(change="新增：DONE 已经完成的任务")
        task_id = proposal["taskIds"][0]
        self.run_ok(
            "proposal", "approve", proposal["entityId"],
            "--expected-revision", "1", "--project", PROJECT, "--json",
        )
        self.assertEqual(tasks.resolve_status(self.read_tasks_row(task_id)), "TODO")

    def test_criteria_ride_from_proposal_to_task(self) -> None:
        """提案带 --criterion，批准后任务必须真的带上这些验收标准。"""
        source = self.capture("带验收标准的提案源")
        proposal = self.run_ok(
            "proposal", "create", "--source-inbox", source,
            "--change", "新增：带验收标准", "--criterion", "甲", "--criterion", "乙",
            "--project", PROJECT, "--json",
        )
        task_id = proposal["taskIds"][0]
        self.run_ok(
            "proposal", "approve", proposal["entityId"],
            "--expected-revision", "1", "--project", PROJECT, "--json",
        )
        row = self.read_tasks_row(task_id)
        self.assertEqual([item["text"] for item in row["criteria"]], ["甲", "乙"])
        self.assertTrue(all(item["done"] is False for item in row["criteria"]))

    def test_criterion_with_multiple_changes_is_rejected(self) -> None:
        source = self.capture("多条变更的源")
        before = self.tree_hash()
        code, payload, _ = self.run_err(
            "proposal", "create", "--source-inbox", source,
            "--change", "新增：A", "--change", "新增：B", "--criterion", "X",
            "--project", PROJECT, "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "CRITERION_AMBIGUOUS")
        self.assertEqual(self.tree_hash(), before, "--criterion 歧义时不该落盘")

    def test_reject_leaves_tasks_untouched(self) -> None:
        proposal = self.make_proposal()
        before = self.task_file().read_bytes()
        self.run_ok(
            "proposal", "reject", proposal["entityId"],
            "--expected-revision", "1", "--reason", "不做", "--json",
        )
        self.assertEqual(self.task_file().read_bytes(), before)


# ================================================================ 接缝 2：inbox.note → memory 候选


class InboxNoteToMemoryTest(IntegrationBaseTest):
    """inbox note 写下的候选，memory 模块必须能解析并按属性回链。"""

    def test_note_candidate_parses_with_inbox_backlink(self) -> None:
        inbox_id = self.capture("要变成记忆候选的条目")
        note = self.run_ok(
            "inbox", "note", inbox_id,
            "--expected-revision", "1", "--project", PROJECT, "--json",
        )
        memory_id = note["noteId"]

        entries = memory.parse_candidates(self.library)
        entry = next(item for item in entries if item.id == memory_id)
        self.assertEqual(entry.status, memory.STATUS_CANDIDATE)
        self.assertEqual(entry.scope, PROJECT)
        self.assertEqual(entry.type, memory.TYPE_FACT)

        # 回链是 org 属性，MemoryEntry 不暴露 → 直接读原文断言（不信任字段名）。
        raw = (self.library / "memory-candidates.org").read_text(encoding="utf-8")
        block = raw.split("** ", 1)[1]
        self.assertIn(":PM_SOURCE_INBOX_ID: " + inbox_id, block)
        self.assertIn(":PM_STATUS: CANDIDATE", block)

    def test_note_flips_inbox_status_to_note(self) -> None:
        inbox_id = self.capture("note 之后应变成 NOTE")
        self.run_ok(
            "inbox", "note", inbox_id,
            "--expected-revision", "1", "--project", PROJECT, "--json",
        )
        listed = self.run_ok("inbox", "list", "--json")
        entry = next(item for item in listed["entries"] if item["id"] == inbox_id)
        self.assertEqual(entry["status"], "NOTE")


# ================================================================ 接缝 3：memory.verify → context_pack


class MemoryContextSeamTest(IntegrationBaseTest):
    """context_pack 只含 VERIFIED；未确认的候选绝不能漏进去。"""

    def add_candidate(self, text: str) -> str:
        return self.run_ok(
            "memory", "add", "--text", text, "--scope", PROJECT, "--type", "fact", "--json"
        )["entityId"]

    def context_ids(self, *extra: str) -> list:
        payload = self.run_ok("memory", "context", "--scope", PROJECT, *extra, "--json")
        return [entry["id"] for entry in payload["entries"]], payload

    def test_unverified_candidate_is_excluded_from_context(self) -> None:
        candidate = self.add_candidate("还没人确认的候选")
        ids, payload = self.context_ids()
        self.assertNotIn(candidate, ids)
        self.assertEqual(payload["counts"]["total"], 0)
        self.assertGreaterEqual(payload["excluded"]["candidate"], 1)
        self.assertTrue(payload["onlyVerified"])

    def test_verified_candidate_appears_in_context(self) -> None:
        candidate = self.add_candidate("确认后才进上下文包")
        self.run_ok(
            "memory", "verify", candidate,
            "--expected-revision", "1", "--actor", "human", "--json",
        )
        ids, payload = self.context_ids()
        self.assertIn(candidate, ids)
        self.assertEqual(payload["counts"]["total"], 1)

    def test_verify_rejected_for_ai_and_leaves_files_untouched(self) -> None:
        candidate = self.add_candidate("AI 不许自己确认")
        before = self.tree_hash()
        code, payload, _ = self.run_err(
            "memory", "verify", candidate,
            "--expected-revision", "1", "--actor", "ai", "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "AI_CANNOT_VERIFY")
        self.assertEqual(self.tree_hash(), before, "被拒的 verify 不该改任何文件")

    def test_deprecated_memory_leaves_context(self) -> None:
        candidate = self.add_candidate("先确认再废弃")
        verified = self.run_ok(
            "memory", "verify", candidate,
            "--expected-revision", "1", "--actor", "human", "--json",
        )
        self.assertIn(candidate, self.context_ids()[0])
        # verify 返回的 revision 必须能直接用于下一次 CAS 写。
        self.run_ok(
            "memory", "deprecate", candidate,
            "--expected-revision", str(verified["revision"]), "--reason", "过时", "--json",
        )
        ids, payload = self.context_ids()
        self.assertNotIn(candidate, ids)
        self.assertGreaterEqual(payload["excluded"]["deprecated"], 1)


# ================================================================ §5 写返回形状（四域逐命令）


class WriteReturnShapeTest(IntegrationBaseTest):
    """四域每个写命令的 --json 都必须含 §5 五字段，且 entityId == 域内 id。"""

    def test_inbox_writes(self) -> None:
        cases = {
            "archive": lambda i: ["inbox", "archive", i, "--expected-revision", "1", "--json"],
            "snooze": lambda i: ["inbox", "snooze", i, "--expected-revision", "1", "--until", "2030-01-01", "--json"],
            "note": lambda i: ["inbox", "note", i, "--expected-revision", "1", "--project", PROJECT, "--json"],
            "dismiss": lambda i: ["inbox", "dismiss", i, "--expected-revision", "1", "--reason", "r", "--json"],
            "set-status": lambda i: ["inbox", "set-status", i, "--expected-revision", "1", "--status", "TRIAGE", "--json"],
        }
        for name, build in cases.items():
            with self.subTest(command=name):
                inbox_id = self.capture("写形状 " + name)
                payload = self.run_ok(*build(inbox_id))
                self.assert_section5(payload, domain_id=inbox_id, where="inbox " + name)

    def test_inbox_merge(self) -> None:
        target = self.capture("合并目标")
        source = self.capture("合并源")
        payload = self.run_ok("inbox", "merge", source, "--expected-revision", "1", "--into", target, "--json")
        self.assert_section5(payload, domain_id=source, where="inbox merge")

    def test_task_writes(self) -> None:
        created = self.make_task(title="写形状", criterion=["标准"])
        self.assert_section5(created, domain_id=created["taskId"], where="task create")
        task_id = created["taskId"]
        moved = self.run_ok(
            "task", "transition", task_id,
            "--project", PROJECT, "--to", "NEXT", "--expected-revision", "1", "--json",
        )
        self.assert_section5(moved, domain_id=task_id, where="task transition")
        checked = self.run_ok(
            "task", "check", task_id,
            "--project", PROJECT, "--index", "0", "--expected-revision", "2", "--json",
        )
        self.assert_section5(checked, domain_id=task_id, where="task check")

    def test_proposal_writes(self) -> None:
        created = self.make_proposal()
        self.assert_section5(created, domain_id=created["proposalId"], where="proposal create")
        approved = self.run_ok(
            "proposal", "approve", created["entityId"],
            "--expected-revision", "1", "--project", PROJECT, "--json",
        )
        self.assert_section5(approved, domain_id=created["entityId"], where="proposal approve")
        other = self.make_proposal()
        rejected = self.run_ok(
            "proposal", "reject", other["entityId"],
            "--expected-revision", "1", "--reason", "r", "--json",
        )
        self.assert_section5(rejected, domain_id=other["entityId"], where="proposal reject")

    def test_memory_writes(self) -> None:
        added = self.run_ok("memory", "add", "--text", "写形状", "--scope", PROJECT, "--type", "fact", "--json")
        self.assert_section5(added, domain_id=added["memoryId"], where="memory add")
        verified = self.run_ok(
            "memory", "verify", added["entityId"],
            "--expected-revision", "1", "--actor", "human", "--json",
        )
        self.assert_section5(verified, domain_id=added["entityId"], where="memory verify")
        # verify 之后同一个 :ID: 同时存在于候选区与正式区（memory/<type>.org）。
        # §5 说 revision 是"该实体当前的 revision"——那么 verify 返回的 revision
        # 必须等于 memory list 报的，也必须是下一次 CAS 写要用的那一个；
        # 否则调用方按 verify 的返回值接着写就会拿到假 409。
        listed = self.run_ok("memory", "list", "--json")
        current = next(item for item in listed["entries"] if item["id"] == added["entityId"])
        self.assertEqual(
            current["revision"], verified["revision"],
            "verify 返回的 revision 与 memory list 报的不一致（§5 契约要求它们是同一个）",
        )
        deprecated = self.run_ok(
            "memory", "deprecate", added["entityId"],
            "--expected-revision", str(verified["revision"]), "--reason", "r", "--json",
        )
        self.assert_section5(deprecated, domain_id=added["entityId"], where="memory deprecate")

    def test_capture_follows_section5(self) -> None:
        """capture 也写 inbox.org，因此同样受 §5 写返回契约约束（Lead 已裁定纳入）。

        历史：本条原本登记的是"capture 不遵循 §5"的事实形状；裁定后实现改成走
        entities.create_entity，于是翻转为正向断言。
        """
        payload = self.run_ok("capture", "capture 的形状", "--json")
        self.assert_section5(payload, domain_id=payload["entityId"], where="capture")
        self.assertEqual(payload["entityId"], payload["inboxId"], "capture 的 entityId 与 inboxId 应等值")
        text = (self.library / "inbox.org").read_text(encoding="utf-8")
        self.assertIn(":LOGBOOK:", text)
        self.assertIn("audit=" + payload["auditEventId"], text)

    def test_capture_dry_run_carries_section5_without_writing(self) -> None:
        before = self.tree_hash()
        payload = self.run_ok("capture", "干跑不落盘", "--dry-run", "--json")
        self.assert_section5(payload, domain_id=payload["entityId"], where="capture --dry-run")
        self.assertTrue(payload.get("dry_run") is True)
        self.assertEqual(self.tree_hash(), before, "--dry-run 不该落盘")
        # 预演出来的 id / 审计 id 不能被随后的真实写入复用（否则预演值会"成真"）
        real = self.run_ok("capture", "干跑不落盘", "--json")
        self.assertNotEqual(real["entityId"], payload["entityId"], "dry-run 的 entityId 被真写复用")
        self.assertNotEqual(real["auditEventId"], payload["auditEventId"], "dry-run 的 auditEventId 被真写复用")
        text = (self.library / "inbox.org").read_text(encoding="utf-8")
        self.assertNotIn(payload["entityId"], text, "dry-run 的 id 不该出现在文件里")
        self.assertIn(real["entityId"], text)


# ================================================================ 「DONE 只能由人写」


class DoneRequiresHumanTest(IntegrationBaseTest):
    def test_ai_cannot_transition_to_done(self) -> None:
        task_id, revision = self.make_task_at("REVIEW")
        before = self.tree_hash()
        code, payload, _ = self.run_err(
            "task", "transition", task_id,
            "--project", PROJECT, "--to", "DONE",
            "--actor", "ai", "--expected-revision", str(revision), "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "DONE_REQUIRES_HUMAN")
        self.assertEqual(self.tree_hash(), before)

    def test_system_cannot_transition_to_done(self) -> None:
        task_id, revision = self.make_task_at("REVIEW")
        code, payload, _ = self.run_err(
            "task", "transition", task_id,
            "--project", PROJECT, "--to", "DONE",
            "--actor", "system", "--expected-revision", str(revision), "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "DONE_REQUIRES_HUMAN")

    def test_human_can_transition_to_done_then_state_is_terminal(self) -> None:
        task_id, revision = self.make_task_at("REVIEW")
        moved = self.run_ok(
            "task", "transition", task_id,
            "--project", PROJECT, "--to", "DONE",
            "--actor", "human", "--expected-revision", str(revision), "--json",
        )
        self.assertEqual(moved["status"], "DONE")
        self.assertEqual(tasks.resolve_status(self.read_tasks_row(task_id)), "DONE")
        for target in ("DOING", "CANCELLED", "TODO"):
            with self.subTest(target=target):
                code, payload, _ = self.run_err(
                    "task", "transition", task_id,
                    "--project", PROJECT, "--to", target,
                    "--actor", "human", "--expected-revision", str(moved["revision"]), "--json",
                )
                self.assertEqual(code, 2)
                self.assertEqual(payload["error"]["code"], "TERMINAL_STATE")

    def test_todo_cannot_jump_straight_to_done(self) -> None:
        task_id = self.make_task(title="跳级")["entityId"]
        code, payload, _ = self.run_err(
            "task", "transition", task_id,
            "--project", PROJECT, "--to", "DONE",
            "--actor", "human", "--expected-revision", "1", "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "INVALID_TRANSITION")

    def test_cancelled_is_terminal_too(self) -> None:
        task_id = self.make_task(title="取消")["entityId"]
        self.run_ok(
            "task", "transition", task_id,
            "--project", PROJECT, "--to", "CANCELLED",
            "--actor", "human", "--expected-revision", "1", "--json",
        )
        code, payload, _ = self.run_err(
            "task", "transition", task_id,
            "--project", PROJECT, "--to", "NEXT",
            "--actor", "human", "--expected-revision", "2", "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "TERMINAL_STATE")


# ================================================================ 接缝：MCP 入口的越权（D1）


class McpTaskAddGateTest(IntegrationBaseWithProjectTest):
    """D1 修复后：MCP 的 task_add 是 **AI 路径**，状态必须过 tasks.py 的状态机。

    校验复用 tasks.normalize_status / validate_transition / is_terminal（延迟 import），
    非法状态**明确报错**，绝不静默降级成 TODO，也不让关键词漏进标题。
    """

    def service(self) -> "mcp.Service":
        return mcp.Service(str(self.config))

    def parsed_statuses(self) -> dict:
        rows = tasks.parse_tasks(self.merged_task_file.read_text(encoding="utf-8"))
        return {row.get("title"): tasks.resolve_status(row) for row in rows}

    def test_task_add_rejects_done(self) -> None:
        svc = self.service()
        with self.assertRaises(mcp.ToolError) as ctx:
            mcp.tool_task_add(svc, {"project": self.merged_project, "title": "越权 DONE", "todo": "DONE"})
        self.assertIn("DONE_REQUIRES_HUMAN", str(ctx.exception))
        self.assertNotIn("越权 DONE", self.parsed_statuses())
        self.assertNotIn("DONE", self.parsed_statuses().values())

    def test_task_add_rejects_cancelled(self) -> None:
        svc = self.service()
        with self.assertRaises(mcp.ToolError):
            mcp.tool_task_add(
                svc, {"project": self.merged_project, "title": "越权 CANCELLED", "todo": "CANCELLED"}
            )
        self.assertNotIn("越权 CANCELLED", self.parsed_statuses())
        self.assertNotIn("CANCELLED", self.parsed_statuses().values())

    def test_task_add_invalid_status_is_rejected_loudly(self) -> None:
        """不静默降级：报错、不落盘、关键词也不许漏进文件。"""
        svc = self.service()
        with self.assertRaises(mcp.ToolError) as ctx:
            mcp.tool_task_add(svc, {"project": self.merged_project, "title": "非法状态", "todo": "BOGUS"})
        self.assertIn("INVALID_STATUS", str(ctx.exception))
        self.assertNotIn("非法状态", self.parsed_statuses())
        self.assertNotIn("BOGUS", self.merged_task_file.read_text(encoding="utf-8"))

    def test_task_add_normal_todo_still_works_and_title_is_clean(self) -> None:
        svc = self.service()
        mcp.tool_task_add(svc, {"project": self.merged_project, "title": "正常任务", "todo": "NEXT"})
        self.assertEqual(self.parsed_statuses()["正常任务"], "NEXT")
        text = self.merged_task_file.read_text(encoding="utf-8")
        self.assertIn("** NEXT 正常任务", text)
        self.assertNotIn("NEXT 正常任务 NEXT", text)


# ================================================================ 接缝 4/7：CAS 跨域一致


class CasAcrossDomainsTest(IntegrationBaseTest):
    """四个域的写命令在 expected-revision 过期时都必须是：退出码 3 + REVISION_CONFLICT + 一字节不写。"""

    def test_stale_revision_conflicts_in_every_domain(self) -> None:
        plan = {}

        inbox_id = self.capture("inbox CAS")
        plan["inbox"] = ["inbox", "archive", inbox_id, "--expected-revision", "999", "--json"]

        task_id = self.make_task(title="task CAS")["entityId"]
        plan["task"] = [
            "task", "transition", task_id,
            "--project", PROJECT, "--to", "NEXT", "--expected-revision", "999", "--json",
        ]

        proposal = self.make_proposal()
        plan["proposal"] = [
            "proposal", "reject", proposal["entityId"],
            "--expected-revision", "999", "--reason", "r", "--json",
        ]

        memory_id = self.run_ok(
            "memory", "add", "--text", "memory CAS", "--scope", PROJECT, "--type", "fact", "--json"
        )["entityId"]
        plan["memory"] = ["memory", "verify", memory_id, "--expected-revision", "999", "--json"]

        for domain, argv in plan.items():
            with self.subTest(domain=domain):
                before = self.tree_hash()
                code, payload, _ = self.run_err(*argv)
                self.assertEqual(code, 3, "%s 的 CAS 过期退出码不是 3" % domain)
                self.assertEqual(payload["error"]["code"], "REVISION_CONFLICT")
                self.assertEqual(self.tree_hash(), before, "%s 的 CAS 过期后文件被改动了" % domain)

    def test_matching_revision_succeeds_in_every_domain(self) -> None:
        inbox_id = self.capture("inbox CAS ok")
        payload = self.run_ok("inbox", "archive", inbox_id, "--expected-revision", "1", "--json")
        self.assertEqual(payload["revision"], 2)


# ================================================================ 接缝 8：终态不可迁出


class TerminalStateTest(IntegrationBaseTest):
    def test_inbox_terminal_states_reject_further_changes(self) -> None:
        cases = {
            "ARCHIVED": lambda i: ["inbox", "archive", i, "--expected-revision", "1", "--json"],
            "DISMISSED": lambda i: ["inbox", "dismiss", i, "--expected-revision", "1", "--reason", "r", "--json"],
        }
        target = self.capture("合并目标")
        for expected_status, build in cases.items():
            with self.subTest(status=expected_status):
                inbox_id = self.capture("终态 " + expected_status)
                self.run_ok(*build(inbox_id))
                before = self.tree_hash()
                code, payload, _ = self.run_err(
                    "inbox", "set-status", inbox_id,
                    "--expected-revision", "2", "--status", "TRIAGE", "--json",
                )
                self.assertEqual(code, 2)
                self.assertEqual(payload["error"]["code"], "ILLEGAL_TRANSITION")
                self.assertEqual(self.tree_hash(), before)

        merged = self.capture("会被合并的源")
        self.run_ok("inbox", "merge", merged, "--expected-revision", "1", "--into", target, "--json")
        for argv in (
            ["inbox", "set-status", merged, "--expected-revision", "2", "--status", "TRIAGE", "--json"],
            ["inbox", "archive", merged, "--expected-revision", "2", "--json"],
        ):
            code, payload, _ = self.run_err(*argv)
            self.assertEqual(code, 2)
            self.assertEqual(payload["error"]["code"], "ILLEGAL_TRANSITION")

    def test_inbox_terminal_states_match_documented_set(self) -> None:
        """终态集合来自行为，不来自文档：逐个走一遍。"""
        seen = {}
        for status in ("ARCHIVED", "MERGED", "DISMISSED"):
            inbox_id = self.capture("终态集合 " + status)
            if status == "ARCHIVED":
                self.run_ok("inbox", "archive", inbox_id, "--expected-revision", "1", "--json")
            elif status == "DISMISSED":
                self.run_ok("inbox", "dismiss", inbox_id, "--expected-revision", "1", "--reason", "r", "--json")
            else:
                other = self.capture("merge 目标")
                self.run_ok("inbox", "merge", inbox_id, "--expected-revision", "1", "--into", other, "--json")
            listed = self.run_ok("inbox", "list", "--json")
            entry = next(item for item in listed["entries"] if item["id"] == inbox_id)
            seen[status] = entry["status"]
            self.assertEqual(entry["status"], status)
        self.assertEqual(sorted(seen), ["ARCHIVED", "DISMISSED", "MERGED"])


# ================================================================ CLI 韧性（D2）


class CliSurvivesBrokenDomainTest(unittest.TestCase):
    """CLI 是所有人的入口：一个领域模块坏掉，不该让 pm --help 整体挂掉。

    D2（已知缺陷）：cli._register_domain_commands 只 except ImportError，
    兜不住 SyntaxError 等在 import 期抛出的其它异常。实测一个 Domain 模块的
    语法错误就能让 pm --help 直接 traceback（本次 task-23 期间真发生过）。
    修法：把捕获放宽到 Exception，并保留"先在一次性的 parser 上试跑"的写法。
    修好后请删掉本类的 expectedFailure，并翻转钉死用例。
    """

    @staticmethod
    def _raiser(target_name: str, exc: BaseException):
        real = importlib.import_module

        def fake(target, *args, **kwargs):
            if target == target_name:
                raise exc
            return real(target, *args, **kwargs)

        return fake

    def test_syntax_error_in_one_domain_does_not_kill_cli(self) -> None:
        with mock.patch(
            "importlib.import_module",
            side_effect=self._raiser("pm.proposals", SyntaxError("simulated broken module")),
        ):
            parser = cli.build_parser()  # D2 修复后：不该抛
            self.assertIsNotNone(parser)
            # 坏掉的那个域缺席，但其余域照常可用
            parser.parse_args(["task", "list", "--project", "x"])
            parser.parse_args(["memory", "list"])

    def test_import_error_is_already_contained(self) -> None:
        """对照组：ImportError 本来就被兜住了，说明缺的只是异常种类。"""
        with mock.patch(
            "importlib.import_module",
            side_effect=self._raiser("pm.proposals", ImportError("simulated missing dep")),
        ):
            parser = cli.build_parser()
            self.assertIsNotNone(parser)

    def test_other_domains_still_register_when_one_is_missing(self) -> None:
        with mock.patch(
            "importlib.import_module",
            side_effect=self._raiser("pm.proposals", ImportError("simulated missing dep")),
        ):
            parser = cli.build_parser()
            # task / memory 两个域仍应注册成功（能解析自己的子命令即证明）
            parser.parse_args(["task", "list", "--project", "x"])
            parser.parse_args(["memory", "list"])


if __name__ == "__main__":
    unittest.main()
