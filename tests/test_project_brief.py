"""pm project brief get：project.org 六段的只读投影（task-51）。

只读：跑前后库 sha 不变；不给任何写路径。
没有 project.org → brief=null + reason（不假造空对象）；未知 key → NOT_FOUND + hint。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from pm import cli
from pm import projects as projects_module
from pm import scaffold

FULL_PROJECT_ORG = """#+TITLE: 手写项目
#+CATEGORY: hand

* 手写项目                                                             :project:
:PROPERTIES:
:ID: proj-hand
:PM_KIND: project
:PM_KEY: hand
:PM_RUNTIME_STATUS: unknown
:END:

  这是**人工管理区**。pm 工具只在文件缺失时创建它，此后永不写入。

** 目标
   把随手记变成可执行的任务。

** 范围（做什么）
   - 记录
   - 分流

** 非目标（明确不做什么）
   不做派发、不碰别人的项目。

** 验收标准
   - [x] 能列出项目
   - [ ] 能读出简报
   附注：这条不是复选框，单独收集。

** 里程碑
   M1 只读投影

** 风险与依赖
   依赖同事的 proposals.py 改完。
"""


class ProjectBriefBaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.library = self.base / "wm"
        self.library.mkdir()
        self.config = self.base / "pm.toml"
        self.config.write_text('library = "' + str(self.library) + '"\n', encoding="utf-8")

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

    def write_project(self, dir_name: str, content: str) -> Path:
        directory = self.library / "projects" / dir_name
        directory.mkdir(parents=True)
        (directory / "project.org").write_text(content, encoding="utf-8")
        return directory

    def library_sha(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(p for p in self.library.rglob("*") if p.is_file()):
            digest.update(str(path.relative_to(self.library)).encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()


class ParseBriefUnitTest(unittest.TestCase):
    def test_parse_six_sections_and_checkboxes(self) -> None:
        brief = projects_module.parse_brief(FULL_PROJECT_ORG)
        self.assertEqual(brief["goal"], "把随手记变成可执行的任务。")
        self.assertEqual(brief["scope"], "- 记录\n- 分流")
        self.assertEqual(brief["nonGoal"], "不做派发、不碰别人的项目。")
        self.assertEqual(
            brief["acceptance"],
            [
                {"text": "能列出项目", "done": True},
                {"text": "能读出简报", "done": False},
            ],
        )
        self.assertEqual(brief["acceptanceNotes"], ["附注：这条不是复选框，单独收集。"])
        self.assertEqual(brief["milestones"], "M1 只读投影")
        self.assertEqual(brief["risks"], "依赖同事的 proposals.py 改完。")
        self.assertEqual(brief["missingSections"], [])

    def test_parse_missing_sections_are_listed(self) -> None:
        brief = projects_module.parse_brief("* Inbox\n** 目标\n   只有目标\n")
        self.assertEqual(brief["goal"], "只有目标")
        self.assertEqual(brief["missingSections"], ["scope", "nonGoal", "acceptance", "milestones", "risks"])

    def test_checkbox_mark_variants(self) -> None:
        text = "* 项目\n** 验收标准\n   - [x] 大写 X 也算完成\n   - [X] 这个也是\n   - [ ] 未完成\n"
        brief = projects_module.parse_brief(text)
        self.assertEqual(
            [(item["text"], item["done"]) for item in brief["acceptance"]],
            [("大写 X 也算完成", True), ("这个也是", True), ("未完成", False)],
        )


class BriefCliTest(ProjectBriefBaseTest):
    def test_scaffold_project_brief(self) -> None:
        self.ok("project", "create", "demo01", "--json")
        payload = self.ok("project", "brief", "get", "demo01", "--json")
        self.assertEqual(payload["project"], "demo01")
        self.assertEqual(payload["id"], "proj-demo01")
        self.assertEqual(payload["path"], "projects/proj-demo01")
        self.assertEqual(payload["title"], "demo01")
        self.assertIs(payload["readOnly"], True)
        self.assertIsNone(payload["reason"])
        brief = payload["brief"]
        self.assertIsNotNone(brief)
        self.assertIn("这个项目要达成什么", brief["goal"])
        self.assertEqual(brief["missingSections"], [])
        self.assertEqual(set(brief["sectionTitles"]), {"goal", "scope", "nonGoal", "acceptance", "milestones", "risks"})
        # 骨架里的验收标准就是一个空的未勾选复选框 —— 如实投影，不假造内容
        self.assertEqual(brief["acceptance"], [{"text": "", "done": False}])

    def test_handwritten_brief_all_six_sections(self) -> None:
        self.write_project("proj-hand", FULL_PROJECT_ORG)
        payload = self.ok("project", "brief", "get", "hand", "--json")
        brief = payload["brief"]
        self.assertEqual(payload["title"], "手写项目")
        self.assertEqual(brief["goal"], "把随手记变成可执行的任务。")
        self.assertEqual(brief["nonGoal"], "不做派发、不碰别人的项目。")
        self.assertEqual([item["done"] for item in brief["acceptance"]], [True, False])
        self.assertEqual(brief["acceptanceNotes"], ["附注：这条不是复选框，单独收集。"])
        self.assertEqual(brief["risks"], "依赖同事的 proposals.py 改完。")

    def test_proj_prefixed_key_accepted(self) -> None:
        self.write_project("proj-hand", FULL_PROJECT_ORG)
        by_key = self.ok("project", "brief", "get", "hand", "--json")
        by_dir = self.ok("project", "brief", "get", "proj-hand", "--json")
        self.assertEqual(by_key, by_dir)

    def test_missing_project_org_is_null_with_reason(self) -> None:
        (self.library / "projects" / "proj-nofile").mkdir(parents=True)
        payload = self.ok("project", "brief", "get", "nofile", "--json")
        self.assertIsNone(payload["brief"], "不假造空对象")
        self.assertEqual(payload["reason"], "NO_PROJECT_ORG")
        self.assertEqual(payload["project"], "nofile")
        self.assertIn("人工管理区", payload["message"])
        self.assertIn("显式提交编辑", payload["message"], "文案要用 2026-10-12 批准的新契约")
        self.assertNotIn("永不写入", payload["message"])

    def test_unknown_key_is_not_found_with_hint(self) -> None:
        self.write_project("proj-hand", FULL_PROJECT_ORG)
        code, stdout, _ = self.pm("project", "brief", "get", "nope", "--json")
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")
        self.assertIn("pm project create nope", payload["hint"])
        self.assertTrue(payload["canCreate"])
        self.assertEqual(payload["knownProjects"], ["hand"])

    def test_brief_is_read_only(self) -> None:
        self.write_project("proj-hand", FULL_PROJECT_ORG)
        before = self.library_sha()
        self.ok("project", "brief", "get", "hand", "--json")
        code, _stdout, _stderr = self.pm("project", "brief", "get", "hand")
        self.assertEqual(code, 0)
        self.assertEqual(self.library_sha(), before, "只读命令不能改任何字节")

    def test_brief_get_has_no_write_flags(self) -> None:
        import argparse

        parser = cli.build_parser()
        root = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)][0]
        project_parser = root.choices["project"]
        project_sub = [
            action for action in project_parser._actions if isinstance(action, argparse._SubParsersAction)
        ][0]
        brief_parser = project_sub.choices["brief"]
        brief_sub = [
            action for action in brief_parser._actions if isinstance(action, argparse._SubParsersAction)
        ][0]
        flags = {
            option for action in brief_sub.choices["get"]._actions for option in action.option_strings
        }
        for forbidden in ("--yes", "--expected-revision", "--dry-run", "--idempotency-key"):
            self.assertNotIn(forbidden, flags, "只读命令不给写路径")

    def test_human_output_is_readable(self) -> None:
        self.write_project("proj-hand", FULL_PROJECT_ORG)
        code, stdout, _ = self.pm("project", "brief", "get", "hand")
        self.assertEqual(code, 0)
        self.assertIn("目标", stdout)
        self.assertIn("[x] 能列出项目", stdout)
        self.assertIn("[ ] 能读出简报", stdout)

    def test_old_project_org_without_sections(self) -> None:
        self.write_project(
            "proj-old",
            "#+TITLE: 老项目\n\n* 老项目 :project:\n:PROPERTIES:\n:ID: proj-old\n:PM_KIND: project\n"
            ":PM_KEY: old\n:END:\n\n** 目标\n   只剩目标。\n",
        )
        payload = self.ok("project", "brief", "get", "old", "--json")
        self.assertIsNotNone(payload["brief"])
        self.assertEqual(payload["brief"]["goal"], "只剩目标。")
        self.assertEqual(
            payload["brief"]["missingSections"],
            ["scope", "nonGoal", "acceptance", "milestones", "risks"],
        )


GOLDEN_ORG = """#+TITLE: 小项目
#+CATEGORY: small

* 小项目 :project:
:PROPERTIES:
:ID: proj-small
:PM_KIND: project
:PM_KEY: small
:END:

  这是**人工管理区**。pm 工具只在文件缺失时创建它，此后永不写入。

** 目标
   老目标。

** 范围（做什么）
   老范围。
"""


class BriefSetTest(ProjectBriefBaseTest):
    """pm project brief set：整文件 sha256 CAS + 只改一段 + 审计（task-54）。"""

    def digest(self, key: str = "hand") -> str:
        return self.ok("project", "brief", "get", key, "--json")["digest"]

    def set_section(self, key: str, section: str, text: str, *, digest: str | None = None,
                    actor: str = "human", extra=()) -> dict:
        argv = [
            "project", "brief", "set", key, "--section", section, "--text", text,
            "--actor", actor, "--expect-digest", digest if digest is not None else self.digest(key),
            "--json", *extra,
        ]
        code, stdout, stderr = self.pm(*argv)
        self.assertEqual(code, 0, "命令失败 %r: %s" % (argv, stderr))
        return json.loads(stdout)

    def sections(self, key: str = "hand") -> dict:
        return self.ok("project", "brief", "get", key, "--json")["brief"]

    def test_only_target_section_bytes_change(self) -> None:
        self.write_project("proj-hand", FULL_PROJECT_ORG)
        before = self.sections()
        self.set_section("hand", "goal", "把随手记变成可验收的任务。")
        after = self.sections()
        self.assertEqual(after["goal"], "把随手记变成可验收的任务。")
        for name in ("scope", "nonGoal", "acceptance", "milestones", "risks"):
            self.assertEqual(after[name], before[name], "其它段必须逐字不动: " + name)
        self.assertEqual(after["acceptanceNotes"], before["acceptanceNotes"])
        text = (self.library / "projects" / "proj-hand" / "project.org").read_text(encoding="utf-8")
        self.assertIn("把随手记变成可验收的任务。", text)
        self.assertNotIn("把随手记变成可执行的任务。", text, "目标段被替换，旧值不该残留")
        # 其余五段逐字留在文件里
        for kept in ("- 记录", "不做派发、不碰别人的项目。", "[x] 能列出项目", "M1 只读投影", "依赖同事的 proposals.py 改完。"):
            self.assertIn(kept, text, kept)

    def test_bytes_exact_golden(self) -> None:
        """逐字节证明：只有正文行、抽屉属性、LOGBOOK、旧措辞四处变了。"""
        directory = self.write_project("proj-small", GOLDEN_ORG)
        payload = self.set_section("small", "goal", "新目标")
        actual = (directory / "project.org").read_text(encoding="utf-8")
        stamp = payload["observedAt"]
        at_org = datetime.fromisoformat(stamp).strftime("%Y-%m-%d %a %H:%M")
        expected = "\n".join(
            [
                "#+TITLE: 小项目",
                "#+CATEGORY: small",
                "",
                "* 小项目 :project:",
                ":PROPERTIES:",
                ":ID: proj-small",
                ":PM_KIND: project",
                ":PM_KEY: small",
                f":PM_BRIEF_UPDATED: {stamp}",
                ":END:",
                ":LOGBOOK:",
                f'- brief-set "goal" [{at_org}] id=proj-small audit={payload["auditEventId"]} '
                f"at={stamp} actor=human rev=1 op=brief-set section=goal digest=<X>",
                ":END:",
                "",
                *scaffold.indent_lines("\n".join(scaffold.HUMAN_AREA_NOTE)).split("\n"),
                "",
                "** 目标",
                "   新目标",
                "",
                "** 范围（做什么）",
                "   老范围。",
                "",
            ]
        )
        self.assertEqual(self._mask(actual), self._mask(expected))
        self.assertRegex(actual, r"digest=[0-9a-f]{12}->[0-9a-f]{12}")
        self.assertIn("digest=" + payload["previousDigest"][:12] + "->", actual)

    def _mask(self, text: str) -> str:
        return re.sub(r"digest=[0-9a-f]{12}->[0-9a-f]{12}", "digest=<X>", text)

    def test_cas_digest_mismatch_writes_nothing(self) -> None:
        directory = self.write_project("proj-hand", FULL_PROJECT_ORG)
        before = (directory / "project.org").read_bytes()
        code, stdout, _ = self.pm(
            "project", "brief", "set", "hand", "--section", "goal", "--text", "x",
            "--actor", "human", "--expect-digest", "0" * 64, "--json",
        )
        self.assertEqual(code, 3)
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "DIGEST_CONFLICT")
        self.assertEqual(payload["expectedDigest"], "0" * 64)
        self.assertEqual(
            payload["currentDigest"],
            hashlib.sha256(before).hexdigest(),
            "要返回当前 digest 供前端重载",
        )
        self.assertEqual((directory / "project.org").read_bytes(), before)

    def test_logbook_created_then_appended(self) -> None:
        directory = self.write_project("proj-hand", FULL_PROJECT_ORG)
        first = self.set_section("hand", "goal", "目标一")
        text = (directory / "project.org").read_text(encoding="utf-8")
        self.assertEqual(text.count(":LOGBOOK:"), 1, "首次写入创建 LOGBOOK")
        self.assertIn("op=brief-set section=goal", text)
        self.assertIn(f'audit={first["auditEventId"]}', text)
        self.assertIn(f':PM_BRIEF_UPDATED: {first["observedAt"]}', text)

        second = self.set_section("hand", "milestones", "M1")
        text = (directory / "project.org").read_text(encoding="utf-8")
        self.assertEqual(text.count(":LOGBOOK:"), 1, "第二次只是追加，不再造抽屉")
        self.assertEqual(text.count("op=brief-set"), 2)
        self.assertIn("op=brief-set section=milestones", text)
        self.assertIn(f'audit={second["auditEventId"]}', text)
        self.assertEqual(second["revision"], 2)
        self.assertIn(f':PM_BRIEF_UPDATED: {second["observedAt"]}', text)

    def test_legacy_wording_migrated_in_same_write(self) -> None:
        directory = self.write_project("proj-hand", FULL_PROJECT_ORG)
        self.assertIn("此后永不写入", (directory / "project.org").read_text(encoding="utf-8"))
        self.set_section("hand", "scope", "只做只读投影。")
        text = (directory / "project.org").read_text(encoding="utf-8")
        self.assertNotIn("此后永不写入", text, "同一次原子写要把旧措辞换掉")
        for line in scaffold.HUMAN_AREA_NOTE:
            self.assertIn(line, text)
        self.assertIn("只做只读投影。", text)

    def test_dry_run_writes_nothing(self) -> None:
        directory = self.write_project("proj-hand", FULL_PROJECT_ORG)
        before = (directory / "project.org").read_bytes()
        payload = self.set_section("hand", "goal", "干跑目标", extra=("--dry-run",))
        self.assertTrue(payload["dry_run"])
        self.assertTrue(payload["changed"])
        self.assertFalse(payload["written"])
        self.assertNotEqual(payload["digest"], payload["previousDigest"])
        self.assertEqual((directory / "project.org").read_bytes(), before)

    def test_unchanged_content_is_zero_change(self) -> None:
        directory = self.write_project("proj-hand", FULL_PROJECT_ORG)
        self.set_section("hand", "goal", "同一个目标")
        after_first = (directory / "project.org").read_bytes()
        payload = self.set_section("hand", "goal", "同一个目标")
        self.assertFalse(payload["changed"])
        self.assertFalse(payload["written"])
        self.assertEqual(payload["digest"], payload["previousDigest"])
        self.assertEqual((directory / "project.org").read_bytes(), after_first)
        self.assertEqual(
            (directory / "project.org").read_text(encoding="utf-8").count("op=brief-set"), 1,
            "零变更不加审计行",
        )

    def test_unknown_section_exit_2(self) -> None:
        directory = self.write_project("proj-hand", FULL_PROJECT_ORG)
        before = (directory / "project.org").read_bytes()
        code, stdout, _ = self.pm(
            "project", "brief", "set", "hand", "--section", "nope", "--text", "x",
            "--actor", "human", "--expect-digest", self.digest("hand"), "--json",
        )
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "UNKNOWN_SECTION")
        self.assertEqual(
            payload["allowedSections"],
            ["goal", "scope", "nonGoal", "acceptance", "milestones", "risks"],
        )
        self.assertEqual((directory / "project.org").read_bytes(), before)

    def test_chinese_section_name_accepted(self) -> None:
        self.write_project("proj-hand", FULL_PROJECT_ORG)
        self.set_section("hand", "里程碑", "M1 只读；M2 编辑通道")
        self.assertEqual(self.sections("hand")["milestones"], "M1 只读；M2 编辑通道")

    def test_round_trip_all_six_sections(self) -> None:
        self.write_project("proj-hand", FULL_PROJECT_ORG)
        wanted = {
            "goal": "目标第一行\n目标第二行",
            "scope": "范围一",
            "nonGoal": "非目标一",
            "acceptance": "- [x] 已完成项\n- [ ] 未完成项",
            "milestones": "M1\nM2",
            "risks": "风险一",
        }
        for section, text in wanted.items():
            self.set_section("hand", section, text)
        brief = self.sections("hand")
        for section, text in wanted.items():
            if section == "acceptance":
                continue
            self.assertEqual(brief[section], text, "brief get 必须原样读回: " + section)
        self.assertEqual(
            brief["acceptance"],
            [{"text": "已完成项", "done": True}, {"text": "未完成项", "done": False}],
        )

    def test_sub_headline_stays_at_column_zero(self) -> None:
        directory = self.write_project("proj-hand", FULL_PROJECT_ORG)
        self.set_section("hand", "scope", "*** 子标题\n- 条目")
        text = (directory / "project.org").read_text(encoding="utf-8")
        self.assertIn("\n*** 子标题\n", text, "以 * 开头的行不加缩进")
        self.assertEqual(self.sections("hand")["scope"], "*** 子标题\n- 条目")

    def test_actor_is_required_and_recorded(self) -> None:
        self.write_project("proj-hand", FULL_PROJECT_ORG)
        code, _stdout, _stderr = self.pm(
            "project", "brief", "set", "hand", "--section", "goal", "--text", "x",
            "--expect-digest", self.digest("hand"), "--json",
        )
        self.assertEqual(code, 2, "--actor 必须显式给出")
        payload = self.set_section("hand", "goal", "AI 写的目标", actor="ai")
        text = (self.library / "projects" / "proj-hand" / "project.org").read_text(encoding="utf-8")
        self.assertIn("actor=ai", text)
        self.assertEqual(payload["auditEventId"][:6], "audit-")

    def test_text_and_text_file_conflict(self) -> None:
        self.write_project("proj-hand", FULL_PROJECT_ORG)
        source = self.base / "text.txt"
        source.write_text("来自文件", encoding="utf-8")
        code, stdout, _ = self.pm(
            "project", "brief", "set", "hand", "--section", "goal", "--text", "来自参数",
            "--text-file", str(source), "--actor", "human",
            "--expect-digest", self.digest("hand"), "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "TEXT_CONFLICT")

    def test_missing_project_org_refused(self) -> None:
        (self.library / "projects" / "proj-nofile").mkdir(parents=True)
        code, stdout, _ = self.pm(
            "project", "brief", "set", "nofile", "--section", "goal", "--text", "x",
            "--actor", "human", "--expect-digest", "0" * 64, "--json",
        )
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "NO_PROJECT_ORG")
        self.assertIn("pm project create nofile", payload["hint"])
        self.assertFalse((self.library / "projects" / "proj-nofile" / "project.org").exists())

    def test_does_not_touch_other_files(self) -> None:
        self.write_project("proj-hand", FULL_PROJECT_ORG)
        (self.library / "inbox.org").write_text("#+TITLE: Inbox\n\n* Inbox\n", encoding="utf-8")
        (self.library / "proposals.org").write_text("#+TITLE: 提案\n", encoding="utf-8")
        (self.library / "projects" / "proj-hand" / "tasks.org").write_text("#+TITLE: 任务\n", encoding="utf-8")
        others = {
            name: (self.library / name).read_bytes()
            for name in ("inbox.org", "proposals.org", "projects/proj-hand/tasks.org")
        }
        self.set_section("hand", "goal", "只该动 project.org")
        for name, before in others.items():
            self.assertEqual((self.library / name).read_bytes(), before, name + " 被动过了")


class ScaffoldContractTest(ProjectBriefBaseTest):
    def test_new_projects_use_the_new_contract_wording(self) -> None:
        self.ok("project", "create", "demo01", "--json")
        text = (self.library / "projects" / "proj-demo01" / "project.org").read_text(encoding="utf-8")
        self.assertIn("pm 只在项目创建时生成骨架", text)
        self.assertIn("只在你显式提交编辑时写入你指定的那一段", text)
        self.assertNotIn("此后永不写入", text)


class AbsolutePathTest(ProjectBriefBaseTest):
    """task-224：brief 投影新增**服务端解析**的 `absolutePath`；不可解析必须 `null`。

    背景：`path` 是相对库根的路径，前端拼绝对路径只能靠猜；面板上别处的 `projects[].paths[]`
    是 **DSH 工作区路径**，不保证等于库根 —— 前端硬拼就是编造。
    """

    TOP_KEYS = {"project", "id", "path", "absolutePath", "title", "readOnly", "digest", "brief", "reason", "message"}

    def test_positive_resolves_to_existing_file(self) -> None:
        self.ok("project", "create", "demo01", "--json")
        payload = self.ok("project", "brief", "get", "demo01", "--json")
        expected = (self.library / "projects" / "proj-demo01" / "project.org").resolve()
        self.assertEqual(payload["absolutePath"], str(expected), "必须是服务端解析的绝对路径")
        self.assertTrue(Path(payload["absolutePath"]).is_file(), "指向的文件必须真实存在")
        self.assertTrue(payload["absolutePath"].startswith(str(self.library.resolve())), "必须落在库根下")
        self.assertNotEqual(payload["absolutePath"], payload["path"], "绝不用相对路径冒充")
        self.assertNotIn("/home/", payload["absolutePath"].replace(str(self.library), ""), "不许掺工作区路径")

    def test_negative_missing_project_org_is_null(self) -> None:
        self.ok("project", "create", "demo01", "--json")
        (self.library / "projects" / "proj-demo01" / "project.org").unlink()
        payload = self.ok("project", "brief", "get", "demo01", "--json")
        self.assertIsNone(payload["absolutePath"], "文件不在 → 必须 null（不回落相对/工作区路径）")
        self.assertIsNone(payload["brief"])
        self.assertEqual(payload["reason"], "NO_PROJECT_ORG")
        self.assertIn("project.org", payload["message"])

    def test_negative_missing_library_root_is_null_via_domain_call(self) -> None:
        """库根不存在时直接调领域函数：明确 NOT_FOUND，**不返回编造的路径**。"""
        from pm.layout import Layout
        from pm.projects import ProjectsError

        with self.assertRaises(ProjectsError) as raised:
            projects_module.get_brief(Layout(self.base / "does-not-exist"), "demo01")
        self.assertEqual(raised.exception.code, "NOT_FOUND")

    def test_negative_deleted_library_errors_at_cli(self) -> None:
        """整库被删（等价"未配置"）：CLI 明确失败，不输出任何幻觉 payload。"""
        import shutil

        self.ok("project", "create", "demo01", "--json")
        shutil.rmtree(self.library)
        code, stdout, stderr = self.pm("project", "brief", "get", "demo01", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("LIBRARY_MISSING", stderr)
        # --json 时 stdout 是**错误信封**（{ok:false,error:{...}}），不是库数据：里面绝不能有 absolutePath
        if stdout.strip():
            envelope = json.loads(stdout)
            self.assertFalse(envelope["ok"])
            self.assertEqual(envelope["error"]["code"], "LIBRARY_MISSING")
            self.assertNotIn("absolutePath", stdout)

    def test_regression_other_fields_unchanged(self) -> None:
        self.ok("project", "create", "demo01", "--json")
        payload = self.ok("project", "brief", "get", "demo01", "--json")
        self.assertEqual(set(payload), self.TOP_KEYS, "字段集合：只多一个 absolutePath（additive）")
        self.assertEqual(payload["project"], "demo01")
        self.assertEqual(payload["id"], "proj-demo01")
        self.assertEqual(payload["path"], "projects/proj-demo01")
        self.assertEqual(payload["title"], "demo01")
        self.assertIs(payload["readOnly"], True)
        self.assertIsNone(payload["reason"])
        self.assertIsInstance(payload["digest"], str)
        self.assertEqual(len(payload["digest"]), 64)
        self.assertEqual(payload["brief"]["missingSections"], [])


if __name__ == "__main__":
    unittest.main()
