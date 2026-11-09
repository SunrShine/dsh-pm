from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from pm import cli
from pm.config import derive_source_instance

import fixtures


class ScanCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = fixtures.build_dsh_home(Path(self._tmp.name))
        self.config = Path(self._tmp.name) / "pm.toml"
        self.config.write_text(
            fixtures.fixture_config_toml().replace("REPLACED", str(self.home)), encoding="utf-8"
        )

    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_json_all(self) -> None:
        code, stdout, _ = self.run_cli(
            ["--config", str(self.config), "scan", "--all", "--json", "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["stats"]["workspaces"], 5)
        self.assertEqual(payload["stats"]["agents_total"], 8)
        self.assertEqual(payload["stats"]["unregistered"], 1)
        self.assertEqual(payload["stats"]["ignored"], 1)
        self.assertEqual(payload["stats"]["agents_shown"], 6)
        self.assertEqual([p["key"] for p in payload["projects"]], ["alpha_beta"])

    def test_default_filter_reduces_rows(self) -> None:
        code, stdout, _ = self.run_cli(
            ["--config", str(self.config), "scan", "--json", "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertLessEqual(payload["stats"]["agents_shown"], 6)
        self.assertGreaterEqual(payload["stats"]["agents_hidden"], 2)

    def test_text_output_contains_project_title(self) -> None:
        code, stdout, _ = self.run_cli(
            ["--config", str(self.config), "scan", "--no-color", "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 0)
        self.assertIn("Alpha Beta", stdout)

    def test_unknown_project_exits_nonzero(self) -> None:
        code, _, stderr = self.run_cli(
            ["--config", str(self.config), "scan", "--project", "nope", "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 2)
        self.assertIn("未知项目", stderr)

    def test_strict_exits_nonzero_on_unsupported_source(self) -> None:
        code, _, stderr = self.run_cli(
            ["--config", str(self.config), "scan", "--json", "--strict", "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 3)
        self.assertIn("未经验证", stderr)

    def test_prompt_text_is_hidden_by_default(self) -> None:
        _, plain, _ = self.run_cli(
            ["--config", str(self.config), "scan", "--json", "--all", "--dsh-home", str(self.home)]
        )
        payload = json.loads(plain)
        agents = [a for p in payload["projects"] for a in p["agents"]]
        flagged = [a for a in agents if a["recent_action_from_prompt"]]
        self.assertTrue(flagged, "夹具里应当有仅来自对话正文的动作")
        for agent in agents:
            self.assertEqual(agent["runtime_status"], "unknown")
            self.assertEqual(agent["summary_status"], "not_generated")

    def test_scan_reflects_summaries_written_into_the_library(self) -> None:
        """回归：曾出现 scan 说「全部缺摘要」、看板却说 30/88 有摘要的矛盾。

        根因是 scan 不知道库在哪，于是读不到 ai-summaries.org。
        """
        library = Path(self._tmp.name) / "wm"
        library.mkdir()
        instance = derive_source_instance(self.home)
        sid = fixtures.ALPHA_RECENT
        (library / "ai-summaries.org").write_text(
            "#+TITLE: AI\n\n* AI 摘要\n** " + sid + "\n"
            "   :PROPERTIES:\n"
            "   :PM_SESSION: " + sid + "\n"
            "   :PM_SOURCE_INSTANCE: " + instance + "\n"
            "   :PM_SUMMARY_SOURCE: ai\n"
            "   :END:\n"
            "   库里的摘要\n",
            encoding="utf-8",
        )
        config_path = Path(self._tmp.name) / "pm_lib.toml"
        config_path.write_text(
            fixtures.fixture_config_toml(library=str(library)).replace("REPLACED", str(self.home)),
            encoding="utf-8",
        )

        code, stdout, _ = self.run_cli(
            ["--config", str(config_path), "scan", "--all", "--json", "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        agents = [a for p in payload["projects"] for a in p["agents"]]
        target = next(a for a in agents if a["session_id"] == sid)
        self.assertEqual(target["summary_status"], "ai")
        self.assertEqual(target["summary"], "库里的摘要")

    def test_no_subcommand_prints_help_to_stderr(self) -> None:
        """usage 一律走 stderr：--json 调用方要直接解析 stdout（task-10）。"""
        code, stdout, stderr = self.run_cli([])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "", "stdout 不能混入帮助文本")
        self.assertIn("usage", stderr.lower())


class MissingDshTest(unittest.TestCase):
    def test_missing_dsh_home_still_renders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["scan", "--no-color", "--dsh-home", str(Path(tmp) / "nope")])
            self.assertEqual(code, 0)
            self.assertIn("工作卡", out.getvalue())


if __name__ == "__main__":
    unittest.main()
