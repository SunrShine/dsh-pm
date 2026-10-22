"""pm capture 子命令测试。

关注三件事：
1. 复用同一条写入实现（humanwrite.append_entry_tracked ← mcp.capture_text），只追加不改写；
2. --json 的 stdout 必须是纯 JSON（argparse/usage 全走 stderr）；
3. 空文本 / 无库 → 退出码 2 且一个字节都不写。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pm import cli, mcp
from pm.humanwrite import append_entry, append_entry_tracked

import fixtures

DOC = "#+TITLE: Inbox\n\n* Inbox\n  随手记\n\n* 别的组\n  保留内容\n"


class CaptureCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.library = self.base / "wm"
        self.library.mkdir()
        self.inbox = self.library / "inbox.org"
        self.config = self.base / "pm.toml"
        self.config.write_text('library = "' + str(self.library) + '"\nactive_days = 14\n', encoding="utf-8")

    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(argv)
        except SystemExit as exc:  # argparse 的参数错误走这里，退出码 2
            code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def capture(self, *extra: str) -> tuple[int, str, str]:
        return self.run_cli(["--config", str(self.config), "capture", *extra])

    # ---- 正常追加 ----

    def test_json_is_pure_and_has_contract_shape(self) -> None:
        code, stdout, stderr = self.capture("测试笔记", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)  # stdout 必须是纯 JSON，混一个字符就炸
        self.assertEqual(
            set(payload),
            {
                "ok",
                "entityId",
                "inboxId",
                "source",
                "observedAt",
                "auditEventId",
                "path",
                "line",
                "revision",
            },
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["path"], "inbox.org")
        self.assertEqual(payload["revision"], 1)
        self.assertEqual(payload["entityId"], payload["inboxId"], "§5：entityId 与 inboxId 等值")
        self.assertEqual(payload["source"], "org")
        self.assertRegex(payload["observedAt"], r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{2}:[0-9]{2}$")
        self.assertRegex(payload["auditEventId"], r"^audit-[0-9A-HJKMNP-TV-Z]{26}$")
        self.assertRegex(payload["inboxId"], r"^inbox-[0-9A-HJKMNP-TV-Z]{26}$")
        self.assertIsInstance(payload["line"], int)
        lines = self.inbox.read_text(encoding="utf-8").split("\n")
        # §11：capture 也有审计事件（写进该条目的 LOGBOOK）
        self.assertIn(":LOGBOOK:", [line.strip() for line in lines])
        self.assertIn("audit=" + payload["auditEventId"], "\n".join(lines))
        self.assertIn('State "CAPTURED" from "(created)"', "\n".join(lines))
        self.assertEqual(lines[payload["line"] - 1], "** INBOX 测试笔记")
        stripped = [line.strip() for line in lines]
        self.assertIn(":ID: " + payload["inboxId"], stripped)
        self.assertIn(":PM_KIND: inbox", stripped)
        self.assertIn(":PM_STATUS: CAPTURED", stripped)
        self.assertIn(":PM_SOURCE: cli", stripped)
        self.assertIn(":PM_REVISION: 1", stripped)

    def test_project_hint_is_written_as_property_but_does_not_change_target(self) -> None:
        tasks = self.library / "projects" / "proj-demo" / "tasks.org"
        code, stdout, _ = self.capture("带项目提示", "--project", "demo", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["path"], "inbox.org")
        self.assertNotIn("project_hint", payload, "P1-4 起 capture --json 固定为五个键")
        text = self.inbox.read_text(encoding="utf-8")
        self.assertIn(":PM_PROJECT_HINT: demo", text, "hint 落成 org 属性")
        self.assertIn("带项目提示", text)
        self.assertFalse(tasks.exists(), "--project 只是提示，不得写到任务文件")

    def test_creates_missing_inbox_with_headline(self) -> None:
        self.assertFalse(self.inbox.exists())
        code, _stdout, _ = self.capture("第一条", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(self.inbox.is_file())
        text = self.inbox.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("* Inbox"))
        self.assertIn("第一条", text)

    def test_only_appends_and_never_rewrites(self) -> None:
        self.inbox.write_text(DOC, encoding="utf-8")
        before = self.inbox.read_text(encoding="utf-8")
        code, _stdout, _ = self.capture("新笔记", "--json")
        self.assertEqual(code, 0)
        text = self.inbox.read_text(encoding="utf-8")
        for line in before.split("\n"):
            if line.strip():
                self.assertIn(line, text, "已有内容必须原样保留")
        self.assertLess(text.index("新笔记"), text.index("* 别的组"))
        self.assertIn("保留内容", text)

        code, _stdout, _ = self.capture("第二条", "--json")
        self.assertEqual(code, 0)
        text = self.inbox.read_text(encoding="utf-8")
        self.assertIn("新笔记", text)
        self.assertIn("第二条", text)
        self.assertLess(text.index("新笔记"), text.index("第二条"))

    def test_capture_preserves_crlf(self) -> None:
        self.inbox.write_bytes(DOC.replace("\n", "\r\n").encode("utf-8"))
        code, _stdout, _ = self.capture("CRLF 笔记", "--json")
        self.assertEqual(code, 0)
        self.assertIn(b"\r\n", self.inbox.read_bytes())
        self.assertIn("CRLF 笔记", self.inbox.read_text(encoding="utf-8"))

    def test_multiline_capture_is_lossless_through_read_inbox(self) -> None:
        from pm.inbox import read_inbox

        text = "第一行 * 星号 | 竖线\n第二行 中文 ✓\n\n第四行"
        code, stdout, _ = self.capture(text, "--json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["revision"], 1)
        inbox = read_inbox(self.library)
        assert inbox is not None
        self.assertEqual(inbox["count"], 1)
        entry = inbox["entries"][0]
        self.assertEqual(entry["text"], text, "写入再读回必须逐字节相同")
        self.assertEqual(entry["id"], payload["inboxId"])
        self.assertEqual(entry["status"], "CAPTURED")

    def test_two_captures_get_unique_monotonic_ids(self) -> None:
        from pm.inbox import read_inbox

        self.capture("第一条", "--json")
        self.capture("第二条", "--json")
        inbox = read_inbox(self.library)
        assert inbox is not None
        ids = [entry["id"] for entry in inbox["entries"]]
        self.assertEqual(len(set(ids)), 2, "同一进程内 ID 必须唯一")
        self.assertEqual(ids, sorted(ids), "同一进程内 ID 单调递增")

    def test_capture_writes_design_property_set(self) -> None:
        code, stdout, _ = self.capture("属性检查", "--project", "demo", "--json")
        self.assertEqual(code, 0)
        inbox_id = json.loads(stdout)["inboxId"]
        text = self.inbox.read_text(encoding="utf-8")
        self.assertIn("** INBOX 属性检查", text)
        for expected in (
            ":ID: " + inbox_id,
            ":PM_KIND: inbox",
            ":PM_STATUS: CAPTURED",
            ":PM_SOURCE: cli",
            ":PM_CAPTURED_AT: ",
            ":PM_PROJECT_HINT: demo",
            ":PM_REVISION: 1",
        ):
            self.assertIn(expected, text)

    # ---- 拒绝路径：一个字节都不写 ----

    def test_empty_and_blank_text_rejected_without_writing(self) -> None:
        self.inbox.write_text(DOC, encoding="utf-8")
        before = self.inbox.read_bytes()
        for text in ("", "   ", "\t\n"):
            code, stdout, stderr = self.capture(text, "--json")
            self.assertEqual(code, 2)
            payload = json.loads(stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("文本为空", payload["error"])
            self.assertIn("文本为空", stderr)
            self.assertEqual(self.inbox.read_bytes(), before)
        self.assertEqual(len(self.inbox.read_text(encoding="utf-8").split("\n")), len(DOC.split("\n")))

    def test_missing_text_argument_rejected_with_json(self) -> None:
        code, stdout, _ = self.capture("--json")
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(stdout)["ok"])
        self.assertFalse(self.inbox.exists())

    def test_human_mode_error_keeps_stdout_empty(self) -> None:
        code, stdout, stderr = self.capture("")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "", "人类模式下 stdout 不应出现帮助或错误文本")
        self.assertIn("文本为空", stderr)

    def test_library_not_configured_fails_loudly(self) -> None:
        nolib = self.base / "nolib.toml"
        nolib.write_text("active_days = 14\n", encoding="utf-8")
        code, stdout, stderr = self.run_cli(["--config", str(nolib), "capture", "笔记", "--json"])
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("library", payload["error"])
        self.assertIn("未配置", stderr)
        self.assertFalse(self.inbox.exists())

    def test_library_dir_missing_fails(self) -> None:
        gone = self.base / "gone.toml"
        gone.write_text('library = "' + str(self.base / "nope") + '"\n', encoding="utf-8")
        code, stdout, _ = self.run_cli(["--config", str(gone), "capture", "笔记", "--json"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(stdout)["ok"])

    def test_dry_run_json_shape_and_writes_nothing(self) -> None:
        self.inbox.write_text(DOC, encoding="utf-8")
        before_bytes = self.inbox.read_bytes()
        before_mtime = self.inbox.stat().st_mtime_ns
        code, stdout, _ = self.capture("预演笔记", "--dry-run", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(
            set(payload),
            {
                "ok",
                "dry_run",
                "entityId",
                "inboxId",
                "source",
                "observedAt",
                "auditEventId",
                "revision",
                "path",
                "line",
                "block",
            },
        )
        self.assertRegex(payload["auditEventId"], r"^audit-[0-9A-HJKMNP-TV-Z]{26}$")
        self.assertIn("audit=" + payload["auditEventId"], payload["block"], "预演块里就有审计行")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["path"], "inbox.org")
        self.assertEqual(payload["revision"], 1)
        self.assertRegex(payload["inboxId"], r"^inbox-[0-9A-HJKMNP-TV-Z]{26}$")
        self.assertIn(payload["inboxId"], payload["block"], "dry-run 的块里就是用这个 ID")
        self.assertIsInstance(payload["line"], int)
        self.assertTrue(payload["block"].startswith("**"))
        self.assertIn("预演笔记", payload["block"])
        self.assertEqual(self.inbox.read_bytes(), before_bytes, "dry-run 不得落盘")
        self.assertEqual(self.inbox.stat().st_mtime_ns, before_mtime)

        # 预演的行号 == 真写时的行号（同一处插入位置算法）
        code, stdout, _ = self.capture("预演笔记", "--json")
        self.assertEqual(code, 0)
        written = json.loads(stdout)
        self.assertEqual(written["line"], payload["line"])
        lines = self.inbox.read_text(encoding="utf-8").split("\n")
        # P1-1：单行输入进标题（正文为空），预演与真写落在同一行
        self.assertEqual(lines[payload["line"] - 1], "** INBOX 预演笔记")

    def test_dry_run_human_mode_shows_target_and_project_hint(self) -> None:
        self.inbox.write_text(DOC, encoding="utf-8")
        before = self.inbox.read_bytes()
        code, stdout, _ = self.capture("预演", "--dry-run", "--project", "demo")
        self.assertEqual(code, 0)
        self.assertIn("将写入", stdout)
        self.assertIn("inbox.org", stdout)
        self.assertIn("demo", stdout)
        self.assertIn("预演", stdout)
        self.assertEqual(self.inbox.read_bytes(), before)

    def test_dry_run_does_not_create_missing_inbox(self) -> None:
        self.assertFalse(self.inbox.exists())
        code, stdout, _ = self.capture("新库预演", "--dry-run", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["line"], 3)  # * Inbox + 空行之后
        self.assertFalse(self.inbox.exists(), "dry-run 不得创建文件")

    def test_dry_run_empty_text_still_rejected(self) -> None:
        self.inbox.write_text(DOC, encoding="utf-8")
        before = self.inbox.read_bytes()
        code, stdout, _ = self.capture("   ", "--dry-run", "--json")
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("文本为空", payload["error"])
        self.assertEqual(self.inbox.read_bytes(), before)

    def test_argparse_error_writes_nothing_to_stdout(self) -> None:
        code, stdout, stderr = self.run_cli(
            ["--config", str(self.config), "capture", "笔记", "--bogus", "--json"]
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "", "argparse 的 usage 不得混进 stdout")
        self.assertIn("usage", stderr)

    def test_no_subcommand_help_goes_to_stderr(self) -> None:
        code, stdout, stderr = self.run_cli([])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("usage", stderr)

    # ---- 与 ui-cards 的连通 ----

    def test_ui_cards_inbox_count_increments_and_last_entry_is_new_text(self) -> None:
        home = fixtures.build_dsh_home(self.base / "dsh")
        config = self.base / "with_dsh.toml"
        config.write_text(
            fixtures.fixture_config_toml(library=str(self.library)).replace("REPLACED", str(home)),
            encoding="utf-8",
        )
        self.inbox.write_text("#+TITLE: Inbox\n\n* Inbox\n  随手记\n\n- 旧笔记\n", encoding="utf-8")
        argv = ["--config", str(config), "ui-cards", "--dsh-home", str(home)]
        before = json.loads(self.run_cli(argv)[1])["inbox"]["count"]
        self.assertEqual(before, 1)
        code, _stdout, _ = self.run_cli(
            ["--config", str(config), "capture", "写进库的新笔记", "--json"]
        )
        self.assertEqual(code, 0)
        payload = json.loads(self.run_cli(argv)[1])
        self.assertEqual(payload["inbox"]["count"], before + 1)
        entry = payload["inbox"]["entries"][-1]
        self.assertEqual(entry["text"], "写进库的新笔记")
        # 前端要显示的三个字段（原来缺失，界面只能写「未记录」）
        self.assertTrue(entry["capturedAt"], "ui-cards 必须暴露 :PM_CAPTURED_AT:")
        self.assertEqual(entry["source"], "cli")
        self.assertIsNone(entry["projectHint"])
        # 旧条目（种子里的人工列表项）三个字段都是 null
        legacy = payload["inbox"]["entries"][0]
        self.assertIsNone(legacy["capturedAt"])
        self.assertIsNone(legacy["source"])
        self.assertIsNone(legacy["projectHint"])


class CaptureWriteGateTest(unittest.TestCase):
    """写入闸门：没显式给 --config 又不是 --dry-run 时必须 --yes。

    用 PM_CONFIG 模拟「默认配置」：它不是命令行 --config，所以闸门照样生效；
    这样测试既能覆盖默认配置路径，又不会碰到仓库里那份真实配置。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.library = self.base / "wm"
        self.library.mkdir()
        self.inbox = self.library / "inbox.org"
        self.inbox.write_text("#+TITLE: Inbox\n\n* Inbox\n  随手记\n", encoding="utf-8")
        self.config = self.base / "pm.toml"
        self.config.write_text('library = "' + str(self.library) + '"\n', encoding="utf-8")

    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        try:
            with mock.patch.dict(os.environ, {"PM_CONFIG": str(self.config)}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def test_gate_blocks_without_config_or_yes(self) -> None:
        before = self.inbox.read_bytes()
        code, stdout, stderr = self.run_cli(["capture", "探针", "--json"])
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertEqual(set(payload), {"ok", "error"})
        self.assertFalse(payload["ok"])
        self.assertIn(str(self.library.resolve()), payload["error"])
        self.assertIn("默认配置指向的库", payload["error"])
        self.assertIn("--config", payload["error"])
        self.assertIn("--yes", payload["error"])
        self.assertIn("默认配置指向的库", stderr)
        self.assertEqual(self.inbox.read_bytes(), before, "被闸门拒绝时一个字节都不能写")

    def test_gate_allows_with_yes(self) -> None:
        code, stdout, _ = self.run_cli(["capture", "确认写入", "--yes", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout)["ok"])
        self.assertIn("确认写入", self.inbox.read_text(encoding="utf-8"))

    def test_explicit_config_needs_no_yes(self) -> None:
        code, stdout, _ = self.run_cli(["--config", str(self.config), "capture", "显式库", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout)["ok"])
        self.assertIn("显式库", self.inbox.read_text(encoding="utf-8"))

    def test_dry_run_needs_no_yes_and_writes_nothing(self) -> None:
        before = self.inbox.read_bytes()
        code, stdout, _ = self.run_cli(["capture", "预演", "--dry-run", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["dry_run"])
        self.assertIn("预演", payload["block"])
        self.assertEqual(self.inbox.read_bytes(), before)

    def test_missing_explicit_config_does_not_fall_back(self) -> None:
        """--config 指向不存在的文件时 load_config 会静默回落，绝不能让那次回落写进默认库。"""
        before = self.inbox.read_bytes()
        missing = self.base / "nope.toml"
        code, stdout, _ = self.run_cli(["--config", str(missing), "capture", "x", "--json"])
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("不存在", payload["error"])
        self.assertEqual(self.inbox.read_bytes(), before)

    def test_gate_does_not_apply_to_read_commands(self) -> None:
        home = fixtures.build_dsh_home(self.base / "dsh")
        code, stdout, _ = self.run_cli(["ui-cards", "--dsh-home", str(home)])
        self.assertEqual(code, 0)
        self.assertIn("runtime_status", json.loads(stdout))


class TrackedAppendTest(unittest.TestCase):
    """行号来自 humanwrite 的同一处写入实现，不是事后猜的。"""

    def test_line_points_at_appended_block_in_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inbox.org"
            path.write_text(DOC, encoding="utf-8")
            _path, found, line = append_entry_tracked(
                path, headline="Inbox", block="** 新条目\n   正文"
            )
            self.assertTrue(found)
            lines = path.read_text(encoding="utf-8").split("\n")
            self.assertEqual(lines[line - 1], "** 新条目")

    def test_line_points_at_block_when_section_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inbox.org"
            path.write_text("* 别的组\n  内容\n", encoding="utf-8")
            _path, found, line = append_entry_tracked(
                path, headline="不存在", block="** 追加到末尾"
            )
            self.assertFalse(found)
            lines = path.read_text(encoding="utf-8").split("\n")
            self.assertEqual(lines[line - 1], "** 追加到末尾")

    def test_append_entry_api_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inbox.org"
            written, found = append_entry(path, headline="Inbox", block="** 旧接口")
            self.assertEqual(written, path)
            self.assertTrue(found)
            self.assertIn("** 旧接口", path.read_text(encoding="utf-8"))


class McpParityTest(unittest.TestCase):
    """MCP 工具与 CLI 走同一条实现，重构后行为不变。"""

    def test_tool_capture_still_appends(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        home = fixtures.build_dsh_home(base / "dsh")
        library = base / "wm"
        library.mkdir()
        config = base / "pm.toml"
        config.write_text(
            fixtures.fixture_config_toml(library=str(library)).replace("REPLACED", str(home)),
            encoding="utf-8",
        )
        service = mcp.Service(str(config))
        message = mcp.tool_capture(service, {"text": "MCP 写的一条", "model": "test-model"})
        self.assertIn("已追加到", message)
        text = (library / "inbox.org").read_text(encoding="utf-8")
        self.assertIn("MCP 写的一条", text)
        self.assertIn(":PM_ADDED_BY: test-model", text)


if __name__ == "__main__":
    unittest.main()
