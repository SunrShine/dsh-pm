"""pm project list / create + PROJECT_NOT_FOUND 可操作提示（task-43）。

- list：库内目录 ∪ 投影（inLibrary 区分；缺 project.org 的目录按目录名兜底、title 为空）
- create：复用 scaffold 的同一套 skeleton；幂等；非法 key exit 2
- approve 到新目录：任务落在 projects/proj-<key>/tasks.org
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from pm import cli

import fixtures


def _project_org(dir_name: str, key: str, title: str, paths=()) -> str:
    lines = [
        f"#+TITLE: {title}",
        f"#+CATEGORY: {key}",
        "#+FILETAGS: :pm:project:",
    ]
    lines.extend(f"#+PM_PATH: {path}" for path in paths)
    lines.extend(
        [
            "",
            f"* {title} :project:",
            ":PROPERTIES:",
            f":ID: {dir_name}",
            ":PM_KIND: project",
            f":PM_KEY: {key}",
            ":PM_RUNTIME_STATUS: unknown",
            ":END:",
            "",
        ]
    )
    return "\n".join(lines)


def _tasks_org(count: int) -> str:
    blocks = []
    for index in range(count):
        blocks.append(
            "** TODO 任务%d\n   :PROPERTIES:\n   :ID: task-0000000000000000000000000%d\n"
            "   :PM_KIND: task\n   :PM_STATUS: TODO\n   :PM_REVISION: 1\n   :END:\n" % (index, index)
        )
    return "#+TITLE: 任务\n\n* 任务\n" + "\n".join(blocks)


class ProjectCommandsBaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.home = fixtures.build_dsh_home(self.base / "dsh")
        self.library = self.base / "wm"
        self.library.mkdir()
        self.config = self.base / "pm.toml"
        self.config.write_text(self._config_for(self.library), encoding="utf-8")

    def _config_for(self, library: Path) -> str:
        return fixtures.fixture_config_toml(library=str(library)).replace("REPLACED", str(self.home))

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

    def seed_project_dir(self, dir_name: str, key: str, title: str, paths=(), task_count: int = 0) -> Path:
        directory = self.library / "projects" / dir_name
        directory.mkdir(parents=True)
        (directory / "project.org").write_text(
            _project_org(dir_name, key, title, paths), encoding="utf-8"
        )
        if task_count:
            (directory / "tasks.org").write_text(_tasks_org(task_count), encoding="utf-8")
        return directory

    def rows(self, *argv: str) -> dict:
        payload = self.ok("project", "list", "--json", *argv)
        return {row["key"]: row for row in payload["projects"]}


class ProjectListTest(ProjectCommandsBaseTest):
    def test_three_states_library_projection_and_fallback(self) -> None:
        self.seed_project_dir("proj-001_inlib", "001_inlib", "库内项目", paths=["/w/one"], task_count=2)
        (self.library / "projects" / "proj-nofile").mkdir(parents=True)  # 没 project.org

        payload = self.ok("project", "list", "--json")
        self.assertEqual(set(payload), {"projects", "count"})
        rows = {row["key"]: row for row in payload["projects"]}
        self.assertEqual(set(rows), {"001_inlib", "nofile", "alpha_beta"})
        self.assertEqual(payload["count"], 3)

        in_library = rows["001_inlib"]
        self.assertEqual(
            set(in_library),
            {"key", "id", "title", "inLibrary", "path", "taskCount", "workspaceCount"},
        )
        self.assertTrue(in_library["inLibrary"])
        self.assertEqual(in_library["id"], "proj-001_inlib")
        self.assertEqual(in_library["path"], "projects/proj-001_inlib")
        self.assertEqual(in_library["title"], "库内项目")
        self.assertEqual(in_library["taskCount"], 2)
        self.assertEqual(in_library["workspaceCount"], 1)

        nofile = rows["nofile"]
        self.assertTrue(nofile["inLibrary"])
        self.assertEqual(nofile["path"], "projects/proj-nofile")
        self.assertEqual(nofile["title"], "", "缺 project.org → 目录名兜底、title 为空")

        projection = rows["alpha_beta"]
        self.assertFalse(projection["inLibrary"])
        self.assertIsNone(projection["path"])
        self.assertEqual(projection["workspaceCount"], 2, "投影的两个工作区")
        self.assertEqual(projection["taskCount"], 0)

        # 排序：库内优先，其次 key
        self.assertEqual([row["key"] for row in payload["projects"]], ["001_inlib", "nofile", "alpha_beta"])

    def test_in_library_only(self) -> None:
        self.seed_project_dir("proj-001_inlib", "001_inlib", "库内项目")
        rows = self.rows("--in-library-only")
        self.assertEqual(set(rows), {"001_inlib"})

    def test_empty_library_lists_projection_only(self) -> None:
        empty = self.base / "empty"
        empty.mkdir()
        config = self.base / "empty.toml"
        config.write_text(self._config_for(empty), encoding="utf-8")
        code, stdout, _ = self.run_cli(["--config", str(config), "project", "list", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["projects"], "空库也有投影项目")
        for row in payload["projects"]:
            self.assertFalse(row["inLibrary"])
            self.assertIsNone(row["path"])
        code, stdout, _ = self.run_cli(
            ["--config", str(config), "project", "list", "--in-library-only", "--json"]
        )
        self.assertEqual(json.loads(stdout)["count"], 0)

    def test_list_is_read_only(self) -> None:
        self.seed_project_dir("proj-001_inlib", "001_inlib", "库内项目")
        before = hashlib.sha256(b"".join(sorted(p.read_bytes() for p in self.library.rglob("*") if p.is_file()))).hexdigest()
        self.ok("project", "list", "--json")
        after = hashlib.sha256(b"".join(sorted(p.read_bytes() for p in self.library.rglob("*") if p.is_file()))).hexdigest()
        self.assertEqual(before, after)

    def test_list_after_create_marks_in_library(self) -> None:
        self.ok("project", "create", "alpha_beta", "--json")
        row = self.rows()["alpha_beta"]
        self.assertTrue(row["inLibrary"])
        self.assertEqual(row["path"], "projects/proj-alpha_beta")
        self.assertEqual(row["workspaceCount"], 2, "投影的两个工作区也要算进已建目录")


class ProjectCreateTest(ProjectCommandsBaseTest):
    def test_create_new_then_idempotent(self) -> None:
        payload = self.ok("project", "create", "demo01", "--json")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["created"])
        self.assertFalse(payload["exists"])
        self.assertEqual(payload["key"], "demo01")
        self.assertEqual(payload["id"], "proj-demo01")
        self.assertEqual(payload["path"], "projects/proj-demo01")
        directory = self.library / "projects" / "proj-demo01"
        for name in ("project.org", "tasks.org", "memory.org"):
            self.assertTrue((directory / name).is_file(), name)
        self.assertIn(":PM_KEY: demo01", (directory / "project.org").read_text(encoding="utf-8"))

        snapshot = {name: (directory / name).read_bytes() for name in ("project.org", "tasks.org", "memory.org")}
        again = self.ok("project", "create", "demo01", "--json")
        self.assertFalse(again["created"])
        self.assertTrue(again["exists"])
        self.assertEqual(again["files"], [])
        self.assertEqual(again["path"], "projects/proj-demo01")
        self.assertEqual(
            {name: (directory / name).read_bytes() for name in snapshot}, snapshot, "重复调用不改字节"
        )

    def test_create_rejects_invalid_key(self) -> None:
        for key in ("bad key", "a/b", "", "a*b", "../x"):
            code, stdout, _ = self.pm("project", "create", key, "--json")
            self.assertEqual(code, 2, key)
            self.assertEqual(json.loads(stdout)["error"]["code"], "INVALID_PROJECT_KEY", key)
        self.assertFalse((self.library / "projects").exists(), "非法 key 不建任何目录")

    def test_create_matches_init_skeleton(self) -> None:
        """与 pm init 的产物一致（复用同一套 scaffold 函数）。"""
        init_library = self.base / "init_lib"
        init_library.mkdir()
        init_config = self.base / "init.toml"
        init_config.write_text(self._config_for(init_library), encoding="utf-8")
        code, _stdout, stderr = self.run_cli(
            [
                "--config", str(init_config), "init", "--root", str(init_library),
                "--project", "alpha_beta", "--no-git",
            ]
        )
        self.assertEqual(code, 0, stderr)
        created = self.ok("project", "create", "alpha_beta", "--json")
        self.assertTrue(created["created"])
        for name in ("project.org", "tasks.org", "memory.org"):
            from_init = (init_library / "projects" / "proj-alpha_beta" / name).read_text(encoding="utf-8")
            from_create = (self.library / "projects" / "proj-alpha_beta" / name).read_text(encoding="utf-8")
            self.assertEqual(from_init, from_create, name)

    def test_create_title_paths_and_dry_run(self) -> None:
        planned = self.ok(
            "project", "create", "withpaths", "--title", "我的项目",
            "--path", "/w/x", "--path", "/w/y", "--dry-run", "--json",
        )
        self.assertTrue(planned["dry_run"])
        self.assertFalse(planned["created"])
        self.assertFalse((self.library / "projects" / "proj-withpaths").exists(), "干跑不落盘")

        payload = self.ok(
            "project", "create", "withpaths", "--title", "我的项目",
            "--path", "/w/x", "--workspace", "/w/y", "--json",
        )
        self.assertTrue(payload["created"])
        text = (self.library / "projects" / "proj-withpaths" / "project.org").read_text(encoding="utf-8")
        self.assertIn("#+TITLE: 我的项目", text)
        self.assertIn(":PM_PATHS: /w/x|/w/y", text)
        self.assertIn("#+PM_PATH: /w/x", text)
        self.assertEqual(payload["title"], "我的项目")
        self.assertEqual(self.rows()["withpaths"]["workspaceCount"], 2)

    def test_create_does_not_touch_other_projects_or_inbox(self) -> None:
        self.seed_project_dir("proj-001_inlib", "001_inlib", "库内项目")
        (self.library / "inbox.org").write_text("#+TITLE: Inbox\n\n* Inbox\n", encoding="utf-8")
        self.ok("capture", "别动我", "--json")
        other = (self.library / "projects" / "proj-001_inlib" / "project.org").read_bytes()
        inbox = (self.library / "inbox.org").read_bytes()
        self.ok("project", "create", "untouched", "--json")
        self.assertEqual((self.library / "projects" / "proj-001_inlib" / "project.org").read_bytes(), other)
        self.assertEqual((self.library / "inbox.org").read_bytes(), inbox)
        self.assertTrue((self.library / "projects" / "proj-untouched" / "tasks.org").is_file())


class ApproveIntoNewProjectTest(ProjectCommandsBaseTest):
    def test_approve_needs_project_then_works_after_create(self) -> None:
        inbox_id = self.ok("capture", "给新项目的一件事", "--json")["inboxId"]
        proposal = self.ok(
            "proposal", "create", "--source-inbox", inbox_id,
            "--project", "pm_tools",
            "--change", '{"op": "新增", "title": "新项目的第一件事", "criteria": ["有验收"]}',
            "--json",
        )
        proposal_id = proposal["entityId"]

        # 1) 目录不存在 → PROJECT_NOT_FOUND，且错误可操作
        code, stdout, _ = self.pm(
            "proposal", "approve", proposal_id, "--expected-revision", "1", "--json"
        )
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "PROJECT_NOT_FOUND")
        self.assertTrue(payload["canCreate"], "前端据此显示『新建项目』")
        self.assertIn("pm project create pm_tools", payload["hint"])
        self.assertEqual(payload["project"], "pm_tools")

        # 2) 建目录 → 再批准成功
        created = self.ok("project", "create", "pm_tools", "--json")
        self.assertTrue(created["created"])
        approved = self.ok(
            "proposal", "approve", proposal_id, "--expected-revision", "1", "--json"
        )
        self.assertEqual(approved["status"], "APPROVED")
        self.assertEqual(approved["project"], "pm_tools")

        # 3) 任务落在新目录
        tasks_path = self.library / "projects" / "proj-pm_tools" / "tasks.org"
        self.assertTrue(tasks_path.is_file())
        tasks_text = tasks_path.read_text(encoding="utf-8")
        self.assertIn("新项目的第一件事", tasks_text)
        self.assertIn(approved["taskIds"][0], tasks_text)

        # 4) inbox 被标记（approve 的语义是「任务已创建」→ TASK_CREATED，见报告里的口径核对）
        entries = {row["id"]: row for row in self.ok("inbox", "list", "--json")["entries"]}
        self.assertEqual(entries[inbox_id]["status"], "TASK_CREATED")


if __name__ == "__main__":
    unittest.main()
