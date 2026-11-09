"""Task 模型（backend-design §5.2）：解析 / 序列化 / 状态机 / 分组 / 写入路径 / CLI。

全部用临时库；真实库 ~/my-work-memory 一个字节都不碰。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pm import cli, entities, tasks
from pm.layout import Layout

TZ = timezone(timedelta(hours=8))

#: §5.2 文档里的示例任务块（规范化形态；属性顶格，验收标准是 col-0 子标题）。
BLOCK = """** TODO 明确验证计划的输入范围
:PROPERTIES:
:ID: task-01JABCDEFGHJKMNPQRSTVWXYZ0
:PM_KIND: task
:PM_PROJECT_ID: demo
:PM_SOURCE_INBOX_ID: inbox-01JABCDEFGHJKMNPQRSTVWXYZ1
:PM_REVISION: 1
:PM_AI: t
:PM_ASSIGNEE: unassigned
:END:
目标：明确参考模型、输入版本和通过条件。
非目标：本任务不修改 RTL。

*** 验收标准
- [ ] 列出输入数据版本
- [ ] 列出参考模型版本
- [ ] 说明失败时的判断方式
"""

TASK_ID = "task-01JABCDEFGHJKMNPQRSTVWXYZ0"
AUDIT_RE = re.compile(r"^audit-[0-9A-HJKMNP-TV-Z]{26}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")


class TaskTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.library = self.base / "wm"
        (self.library / "projects" / "proj-demo").mkdir(parents=True)
        self.config = self.base / "pm.toml"
        self.config.write_text('library = "' + str(self.library) + '"\n', encoding="utf-8")
        self.layout = Layout(self.library)
        self.tasks_path = tasks.tasks_path(self.layout, "demo")

    # ---- helpers ----

    def write_tasks(self, text: str) -> None:
        self.tasks_path.parent.mkdir(parents=True, exist_ok=True)
        self.tasks_path.write_text(text, encoding="utf-8")

    def seed_file(self, text: str = BLOCK) -> None:
        self.write_tasks("#+TITLE: demo\n#+TODO: INBOX(i) TODO(t) NEXT(n) DOING(s) REVIEW(r) | DONE(d!) CANCELLED(c@)\n\n* 任务\n\n" + text)

    def make_task(self, **kwargs):
        params = {
            "title": "验证计划输入范围",
            "project_id": "demo",
            "ai": True,
            "goal": "明确参考模型与输入版本",
            "non_goal": "不修改 RTL",
            "criteria": ["列出输入数据版本", "列出参考模型版本"],
        }
        params.update(kwargs)
        task = tasks.build_task(**params)
        tasks.create_task(self.tasks_path, task)
        return task

    def parsed(self) -> list[dict]:
        return tasks.parse_tasks(self.tasks_path.read_text(encoding="utf-8"))

    def parsed_one(self, task_id: str) -> dict:
        return tasks.find_task(self.parsed(), task_id)

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


# ================================================================ 解析 / 序列化


class ParseTest(TaskTestCase):
    def test_parse_doc_example_fields(self) -> None:
        self.seed_file()
        rows = self.parsed()
        self.assertEqual(len(rows), 1)
        task = rows[0]
        self.assertEqual(task["id"], TASK_ID)
        self.assertEqual(task["keyword"], "TODO")
        self.assertEqual(task["status"], "TODO")
        self.assertEqual(task["title"], "明确验证计划的输入范围")
        self.assertEqual(task["project_id"], "demo")
        self.assertEqual(task["source_inbox_id"], "inbox-01JABCDEFGHJKMNPQRSTVWXYZ1")
        self.assertEqual(task["revision"], 1)
        self.assertTrue(task["ai"])
        self.assertEqual(task["assignee"], "unassigned")
        self.assertEqual(task["goal"], "明确参考模型、输入版本和通过条件。")
        self.assertEqual(task["non_goal"], "本任务不修改 RTL。")
        self.assertEqual(
            [item["text"] for item in task["criteria"]],
            ["列出输入数据版本", "列出参考模型版本", "说明失败时的判断方式"],
        )
        self.assertEqual([item["done"] for item in task["criteria"]], [False, False, False])

    def test_render_doc_example_is_byte_identical(self) -> None:
        task = tasks.parse_tasks(BLOCK)[0]
        rendered = "\n".join(tasks.render_task_block(task)) + "\n"
        self.assertEqual(rendered, BLOCK, "规范化块必须逐字节往返")

    def test_parse_render_parse_is_lossless(self) -> None:
        task = tasks.parse_tasks(BLOCK)[0]
        again = tasks.parse_tasks("\n".join(tasks.render_task_block(task)) + "\n")[0]
        for key in ("id", "keyword", "status", "title", "project_id", "source_inbox_id",
                    "revision", "ai", "assignee", "goal", "non_goal", "criteria"):
            self.assertEqual(again[key], task[key], key)

    def test_title_with_star_pipe_and_cjk(self) -> None:
        task = tasks.build_task("输入 * 参考 | 中文（括号）", project_id="demo")
        rendered = "\n".join(tasks.render_task_block(task))
        parsed = tasks.parse_tasks(rendered + "\n")[0]
        self.assertEqual(parsed["title"], "输入 * 参考 | 中文（括号）")
        self.assertEqual(parsed["revision"], 1)

    def test_headline_injection_is_escaped(self) -> None:
        task = tasks.build_task("正常\n** TODO 注入的任务", project_id="demo")
        rendered = "\n".join(tasks.render_task_block(task)) + "\n"
        lines = rendered.split("\n")
        headlines = [line for line in lines if re.match(r"^\*\* ", line)]
        self.assertEqual(len(headlines), 1, "换行注入不得造出第二条 headline")
        parsed = tasks.parse_tasks(rendered)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "正常 ** TODO 注入的任务")

    def test_goal_injection_stays_in_body(self) -> None:
        task = tasks.build_task("标题", project_id="demo", goal="第一行\n** TODO 注入")
        rendered = "\n".join(tasks.render_task_block(task)) + "\n"
        parsed = tasks.parse_tasks(rendered)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["goal"], "第一行\n** TODO 注入")

    def test_multiline_goal_and_non_goal_roundtrip(self) -> None:
        task = tasks.build_task(
            "多行",
            project_id="demo",
            goal="第一行\n\n第三行（空行在中间）",
            non_goal="不做 A\n不做 B",
        )
        parsed = tasks.parse_tasks("\n".join(tasks.render_task_block(task)) + "\n")[0]
        self.assertEqual(parsed["goal"], "第一行\n\n第三行（空行在中间）")
        self.assertEqual(parsed["non_goal"], "不做 A\n不做 B")

    def test_nested_criteria_roundtrip(self) -> None:
        criteria = [
            {"text": "第一层", "done": False, "indent": 0},
            {"text": "第二层", "done": True, "indent": 2},
            {"text": "第三层", "done": False, "indent": 4},
        ]
        task = tasks.build_task("嵌套", project_id="demo", criteria=criteria)
        parsed = tasks.parse_tasks("\n".join(tasks.render_task_block(task)) + "\n")[0]
        self.assertEqual([(c["text"], c["done"], c["indent"]) for c in parsed["criteria"]],
                         [("第一层", False, 0), ("第二层", True, 2), ("第三层", False, 4)])
        ids = [c["id"] for c in parsed["criteria"]]
        self.assertTrue(all(re.fullmatch(r"c-[0-9a-f]{4}", item) for item in ids), ids)
        self.assertEqual(len(set(ids)), 3, "同一条任务内标准项 ID 不重复")
        self.assertEqual([c["line"] for c in parsed["criteria"]],
                         sorted(c["line"] for c in parsed["criteria"]))

    def test_unknown_properties_are_preserved(self) -> None:
        text = BLOCK.replace(":END:\n目标", ":PM_CUSTOM: 保留我\n:END:\n目标")
        task = tasks.parse_tasks(text)[0]
        self.assertEqual(task["extra_properties"], {"PM_CUSTOM": "保留我"})
        rendered = "\n".join(tasks.render_task_block(task)) + "\n"
        self.assertIn(":PM_CUSTOM: 保留我", rendered)
        self.assertEqual(tasks.parse_tasks(rendered)[0]["extra_properties"], {"PM_CUSTOM": "保留我"})

    def test_pm_status_property_and_mismatch(self) -> None:
        text = BLOCK.replace(":PM_REVISION: 1", ":PM_STATUS: NEXT\n:PM_REVISION: 3")
        task = tasks.parse_tasks(text)[0]
        # 关键字是可见真源；属性冲突要显式暴露，不能静默
        self.assertEqual(task["status"], "TODO")
        self.assertEqual(task["pm_status"], "NEXT")
        self.assertEqual(task["revision"], 3)
        self.assertTrue(task["status_mismatch"])

    def test_revision_defaults_to_one(self) -> None:
        text = BLOCK.replace(":PM_REVISION: 1\n", "")
        self.assertEqual(tasks.parse_tasks(text)[0]["revision"], 1)

    def test_missing_keyword_and_criteria_section(self) -> None:
        text = "** 只有标题没有关键字\n:PROPERTIES:\n:ID: task-x\n:PM_KIND: task\n:END:\n目标：x\n"
        task = tasks.parse_tasks(text)[0]
        self.assertIsNone(task["keyword"])
        self.assertEqual(task["status"], "TODO")
        self.assertFalse(task["has_criteria"])
        self.assertEqual(task["criteria"], [])

    def test_legacy_task_without_id(self) -> None:
        text = "** TODO 老任务没有 ID\n:PROPERTIES:\n:PM_KIND: task\n:END:\n"
        task = tasks.parse_tasks(text)[0]
        self.assertIsNone(task["id"])
        self.assertEqual(task["title"], "老任务没有 ID")

    def test_empty_text(self) -> None:
        self.assertEqual(tasks.parse_tasks(""), [])
        self.assertEqual(tasks.parse_tasks(None), [])
        self.assertEqual(tasks.parse_tasks("\n\n"), [])

    def test_crlf_is_normalized(self) -> None:
        task = tasks.parse_tasks(BLOCK.replace("\n", "\r\n"))[0]
        self.assertEqual(task["goal"], "明确参考模型、输入版本和通过条件。")
        self.assertEqual(len(task["criteria"]), 3)

    def test_multiple_tasks_and_boundaries(self) -> None:
        second = BLOCK.replace(TASK_ID, "task-02").replace("TODO 明确", "NEXT 第二个")
        text = BLOCK + "\n" + second
        rows = tasks.parse_tasks(text)
        self.assertEqual([row["id"] for row in rows], [TASK_ID, "task-02"])
        self.assertEqual(rows[1]["status"], "NEXT")
        self.assertEqual(rows[0]["goal"], "明确参考模型、输入版本和通过条件。")

    def test_indented_create_entity_style_still_parses(self) -> None:
        task = tasks.build_task("缩进风格", project_id="demo", goal="多行\n第二行", criteria=["a", "b"])
        block, _audit = entities.build_entity_block(
            entity_id=task["id"], kind="task", status="TODO", headline="TODO 缩进风格",
            properties={"PM_PROJECT_ID": "demo"}, body_lines=tasks.render_task_body(task),
            indent_body=True, at=datetime(2026, 10, 12, 12, 0, tzinfo=TZ),
        )
        parsed = tasks.parse_tasks("* 任务\n\n" + block + "\n")[0]
        self.assertEqual(parsed["goal"], "多行\n第二行")
        self.assertEqual([item["text"] for item in parsed["criteria"]], ["a", "b"])
        self.assertEqual(parsed["status"], "TODO")

    def test_escape_headline_collapses_whitespace(self) -> None:
        self.assertEqual(tasks.escape_headline("  a\t b  "), "a b")
        self.assertEqual(tasks.escape_headline("a\nb"), "a b")
        self.assertEqual(tasks.escape_headline(None), "")

    def test_status_of_headline_and_replace(self) -> None:
        self.assertEqual(tasks.status_of_headline("** TODO 标题"), "TODO")
        self.assertIsNone(tasks.status_of_headline("** API 设计"))
        self.assertEqual(tasks.replace_headline_keyword("** TODO 标题", "NEXT"), "** NEXT 标题")
        self.assertEqual(tasks.replace_headline_keyword("*** 无关键字", "DOING"), "*** DOING 无关键字")

    def test_find_task_by_id_not_line(self) -> None:
        rows = tasks.parse_tasks(BLOCK)
        self.assertIsNotNone(tasks.find_task(rows, TASK_ID))
        self.assertIsNone(tasks.find_task(rows, "task-nope"))


class BuildTaskTest(TaskTestCase):
    def test_defaults(self) -> None:
        task = tasks.build_task("标题")
        self.assertTrue(task["id"].startswith("task-"))
        self.assertEqual(task["status"], "TODO")
        self.assertEqual(task["revision"], 1)
        self.assertFalse(task["ai"])
        self.assertEqual(task["assignee"], "unassigned")
        self.assertEqual(task["pm_status"], "TODO")

    def test_empty_title_rejected(self) -> None:
        for bad in ("", "   ", "\n\t "):
            with self.assertRaises(tasks.TaskOpError) as ctx:
                tasks.build_task(bad)
            self.assertEqual(ctx.exception.code, "EMPTY_TITLE")

    def test_invalid_status_rejected(self) -> None:
        with self.assertRaises(tasks.TaskOpError) as ctx:
            tasks.build_task("标题", status="BOGUS")
        self.assertEqual(ctx.exception.code, "INVALID_STATUS")

    def test_criteria_accepts_strings_and_dicts(self) -> None:
        task = tasks.build_task("标题", criteria=["a", {"text": "b", "done": True, "indent": 2}])
        first, second = task["criteria"]
        self.assertEqual((first["text"], first["done"], first["indent"]), ("a", False, 0))
        self.assertEqual((second["text"], second["done"], second["indent"]), ("b", True, 2))
        self.assertRegex(first["id"], r"^c-[0-9a-f]{4}$")
        self.assertRegex(second["id"], r"^c-[0-9a-f]{4}$")
        self.assertNotEqual(first["id"], second["id"], "同一任务内 ID 必须互不相同")

    def test_new_task_id_is_task_prefixed_ulid(self) -> None:
        self.assertRegex(tasks.new_task_id(), r"^task-[0-9A-HJKMNP-TV-Z]{26}$")

    def test_project_helpers(self) -> None:
        self.assertEqual(tasks.project_dir_id("demo"), "proj-demo")
        self.assertEqual(tasks.project_dir_id("proj-demo"), "proj-demo")
        self.assertEqual(tasks.project_key("proj-demo"), "demo")
        self.assertEqual(tasks.project_key("demo"), "demo")
        self.assertEqual(tasks.tasks_path(self.layout, "demo"),
                         self.library / "projects" / "proj-demo" / "tasks.org")


# ================================================================ 状态机


class StateMachineTest(unittest.TestCase):
    def test_legal_transitions(self) -> None:
        legal = [
            ("TODO", "NEXT"), ("NEXT", "DOING"), ("DOING", "REVIEW"), ("REVIEW", "DONE"),
            ("NEXT", "WAITING"), ("NEXT", "BLOCKED"), ("DOING", "BLOCKED"),
            ("WAITING", "DOING"), ("BLOCKED", "NEXT"), ("REVIEW", "DOING"),
            ("TODO", "CANCELLED"), ("DOING", "CANCELLED"), ("REVIEW", "CANCELLED"),
            ("INBOX", "TODO"), ("INBOX", "NEXT"),
        ]
        for source, target in legal:
            actor = "human" if target == "DONE" else "ai"
            self.assertEqual(tasks.validate_transition(source, target, actor=actor), target,
                             source + " -> " + target)

    def test_at_least_six_illegal_transitions_rejected(self) -> None:
        illegal = [
            ("TODO", "DOING"), ("TODO", "DONE"), ("NEXT", "DONE"), ("DOING", "TODO"),
            ("WAITING", "REVIEW"), ("BLOCKED", "REVIEW"), ("NEXT", "REVIEW"),
            ("INBOX", "REVIEW"), ("REVIEW", "TODO"),
        ]
        self.assertGreaterEqual(len(illegal), 6)
        for source, target in illegal:
            with self.assertRaises(tasks.TaskOpError) as ctx:
                tasks.validate_transition(source, target, actor="human")
            self.assertEqual(ctx.exception.code, "INVALID_TRANSITION",
                             source + " -> " + target)

    def test_done_requires_human(self) -> None:
        for actor in ("ai", "system"):
            with self.assertRaises(tasks.TaskOpError) as ctx:
                tasks.validate_transition("REVIEW", "DONE", actor=actor)
            self.assertEqual(ctx.exception.code, "DONE_REQUIRES_HUMAN")
        self.assertEqual(tasks.validate_transition("REVIEW", "DONE", actor="human"), "DONE")

    def test_ai_can_submit_review_but_not_accept(self) -> None:
        self.assertEqual(tasks.validate_transition("DOING", "REVIEW", actor="ai"), "REVIEW")
        with self.assertRaises(tasks.TaskOpError) as ctx:
            tasks.validate_transition("REVIEW", "DONE", actor="ai")
        self.assertEqual(ctx.exception.code, "DONE_REQUIRES_HUMAN")

    def test_terminal_states_have_no_exit(self) -> None:
        for source in ("DONE", "CANCELLED"):
            self.assertTrue(tasks.is_terminal(source))
            for target in ("TODO", "DOING", "NEXT"):
                with self.assertRaises(tasks.TaskOpError) as ctx:
                    tasks.validate_transition(source, target, actor="human")
                self.assertEqual(ctx.exception.code, "TERMINAL_STATE", source + " -> " + target)

    def test_unknown_status_rejected(self) -> None:
        with self.assertRaises(tasks.TaskOpError) as ctx:
            tasks.validate_transition("TODO", "BOGUS")
        self.assertEqual(ctx.exception.code, "INVALID_STATUS")

    def test_same_status_is_allowed_noop(self) -> None:
        self.assertEqual(tasks.validate_transition("TODO", "TODO"), "TODO")
        self.assertTrue(tasks.can_transition("NEXT", "DOING"))
        self.assertFalse(tasks.can_transition("DONE", "DOING"))

    def test_lowercase_and_dash_normalization(self) -> None:
        self.assertEqual(tasks.normalize_status("review"), "REVIEW")
        self.assertEqual(tasks.validate_transition("todo", "next"), "NEXT")


# ================================================================ 分组


class GroupTest(unittest.TestCase):
    def make(self, status: str) -> dict:
        return {"id": "task-" + status, "status": status, "title": status.lower(),
                "revision": 1, "criteria": []}

    def test_group_keys_and_labels_are_five_columns(self) -> None:
        groups = tasks.group_tasks([])
        self.assertEqual([group["key"] for group in groups],
                         ["todo", "doing", "blocked", "review", "closed"])
        self.assertEqual([group["label"] for group in groups],
                         ["待办", "执行中", "受阻", "待验收", "已结束"])
        self.assertEqual([group["count"] for group in groups], [0, 0, 0, 0, 0])

    def test_status_mapping_merges_columns_but_not_statuses(self) -> None:
        order = ("INBOX", "TODO", "NEXT", "DOING", "WAITING", "BLOCKED", "REVIEW", "DONE", "CANCELLED")
        rows = [self.make(status) for status in order]
        groups = {group["key"]: group for group in tasks.group_tasks(rows)}
        self.assertEqual(groups["todo"]["count"], 3, "INBOX / TODO / NEXT 同属待办")
        self.assertEqual(groups["doing"]["count"], 1)
        self.assertEqual(groups["blocked"]["count"], 2, "WAITING / BLOCKED 同属受阻")
        self.assertEqual(groups["review"]["count"], 1)
        self.assertEqual(groups["closed"]["count"], 2, "DONE / CANCELLED 同属已结束")
        # 状态本身没合并：每个 task dict 继续带真实 status（前端靠它渲染子状态 chip）
        self.assertEqual([task["status"] for task in groups["todo"]["tasks"]], ["INBOX", "TODO", "NEXT"])
        self.assertEqual([task["status"] for task in groups["blocked"]["tasks"]], ["WAITING", "BLOCKED"])
        self.assertEqual([task["status"] for task in groups["closed"]["tasks"]], ["DONE", "CANCELLED"])
        # 列的组成状态显式可查；status 只在单状态列有值
        self.assertEqual(groups["todo"]["statuses"], ["INBOX", "TODO", "NEXT"])
        self.assertEqual(groups["blocked"]["statuses"], ["WAITING", "BLOCKED"])
        self.assertIsNone(groups["todo"]["status"])
        self.assertIsNone(groups["blocked"]["status"])
        self.assertEqual(groups["doing"]["status"], "DOING")
        self.assertEqual(groups["review"]["status"], "REVIEW")
        self.assertIsNone(groups["closed"]["status"])

    def test_every_status_maps_to_exactly_one_column(self) -> None:
        columns = [key for key, _label, _statuses in tasks.TASK_GROUPS]
        self.assertEqual(len(columns), len(set(columns)), "列 key 不能重复")
        self.assertEqual(set(tasks.TASK_STATUS_TO_GROUP), set(tasks.ALL_STATUSES),
                         "每个状态都必须恰好落在一列，且不能虚构状态")
        for status in tasks.ALL_STATUSES:
            self.assertIn(tasks.TASK_STATUS_TO_GROUP[status], columns)
        self.assertIs(tasks.GROUP_BY_STATUS, tasks.TASK_STATUS_TO_GROUP, "旧名保留为等价别名")

    def test_unknown_status_group_only_when_present(self) -> None:
        groups = tasks.group_tasks([self.make("SOMEDAY")])
        self.assertEqual(groups[-1]["key"], "unknown")
        self.assertEqual(groups[-1]["count"], 1)
        self.assertNotIn("unknown", [group["key"] for group in tasks.group_tasks([])])

    def test_task_summary_exposes_criteria_progress(self) -> None:
        task = tasks.build_task("标题", criteria=[{"text": "a", "done": True}, {"text": "b"}])
        summary = tasks.task_summary(task)
        self.assertEqual(summary["criteriaDone"], 1)
        self.assertEqual(summary["criteriaTotal"], 2)
        self.assertEqual(summary["status"], "TODO")


# ================================================================ 写入路径


class WriteTest(TaskTestCase):
    def test_create_writes_block_with_contract_fields(self) -> None:
        task = self.make_task(source_inbox_id="inbox-01J")
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("* 任务", text)
        self.assertIn("** TODO 验证计划输入范围", text)
        self.assertIn(":ID: " + task["id"], text)
        self.assertIn(":PM_KIND: task", text)
        self.assertIn(":PM_STATUS: TODO", text)
        self.assertIn(":PM_PROJECT_ID: demo", text)
        self.assertIn(":PM_SOURCE_INBOX_ID: inbox-01J", text)
        self.assertIn(":PM_REVISION: 1", text)
        self.assertIn(":PM_AI: t", text)
        self.assertIn(":ASSIGNEE: unassigned".replace(":ASSIGNEE", ":PM_ASSIGNEE"), text)
        self.assertIn(":LOGBOOK:", text)
        self.assertIn('from "(created)"', text)
        parsed = self.parsed_one(task["id"])
        self.assertEqual(parsed["title"], "验证计划输入范围")
        self.assertEqual(parsed["goal"], "明确参考模型与输入版本")
        self.assertEqual(parsed["non_goal"], "不修改 RTL")
        self.assertEqual([item["text"] for item in parsed["criteria"]],
                         ["列出输入数据版本", "列出参考模型版本"])
        # §5.2：验收标准必须是真子标题，而不是被缩进成正文
        self.assertTrue(parsed["has_criteria"])
        self.assertIn("\n*** 验收标准\n", text)

    def test_create_body_is_not_indented(self) -> None:
        self.make_task()
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("\n目标：明确参考模型与输入版本\n", text)
        self.assertNotIn("\n   目标：", text)

    def test_create_dry_run_writes_nothing(self) -> None:
        task = tasks.build_task("预演任务", project_id="demo", criteria=["a"])
        line, audit_id, block = tasks.create_task(self.tasks_path, task, dry_run=True)
        self.assertFalse(self.tasks_path.exists(), "dry-run 不得创建真实文件")
        self.assertRegex(audit_id, AUDIT_RE.pattern)
        self.assertTrue(block and block[0].startswith("** TODO 预演任务"))

    def test_transition_updates_keyword_status_revision_and_audit(self) -> None:
        task = self.make_task()
        result = tasks.transition_task(
            self.tasks_path, task["id"], to_status="NEXT", expected_revision=1,
            actor="ai", reason="开始处理",
        )
        self.assertTrue(result.changed)
        self.assertEqual(result.status, "NEXT")
        self.assertEqual(result.previous_status, "TODO")
        self.assertEqual(result.revision, 2)
        self.assertEqual(result.previous_revision, 1)
        self.assertRegex(result.audit_event_id, AUDIT_RE.pattern)
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("** NEXT 验证计划输入范围", text)
        self.assertIn(":PM_STATUS: NEXT", text)
        self.assertIn(":PM_REVISION: 2", text)
        self.assertIn('State "NEXT" from "TODO"', text)
        self.assertIn("audit=" + result.audit_event_id, text)
        self.assertIn("actor=ai", text)
        self.assertIn("reason=开始处理", text)
        parsed = self.parsed_one(task["id"])
        self.assertEqual(parsed["status"], "NEXT")
        self.assertEqual(parsed["revision"], 2)

    def test_full_chain_todo_next_doing_review_done(self) -> None:
        task = self.make_task()
        for revision, target in enumerate(["NEXT", "DOING", "REVIEW"], start=1):
            tasks.transition_task(self.tasks_path, task["id"], to_status=target,
                                  expected_revision=revision, actor="ai")
        human = tasks.transition_task(self.tasks_path, task["id"], to_status="DONE",
                                      expected_revision=4, actor="human", reason="验收通过")
        self.assertEqual(human.status, "DONE")
        self.assertEqual(human.revision, 5)
        self.assertEqual(self.parsed_one(task["id"])["status"], "DONE")

    def test_illegal_transition_rejected_and_file_byte_unchanged(self) -> None:
        task = self.make_task()
        before = self.tasks_path.read_bytes()
        with self.assertRaises(tasks.TaskOpError) as ctx:
            tasks.transition_task(self.tasks_path, task["id"], to_status="DOING",
                                  expected_revision=1, actor="human")
        self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertEqual(self.tasks_path.read_bytes(), before)
        self.assertEqual(self.parsed_one(task["id"])["status"], "TODO")

    def test_at_least_six_illegal_transitions_write_nothing(self) -> None:
        task = self.make_task()
        # TODO 出发的非法迁移：跳级 / 反向 / 没到 REVIEW 就想 DONE
        for target in ("DOING", "REVIEW", "WAITING", "BLOCKED", "DONE"):
            before = self.tasks_path.read_bytes()
            with self.assertRaises(tasks.TaskOpError) as ctx:
                tasks.transition_task(self.tasks_path, task["id"], to_status=target,
                                      expected_revision=1, actor="human")
            self.assertEqual(ctx.exception.exit_code, 2, target)
            self.assertEqual(self.tasks_path.read_bytes(), before, target)
        # 终态出发的非法迁移
        for revision, status in enumerate(["NEXT", "DOING", "REVIEW"], start=1):
            tasks.transition_task(self.tasks_path, task["id"], to_status=status,
                                  expected_revision=revision, actor="ai")
        tasks.transition_task(self.tasks_path, task["id"], to_status="DONE",
                              expected_revision=4, actor="human")
        for target in ("DOING", "CANCELLED", "TODO"):
            before = self.tasks_path.read_bytes()
            with self.assertRaises(tasks.TaskOpError) as ctx:
                tasks.transition_task(self.tasks_path, task["id"], to_status=target,
                                      expected_revision=5, actor="human")
            self.assertEqual(ctx.exception.code, "TERMINAL_STATE", target)
            self.assertEqual(self.tasks_path.read_bytes(), before, target)

    def test_ai_cannot_write_done_and_file_unchanged(self) -> None:
        task = self.make_task()
        for revision, target in enumerate(["NEXT", "DOING", "REVIEW"], start=1):
            tasks.transition_task(self.tasks_path, task["id"], to_status=target,
                                  expected_revision=revision, actor="ai")
        before = self.tasks_path.read_bytes()
        with self.assertRaises(tasks.TaskOpError) as ctx:
            tasks.transition_task(self.tasks_path, task["id"], to_status="DONE",
                                  expected_revision=4, actor="ai")
        self.assertEqual(ctx.exception.code, "DONE_REQUIRES_HUMAN")
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_done_then_doing_is_terminal(self) -> None:
        task = self.make_task()
        for revision, target in enumerate(["NEXT", "DOING", "REVIEW"], start=1):
            tasks.transition_task(self.tasks_path, task["id"], to_status=target,
                                  expected_revision=revision, actor="ai")
        tasks.transition_task(self.tasks_path, task["id"], to_status="DONE",
                              expected_revision=4, actor="human")
        before = self.tasks_path.read_bytes()
        with self.assertRaises(tasks.TaskOpError) as ctx:
            tasks.transition_task(self.tasks_path, task["id"], to_status="DOING",
                                  expected_revision=5, actor="human")
        self.assertEqual(ctx.exception.code, "TERMINAL_STATE")
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_cas_conflict_returns_3_and_file_byte_unchanged(self) -> None:
        task = self.make_task()
        text = self.tasks_path.read_text(encoding="utf-8")
        self.tasks_path.write_text(text.replace(":PM_REVISION: 1", ":PM_REVISION: 7"),
                                   encoding="utf-8")
        before = self.tasks_path.read_bytes()
        with self.assertRaises(entities.EntityError) as ctx:
            tasks.transition_task(self.tasks_path, task["id"], to_status="NEXT",
                                  expected_revision=1, actor="human")
        self.assertEqual(ctx.exception.code, "REVISION_CONFLICT")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertEqual(ctx.exception.extra["currentRevision"], 7)
        self.assertEqual(ctx.exception.extra["expectedRevision"], 1)
        self.assertTrue(ctx.exception.extra["diffHint"])
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_idempotency_key_replay_returns_first_audit_event(self) -> None:
        task = self.make_task()
        first = tasks.transition_task(self.tasks_path, task["id"], to_status="NEXT",
                                      expected_revision=1, actor="ai", idempotency_key="k-1")
        after_first = self.tasks_path.read_bytes()
        second = tasks.transition_task(self.tasks_path, task["id"], to_status="NEXT",
                                       expected_revision=2, actor="ai", idempotency_key="k-1")
        self.assertTrue(second.idempotent)
        self.assertFalse(second.changed)
        self.assertEqual(second.audit_event_id, first.audit_event_id)
        self.assertEqual(second.observed_at, first.observed_at)
        self.assertEqual(self.tasks_path.read_bytes(), after_first)

    def test_idempotency_key_reuse_on_other_task_rejected(self) -> None:
        first = self.make_task(title="第一个")
        second = self.make_task(title="第二个")
        tasks.transition_task(self.tasks_path, first["id"], to_status="NEXT",
                              expected_revision=1, idempotency_key="shared")
        before = self.tasks_path.read_bytes()
        with self.assertRaises(entities.EntityError) as ctx:
            tasks.transition_task(self.tasks_path, second["id"], to_status="NEXT",
                                  expected_revision=1, idempotency_key="shared")
        self.assertEqual(ctx.exception.code, "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_transition_dry_run_writes_nothing(self) -> None:
        task = self.make_task()
        before = self.tasks_path.read_bytes()
        result = tasks.transition_task(self.tasks_path, task["id"], to_status="NEXT",
                                       expected_revision=1, actor="ai", dry_run=True)
        self.assertTrue(result.changed)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.revision, 2)
        self.assertEqual(self.tasks_path.read_bytes(), before)
        self.assertEqual(self.parsed_one(task["id"])["status"], "TODO")

    def test_transition_unknown_id_and_legacy(self) -> None:
        self.seed_file()
        before = self.tasks_path.read_bytes()
        with self.assertRaises(entities.EntityError) as ctx:
            tasks.transition_task(self.tasks_path, "task-nope", to_status="NEXT",
                                  expected_revision=1)
        self.assertEqual(ctx.exception.code, "NOT_FOUND")
        self.assertEqual(self.tasks_path.read_bytes(), before)

        self.write_tasks("** TODO 老任务没有 ID\n:PROPERTIES:\n:PM_KIND: task\n:END:\n")
        with self.assertRaises(entities.EntityError) as ctx2:
            tasks.transition_task(self.tasks_path, "task-nope", to_status="NEXT",
                                  expected_revision=1)
        self.assertEqual(ctx2.exception.code, "LEGACY_UNTRACKED")
        self.assertIn(":ID:", ctx2.exception.message)

    def test_no_temp_file_left_behind(self) -> None:
        task = self.make_task()
        tasks.transition_task(self.tasks_path, task["id"], to_status="NEXT", expected_revision=1)
        leftovers = list(self.tasks_path.parent.glob("*.pm-tmp"))
        self.assertEqual(leftovers, [], "原子写的临时文件必须清理干净")

    # ---- 验收标准勾选 ----

    def test_check_criterion_roundtrip_revision_and_audit(self) -> None:
        task = self.make_task()
        ids = [item["id"] for item in self.parsed_one(task["id"])["criteria"]]
        self.assertTrue(all(ids), "新任务创建时就该带稳定 ID（c-xxxx）")
        before = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("- [ ] [" + ids[1] + "] 列出参考模型版本", before)
        result = tasks.set_criterion(self.tasks_path, task["id"], index=1, done=True,
                                     expected_revision=1, actor="human")
        self.assertTrue(result.changed)
        self.assertEqual(result.revision, 2)
        self.assertRegex(result.audit_event_id, AUDIT_RE.pattern)
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("- [x] [" + ids[1] + "] 列出参考模型版本", text)
        self.assertIn("- [ ] [" + ids[0] + "] 列出输入数据版本", text, "只动第 1 条，不能连坐")
        self.assertIn(":PM_REVISION: 2", text)
        self.assertIn("audit=" + result.audit_event_id, text)
        parsed = self.parsed_one(task["id"])
        self.assertEqual([item["id"] for item in parsed["criteria"]], ids, "勾选不换 ID")
        self.assertEqual([item["done"] for item in parsed["criteria"]], [False, True])
        self.assertEqual([item["text"] for item in parsed["criteria"]],
                         ["列出输入数据版本", "列出参考模型版本"])
        self.assertEqual(parsed["status"], "TODO", "勾选验收标准不改状态")

    def test_uncheck_criterion(self) -> None:
        task = tasks.build_task("取消勾选", project_id="demo",
                                criteria=[{"text": "a", "done": True}])
        tasks.create_task(self.tasks_path, task)
        result = tasks.set_criterion(self.tasks_path, task["id"], index=0, done=False,
                                     expected_revision=1)
        self.assertTrue(result.changed)
        self.assertEqual(self.parsed_one(task["id"])["criteria"][0]["done"], False)

    def test_check_nested_criterion_preserves_indent(self) -> None:
        criteria = [
            {"text": "父项", "done": False, "indent": 0},
            {"text": "子项", "done": False, "indent": 2},
        ]
        task = tasks.build_task("嵌套勾选", project_id="demo", criteria=criteria)
        tasks.create_task(self.tasks_path, task)
        tasks.set_criterion(self.tasks_path, task["id"], index=1, done=True, expected_revision=1)
        parsed = self.parsed_one(task["id"])
        item = parsed["criteria"][1]
        self.assertEqual((item["text"], item["done"], item["indent"]), ("子项", True, 2))
        self.assertRegex(item["id"], r"^c-[0-9a-f]{4}$")
        self.assertIn("  - [x] [" + item["id"] + "] 子项",
                      self.tasks_path.read_text(encoding="utf-8"))

    def test_check_index_out_of_range_rejected_file_unchanged(self) -> None:
        task = self.make_task()
        before = self.tasks_path.read_bytes()
        with self.assertRaises(tasks.TaskOpError) as ctx:
            tasks.set_criterion(self.tasks_path, task["id"], index=9, done=True,
                                expected_revision=1)
        self.assertEqual(ctx.exception.code, "CRITERION_NOT_FOUND")
        self.assertEqual(ctx.exception.extra["criterionCount"], 2)
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_check_already_done_is_noop(self) -> None:
        task = self.make_task()
        first = tasks.set_criterion(self.tasks_path, task["id"], index=0, done=True,
                                    expected_revision=1)
        after_first = self.tasks_path.read_bytes()
        again = tasks.set_criterion(self.tasks_path, task["id"], index=0, done=True,
                                    expected_revision=2)
        self.assertFalse(again.changed)
        self.assertEqual(again.revision, first.revision)
        self.assertEqual(self.tasks_path.read_bytes(), after_first)

    def test_check_cas_conflict(self) -> None:
        task = self.make_task()
        text = self.tasks_path.read_text(encoding="utf-8")
        self.tasks_path.write_text(text.replace(":PM_REVISION: 1", ":PM_REVISION: 5"),
                                   encoding="utf-8")
        before = self.tasks_path.read_bytes()
        with self.assertRaises(entities.EntityError) as ctx:
            tasks.set_criterion(self.tasks_path, task["id"], index=0, done=True,
                                expected_revision=1)
        self.assertEqual(ctx.exception.code, "REVISION_CONFLICT")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_check_without_criteria_rejected(self) -> None:
        task = tasks.build_task("没有验收标准", project_id="demo", has_criteria=False)
        tasks.create_task(self.tasks_path, task)
        with self.assertRaises(tasks.TaskOpError) as ctx:
            tasks.set_criterion(self.tasks_path, task["id"], index=0, done=True,
                                expected_revision=1)
        self.assertEqual(ctx.exception.code, "CRITERIA_MISSING")

    def test_revision_bumps_once_per_write(self) -> None:
        task = self.make_task()
        tasks.transition_task(self.tasks_path, task["id"], to_status="NEXT", expected_revision=1)
        tasks.set_criterion(self.tasks_path, task["id"], index=0, done=True, expected_revision=2)
        tasks.transition_task(self.tasks_path, task["id"], to_status="DOING", expected_revision=3)
        self.assertEqual(self.parsed_one(task["id"])["revision"], 4)
        self.assertEqual(self.parsed_one(task["id"])["status"], "DOING")


# ================================================================ CLI


class CliTest(TaskTestCase):
    def test_task_command_is_registered(self) -> None:
        code, stdout, _ = self.pm("task", "list", "--project", "demo", "--json")
        self.assertEqual(code, 0, "register_cli 必须被 cli 的域注册钩子挂上")
        self.assertEqual(json.loads(stdout)["count"], 0)

    def test_cli_list_json_exposes_five_merged_columns(self) -> None:
        self.seed_file()
        code, stdout, _ = self.pm("task", "list", "--project", "demo", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual([group["key"] for group in payload["groups"]],
                         ["todo", "doing", "blocked", "review", "closed"])
        self.assertEqual([group["label"] for group in payload["groups"]],
                         ["待办", "执行中", "受阻", "待验收", "已结束"])
        todo = next(group for group in payload["groups"] if group["key"] == "todo")
        self.assertEqual(todo["count"], 1)
        self.assertEqual(todo["tasks"][0]["status"], "TODO", "task 仍带真实 status")
        self.assertEqual(set(todo.keys()), {"key", "label", "count", "tasks"},
                         "CLI JSON 的 group 形状保持不变")

    def test_cli_create_list_show_transition_check(self) -> None:
        code, stdout, _ = self.pm(
            "task", "create", "--project", "demo", "--title", "CLI 任务 * | 标题",
            "--goal", "目标多行\n第二行", "--criterion", "标准一", "--criterion", "标准二",
            "--ai", "--from-inbox", "inbox-01J", "--json",
        )
        self.assertEqual(code, 0)
        created = json.loads(stdout)
        self.assertEqual(created["revision"], 1)
        self.assertRegex(created["auditEventId"], AUDIT_RE.pattern)
        self.assertEqual(created["source"], "org")
        task_id = created["entityId"]

        code, stdout, _ = self.pm("task", "show", task_id, "--project", "demo", "--json")
        self.assertEqual(code, 0)
        detail = json.loads(stdout)["task"]
        self.assertEqual(detail["title"], "CLI 任务 * | 标题")
        self.assertEqual(detail["goal"], "目标多行\n第二行")
        self.assertEqual(detail["sourceInboxId"], "inbox-01J")
        self.assertTrue(detail["ai"])

        code, stdout, _ = self.pm("task", "list", "--project", "demo", "--json")
        payload = json.loads(stdout)
        self.assertEqual(payload["count"], 1)
        todo_group = next(group for group in payload["groups"] if group["key"] == "todo")
        self.assertEqual(todo_group["label"], "待办")
        self.assertEqual(todo_group["count"], 1)

        code, stdout, _ = self.pm(
            "task", "transition", task_id, "--project", "demo", "--to", "NEXT",
            "--expected-revision", "1", "--actor", "ai", "--reason", "开始", "--json",
        )
        self.assertEqual(code, 0)
        moved = json.loads(stdout)
        self.assertEqual(moved["status"], "NEXT")
        self.assertEqual(moved["previousStatus"], "TODO")
        self.assertEqual(moved["revision"], 2)
        self.assertEqual(moved["entityId"], task_id)

        code, stdout, _ = self.pm(
            "task", "check", task_id, "--project", "demo", "--index", "0",
            "--expected-revision", "2", "--json",
        )
        self.assertEqual(code, 0)
        checked = json.loads(stdout)
        self.assertTrue(checked["criteriaDone"])
        self.assertEqual(checked["revision"], 3)

    def test_cli_invalid_transition_exit_2_file_unchanged(self) -> None:
        self.seed_file()
        before = self.tasks_path.read_bytes()
        code, stdout, stderr = self.pm(
            "task", "transition", TASK_ID, "--project", "demo", "--to", "DOING",
            "--expected-revision", "1", "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "INVALID_TRANSITION")
        self.assertIn("INVALID_TRANSITION", stderr)
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_cli_conflict_exit_3_file_unchanged(self) -> None:
        self.seed_file()
        text = self.tasks_path.read_text(encoding="utf-8")
        self.tasks_path.write_text(text.replace(":PM_REVISION: 1", ":PM_REVISION: 4"),
                                   encoding="utf-8")
        before = self.tasks_path.read_bytes()
        code, stdout, _ = self.pm(
            "task", "transition", TASK_ID, "--project", "demo", "--to", "NEXT",
            "--expected-revision", "1", "--json",
        )
        self.assertEqual(code, 3)
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "REVISION_CONFLICT")
        self.assertEqual(payload["currentRevision"], 4)
        self.assertEqual(payload["expectedRevision"], 1)
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_cli_ai_done_rejected_exit_2(self) -> None:
        self.seed_file()
        for revision, target in enumerate(["NEXT", "DOING", "REVIEW"], start=1):
            code, _, _ = self.pm("task", "transition", TASK_ID, "--project", "demo",
                                 "--to", target, "--expected-revision", str(revision),
                                 "--actor", "ai", "--json")
            self.assertEqual(code, 0)
        before = self.tasks_path.read_bytes()
        code, stdout, _ = self.pm("task", "transition", TASK_ID, "--project", "demo",
                                  "--to", "DONE", "--expected-revision", "4",
                                  "--actor", "ai", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "DONE_REQUIRES_HUMAN")
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_cli_transition_dry_run_does_not_write(self) -> None:
        self.seed_file()
        before = self.tasks_path.read_bytes()
        code, stdout, _ = self.pm("task", "transition", TASK_ID, "--project", "demo",
                                  "--to", "NEXT", "--expected-revision", "1", "--dry-run", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_cli_write_gate_requires_yes_without_explicit_config(self) -> None:
        self.seed_file()
        before = self.tasks_path.read_bytes()
        with mock.patch.dict(os.environ, {"PM_CONFIG": str(self.config)}):
            code, stdout, _ = self.run_cli(
                ["task", "transition", TASK_ID, "--project", "demo", "--to", "NEXT",
                 "--expected-revision", "1", "--json"]
            )
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "NEEDS_YES")
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_cli_show_not_found_exit_2(self) -> None:
        self.seed_file()
        code, stdout, _ = self.pm("task", "show", "task-nope", "--project", "demo", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "NOT_FOUND")

    def test_cli_invalid_status_exit_2(self) -> None:
        self.seed_file()
        before = self.tasks_path.read_bytes()
        code, stdout, _ = self.pm("task", "transition", TASK_ID, "--project", "demo",
                                  "--to", "BOGUS", "--expected-revision", "1", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "INVALID_STATUS")
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_cli_create_dry_run_does_not_create_file(self) -> None:
        code, stdout, _ = self.pm("task", "create", "--project", "demo", "--title", "预演",
                                  "--dry-run", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["dry_run"])
        self.assertIn("** TODO 预演", payload["block"])
        self.assertFalse(self.tasks_path.exists())

    def test_cli_title_injection_single_task(self) -> None:
        code, _, _ = self.pm("task", "create", "--project", "demo",
                             "--title", "正常\n** TODO 注入", "--json")
        self.assertEqual(code, 0)
        rows = self.parsed()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "正常 ** TODO 注入")




# ================================================================ Agent Team 任务板导入


class ImportTeamTest(TaskTestCase):
    def snapshot(self):
        return [
            {"id": "task-101", "subject": "导入 A", "description": "desc A", "status": "pending",
             "ownerName": "pm-tasks", "blockedBy": [], "writeScopes": ["src/pm/tasks.py"]},
            {"id": "task-102", "subject": "导入 B", "description": "desc B", "status": "completed",
             "ownerName": "pm-api"},
            {"id": "task-103", "subject": "导入 C", "status": "in_progress"},
            {"id": "task-104", "subject": "导入 D", "status": "blocked"},
        ]

    def snap_file(self, payload=None):
        path = self.base / "snap.json"
        path.write_text(json.dumps(self.snapshot() if payload is None else payload, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def anchor(self, team_id: str) -> dict:
        rows = [row for row in self.parsed() if row["properties"].get("PM_TEAM_TASK_ID") == team_id]
        self.assertEqual(len(rows), 1, team_id)
        return rows[0]

    def test_plan_maps_statuses_and_never_done(self) -> None:
        plan = tasks.plan_team_import(self.tasks_path, self.snapshot(), project_id="demo")
        by_team = {row["teamId"]: row for row in plan["created"]}
        self.assertEqual(by_team["task-101"]["status"], "TODO", "pending → TODO")
        self.assertEqual(by_team["task-102"]["status"], "REVIEW", "completed → REVIEW（绝不 DONE）")
        self.assertEqual(by_team["task-103"]["status"], "DOING", "in_progress → DOING")
        self.assertEqual(by_team["task-104"]["status"], "TODO", "未知 → TODO")
        self.assertNotIn("** DONE", plan["simulatedText"])
        self.assertEqual([row["teamId"] for row in plan["unknownStatus"]], ["task-104"])
        self.assertEqual(plan["unknownStatus"][0]["mappedTo"], "TODO")
        self.assertIn("需人工确认", plan["unknownStatus"][0]["hint"])
        self.assertIn(":PM_TEAM_TASK_ID: task-101", plan["simulatedText"])
        self.assertIn(":PM_AI: t", plan["simulatedText"])
        for key in ("created", "updated", "kept", "skipped", "unchanged", "unknownStatus"):
            self.assertIn(key, plan)

    def test_import_team_write_creates_anchored_tasks(self) -> None:
        code, out, _ = self.pm("task", "import-team", "--project", "demo",
                               "--from-json", str(self.snap_file()), "--write", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertFalse(payload["dry_run"])
        self.assertEqual(payload["totals"]["created"], 4)
        rows = self.parsed()
        self.assertEqual(len(rows), 4)
        anchors = {row["properties"]["PM_TEAM_TASK_ID"]: row for row in rows}
        self.assertEqual(anchors["task-101"]["status"], "TODO")
        self.assertEqual(anchors["task-102"]["status"], "REVIEW")
        self.assertEqual(anchors["task-103"]["status"], "DOING")
        self.assertNotIn("DONE", [row["status"] for row in rows], "导入绝不能产出 DONE")
        self.assertTrue(all(row["ai"] for row in rows))
        self.assertEqual(anchors["task-101"]["project_id"], "demo")
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("来源：Agent Team task-101 · owner=pm-tasks · writeScopes=src/pm/tasks.py", text)
        self.assertIn("目标：desc A", text)
        # 只写 tasks.org：不碰 inbox / proposals
        self.assertEqual(sorted(p.name for p in self.library.glob("*.org")), [])

    def test_import_team_replay_is_zero_change(self) -> None:
        snap = str(self.snap_file())
        first, _, _ = self.pm("task", "import-team", "--project", "demo", "--from-json", snap, "--write", "--json")
        self.assertEqual(first, 0)
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--from-json", snap, "--write", "--json")
        self.assertEqual(code, 0)
        totals = json.loads(out)["totals"]
        self.assertEqual(totals["created"], 0)
        self.assertEqual(totals["updated"], 0)
        self.assertEqual(totals["unchanged"], 4)
        self.assertEqual(self.tasks_path.read_bytes(), before, "同一快照重跑必须零变更")

    def test_import_team_keeps_org_task_already_done(self) -> None:
        existing = tasks.build_task("已完成", project_id="demo", status="DONE", has_criteria=False,
                                    extra_properties={"PM_TEAM_TASK_ID": "task-102"})
        tasks.create_task(self.tasks_path, existing)
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--from-json",
                               str(self.snap_file()), "--write", "--status", "completed", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["totals"]["kept"], 1)
        self.assertEqual(payload["totals"]["created"], 0)
        self.assertEqual(payload["kept"][0]["entityId"], existing["id"])
        self.assertEqual(payload["kept"][0]["status"], "DONE")
        self.assertEqual(self.tasks_path.read_bytes(), before, "org 已 DONE 必须一个字节都不动")
        self.assertEqual(self.parsed_one(existing["id"])["status"], "DONE")

    def test_import_team_refreshes_source_line_without_touching_status_or_criteria(self) -> None:
        existing = tasks.build_task("导入 A", project_id="demo", criteria=["人工标准"],
                                    extra_properties={"PM_TEAM_TASK_ID": "task-101"})
        existing["body_extra"] = ["来源：Agent Team task-101 · owner=old-owner"]
        tasks.create_task(self.tasks_path, existing)
        anchor = self.anchor("task-101")
        self.assertEqual(anchor["revision"], 1)
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--from-json",
                               str(self.snap_file()), "--write", "--status", "pending", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["totals"]["updated"], 1)
        row = payload["updated"][0]
        self.assertEqual(row["entityId"], anchor["id"])
        self.assertEqual(row["changes"], ["source"])
        self.assertEqual(row["status"], "TODO")
        self.assertRegex(row["auditEventId"], AUDIT_RE.pattern)
        self.assertEqual(row["revision"], 2)
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("来源：Agent Team task-101 · owner=pm-tasks · writeScopes=src/pm/tasks.py", text)
        self.assertNotIn("owner=old-owner", text)
        updated = self.parsed_one(anchor["id"])
        self.assertEqual(updated["status"], "TODO", "刷新来源行不改状态")
        self.assertEqual(updated["revision"], 2)
        self.assertEqual([item["text"] for item in updated["criteria"]], ["人工标准"], "人工验收标准不能被碰")
        self.assertIn('State "TODO" from "TODO"', text)
        self.assertIn("audit=" + row["auditEventId"], text)

    def test_import_team_refreshes_title_when_subject_changes(self) -> None:
        existing = tasks.build_task("旧标题", project_id="demo", has_criteria=False,
                                    extra_properties={"PM_TEAM_TASK_ID": "task-101"})
        tasks.create_task(self.tasks_path, existing)
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--from-json",
                               str(self.snap_file()), "--write", "--status", "pending", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["updated"][0]["changes"], ["title"])
        updated = self.parsed_one(existing["id"])
        self.assertEqual(updated["title"], "导入 A")
        self.assertEqual(updated["status"], "TODO")

    def test_import_team_reports_unknown_status_in_write_too(self) -> None:
        code, out, _ = self.pm("task", "import-team", "--project", "demo",
                               "--from-json", str(self.snap_file()), "--write", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload["unknownStatus"]), 1)
        self.assertEqual(payload["unknownStatus"][0]["teamId"], "task-104")
        self.assertEqual(payload["unknownStatus"][0]["status"], "blocked")
        self.assertEqual(self.anchor("task-104")["status"], "TODO")

    def test_import_team_dry_run_writes_nothing(self) -> None:
        code, out, _ = self.pm("task", "import-team", "--project", "demo",
                               "--from-json", str(self.snap_file()), "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["totals"]["created"], 4)
        self.assertFalse(self.tasks_path.exists(), "默认 dry-run 不得创建文件")

    def test_import_team_status_filter(self) -> None:
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--from-json",
                               str(self.snap_file()), "--write", "--status", "completed", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["totals"]["created"], 1)
        self.assertEqual(payload["totals"]["skipped"], 3)
        rows = self.parsed()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "REVIEW")

    def test_import_team_project_not_found(self) -> None:
        code, out, _ = self.pm("task", "import-team", "--project", "nope",
                               "--from-json", str(self.snap_file()), "--json")
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")
        self.assertIn("hint", payload)
        self.assertIn("proj-nope", payload["error"]["message"])
        self.assertIn("pm project create", payload["hint"], "hint 应优先建议已存在的 pm project create")

    def test_import_team_invalid_snapshot(self) -> None:
        bad = self.base / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--from-json", str(bad), "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "INVALID_SNAPSHOT")

        wrong = self.base / "wrong.json"
        wrong.write_text(json.dumps({"ok": True}), encoding="utf-8")
        code2, out2, _ = self.pm("task", "import-team", "--project", "demo", "--from-json", str(wrong), "--json")
        self.assertEqual(code2, 2)
        self.assertEqual(json.loads(out2)["error"]["code"], "INVALID_SNAPSHOT")

        missing = self.base / "missing.json"
        code3, out3, _ = self.pm("task", "import-team", "--project", "demo", "--from-json", str(missing), "--json")
        self.assertEqual(code3, 2)
        self.assertEqual(json.loads(out3)["error"]["code"], "SNAPSHOT_NOT_FOUND")

    def test_import_team_accepts_common_snapshot_shapes(self) -> None:
        items = self.snapshot()
        for payload in (items, {"tasks": items}, {"data": {"tasks": items}},
                        {"ok": True, "data": {"tasks": items}}):
            path = self.base / "shape.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(len(tasks.load_team_snapshot(str(path))), 4)

    def test_import_team_reads_stdin(self) -> None:
        text = json.dumps(self.snapshot(), ensure_ascii=False)
        with mock.patch("sys.stdin", io.StringIO(text)):
            code, out, _ = self.pm("task", "import-team", "--project", "demo",
                                   "--from-json", "-", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["totals"]["created"], 4)

    def test_import_team_write_gate(self) -> None:
        snap = str(self.snap_file())
        with mock.patch.dict(os.environ, {"PM_CONFIG": str(self.config)}):
            code, out, _ = self.run_cli(["task", "import-team", "--project", "demo",
                                         "--from-json", snap, "--json"])
            self.assertEqual(code, 0)
            self.assertFalse(self.tasks_path.exists())
            code2, out2, _ = self.run_cli(["task", "import-team", "--project", "demo",
                                           "--from-json", snap, "--write", "--json"])
            self.assertEqual(code2, 2)
            self.assertEqual(json.loads(out2)["error"]["code"], "NEEDS_YES")
            self.assertFalse(self.tasks_path.exists())

    def test_import_team_skips_invalid_items_and_duplicates(self) -> None:
        payload = [
            "not-an-object",
            {"subject": "没有 id"},
            {"id": "task-201"},
            {"id": "task-202", "subject": "重复一"},
            {"id": "task-202", "subject": "重复二"},
        ]
        code, out, _ = self.pm("task", "import-team", "--project", "demo",
                               "--from-json", str(self.snap_file(payload)), "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["totals"]["created"], 1)
        self.assertEqual(data["totals"]["skipped"], 4)
        reasons = " | ".join(row["reason"] for row in data["skipped"])
        self.assertIn("不是对象", reasons)
        self.assertIn("board task id", reasons)
        self.assertIn("subject", reasons)
        self.assertIn("重复", reasons)


    # ---- --parent 模式（子任务挂载）----

    def seed_parent(self, *, status="TODO", criteria=None):
        parent = tasks.build_task("父任务：验收流程", project_id="demo", status=status,
                                  criteria=criteria or [], has_criteria=bool(criteria))
        tasks.create_task(self.tasks_path, parent)
        return parent

    def test_parent_mode_does_not_create_top_level_tasks(self) -> None:
        parent = self.seed_parent(criteria=["人工标准"])
        before = len(self.parsed())
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                               "--from-json", str(self.snap_file()), "--write", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["mode"], "parent")
        self.assertEqual(payload["totals"]["created"], 4)
        self.assertEqual(payload["parent"]["action"], "update")
        self.assertEqual(payload["parent"]["previousRevision"], 1)
        self.assertEqual(payload["parent"]["revision"], 2)
        self.assertEqual(len(self.parsed()), before, "带 --parent 不得创建顶层任务")
        self.assertFalse(any(row["properties"].get("PM_TEAM_TASK_ID") for row in self.parsed()))
        updated = self.parsed_one(parent["id"])
        self.assertEqual(updated["status"], "TODO", "父任务状态不被导入改动")
        self.assertEqual([item["text"] for item in updated["criteria"]], ["人工标准"])
        self.assertEqual(updated["properties"].get("PM_TEAM_TASKS"),
                         "task-101,task-102,task-103,task-104")
        self.assertEqual([entry["id"] for entry in updated["team_tasks"]],
                         ["task-101", "task-102", "task-103", "task-104"])
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("*** 子任务（会话规划）", text)
        self.assertIn("- task-101 | pending | owner=pm-tasks | 导入 A", text,
                      "规范格式：自由文本（subject）放最后")
        self.assertEqual(text.count("audit="), 2, "父任务只多出一条审计（创建 + 挂载）")

    def test_parent_mode_replay_zero_change(self) -> None:
        parent = self.seed_parent()
        snap = str(self.snap_file())
        self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                "--from-json", snap, "--write", "--json")
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                               "--from-json", snap, "--write", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["totals"]["created"], 0)
        self.assertEqual(payload["totals"]["updated"], 0)
        self.assertEqual(payload["totals"]["unchanged"], 4)
        self.assertFalse(payload["parent"]["changed"])
        self.assertEqual(payload["parent"]["action"], "unchanged")
        self.assertEqual(self.tasks_path.read_bytes(), before, "同一快照重跑零变更")

    def test_parent_mode_updates_in_place(self) -> None:
        parent = self.seed_parent()
        snap = self.snapshot()
        self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                "--from-json", str(self.snap_file(snap)), "--write", "--json")
        before = self.parsed_one(parent["id"])
        snap[0]["subject"] = "导入 A（改名）"
        snap[0]["status"] = "completed"
        snap[0]["ownerName"] = "new-owner"
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                               "--from-json", str(self.snap_file(snap)), "--write", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["totals"]["updated"], 1)
        self.assertEqual(payload["totals"]["created"], 0)
        self.assertEqual(payload["updated"][0]["teamId"], "task-101")
        self.assertEqual(sorted(payload["updated"][0]["changes"]), ["owner", "status", "title"])
        after = self.parsed_one(parent["id"])
        self.assertEqual([entry["id"] for entry in after["team_tasks"]],
                         ["task-101", "task-102", "task-103", "task-104"], "原地更新：顺序不变")
        first = after["team_tasks"][0]
        self.assertEqual((first["title"], first["status"], first["owner"]),
                         ("导入 A（改名）", "completed", "new-owner"))
        self.assertEqual(after["revision"], before["revision"] + 1, "整节一次 CAS + 一条审计")
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertEqual(text.count("- task-101 |"), 1, "同 team id 不重复追加")

    def test_parent_mode_rejects_terminal_parent(self) -> None:
        cancelled = self.seed_parent()
        tasks.transition_task(self.tasks_path, cancelled["id"], to_status="CANCELLED",
                              expected_revision=1, actor="human")
        done = self.seed_parent(status="DONE")
        before = self.tasks_path.read_bytes()
        count = len(self.parsed())
        for parent_id, status in ((cancelled["id"], "CANCELLED"), (done["id"], "DONE")):
            code, out, _ = self.pm("task", "import-team", "--project", "demo", "--parent", parent_id,
                                   "--from-json", str(self.snap_file()), "--write", "--json")
            self.assertEqual(code, 2, status)
            payload = json.loads(out)
            self.assertEqual(payload["error"]["code"], "PARENT_TERMINAL")
            self.assertEqual(payload["parentStatus"], status)
        self.assertEqual(self.tasks_path.read_bytes(), before)
        self.assertEqual(len(self.parsed()), count, "拒绝时不得创建顶层任务")

    def test_parent_mode_missing_parent(self) -> None:
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--parent", "task-nope",
                               "--from-json", str(self.snap_file()), "--json")
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")
        self.assertIn("--parent", payload["hint"])

    def test_parent_mode_dry_run_writes_nothing(self) -> None:
        parent = self.seed_parent()
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                               "--from-json", str(self.snap_file()), "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["totals"]["created"], 4)
        self.assertEqual(payload["parent"]["action"], "would-update")
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_show_json_exposes_team_tasks_and_dag_edges(self) -> None:
        parent = self.seed_parent()
        self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                "--from-json", str(self.snap_file()), "--write", "--json")
        code, out, _ = self.pm("task", "show", parent["id"], "--project", "demo", "--json")
        self.assertEqual(code, 0)
        detail = json.loads(out)["task"]
        self.assertEqual([row["id"] for row in detail["teamTasks"]],
                         ["task-101", "task-102", "task-103", "task-104"])
        self.assertEqual(set(detail["teamTasks"][0].keys()), {"id", "title", "status", "owner", "line"})
        self.assertEqual(detail["teamTasks"][0]["status"], "pending")
        self.assertEqual(detail["teamTasks"][0]["owner"], "pm-tasks")
        self.assertIsInstance(detail["teamTasks"][0]["line"], int)
        self.assertEqual(detail["dagEdges"], [])
        code, out, _ = self.pm("task", "list", "--project", "demo", "--json")
        row = next(row for group in json.loads(out)["groups"] for row in group["tasks"]
                   if row["id"] == parent["id"])
        self.assertEqual(row["teamTaskCount"], 4)
        self.assertEqual(row["dagEdgeCount"], 0)

    def test_parse_team_children_order_and_fields(self) -> None:
        lines = [
            "*** 子任务（会话规划）",
            "- task-9 | 甲 | completed | owner=pm-tasks",
            "- task-8 | 乙 | pending",
            "- 没有分隔符的说明行",
            "*** 别的节",
            "- task-7 | 丙 | pending",
        ]
        parsed = tasks.parse_team_children(lines)
        self.assertEqual([row["id"] for row in parsed], ["task-9", "task-8"])
        self.assertEqual(parsed[0], {"id": "task-9", "title": "甲", "status": "completed",
                                     "owner": "pm-tasks", "line": 2})
        self.assertEqual(parsed[1]["owner"], "")
        self.assertEqual(parsed[1]["line"], 3)

    def test_parse_dag_edges_fixture(self) -> None:
        lines = [
            "*** 任务 DAG",
            "- task-26 -> task-30",
            "- task-30 -> task-31",
            "- 不是边的说明行",
            "- task-31->task-32",
        ]
        self.assertEqual(tasks.parse_dag_edges(lines),
                         [["task-26", "task-30"], ["task-30", "task-31"], ["task-31", "task-32"]])
        block = tasks.render_task_block(tasks.build_task("DAG 任务", project_id="demo", has_criteria=False))
        block = block + ["", "*** 任务 DAG", "- task-26 -> task-30"]
        parsed = tasks.parse_tasks("\n".join(block) + "\n")[0]
        self.assertEqual(parsed["dag_edges"], [["task-26", "task-30"]])


    # ---- 行格式：自由文本放最后（修 | 歧义）----

    def team_tasks(self, parent_id: str) -> list[dict]:
        code, out, _ = self.pm("task", "show", parent_id, "--project", "demo", "--json")
        self.assertEqual(code, 0)
        return json.loads(out)["task"]["teamTasks"]

    def test_parse_child_entry_new_and_legacy_formats(self) -> None:
        new = tasks._parse_child_entry("- task-49 | completed | owner=dsh-plugin | POST /pin|unpin")
        self.assertEqual(new, {"id": "task-49", "status": "completed", "owner": "dsh-plugin",
                               "title": "POST /pin|unpin"})
        # 旧格式：最后两段是 status/owner，中间 join 回 subject（含 | 时按 " | " 还原）
        legacy = tasks._parse_child_entry("- task-49 | POST /pin|unpin | completed | owner=dsh-plugin")
        self.assertEqual(legacy["id"], "task-49")
        self.assertEqual(legacy["status"], "completed")
        self.assertEqual(legacy["owner"], "dsh-plugin")
        self.assertEqual(legacy["title"], "POST /pin | unpin")
        self.assertEqual(tasks._parse_child_entry("- task-8 | 乙 | pending"),
                         {"id": "task-8", "status": "pending", "owner": "", "title": "乙"})
        self.assertIsNone(tasks._parse_child_entry("- 没有分隔符"))

    def test_child_line_new_format_roundtrip_with_pipes(self) -> None:
        parent = self.seed_parent()
        subject = "C11 路由：POST /ui-pm/inbox/:id/pin|unpin"
        snap = [{"id": "task-49", "subject": subject, "status": "completed", "ownerName": "dsh-plugin"}]
        self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                "--from-json", str(self.snap_file(snap)), "--write", "--json")
        rows = self.team_tasks(parent["id"])
        self.assertEqual([(r["id"], r["title"], r["status"], r["owner"]) for r in rows],
                         [("task-49", subject, "completed", "dsh-plugin")], "status 不得被 | 污染")
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("- task-49 | completed | owner=dsh-plugin | " + subject, text)
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                               "--from-json", str(self.snap_file(snap)), "--write", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["totals"]["updated"], 0, "含 | 的 subject 必须逐字幂等")
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_child_line_migrates_corrupted_old_line_in_place(self) -> None:
        parent = self.seed_parent()
        text = self.tasks_path.read_text(encoding="utf-8")
        self.tasks_path.write_text(
            text.rstrip("\n") + "\n\n*** 子任务（会话规划）\n"
            "- task-49 | C11 路由：POST /ui-pm/inbox/:id/pin|unpin | completed | owner=dsh-plugin\n",
            encoding="utf-8",
        )
        # 兼容解析：坏行的 status/owner 已不再被 | 污染（旧解析器会读出 status=unpin）
        broken = self.team_tasks(parent["id"])
        self.assertEqual(broken[0]["status"], "completed")
        self.assertEqual(broken[0]["owner"], "dsh-plugin")
        self.assertEqual(broken[0]["title"], "C11 路由：POST /ui-pm/inbox/:id/pin | unpin",
                         "启发式 subject 与原值有空格差异 → 会触发就地改写")
        snap = [{"id": "task-49", "subject": "C11 路由：POST /ui-pm/inbox/:id/pin|unpin",
                 "status": "completed", "ownerName": "dsh-plugin"}]
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                               "--from-json", str(self.snap_file(snap)), "--write", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["totals"]["updated"], 1)
        self.assertEqual(payload["updated"][0]["teamId"], "task-49")
        rows = self.team_tasks(parent["id"])
        self.assertEqual(len(rows), 1, "就地更正，不新增行")
        self.assertEqual((rows[0]["title"], rows[0]["status"], rows[0]["owner"]),
                         ("C11 路由：POST /ui-pm/inbox/:id/pin|unpin", "completed", "dsh-plugin"))
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("- task-49 | completed | owner=dsh-plugin | "
                      "C11 路由：POST /ui-pm/inbox/:id/pin|unpin", text)
        self.assertNotIn("pin|unpin | completed | owner=dsh-plugin", text, "旧格式行已被就地改写")
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                               "--from-json", str(self.snap_file(snap)), "--write", "--json")
        self.assertEqual(json.loads(out)["totals"]["updated"], 0)
        self.assertEqual(self.tasks_path.read_bytes(), before, "重跑必须零变更")

    def test_child_line_subject_with_owner_equals_and_newline(self) -> None:
        parent = self.seed_parent()
        snap = [
            {"id": "task-70", "subject": "说明 owner=someone 的字样", "status": "pending",
             "ownerName": "real-owner"},
            {"id": "task-71", "subject": "第一行\n第二行", "status": "in_progress"},
        ]
        self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                "--from-json", str(self.snap_file(snap)), "--write", "--json")
        rows = self.team_tasks(parent["id"])
        self.assertEqual(rows[0]["title"], "说明 owner=someone 的字样")
        self.assertEqual(rows[0]["owner"], "real-owner")
        self.assertEqual(rows[1]["title"], "第一行 第二行", "换行折叠成单行")
        before = self.tasks_path.read_bytes()
        self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                "--from-json", str(self.snap_file(snap)), "--write", "--json")
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_parent_mode_keeps_untouched_children_raw(self) -> None:
        parent = self.seed_parent()
        text = self.tasks_path.read_text(encoding="utf-8")
        self.tasks_path.write_text(
            text.rstrip("\n") + "\n\n*** 子任务（会话规划）\n"
            "- task-1 | 甲 | completed | owner=x\n"
            "- task-2 | 乙|丙 | pending\n",
            encoding="utf-8",
        )
        snap = [{"id": "task-1", "subject": "甲", "status": "completed", "ownerName": "x"}]
        self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                "--from-json", str(self.snap_file(snap)), "--write", "--json")
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("- task-1 | completed | owner=x | 甲", text, "快照里的行迁移成规范格式")
        self.assertIn("- task-2 | 乙|丙 | pending", text, "不在快照里的行保留原样（不瞎猜 subject）")


# ================================================================ 任务 DAG 写入


class DagSetTest(TaskTestCase):
    A = "task-01M4QW92NNGHAWW4ZHBJZ8S1Q0"
    B = "task-01M4QW92NNGHAWW4ZHBJZ8S1Q1"
    C = "task-01M4QW92NNGHAWW4ZHBJZ8S1Q2"
    X = "task-01M4QW92NNGHAWW4ZHBJZ8S1Q9"

    def seed_parent(self, *, children=None, status="TODO"):
        parent = tasks.build_task(
            "DAG 父任务", project_id="demo", status=status, has_criteria=False,
            extra_properties={"PM_TEAM_TASKS": self.A + "," + self.B + "," + self.C
                              if children is None else children},
        )
        tasks.create_task(self.tasks_path, parent)
        return parent

    def dag(self, task_id: str) -> list:
        code, out, _ = self.pm("task", "show", task_id, "--project", "demo", "--json")
        self.assertEqual(code, 0)
        return json.loads(out)["task"]["dagEdges"]

    def test_dag_set_merges_sorts_dedupes_and_audits(self) -> None:
        parent = self.seed_parent()
        code, out, _ = self.pm(
            "task", "dag", "set", parent["id"], "--project", "demo",
            "--expected-revision", "1", "--edge", self.B + " -> " + self.C,
            "--edge", self.A + " -> " + self.B, "--edge", self.A + " -> " + self.B,
            "--reason", "规划顺序", "--json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["changed"])
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["dagEdges"],
                         [[self.A, self.B], [self.B, self.C]], "去重并按 from,to 排序")
        self.assertEqual(self.dag(parent["id"]), [[self.A, self.B], [self.B, self.C]])
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("*** 任务 DAG", text)
        self.assertIn("- " + self.A + " -> " + self.B, text)
        self.assertIn("op=dag-set edges=2", text, "审计要带 op=dag-set edges=n")
        self.assertIn("reason=规划顺序", text)
        self.assertEqual(text.count("audit="), 2, "整个写入只加一条审计")

    def test_dag_set_replace_then_clear(self) -> None:
        parent = self.seed_parent()
        self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                "--expected-revision", "1", "--edge", self.A + " -> " + self.B,
                "--edge", self.B + " -> " + self.C, "--json")
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "2", "--replace",
                               "--edge", self.B + " -> " + self.C, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["dagEdges"], [[self.B, self.C]])
        self.assertEqual(self.dag(parent["id"]), [[self.B, self.C]])
        # 空 --edge + --replace = 清空该节
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "3", "--replace", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["dagEdges"], [])
        self.assertEqual(self.dag(parent["id"]), [])
        self.assertNotIn("*** 任务 DAG", self.tasks_path.read_text(encoding="utf-8"))
        # 无 --edge 且无 --replace → 不动
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "4", "--json")
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["changed"])
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_dag_set_rejects_non_child_endpoint(self) -> None:
        parent = self.seed_parent()
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "1",
                               "--edge", self.A + " -> " + self.X, "--json")
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "EDGE_ENDPOINT_NOT_A_CHILD")
        self.assertEqual(payload["unknownEndpoints"], [self.X])
        self.assertEqual(payload["childIds"], [self.A, self.B, self.C])
        self.assertIn("hint", payload)
        self.assertEqual(self.tasks_path.read_bytes(), before, "拒绝时不得写")
        # --allow-unknown 放行并如实报告
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "1", "--allow-unknown",
                               "--edge", self.A + " -> " + self.X, "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["dagEdges"], [[self.A, self.X]])
        self.assertEqual(payload["unknownEndpoints"], [self.X])
        self.assertTrue(payload["allowUnknown"])

    def test_dag_set_validates_edge_and_endpoint_shape(self) -> None:
        parent = self.seed_parent()
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "1", "--edge", "nonsense", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "INVALID_EDGE")
        # 非 task- 前缀 / 明显畸形 → INVALID_EDGE_ENDPOINT（--allow-unknown 也不放行）
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "1", "--edge", "foo -> bar",
                               "--allow-unknown", "--json")
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "INVALID_EDGE_ENDPOINT")
        self.assertEqual(payload["endpoints"], ["foo", "bar"])
        # 形状合法但不在子任务里 → EDGE_ENDPOINT_NOT_A_CHILD（不是 INVALID_EDGE_ENDPOINT）
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "1", "--edge", "task-1 -> task-2", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "EDGE_ENDPOINT_NOT_A_CHILD")
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_dag_set_accepts_board_id_children_and_id_space_matches_team_tasks(self) -> None:
        parent = self.seed_parent(children="")
        snap = [{"id": "task-48", "subject": "A", "status": "pending", "ownerName": "pm-api"},
                {"id": "task-49", "subject": "B", "status": "completed", "ownerName": "dsh-plugin"},
                {"id": "task-50", "subject": "C", "status": "pending"}]
        code, _, _ = self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                             "--from-json", str(self._snap(snap)), "--write", "--json")
        self.assertEqual(code, 0)
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "2", "--edge", "task-48 -> task-49", "--json")
        self.assertEqual(code, 0, "board id 端点（真实形状 task-48）必须能写")
        self.assertEqual(json.loads(out)["dagEdges"], [["task-48", "task-49"]])
        detail = json.loads(self.pm("task", "show", parent["id"], "--project", "demo", "--json")[1])["task"]
        self.assertEqual(detail["dagEdges"], [["task-48", "task-49"]])
        child_ids = {row["id"] for row in detail["teamTasks"]}
        self.assertEqual(child_ids, {"task-48", "task-49", "task-50"})
        for edge in detail["dagEdges"]:
            for endpoint in edge:
                self.assertIn(endpoint, child_ids, "写后 dagEdges 与 teamTasks 是同一 id 空间")

    def test_dag_set_unknown_board_id_needs_allow_unknown(self) -> None:
        parent = self.seed_parent(children="task-48,task-49")
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "1", "--edge", "task-48 -> task-99", "--json")
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "EDGE_ENDPOINT_NOT_A_CHILD")
        self.assertEqual(payload["unknownEndpoints"], ["task-99"])
        self.assertEqual(payload["childIds"], ["task-48", "task-49"])
        self.assertEqual(self.tasks_path.read_bytes(), before)
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "1", "--edge", "task-48 -> task-99",
                               "--allow-unknown", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["dagEdges"], [["task-48", "task-99"]])
        self.assertEqual(payload["unknownEndpoints"], ["task-99"])

    def test_dag_set_membership_wins_over_shape(self) -> None:
        # 成员资格优先：子任务 id 空间里是什么就接受什么（不强制 task- 前缀 / ULID）
        parent = self.seed_parent(children="board-7,task-48")
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "1", "--edge", "board-7 -> task-48", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["dagEdges"], [["board-7", "task-48"]])

    def test_dag_set_ulid_member_edge_still_accepted(self) -> None:
        parent = self.seed_parent()  # 子任务 A/B/C 是 ULID 形状的 org 任务 id
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "1",
                               "--edge", self.A + " -> " + self.B, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["dagEdges"], [[self.A, self.B]])

    def test_dag_set_idempotent_zero_change(self) -> None:
        parent = self.seed_parent()
        first = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                        "--expected-revision", "1", "--edge", self.A + " -> " + self.B, "--json")
        self.assertEqual(first[0], 0)
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "2", "--edge", self.A + " -> " + self.B, "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertFalse(payload["changed"])
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(self.tasks_path.read_bytes(), before, "同一组边重复提交零变更")

    def test_dag_set_dry_run_writes_nothing(self) -> None:
        parent = self.seed_parent()
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "1", "--edge", self.A + " -> " + self.B,
                               "--dry-run", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["dagEdges"], [[self.A, self.B]])
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_dag_set_terminal_task_rejected(self) -> None:
        parent = self.seed_parent(status="DONE")
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "1", "--edge", self.A + " -> " + self.B, "--json")
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "TASK_TERMINAL")
        self.assertEqual(payload["status"], "DONE")
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_dag_set_cas_conflict_returns_3(self) -> None:
        parent = self.seed_parent()
        text = self.tasks_path.read_text(encoding="utf-8")
        self.tasks_path.write_text(text.replace(":PM_REVISION: 1", ":PM_REVISION: 7"), encoding="utf-8")
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "1", "--edge", self.A + " -> " + self.B, "--json")
        self.assertEqual(code, 3)
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "REVISION_CONFLICT")
        self.assertEqual(payload["currentRevision"], 7)
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_dag_set_unknown_task_not_found(self) -> None:
        self.seed_parent()
        code, out, _ = self.pm("task", "dag", "set", "task-nope", "--project", "demo",
                               "--expected-revision", "1", "--edge", self.A + " -> " + self.B, "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "NOT_FOUND")

    def test_dag_set_keeps_children_section_and_other_tasks(self) -> None:
        parent = self.seed_parent()
        snap = [{"id": self.A, "subject": "甲", "status": "pending", "ownerName": "pm-tasks"},
                {"id": self.B, "subject": "乙", "status": "completed"}]
        self.pm("task", "import-team", "--project", "demo", "--parent", parent["id"],
                "--from-json", str(self._snap(snap)), "--write", "--json")
        other = tasks.build_task("别的任务", project_id="demo", has_criteria=False)
        tasks.create_task(self.tasks_path, other)
        other_before = self.parsed_one(other["id"])
        code, out, _ = self.pm("task", "dag", "set", parent["id"], "--project", "demo",
                               "--expected-revision", "2",
                               "--edge", self.A + " -> " + self.B, "--json")
        self.assertEqual(code, 0)
        detail = json.loads(self.pm("task", "show", parent["id"], "--project", "demo", "--json")[1])["task"]
        self.assertEqual([row["id"] for row in detail["teamTasks"]], [self.A, self.B], "子任务节不受影响")
        self.assertEqual(detail["dagEdges"], [[self.A, self.B]])
        other_after = self.parsed_one(other["id"])
        for key in ("id", "title", "status", "revision", "goal", "criteria"):
            self.assertEqual(other_after[key], other_before[key], "不能碰别的任务")

    def _snap(self, payload):
        path = self.base / "dag-snap.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path


# ================================================================ 变更历史（LOGBOOK 读模型）


class HistoryTest(TaskTestCase):
    def test_history_reads_real_writes_old_to_new(self) -> None:
        task = tasks.build_task("历史任务", project_id="demo", criteria=["a", "b"])
        tasks.create_task(self.tasks_path, task)
        tasks.transition_task(self.tasks_path, task["id"], to_status="NEXT", expected_revision=1,
                              actor="ai", reason="开始处理")
        tasks.set_criterion(self.tasks_path, task["id"], index=0, done=True, expected_revision=2)
        tasks.transition_task(self.tasks_path, task["id"], to_status="DOING", expected_revision=3,
                              actor="human", reason="人工接手（带空格）")
        row = self.parsed_one(task["id"])
        history = row["history"]
        self.assertEqual(len(history), 4)
        self.assertEqual([h["to"] for h in history], ["TODO", "NEXT", "NEXT", "DOING"])
        self.assertEqual([h["from"] for h in history], ["(created)", "TODO", "NEXT", "NEXT"],
                         "from \"(created)\" 如实显示，不伪造成状态")
        self.assertEqual([h["revision"] for h in history], [1, 2, 3, 4])
        self.assertEqual([h["actor"] for h in history], ["human", "ai", "human", "human"])
        self.assertEqual(history[1]["reason"], "开始处理")
        self.assertEqual(history[2]["reason"], "勾选验收标准", "勾选类审计的 reason")
        self.assertEqual(history[3]["reason"], "人工接手（带空格）", "reason 含空格也完整")
        self.assertRegex(history[0]["at"], ISO_RE.pattern)
        self.assertRegex(history[0]["orgAt"], r"^\d{4}-\d{2}-\d{2} \w{3} \d{2}:\d{2}$")
        self.assertRegex(history[0]["auditEventId"], AUDIT_RE.pattern)
        self.assertTrue(history[0]["raw"].startswith("   - State"), "raw 是缩进的原始行")
        self.assertFalse(row["history_truncated"])
        # 出口：show 全量 + list 计数
        code, out, _ = self.pm("task", "show", task["id"], "--project", "demo", "--json")
        self.assertEqual(code, 0)
        detail = json.loads(out)["task"]
        self.assertEqual(detail["history"], history)
        self.assertEqual(detail["historyCount"], 4)
        self.assertEqual(detail["historyShown"], 4, "未截断时 Shown == Count")
        self.assertFalse(detail["historyTruncated"])
        self.assertEqual(set(history[0].keys()),
                         {"at", "orgAt", "actor", "from", "to", "revision", "reason",
                          "auditEventId", "raw"})
        code, out, _ = self.pm("task", "list", "--project", "demo", "--json")
        listed = next(r for g in json.loads(out)["groups"] for r in g["tasks"] if r["id"] == task["id"])
        self.assertEqual(listed["historyCount"], 4)
        self.assertEqual(listed["historyShown"], 4)
        self.assertNotIn("history", listed, "list --json 不塞历史数组")

    def test_history_old_form_missing_fields_are_null(self) -> None:
        text = ("** TODO 老条目\n:PROPERTIES:\n:ID: task-OLD\n:PM_KIND: task\n:END:\n"
                "   :LOGBOOK:\n"
                "   - State \"NEXT\" from \"TODO\" [2026-10-12 Mon 12:16]\n"
                "   :END:\n")
        history = tasks.parse_tasks(text)[0]["history"]
        self.assertEqual(history, [{
            "at": None, "orgAt": "2026-10-12 Mon 12:16", "actor": None, "from": "TODO",
            "to": "NEXT", "revision": None, "reason": None, "auditEventId": None,
            "raw": "   - State \"NEXT\" from \"TODO\" [2026-10-12 Mon 12:16]",
        }], "缺字段一律 null，绝不猜")

    def test_history_without_logbook_or_empty_is_empty_list(self) -> None:
        no_log = "** TODO 没有历史\n:PROPERTIES:\n:ID: task-NONE\n:PM_KIND: task\n:END:\n目标：正文\n"
        row = tasks.parse_tasks(no_log)[0]
        self.assertEqual(row["history"], [], "无 LOGBOOK 是 [] 不是 null")
        self.assertFalse(row["history_truncated"])
        self.assertEqual(tasks.task_summary(row)["historyCount"], 0)
        self.assertEqual(tasks.task_summary(row)["historyShown"], 0)
        empty = ("** TODO 空历史\n:PROPERTIES:\n:ID: task-EMPTY\n:PM_KIND: task\n:END:\n"
                 "   :LOGBOOK:\n   :END:\n")
        empty_row = tasks.parse_tasks(empty)[0]
        self.assertEqual(empty_row["history"], [])
        self.assertEqual(empty_row["history_count"], 0)
        self.assertFalse(empty_row["history_truncated"])

    def test_history_isolated_from_body_and_other_tasks(self) -> None:
        text = (
            "** TODO 甲\n:PROPERTIES:\n:ID: task-AAA\n:PM_KIND: task\n:END:\n"
            "   :LOGBOOK:\n"
            "   - State \"NEXT\" from \"TODO\" [2026-10-12 Mon 12:16] id=task-AAA audit=audit-A "
            "at=2026-10-12T12:16:00+08:00 actor=ai rev=2\n"
            "   :END:\n"
            "目标：正文里写一行 - State \"FAKE\" from \"X\" 不该被当成历史\n\n"
            "** TODO 乙\n:PROPERTIES:\n:ID: task-BBB\n:PM_KIND: task\n:END:\n"
            "   :LOGBOOK:\n"
            "   - State \"DOING\" from \"NEXT\" [2026-10-12 Mon 13:00] id=task-BBB audit=audit-B "
            "at=2026-10-12T13:00:00+08:00 actor=human rev=3\n"
            "   :END:\n"
        )
        rows = tasks.parse_tasks(text)
        self.assertEqual([h["to"] for h in rows[0]["history"]], ["NEXT"], "正文伪造的 - State 行不能混进来")
        self.assertEqual([h["to"] for h in rows[1]["history"]], ["DOING"], "两个任务各自的 LOGBOOK 不串")
        self.assertEqual(rows[0]["history"][0]["auditEventId"], "audit-A")
        self.assertEqual(rows[1]["history"][0]["auditEventId"], "audit-B")

    def test_history_indentation_tolerance(self) -> None:
        for indent in ("   ", "\t", ""):
            line = (indent + "- State \"NEXT\" from \"TODO\" [2026-10-12 Mon 12:16] "
                    "id=task-I audit=audit-I at=2026-10-12T12:16:00+08:00 actor=ai rev=2")
            text = ("** TODO 缩进\n:PROPERTIES:\n:ID: task-I\n:PM_KIND: task\n:END:\n"
                    "   :LOGBOOK:\n" + line + "\n   :END:\n")
            history = tasks.parse_tasks(text)[0]["history"]
            self.assertEqual(len(history), 1, repr(indent))
            self.assertEqual(history[0]["to"], "NEXT")

    def test_history_count_is_total_not_shown(self) -> None:
        lines = ["** TODO 多历史", ":PROPERTIES:", ":ID: task-MANY", ":PM_KIND: task", ":END:",
                 "   :LOGBOOK:"]
        for index in range(1, 131):
            lines.append(
                "   - State \"S%d\" from \"S%d\" [2026-10-12 Mon 12:16] id=task-MANY "
                "audit=audit-%d at=2026-10-12T12:16:00+08:00 actor=ai rev=%d"
                % (index, index - 1, index, index)
            )
        lines.append("   :END:")
        text = "\n".join(lines) + "\n"
        row = tasks.parse_tasks(text)[0]
        self.assertEqual(row["history_count"], 130, "historyCount 是事件总数，不受截断影响")
        self.assertEqual(len(row["history"]), tasks.HISTORY_LIMIT)
        self.assertEqual(row["history"][0]["to"], "S31", "返回最近 100 条：首条=第 31 条")
        self.assertEqual(row["history"][-1]["to"], "S130", "末条=第 130 条")
        self.assertTrue(row["history_truncated"], "截断必须如实标注")
        # show / list 两个计数都要对
        self.tasks_path.parent.mkdir(parents=True, exist_ok=True)
        self.tasks_path.write_text(text, encoding="utf-8")
        code, out, _ = self.pm("task", "show", "task-MANY", "--project", "demo", "--json")
        self.assertEqual(code, 0)
        detail = json.loads(out)["task"]
        self.assertEqual(detail["historyCount"], 130)
        self.assertEqual(detail["historyShown"], 100)
        self.assertEqual(len(detail["history"]), 100)
        self.assertTrue(detail["historyTruncated"])
        code, out, _ = self.pm("task", "list", "--project", "demo", "--json")
        listed = next(r for g in json.loads(out)["groups"] for r in g["tasks"]
                      if r["id"] == "task-MANY")
        self.assertEqual(listed["historyCount"], 130)
        self.assertEqual(listed["historyShown"], 100)
        self.assertNotIn("history", listed, "list --json 不给数组")

    def test_history_keeps_unknown_keys_in_raw(self) -> None:
        line = ("   - State \"TODO\" from \"TODO\" [2026-10-12 Mon 12:16] id=task-U audit=audit-U "
                "at=2026-10-12T12:16:00+08:00 actor=human rev=2 reason=更新任务 DAG op=dag-set edges=2")
        text = ("** TODO 未知键\n:PROPERTIES:\n:ID: task-U\n:PM_KIND: task\n:END:\n"
                "   :LOGBOOK:\n" + line + "\n   :END:\n")
        history = tasks.parse_tasks(text)[0]["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["reason"], "更新任务 DAG", "reason 取到下一个 key= 之前")
        self.assertIn("op=dag-set edges=2", history[0]["raw"], "未知键不报错，原样保留")

    def test_history_follows_own_logbook_even_without_id(self) -> None:
        # 裁定：history 归属只看该任务自己的 LOGBOOK 区间，与有没有 :ID: 无关
        with_log = ("** TODO 没有 ID 但有历史\n:PROPERTIES:\n:PM_KIND: task\n:END:\n"
                    "   :LOGBOOK:\n"
                    "   - State \"NEXT\" from \"TODO\" [2026-10-12 Mon 12:16] id=task-X "
                    "audit=audit-X at=2026-10-12T12:16:00+08:00 actor=ai rev=2\n"
                    "   :END:\n")
        row = tasks.parse_tasks(with_log)[0]
        self.assertIsNone(row["id"])
        self.assertEqual(row["history_count"], 1, "无 :ID: 也照常解析它自己的 LOGBOOK")
        self.assertEqual(len(row["history"]), 1)
        self.assertEqual(row["history"][0]["to"], "NEXT")
        self.assertEqual(row["history"][0]["auditEventId"], "audit-X")
        self.assertFalse(row["history_truncated"])
        without = "** TODO 没有 ID 也没有历史\n:PROPERTIES:\n:PM_KIND: task\n:END:\n"
        self.assertEqual(tasks.parse_tasks(without)[0]["history"], [])
        self.assertEqual(tasks.parse_tasks(without)[0]["history_count"], 0)


# ================================================================ 验收标准项稳定 ID（E1）


def _without_audits(text: str) -> str:
    """去掉所有 LOGBOOK 审计行（用于「除了这次写入的审计，其余逐字节相同」的比较）。"""
    return "\n".join(line for line in text.split("\n")
                      if not line.strip().startswith("- State"))


def _criteria_only(text: str) -> list:
    """只取标准行的列表（去掉插入的 ID），用于跨状态变更比较缩进/文本/勾选态。"""
    out = []
    for line in text.split("\n"):
        if re.match(r"^\s*- \[[ xX]\]", line):
            out.append(re.sub(r"\[c-[0-9a-f]{4}\] ", "", line))
    return out


def _without_migration_noise(text: str) -> str:
    """去掉一次迁移写入必然产生的副作用，用于逐字节比较：

    - 插入的 [c-xxxx]（迁移本身）
    - :PM_REVISION: 的 +1
    - 新写入的那条 op=criteria-ids-init 审计行
    除此之外必须与迁移前逐字节一致（文本、勾选态、缩进、父子关系都不许动）。
    """
    out: list[str] = []
    for line in text.split("\n"):
        if "op=criteria-ids-init" in line:
            continue
        line = re.sub(r"\[c-[0-9a-f]{4}\] ", "", line)
        line = re.sub(r":PM_REVISION: \d+", ":PM_REVISION: X", line)
        out.append(line)
    return "\n".join(out)


class CriteriaIdTest(TaskTestCase):
    def seed_old_style(self, criteria=None):
        """pm 风格任务（抽屉 3 空格缩进），但把标准行里的 ID 去掉 —— 模拟旧数据。"""
        task = tasks.build_task("历史任务", project_id="demo",
                                criteria=criteria if criteria is not None else ["甲标准", "乙标准", "丙标准"])
        tasks.create_task(self.tasks_path, task)
        text = self.tasks_path.read_text(encoding="utf-8")
        stripped = re.sub(r"\[c-[0-9a-f]{4}\] ", "", text)
        self.tasks_path.write_text(stripped, encoding="utf-8")
        return task, stripped

    def test_parse_accepts_old_lines_without_id(self) -> None:
        text = ("** TODO 旧数据\n:PROPERTIES:\n:ID: task-OLD\n:PM_KIND: task\n:END:\n"
                "*** 验收标准\n- [ ] 甲\n- [x] 乙\n")
        row = tasks.parse_tasks(text)[0]
        self.assertEqual([(c["id"], c["text"], c["done"]) for c in row["criteria"]],
                         [(None, "甲", False), (None, "乙", True)], "旧行无 ID → id=null，绝不现编")
        self.assertEqual([c["line"] for c in row["criteria"]], [7, 8], "line 是文件 1-based 行号")

    def test_parse_and_render_keep_id_stable(self) -> None:
        text = ("** TODO 新数据\n:PROPERTIES:\n:ID: task-NEW\n:PM_KIND: task\n:END:\n"
                "*** 验收标准\n- [ ] [c-1a2b] 带 ID 的文本\n- [x] 无 ID 的老行\n")
        row = tasks.parse_tasks(text)[0]
        self.assertEqual(row["criteria"][0]["id"], "c-1a2b")
        self.assertEqual(row["criteria"][0]["text"], "带 ID 的文本")
        self.assertIsNone(row["criteria"][1]["id"])
        rendered = "\n".join(tasks.render_task_body(row))
        self.assertIn("- [ ] [c-1a2b] 带 ID 的文本", rendered)
        self.assertIn("- [x] 无 ID 的老行", rendered, "无 ID 的行不会被硬塞一个 ID")
        again = tasks.parse_tasks("\n".join(tasks.render_task_block(row)) + "\n")[0]
        self.assertEqual([c["id"] for c in again["criteria"]], ["c-1a2b", None])

    def test_new_task_gets_ids_at_creation(self) -> None:
        task = tasks.build_task("新任务", project_id="demo", criteria=["甲", "乙"])
        tasks.create_task(self.tasks_path, task)
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertRegex(text, r"- \[ \] \[c-[0-9a-f]{4}\] 甲")
        ids = [c["id"] for c in self.parsed_one(task["id"])["criteria"]]
        self.assertTrue(all(re.fullmatch(r"c-[0-9a-f]{4}", i) for i in ids))
        self.assertEqual(len(set(ids)), 2)

    def test_init_ids_only_touches_ids_byte_level(self) -> None:
        task, before = self.seed_old_style()
        result = tasks.init_criterion_ids(self.tasks_path, task["id"], expected_revision=1,
                                          actor="ai", reason="迁移")
        self.assertTrue(result.changed)
        self.assertEqual(result.revision, 2)
        after = self.tasks_path.read_text(encoding="utf-8")
        self.assertEqual(_without_migration_noise(after), _without_migration_noise(before),
                         "除插入的 ID / revision+1 / 一条迁移审计外，逐字节不变")
        row = self.parsed_one(task["id"])
        self.assertEqual([(c["text"], c["done"]) for c in row["criteria"]],
                         [("甲标准", False), ("乙标准", False), ("丙标准", False)])
        self.assertTrue(all(c["id"] for c in row["criteria"]))
        self.assertIn("op=criteria-ids-init", after)
        self.assertEqual(after.count("audit="), before.count("audit=") + 1, "一次 CAS 只多一条审计")

    def test_init_ids_is_idempotent(self) -> None:
        task, _ = self.seed_old_style()
        tasks.init_criterion_ids(self.tasks_path, task["id"], expected_revision=1)
        after_first = self.tasks_path.read_bytes()
        again = tasks.init_criterion_ids(self.tasks_path, task["id"], expected_revision=2)
        self.assertFalse(again.changed)
        self.assertEqual(again.revision, 2)
        self.assertEqual(self.tasks_path.read_bytes(), after_first, "再跑零变更")

    def test_check_backfills_ids_in_same_cas(self) -> None:
        task, _ = self.seed_old_style()
        result = tasks.set_criterion(self.tasks_path, task["id"], index=0, done=True,
                                     expected_revision=1, actor="ai")
        self.assertTrue(result.changed)
        self.assertEqual(result.revision, 2, "迁移与勾选是同一次 CAS")
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("op=criteria-ids-init", text)
        self.assertIn("with=check", text)
        self.assertIn("ids=3", text)
        row = self.parsed_one(task["id"])
        self.assertTrue(all(c["id"] for c in row["criteria"]))
        self.assertEqual([c["done"] for c in row["criteria"]], [True, False, False])
        self.assertEqual([c["text"] for c in row["criteria"]], ["甲标准", "乙标准", "丙标准"])

    def test_transition_backfills_ids_in_same_cas(self) -> None:
        task, _ = self.seed_old_style()
        result = tasks.transition_task(self.tasks_path, task["id"], to_status="NEXT",
                                       expected_revision=1, actor="ai")
        self.assertEqual(result.status, "NEXT")
        self.assertEqual(result.revision, 2)
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("op=criteria-ids-init", text)
        self.assertIn("with=transition", text)
        row = self.parsed_one(task["id"])
        self.assertEqual(row["status"], "NEXT")
        self.assertTrue(all(c["id"] for c in row["criteria"]), "转移时顺带补齐 ID")
        self.assertEqual([c["text"] for c in row["criteria"]], ["甲标准", "乙标准", "丙标准"])

    def test_check_by_criterion_id_hit_and_miss(self) -> None:
        task = tasks.build_task("按 ID 勾选", project_id="demo", criteria=["甲", "乙"])
        tasks.create_task(self.tasks_path, task)
        cid = self.parsed_one(task["id"])["criteria"][1]["id"]
        code, out, _ = self.pm("task", "check", task["id"], "--project", "demo",
                               "--criterion-id", cid, "--expected-revision", "1", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["criterionId"], cid)
        self.assertEqual(self.parsed_one(task["id"])["criteria"][1]["done"], True)
        # 不存在的 id → CRITERION_NOT_FOUND，extra 带现有 ids
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "check", task["id"], "--project", "demo",
                               "--criterion-id", "c-0000", "--expected-revision", "2", "--json")
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "CRITERION_NOT_FOUND")
        self.assertEqual(payload["criterionId"], "c-0000")
        self.assertIn(cid, payload["ids"])
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_check_deprecated_selectors_and_conflicts(self) -> None:
        task = tasks.build_task("选择器", project_id="demo", criteria=["甲", "同名", "同名"])
        tasks.create_task(self.tasks_path, task)
        # --index（deprecated）→ rev2
        code, out, _ = self.pm("task", "check", task["id"], "--project", "demo",
                               "--index", "0", "--expected-revision", "1", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["criteriaIndex"], 0)
        # --criterion 数字（序号）→ rev3
        code, _, _ = self.pm("task", "check", task["id"], "--project", "demo",
                             "--criterion", "1", "--expected-revision", "2", "--json")
        self.assertEqual(code, 0)
        # --criterion 文本（唯一的「甲」，已勾选 → 合法的 no-op，但选择器路径仍要能解析）
        code, out, _ = self.pm("task", "check", task["id"], "--project", "demo",
                               "--criterion", "甲", "--expected-revision", "3", "--json")
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["changed"])
        # 文本重复 → AMBIGUOUS_CRITERION（不改文件）
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "check", task["id"], "--project", "demo",
                               "--criterion", "同名", "--expected-revision", "3", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "AMBIGUOUS_CRITERION")
        self.assertEqual(self.tasks_path.read_bytes(), before)
        # 没给 / 给了两个选择器
        code, out, _ = self.pm("task", "check", task["id"], "--project", "demo",
                               "--expected-revision", "3", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "CRITERION_SELECTOR_REQUIRED")
        code, out, _ = self.pm("task", "check", task["id"], "--project", "demo",
                               "--index", "0", "--criterion", "甲",
                               "--expected-revision", "3", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "CRITERION_SELECTOR_CONFLICT")

    def test_criteria_selector_by_id_keeps_same_id_after_check(self) -> None:
        task = tasks.build_task("稳定", project_id="demo", criteria=["甲", "乙"])
        tasks.create_task(self.tasks_path, task)
        ids_before = [c["id"] for c in self.parsed_one(task["id"])["criteria"]]
        self.pm("task", "check", task["id"], "--project", "demo",
                "--criterion-id", ids_before[0], "--expected-revision", "1", "--json")
        ids_after = [c["id"] for c in self.parsed_one(task["id"])["criteria"]]
        self.assertEqual(ids_after, ids_before, "一经写入 ID 不变")

    def test_ids_stable_when_lines_added_or_removed(self) -> None:
        task = tasks.build_task("增删", project_id="demo", criteria=["甲", "乙"])
        tasks.create_task(self.tasks_path, task)
        before = self.parsed_one(task["id"])
        first_id = before["criteria"][0]["id"]
        # 人工在验收标准节末尾加一行（不带 ID）
        text = self.tasks_path.read_text(encoding="utf-8")
        text = text.replace("- [ ] [" + before["criteria"][1]["id"] + "] 乙\n",
                            "- [ ] [" + before["criteria"][1]["id"] + "] 乙\n- [ ] 丙（人工新增）\n")
        self.tasks_path.write_text(text, encoding="utf-8")
        row = self.parsed_one(task["id"])
        self.assertEqual([c["id"] for c in row["criteria"]], [first_id, before["criteria"][1]["id"], None])
        # 下一次写（check 第一条）补齐新行的 ID，且老 ID 不变
        tasks.set_criterion(self.tasks_path, task["id"], criterion_id=first_id, done=True,
                            expected_revision=1)
        after = self.parsed_one(task["id"])
        self.assertEqual(after["criteria"][0]["id"], first_id, "老 ID 不动")
        self.assertTrue(all(c["id"] for c in after["criteria"]), "新行补 ID")
        self.assertEqual([c["text"] for c in after["criteria"]], ["甲", "乙", "丙（人工新增）"])
        # 删掉最后一条后：其余 ID 不变，按 ID 仍能勾选
        text = self.tasks_path.read_text(encoding="utf-8")
        self.tasks_path.write_text(
            "\n".join(line for line in text.split("\n") if "丙（人工新增）" not in line),
            encoding="utf-8",
        )
        tasks.set_criterion(self.tasks_path, task["id"], criterion_id=first_id, done=False,
                            expected_revision=2)
        after_delete = self.parsed_one(task["id"])
        self.assertEqual([c["id"] for c in after_delete["criteria"]],
                         [first_id, before["criteria"][1]["id"]], "删除一条不影响其它 ID")
        self.assertEqual(after_delete["criteria"][0]["done"], False)

    def test_init_ids_terminal_and_conflict_and_dry_run(self) -> None:
        task, _ = self.seed_old_style()
        # dry-run 零写入
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "criteria", "init-ids", task["id"], "--project", "demo",
                               "--expected-revision", "1", "--dry-run", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(len(payload["criteriaIdsAdded"]), 3)
        self.assertEqual(self.tasks_path.read_bytes(), before)
        # CAS 冲突
        code, out, _ = self.pm("task", "criteria", "init-ids", task["id"], "--project", "demo",
                               "--expected-revision", "9", "--json")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["error"]["code"], "REVISION_CONFLICT")
        # 终态拒绝
        terminal = tasks.build_task("终态任务", project_id="demo", status="DONE", criteria=["甲"])
        tasks.create_task(self.tasks_path, terminal)
        text = self.tasks_path.read_text(encoding="utf-8")
        self.tasks_path.write_text(re.sub(r"\[c-[0-9a-f]{4}\] ", "", text), encoding="utf-8")
        code, out, _ = self.pm("task", "criteria", "init-ids", terminal["id"], "--project", "demo",
                               "--expected-revision", "1", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "TASK_TERMINAL")

    # ---- 行首缩进：迁移/勾选都只动该动的字节 ----

    def seed_indented(self, indent: str):
        """pm 风格任务，但把标准行改成指定行首缩进并去掉 ID（模拟旧数据）。"""
        task = tasks.build_task("缩进任务", project_id="demo", criteria=["甲标准", "乙标准"])
        tasks.create_task(self.tasks_path, task)
        text = self.tasks_path.read_text(encoding="utf-8")
        out = []
        for line in text.split("\n"):
            match = re.match(r"^\s*- \[([ xX])\] (?:\[c-[0-9a-f]{4}\] )?(.*)$", line)
            out.append(indent + "- [" + match.group(1) + "] " + match.group(2) if match else line)
        stripped = "\n".join(out)
        self.tasks_path.write_text(stripped, encoding="utf-8")
        return task, stripped

    def test_migration_preserves_leading_indent(self) -> None:
        for indent in ("   ", "\t", ""):
            with self.subTest(indent=repr(indent)):
                self.setUp() if False else None
                task, before = self.seed_indented(indent)
                tasks.init_criterion_ids(self.tasks_path, task["id"], expected_revision=1)
                after = self.tasks_path.read_text(encoding="utf-8")
                self.assertEqual(_without_migration_noise(after), _without_migration_noise(before),
                                 "除插入的 ID / revision+1 / 审计行外，逐字节相同（含行首缩进）")
                self.assertIn(indent + "- [ ] [c-", after, "缩进必须保留")
                row = self.parsed_one(task["id"])
                self.assertEqual([c["indent"] for c in row["criteria"]],
                                 [len(indent.expandtabs(4))] * 2, "读模型里的 indent 也要对")
                self.assertTrue(all(c["id"] for c in row["criteria"]))
                self.tasks_path.unlink()

    def test_check_preserves_leading_indent(self) -> None:
        task, _ = self.seed_indented("\t")
        # 迁移先补 ID（不动缩进），再按 ID 勾选
        tasks.init_criterion_ids(self.tasks_path, task["id"], expected_revision=1)
        cid = self.parsed_one(task["id"])["criteria"][0]["id"]
        after_migration = self.tasks_path.read_text(encoding="utf-8")
        result = tasks.set_criterion(self.tasks_path, task["id"], criterion_id=cid, done=True,
                                     expected_revision=2)
        self.assertTrue(result.changed)
        after = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("\t- [x] [" + cid + "] 甲标准", after, "勾选保留 tab 缩进，只改复选框")
        self.assertEqual(_without_audits(_without_migration_noise(after)).replace("- [x] ", "- [ ] ", 1),
                         _without_audits(_without_migration_noise(after_migration)),
                         "勾选只改复选框字符（revision/ID/审计之外逐字节相同）")
        # 取消勾选同样保留缩进
        tasks.set_criterion(self.tasks_path, task["id"], criterion_id=cid, done=False,
                            expected_revision=3)
        self.assertIn("\t- [ ] [" + cid + "] 甲标准",
                      self.tasks_path.read_text(encoding="utf-8"))

    def test_transition_backfill_preserves_leading_indent(self) -> None:
        task, before = self.seed_indented("   ")
        result = tasks.transition_task(self.tasks_path, task["id"], to_status="NEXT",
                                       expected_revision=1, actor="ai")
        self.assertEqual(result.status, "NEXT")
        after = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("   - [ ] [c-", after, "转移顺带补 ID 时也保留缩进")
        self.assertEqual(_criteria_only(after), _criteria_only(before),
                         "转移顺带补 ID 时标准行除 ID 外逐字节相同（含缩进）")


    def test_init_ids_on_indented_criteria_headline_is_not_silent(self) -> None:
        task, _ = self.seed_indented("   ")
        # 再把 *** 验收标准 标题本身缩进 3 空格 —— Org 里它就不再是标题
        text = self.tasks_path.read_text(encoding="utf-8")
        self.tasks_path.write_text(re.sub(r"(?m)^\*\*\* 验收标准$", "   *** 验收标准", text),
                                   encoding="utf-8")
        before = self.tasks_path.read_bytes()
        code, out, _ = self.pm("task", "criteria", "init-ids", task["id"], "--project", "demo",
                               "--expected-revision", "1", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertFalse(payload["changed"], "认不到节 → 不许写入")
        self.assertEqual(payload["criteriaIdsAdded"], [])
        self.assertEqual(payload["criteria"], [])
        self.assertIn("顶格", payload["note"], "必须给可操作原因，不许静默")
        self.assertEqual(self.tasks_path.read_bytes(), before, "一个字节都不许改（缩进也不许动）")
        self.assertIn("   *** 验收标准", self.tasks_path.read_text(encoding="utf-8"))
        # 人类可读输出也要带原因
        code2, out2, _ = self.pm("task", "criteria", "init-ids", task["id"], "--project", "demo",
                                 "--expected-revision", "1")
        self.assertEqual(code2, 0)
        self.assertIn("顶格", out2)

    def test_init_ids_without_criteria_section_reports_reason(self) -> None:
        task = tasks.build_task("没有标准", project_id="demo", has_criteria=False)
        tasks.create_task(self.tasks_path, task)
        code, out, _ = self.pm("task", "criteria", "init-ids", task["id"], "--project", "demo",
                               "--expected-revision", "1", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertFalse(payload["changed"])
        self.assertIn("没有 *** 验收标准 节", payload["note"], "没有可迁移的节也要说明")


    def test_show_json_criteria_exposes_id_and_line(self) -> None:
        task = tasks.build_task("读模型", project_id="demo", criteria=["甲", "乙"])
        tasks.create_task(self.tasks_path, task)
        code, out, _ = self.pm("task", "show", task["id"], "--project", "demo", "--json")
        self.assertEqual(code, 0)
        criteria = json.loads(out)["task"]["criteria"]
        self.assertEqual(len(criteria), 2)
        for item in criteria:
            self.assertRegex(item["id"], r"^c-[0-9a-f]{4}$")
            self.assertIsInstance(item["line"], int)
        lines = self.tasks_path.read_text(encoding="utf-8").split("\n")
        for item in criteria:
            self.assertIn("[" + item["id"] + "] " + item["text"], lines[item["line"] - 1])


# ================================================================ 验收证据（E2）


class EvidenceTest(TaskTestCase):
    def seed(self, criteria=None, **kwargs):
        task = tasks.build_task("证据任务", project_id="demo",
                                criteria=list(criteria if criteria is not None else ["甲标准", "乙标准"]),
                                **kwargs)
        tasks.create_task(self.tasks_path, task)
        return task, self.parsed_one(task["id"])["criteria"][0]["id"]

    def add(self, task_id, cid, *, kind="test", result="pass", ref="commit abc123",
            note="", actor="ai", revision=1, extra=()):
        return self.pm("task", "evidence", "add", task_id, "--project", "demo",
                       "--criterion-id", cid, "--kind", kind, "--result", result,
                       "--ref", ref, "--note", note, "--actor", actor,
                       "--expected-revision", str(revision), *extra, "--json")

    def test_add_and_list_roundtrip(self) -> None:
        task, cid = self.seed()
        code, out, _ = self.add(task["id"], cid, note="跑了 pytest | 含竖线 | 与空格")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["changed"])
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["evidenceCount"], 1)
        entry = payload["evidence"]
        self.assertEqual((entry["criterionId"], entry["kind"], entry["result"], entry["ref"],
                          entry["actor"], entry["note"]),
                         (cid, "test", "pass", "commit abc123", "ai", "跑了 pytest | 含竖线 | 与空格"))
        self.assertRegex(entry["at"], ISO_RE.pattern)
        # task-01M4ZPRF…：证据多了一个**内容寻址的可核对 id**（rm 按它删、list 按它对账）
        self.assertEqual(set(entry.keys()),
                         {"id", "criterionId", "kind", "result", "ref", "at", "actor", "note", "raw", "line"})
        self.assertRegex(entry["id"], r"^e-[0-9a-f]{4}(-[0-9]+)?$", "id 形如 e-1a2b（重复行带出现序号）")
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("*** 证据（验收）", text)
        self.assertGreater(text.index("*** 证据（验收）"), text.index("*** 验收标准"),
                           "证据节固定在验收标准之后")
        self.assertIn("- " + cid + " | test | pass | commit abc123 | " + entry["at"]
                      + " | ai | 跑了 pytest | 含竖线 | 与空格", text)
        self.assertIn("op=evidence-add", text)
        self.assertIn("ref=commit abc12", text, "审计 reason 带 ref 前 12 字符，便于在 Org 里人眼扫")
        self.assertNotIn("跑了 pytest", text.split("op=evidence-add")[1].split("\n")[0],
                         "长 note 不许塞进审计行")
        self.assertIn("criterion=" + cid, text)
        self.assertIn("kind=test", text)
        self.assertIn("result=pass", text)
        self.assertEqual(text.count("audit="), 2, "一次 CAS 只多一条审计")
        # list 出口
        code, out, _ = self.pm("task", "evidence", "list", task["id"], "--project", "demo", "--json")
        self.assertEqual(code, 0)
        listed = json.loads(out)
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["evidence"][0]["criterionId"], cid)
        # show / task list
        detail = json.loads(self.pm("task", "show", task["id"], "--project", "demo", "--json")[1])["task"]
        self.assertEqual(detail["evidenceCount"], 1)
        self.assertEqual(detail["evidence"][0]["raw"], listed["evidence"][0]["raw"])
        row = next(r for g in json.loads(self.pm("task", "list", "--project", "demo", "--json")[1])["groups"]
                   for r in g["tasks"] if r["id"] == task["id"])
        self.assertEqual(row["evidenceCount"], 1)
        self.assertNotIn("evidence", row, "list 只给计数，不塞数组")

    def test_evidence_missing_fields_are_null(self) -> None:
        task, cid = self.seed()
        text = self.tasks_path.read_text(encoding="utf-8")
        self.tasks_path.write_text(text.rstrip("\n") + "\n\n*** 证据（验收）\n- " + cid + " | test\n",
                                   encoding="utf-8")
        evidence = self.parsed_one(task["id"])["evidence"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["criterionId"], cid)
        self.assertEqual(evidence[0]["kind"], "test")
        for field in ("result", "ref", "at", "actor", "note"):
            self.assertIsNone(evidence[0][field], field + " 缺失必须 null")

    def test_evidence_only_from_own_section(self) -> None:
        task, cid = self.seed()
        self.add(task["id"], cid)
        text = self.tasks_path.read_text(encoding="utf-8")
        other = ("\n\n** TODO 别的任务\n:PROPERTIES:\n:ID: task-OTHER\n:PM_KIND: task\n:END:\n"
                 "*** 证据（验收）\n- " + cid + " | build | info | other | 2026-01-01T00:00:00+08:00 | human\n")
        body_line = "\n正文里长得像证据: - " + cid + " | review | pass | fake\n"
        self.tasks_path.write_text(text.rstrip("\n") + body_line + other, encoding="utf-8")
        rows = tasks.parse_tasks(self.tasks_path.read_text(encoding="utf-8"))
        first = next(r for r in rows if r["id"] == task["id"])
        second = next(r for r in rows if r["id"] == "task-OTHER")
        self.assertEqual(len(first["evidence"]), 1, "节外/正文里的伪证据不得被收")
        self.assertEqual(first["evidence"][0]["kind"], "test")
        self.assertEqual([e["kind"] for e in second["evidence"]], ["build"], "两任务证据不串")

    def test_ref_with_pipe_rejected(self) -> None:
        task, cid = self.seed()
        before = self.tasks_path.read_bytes()
        code, out, _ = self.add(task["id"], cid, ref="commit a|b")
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "INVALID_EVIDENCE_REF")
        self.assertIn("--note", payload["hint"])
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_unknown_criterion_id_rejected(self) -> None:
        task, cid = self.seed()
        before = self.tasks_path.read_bytes()
        code, out, _ = self.add(task["id"], "c-0000")
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "CRITERION_NOT_FOUND")
        self.assertEqual(payload["criterionId"], "c-0000")
        self.assertIn(cid, payload["ids"])
        self.assertIn("hint", payload)
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_enum_validation(self) -> None:
        task, cid = self.seed()
        for overrides, field in (({"kind": "bogus"}, "kind"), ({"result": "maybe"}, "result"),
                                 ({"actor": "robot"}, "actor")):
            kwargs = {"criterion_id": cid, "kind": "test", "result": "info", "ref": "r", "actor": "human"}
            kwargs.update(overrides)
            with self.assertRaises(tasks.TaskOpError) as ctx:
                tasks.add_evidence(self.tasks_path, task["id"], expected_revision=1, **kwargs)
            self.assertEqual(ctx.exception.code, "INVALID_EVIDENCE_FIELD")
            self.assertEqual(ctx.exception.extra["field"], field)
        # result=info 是合法兜底（不知道就 info，绝不猜 pass）
        result = tasks.add_evidence(self.tasks_path, task["id"], criterion_id=cid, kind="other",
                                    result="info", ref="unknown", expected_revision=1)
        self.assertTrue(result.changed)

    def test_duplicate_submission_is_noop(self) -> None:
        task, cid = self.seed()
        self.add(task["id"], cid, note="同一条")
        after_first = self.tasks_path.read_bytes()
        code, out, _ = self.add(task["id"], cid, note="同一条", revision=2)
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertFalse(payload["changed"], "六字段（不含自动的 at）全同 → changed:false")
        self.assertEqual(payload["evidenceCount"], 1)
        self.assertEqual(self.tasks_path.read_bytes(), after_first)

    def test_terminal_task_rejected(self) -> None:
        task, cid = self.seed()
        tasks.transition_task(self.tasks_path, task["id"], to_status="CANCELLED",
                              expected_revision=1, actor="human")
        before = self.tasks_path.read_bytes()
        code, out, _ = self.add(task["id"], cid, revision=2)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "TASK_TERMINAL")
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_dry_run_writes_nothing(self) -> None:
        task, cid = self.seed()
        before = self.tasks_path.read_bytes()
        code, out, _ = self.add(task["id"], cid, extra=("--dry-run",))
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["evidence"]["criterionId"], cid)
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_cas_conflict(self) -> None:
        task, cid = self.seed()
        before = self.tasks_path.read_bytes()
        code, out, _ = self.add(task["id"], cid, revision=9)
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["error"]["code"], "REVISION_CONFLICT")
        self.assertEqual(self.tasks_path.read_bytes(), before)

    def test_empty_evidence_is_empty_list(self) -> None:
        task, cid = self.seed()
        code, out, _ = self.pm("task", "evidence", "list", task["id"], "--project", "demo", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["evidence"], [])
        detail = json.loads(self.pm("task", "show", task["id"], "--project", "demo", "--json")[1])["task"]
        self.assertEqual(detail["evidence"], [])
        self.assertEqual(detail["evidenceCount"], 0)

    def test_evidence_appended_to_existing_section(self) -> None:
        task, cid = self.seed(criteria=["甲", "乙"])
        cid2 = self.parsed_one(task["id"])["criteria"][1]["id"]
        self.add(task["id"], cid)
        self.add(task["id"], cid2, kind="manual", result="fail", ref="人工复核", note="不通过", revision=2)
        evidence = self.parsed_one(task["id"])["evidence"]
        self.assertEqual([e["criterionId"] for e in evidence], [cid, cid2])
        self.assertEqual([e["kind"] for e in evidence], ["test", "manual"])
        text = self.tasks_path.read_text(encoding="utf-8")
        self.assertEqual(text.count("*** 证据（验收）"), 1, "不会重复建节")


if __name__ == "__main__":
    unittest.main()

