"""MCP `pm_recall`：只读记忆检索（P1 卡 task-01M52EY6S1R54AN3SQP4NY4A1Q）。

判据：
  0. 工具注册 + 手工调用返回命中（带 path:line）；
  1. 参数与 `pm recall --help` **对齐**（含必填集一致 ⇒ P0 改 flag 时会红，不会静默漂移）；
  2. 缺 query ⇒ 明确报错；
  3. 只读：人类文件（*.org）一字不变（派生索引落 .local/ 允许）。
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import unittest
from pathlib import Path

from pm import mcp, tasks

from test_mcp import make_service

TOKEN = "mcp-recall-probe-token"


def _pm(config: Path, *argv: str) -> tuple:
    p = subprocess.run(["./bin/pm", "--config", str(config), *argv], capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def _snapshot(lib: Path) -> dict:
    return {str(p.relative_to(lib)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(lib.rglob("*")) if p.is_file()}


class McpRecallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = make_service(self)
        self.config = Path(self.service.config_path)
        self.library = Path(self.service.config.library)
        code, out, err = _pm(self.config, "init", "--root", str(self.library), "--no-git")
        self.assertEqual(code, 0, err)
        code, out, err = _pm(self.config, "memory", "add", "--text", TOKEN + " 记忆检索 MCP 验收片段",
                             "--scope", "project", "--type", "fact", "--sources", "verify",
                             "--reason", "MCP 验收夹具", "--json")
        self.assertEqual(code, 0, err)
        memory_id = json.loads(out)["memoryId"]
        code, out, err = _pm(self.config, "memory", "verify", memory_id, "--actor", "human",
                             "--expected-revision", "1", "--json")
        self.assertEqual(code, 0, err)
        self.assertTrue((self.library / "memory" / "facts.org").is_file())

    def spec(self) -> mcp.ToolSpec:
        for spec in mcp.TOOLS:
            if spec.name == "pm_recall":
                return spec
        self.fail("MCP 工具列表里没有 pm_recall")

    def test_tool_registered_query_required(self) -> None:
        spec = self.spec()
        self.assertEqual(spec.input_schema["required"], ["query"])
        for key in ("query", "scope", "type", "limit", "include_candidate", "include_deprecated"):
            self.assertIn(key, spec.input_schema["properties"])

    def test_schema_aligns_with_cli_flags(self) -> None:
        """与 `pm recall --help` 对齐：必填集与可选 flag 都要有对应参数（漂移即红）。"""
        code, help_text, err = _pm(self.config, "recall", "--help")
        self.assertEqual(code, 0, err)
        usage = help_text.split("options:")[0]
        depth, required, optional = 0, set(), set()
        for token in re.findall(r"\[|\]|--[a-z-]+", usage):
            if token == "[":
                depth += 1
            elif token == "]":
                depth -= 1
            elif token.startswith("--"):
                flag = token[2:]
                if flag in ("help", "json", "config", "dsh-home"):
                    continue
                (required if depth == 0 else optional).add(flag)

        def as_param(flag: str) -> str:
            return flag.replace("-", "_")

        self.assertEqual({as_param(f) for f in required}, {"query"}, "CLI 必填集应为 query")
        schema_keys = set(self.spec().input_schema["properties"])
        missing = [as_param(f) for f in (required | optional) if as_param(f) not in schema_keys]
        self.assertEqual(missing, [], "MCP 参数漏了 CLI flag：" + ", ".join(missing))

    def test_manual_call_returns_path_line(self) -> None:
        text = mcp.tool_pm_recall(self.service, {"query": TOKEN})
        self.assertIn("命中 1 条", text, text)
        self.assertIn("memory/facts.org:", text, text)
        self.assertIn(TOKEN, text)
        self.assertRegex(text, r"memory/facts\.org:\d+\tfact\tVERIFIED")

    def test_missing_query_is_explicit_error(self) -> None:
        with self.assertRaises(mcp.ToolError) as raised:
            mcp.tool_pm_recall(self.service, {})
        self.assertIn("query", str(raised.exception))

    def test_read_only_human_files_untouched(self) -> None:
        before = _snapshot(self.library)
        mcp.tool_pm_recall(self.service, {"query": TOKEN})
        after = _snapshot(self.library)
        human = [k for k in set(before) | set(after)
                 if before.get(k) != after.get(k) and k.endswith(".org")]
        self.assertEqual(human, [], "recall 不该改人类文件")
        changed = [k for k in set(before) | set(after) if before.get(k) != after.get(k)]
        self.assertTrue(all(k.startswith(".local/") for k in changed),
                        "非 org 的变化只允许落在 .local/：" + repr(changed))

    def test_scope_and_limit_are_transparent(self) -> None:
        hit = mcp.tool_pm_recall(self.service, {"query": TOKEN, "limit": 1, "scope": "project"})
        self.assertIn("命中 1 条", hit)
        miss = mcp.tool_pm_recall(self.service, {"query": TOKEN, "scope": "definitely-not-a-scope"})
        self.assertIn("命中 0 条", miss)
        self.assertIn("0 命中", miss)


if __name__ == "__main__":
    unittest.main()
