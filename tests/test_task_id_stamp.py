"""MCP task_add 必须产出可寻址任务 + id-less 条目的修复路径 + 负例有牙。

库任务 task-01M51Y84TKZE00TWYEG03Z3YWB 的验收标准 0–4：
0. MCP 建成后 list 显示 id=task-<ULID> 且 show 能读到；
1. 该任务可寻址：transition / evidence add 各成功一次；
2. 修复路径覆盖现存孤儿（补 :ID: + 审计 + 幂等 + dry-run）；
3. 负例有牙：写入路径缺 :ID: 必须报错，不许静默接受；
4. 回归：CLI task create 行为不变。
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pm import cli, entities, humanwrite, mcp, tasks

import fixtures
from test_mcp import make_service


class TaskIdStampBase(unittest.TestCase):
    def setUp(self) -> None:
        self.service = make_service(self)
        self.project_key = self.service.scan(include_all=True, limit=0).projects[0].key
        self.library = Path(self.service.config.library)
        self.config_path = self.service.config_path
        self.path = self.library / "projects" / ("proj-" + self.project_key) / "tasks.org"
        self.pm("project", "create", self.project_key)

    def run_cli(self, argv: list) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def pm(self, *argv: str) -> tuple:
        return self.run_cli(["--config", str(self.config_path), *argv])

    def ok(self, *argv: str) -> dict:
        code, stdout, stderr = self.pm(*argv)
        self.assertEqual(code, 0, "命令失败 %r: %s" % (list(argv), stderr))
        return json.loads(stdout)

    def add_orphan(self, title: str = "孤儿任务") -> None:
        """照旧 MCP 的写法造一个**没有 :ID:** 的条目（模拟那 5 条孤儿）。"""
        block = humanwrite.entry_block(
            "正文（AI 建的）", title=title, todo=tasks.STATUS_TODO,
            properties={"PM_SOURCE": "ai", "PM_ADDED_AT": "2026-10-16 Fri 16:42",
                        "PM_ADDED_BY": "mcp", "PM_AI": "t", "PM_ASSIGNEE": "pm-frontend"},
        )
        humanwrite.append_entry(self.path, headline=tasks.TASKS_SECTION, block=block)

    def rows(self) -> list:
        return [t for g in self.ok("task", "list", "--project", self.project_key, "--json")["groups"]
                for t in g["tasks"]]


class McpTaskAddTest(TaskIdStampBase):
    def add_via_mcp(self, **overrides) -> str:
        payload = {"project": self.project_key, "title": "MCP 建的任务", "todo": "TODO",
                   "body": "目标：验证 :ID: 铸造", "criteria": ["能被 show 读到", "能被 evidence add"],
                   "ai": True, "assignee": "pm-frontend", "model": "mcp"}
        payload.update(overrides)
        return mcp.tool_task_add(self.service, payload)

    def test_standard0_list_and_show_work(self) -> None:
        note = self.add_via_mcp()
        self.assertIn("已创建任务 task-", note)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(str(row["id"]).startswith("task-"), "id 必须是 task-<ULID>，不能是 None")
        self.assertEqual(row["status"], "TODO")
        # 属性铸造（原文）
        text = self.path.read_text(encoding="utf-8")
        block = text[text.index("MCP 建的任务"):]
        for prop in (":ID: task-", ":PM_KIND: task", ":PM_STATUS: TODO",
                     ":PM_PROJECT_ID: " + self.project_key, ":PM_AI: t", ":PM_ASSIGNEE: pm-frontend"):
            self.assertIn(prop, block, "缺属性：" + prop)
        # show 能按 id 读到
        shown = self.ok("task", "show", row["id"], "--project", self.project_key, "--json")["task"]
        self.assertEqual(shown["id"], row["id"])
        self.assertEqual([c["text"] for c in shown["criteria"]], ["能被 show 读到", "能被 evidence add"])

    def test_standard1_transition_and_evidence_add_succeed(self) -> None:
        self.add_via_mcp()
        task_id = self.rows()[0]["id"]
        moved = self.ok("task", "transition", task_id, "--project", self.project_key, "--to", "NEXT",
                        "--actor", "ai", "--expected-revision", "1", "--json")
        self.assertTrue(moved["auditEventId"].startswith("audit-"))
        criterion_id = self.ok("task", "show", task_id, "--project", self.project_key,
                               "--json")["task"]["criteria"][0]["id"]
        added = self.ok("task", "evidence", "add", task_id, "--project", self.project_key,
                        "--criterion-id", criterion_id, "--kind", "test", "--result", "info",
                        "--ref", "tests/test_task_id_stamp.py", "--actor", "ai",
                        "--expected-revision", "2", "--json")
        self.assertTrue(added["changed"])
        self.assertTrue(added["auditEventId"].startswith("audit-"))
        self.assertEqual(added["evidenceCount"], 1)
        self.assertEqual(self.ok("task", "evidence", "list", task_id, "--project", self.project_key,
                                 "--json")["count"], 1)

    def test_standard3_mcp_add_failure_is_explicit(self) -> None:
        """负例：铸造失败（id 铸不出来）时，MCP 必须明确报错，不许静默写不可寻址条目。"""
        before = self.path.read_bytes() if self.path.is_file() else b""
        with mock.patch.object(tasks, "new_task_id", return_value=""):
            with self.assertRaises(mcp.ToolError) as raised:
                self.add_via_mcp()
        self.assertIn("TASK_STAMP_INCOMPLETE", str(raised.exception))
        after = self.path.read_bytes() if self.path.is_file() else b""
        self.assertEqual(after, before, "报错时一个字节都不写")


class InitTaskIdsTest(TaskIdStampBase):
    def test_standard2_repairs_orphan_with_audit(self) -> None:
        self.add_orphan("孤儿 A")
        self.add_orphan("孤儿 B")
        before_rows = self.rows()
        self.assertEqual(len(before_rows), 2)
        self.assertTrue(all(not row["id"] for row in before_rows), "造出来的必须是 id-less 条目")
        payload = self.ok("task", "init-ids", "--project", self.project_key, "--actor", "human", "--json")
        self.assertTrue(payload["changed"])
        self.assertEqual(payload["count"], 2)
        new_ids = [item["id"] for item in payload["stamped"]]
        self.assertTrue(all(str(item).startswith("task-") for item in new_ids))
        rows = self.rows()
        self.assertEqual(sorted(row["id"] for row in rows), sorted(new_ids), "补完后 list 必须有 id")
        text = self.path.read_text(encoding="utf-8")
        for task_id in new_ids:
            self.assertIn(":ID: " + task_id, text)
            shown = self.ok("task", "show", task_id, "--project", self.project_key, "--json")["task"]
            self.assertEqual(shown["id"], task_id, "补完必须能被 show 寻址")
        self.assertEqual(text.count("op=task-id-stamp"), 2, "每个块一条审计")
        self.assertIn(":PM_KIND: task", text)
        self.assertIn(":PM_STATUS: TODO", text)
        self.assertIn(":PM_PROJECT_ID: " + self.project_key, text)

    def test_reason_lands_in_the_stamp_audit(self) -> None:
        """`--reason` 必须写进审计行（task-id-stamp 的 reason=…），方便人回看为什么补。"""
        self.add_orphan("孤儿")
        self.ok("task", "init-ids", "--project", self.project_key, "--actor", "ai",
                "--reason", "修复 MCP task_add 缺 :ID: 的历史孤儿（演示）", "--json")
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("op=task-id-stamp", text)
        self.assertIn("reason=修复 MCP task_add 缺 :ID: 的历史孤儿", text)
        self.assertRegex(text, r"actor=ai rev=1 reason=[^\n]*op=task-id-stamp")

    def test_standard2_idempotent_and_dry_run(self) -> None:
        self.add_orphan("孤儿")
        before = self.path.read_bytes()
        dry = self.ok("task", "init-ids", "--project", self.project_key, "--dry-run", "--json")
        self.assertTrue(dry["dry_run"])
        self.assertEqual(self.path.read_bytes(), before, "--dry-run 零写入")
        first = self.ok("task", "init-ids", "--project", self.project_key, "--json")
        self.assertTrue(first["changed"])
        snapshot = self.path.read_bytes()
        second = self.ok("task", "init-ids", "--project", self.project_key, "--json")
        self.assertFalse(second["changed"], "再跑一次应无变化（幂等）")
        self.assertEqual(second["count"], 0)
        self.assertEqual(self.path.read_bytes(), snapshot)

    def test_repair_must_not_swallow_following_blocks(self) -> None:
        """回归（task-01M52D77… 的 422）：补 :ID: 之后，**后面的块必须仍然可寻址**。

        曾经漏了注入 `:LOGBOOK:` 的闭合 `:END:` ⇒ 抽屉一路吃到后面块的 `:END:`，
        把后续任务吞进抽屉 ⇒ 那些 :ID: 在文件里、show 正常，但写路径报 NOT_FOUND。
        """
        self.add_orphan("孤儿（补 ID 目标）")
        created = self.ok("task", "create", "--project", self.project_key, "--title", "后面的正常任务",
                          "--criterion", "一条标准", "--json")
        later_id = created["entityId"]
        before = self.path.read_text(encoding="utf-8")
        self.ok("task", "init-ids", "--project", self.project_key, "--json")
        after = self.path.read_text(encoding="utf-8")
        # 1) headline 序列必须一字不变
        self.assertEqual(tasks._headline_sequence(before.split("\n")),
                         tasks._headline_sequence(after.split("\n")), "headline 序列被改了（抽屉吞块）")
        # 2) 后续任务仍能被实体寻址（写路径的前提）
        entity = entities.load_entity(self.path, later_id, default_status=tasks.DEFAULT_STATUS)
        self.assertEqual(entity.entity_id, later_id)
        # 3) 抽屉闭合：每个块的 :LOGBOOK:/:PROPERTIES: 都有对应 :END:
        for block in entities.iter_entity_blocks(after, headline=tasks.TASKS_SECTION, level=2):
            region = after.split("\n")[block["start"]:block["end"]]
            opened = sum(1 for line in region if line.strip() in (":PROPERTIES:", ":LOGBOOK:"))
            closed = sum(1 for line in region if line.strip() == ":END:")
            self.assertEqual(opened, closed, "块内抽屉不闭合：" + (block["headline"] or "")[:40])
        # 4) 后续任务还能真流转（dry-run，零写入）
        code, _out, stderr = self.pm("task", "transition", later_id, "--project", self.project_key,
                                     "--to", "NEXT", "--actor", "ai", "--expected-revision", "1", "--dry-run")
        self.assertEqual(code, 0, "后续任务仍应可流转（dry-run）：" + stderr[:120])

    def test_headline_guard_refuses_swallowing_edit(self) -> None:
        """守卫本体：headline 少一行就必须拒绝（把结构性损坏挡在写盘前）。"""
        before = ["* 任务", "", "** TODO A", "   :PROPERTIES:", "   :ID: task-1", "   :END:", "",
                  "** TODO B", "   :PROPERTIES:", "   :ID: task-2", "   :END:"]
        after = ["* 任务", "", "** TODO A", "   :PROPERTIES:", "   :ID: task-1", "   :END:",
                 "   :LOGBOOK:", "   - State \"x\"", "", "** TODO B", "   :PROPERTIES:",
                 "   :ID: task-2", "   :END:"]
        with self.assertRaises(entities.EntityError) as raised:
            tasks._assert_structure_intact(before, "\n".join(after), headline=tasks.TASKS_SECTION, level=2)
        self.assertEqual(raised.exception.code, "DRAWER_BREAKS_HEADLINES")
        self.assertIn("抽屉", str(raised.exception))
        # 干净编辑（B 块依然被识别）→ 不报错
        tasks._assert_structure_intact(before, "\n".join(before), headline=tasks.TASKS_SECTION, level=2)
        # 只为 A 插入属性 + 闭合 LOGBOOK 的编辑 → 不报错
        good = before[:5] + ["   :END:", "   :LOGBOOK:", "   - State \"x\"", "   :END:"] + before[5:]
        tasks._assert_structure_intact(before, "\n".join(good), headline=tasks.TASKS_SECTION, level=2)

    def test_not_found_message_is_self_diagnosing(self) -> None:
        """报错质量：要找的 :ID: 在文件里但不可寻址 ⇒ 报错必须带**查了哪个文件** + 抽屉提示。"""
        swallowed = (
            "* 任务\n\n"
            "** TODO 坏块\n   :PROPERTIES:\n   :ID: task-bad\n   :END:\n   :LOGBOOK:\n"
            "   - State \"TODO\" from \"(stamped)\"\n\n"   # ← 故意不闭合
            "** TODO 后面的任务\n   :PROPERTIES:\n   :ID: task-later\n   :END:\n"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(swallowed, encoding="utf-8")
        with self.assertRaises(entities.EntityError) as raised:
            entities.load_entity(self.path, "task-later", default_status=tasks.DEFAULT_STATUS)
        message = str(raised.exception)
        self.assertIn(str(self.path), message, "必须报出查了哪个文件")
        self.assertIn("抽屉", message)
        self.assertIn("可寻址", message)

    def test_standard3_create_task_guard_blocks_idless_write(self) -> None:
        """直接构造一个没有 id 的任务 dict 走 create_task → 必须报错且零写入。"""
        task = tasks.build_task("守卫任务", project_id="proj-" + self.project_key, status="TODO")
        task["id"] = None  # 模拟"铸造漏了"
        before = self.path.read_bytes() if self.path.is_file() else b""
        with self.assertRaises(entities.EntityError) as raised:
            tasks.create_task(self.path, task, actor="ai")
        self.assertEqual(raised.exception.code, "TASK_STAMP_INCOMPLETE")
        after = self.path.read_bytes() if self.path.is_file() else b""
        self.assertEqual(after, before)


class CliCreateRegressionTest(TaskIdStampBase):
    def test_standard4_cli_create_unchanged(self) -> None:
        created = self.ok("task", "create", "--project", self.project_key, "--title", "CLI 建的任务",
                          "--goal", "目标", "--criterion", "一条标准", "--ai", "--json")
        task_id = created["entityId"]
        self.assertTrue(str(task_id).startswith("task-"))
        self.assertEqual(created["revision"], 1)
        shown = self.ok("task", "show", task_id, "--project", self.project_key, "--json")["task"]
        self.assertEqual(shown["id"], task_id)
        self.assertEqual(len(shown["criteria"]), 1)
        self.assertTrue(shown["criteria"][0]["id"].startswith("c-"))
        text = self.path.read_text(encoding="utf-8")
        for prop in (":ID: " + task_id, ":PM_KIND: task", ":PM_STATUS: TODO",
                     ":PM_PROJECT_ID: " + self.project_key, ":PM_AI: t"):
            self.assertIn(prop, text)


if __name__ == "__main__":
    unittest.main()
