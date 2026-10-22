from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pm import mcp
from pm.config import Config

import fixtures


def make_service(case: unittest.TestCase) -> mcp.Service:
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    base = Path(tmp.name)
    home = fixtures.build_dsh_home(base / "dsh")
    library = base / "wm"
    library.mkdir()
    config_path = base / "pm.toml"
    config_path.write_text(
        fixtures.fixture_config_toml(library=str(library)).replace("REPLACED", str(home)),
        encoding="utf-8",
    )
    return mcp.Service(str(config_path))


class ProtocolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = make_service(self)

    def test_initialize_echoes_supported_version(self) -> None:
        response = mcp.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2026-07-28"},
            },
            self.service,
        )
        assert response is not None
        self.assertEqual(response["result"]["protocolVersion"], "2026-07-28")
        self.assertEqual(response["result"]["serverInfo"]["name"], "pm")

    def test_initialize_falls_back_on_unknown_version(self) -> None:
        response = mcp.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}},
            self.service,
        )
        assert response is not None
        self.assertEqual(response["result"]["protocolVersion"], mcp.LATEST_PROTOCOL_VERSION)

    def test_notifications_get_no_reply(self) -> None:
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.service))

    def test_tools_list_shape(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, self.service)
        assert response is not None
        tools = response["result"]["tools"]
        self.assertEqual(len(tools), len(mcp.TOOLS))
        for tool in tools:
            self.assertIn("name", tool)
            self.assertIn("description", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_ping(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 9, "method": "ping"}, self.service)
        assert response is not None
        self.assertEqual(response["result"], {})

    def test_unknown_method_is_jsonrpc_error(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"}, self.service)
        assert response is not None
        self.assertEqual(response["error"]["code"], -32601)

    def test_unknown_tool_reports_in_text(self) -> None:
        response = mcp.handle(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            self.service,
        )
        assert response is not None
        self.assertIn("未知工具", response["result"]["content"][0]["text"])

    def test_tool_error_becomes_iserror_not_disconnect(self) -> None:
        response = mcp.handle(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "card", "arguments": {"session_id": "session-nope"}},
            },
            self.service,
        )
        assert response is not None
        self.assertTrue(response["result"]["isError"])

    def test_every_tool_callable_shape(self) -> None:
        # 每个工具都要能拿到调用（缺参数时返回 isError 而不是抛异常）
        for tool in mcp.TOOLS:
            response = mcp.handle(
                {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": tool.name, "arguments": {}}},
                self.service,
            )
            assert response is not None
            self.assertIn("content", response["result"], tool.name)


class ServeTest(unittest.TestCase):
    def test_line_protocol_round_trip(self) -> None:
        import io

        service = make_service(self)
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            + "\n"
            + "not json\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            + "\n"
        )
        stdout = io.StringIO()
        code = mcp.serve(service.config_path, stdin=stdin, stdout=stdout)
        self.assertEqual(code, 0)
        lines = [l for l in stdout.getvalue().split("\n") if l.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["id"], 2)


class ProposalDraftToolTest(unittest.TestCase):
    """MCP proposal_draft：只创建提案，绝不创建正式任务（§5.3 铁律）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        home = fixtures.build_dsh_home(self.base / "dsh")
        self.library = self.base / "wm"
        self.library.mkdir()
        self.config_path = self.base / "pm.toml"
        self.config_path.write_text(
            fixtures.fixture_config_toml(library=str(self.library)).replace("REPLACED", str(home)),
            encoding="utf-8",
        )
        self.service = mcp.Service(str(self.config_path))
        self.tasks_file = self.library / "projects" / "proj-alpha_beta" / "tasks.org"

    def draft(self, **overrides):
        captured = mcp.capture_text(
            self.library, "验证计划的输入范围要先定", source="cli", model="cli",
            project_hint="demo",
        )
        args = {
            "sourceInboxId": captured.inbox_id,
            "project": "alpha_beta",
            "title": "明确验证计划输入范围",
            "changes": [{"op": "新增", "title": "明确输入范围", "criteria": ["列出输入版本"]}],
            "risks": ["尚未确认参考模型 revision"],
            "actions": ["批准后创建任务"],
        }
        args.update(overrides)
        return mcp.tool_proposal_draft(self.service, args)

    def test_tools_list_advertises_the_constraint(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, self.service)
        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        self.assertIn("proposal_draft", tools)
        self.assertIn("绝不创建正式任务", tools["proposal_draft"]["description"])

    def test_draft_writes_proposal_and_leaves_tasks_untouched(self) -> None:
        before = self.tasks_file.read_bytes() if self.tasks_file.is_file() else None
        payload = json.loads(self.draft())
        for key in ("entityId", "revision", "source", "observedAt", "auditEventId", "status", "path"):
            self.assertIn(key, payload)
        self.assertEqual(payload["source"], "org")
        self.assertEqual(payload["status"], "PENDING")
        self.assertEqual(payload["path"], "proposals.org")
        self.assertRegex(payload["entityId"], r"^proposal-[0-9A-HJKMNP-TV-Z]{26}$")

        proposals = (self.library / "proposals.org").read_text(encoding="utf-8")
        self.assertIn(payload["entityId"], proposals)
        self.assertIn("明确验证计划输入范围", proposals)
        self.assertIn("列出输入版本", proposals)

        after = self.tasks_file.read_bytes() if self.tasks_file.is_file() else None
        self.assertEqual(before, after, "提案工具绝不能改 tasks.org")
        self.assertFalse(self.tasks_file.is_file(), "MCP 提案工具不得创建 tasks.org")

    def test_unknown_source_inbox_is_rejected(self) -> None:
        with self.assertRaises(mcp.ToolError) as ctx:
            self.draft(sourceInboxId="inbox-does-not-exist")
        self.assertIn("[NOT_FOUND]", str(ctx.exception))
        self.assertFalse((self.library / "proposals.org").is_file(), "被拒时不写提案")

    def test_unknown_source_error_matches_cli(self) -> None:
        """错误码必须与 CLI 一致 —— 两边都走 proposals 模块的同一套校验。"""
        import contextlib
        import io

        from pm import cli

        (self.library / "inbox.org").write_text(
            "#+TITLE: Inbox\n\n* Inbox\n\n- 旧条目\n", encoding="utf-8"
        )
        with self.assertRaises(mcp.ToolError) as ctx:
            mcp.tool_proposal_draft(
                self.service, {"sourceInboxId": "inbox-nope", "changes": [{"op": "新增", "title": "x"}]}
            )
        self.assertIn("[NOT_FOUND]", str(ctx.exception))
        self.assertFalse((self.library / "proposals.org").is_file(), "被拒时不写提案")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(
                [
                    "--config", str(self.config_path),
                    "proposal", "create",
                    "--source-inbox", "inbox-nope",
                    "--change", "新增:x",
                    "--json",
                ]
            )
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "NOT_FOUND")

    def test_missing_changes_is_rejected(self) -> None:
        with self.assertRaises(mcp.ToolError):
            self.draft(changes=[])


if __name__ == "__main__":
    unittest.main()
