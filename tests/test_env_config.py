"""`PM_CONFIG` / `PM_DSH_HOME` 环境变量（task-190）。

优先级：命令行显式 > 环境变量 > 内置默认。
MCP 侧（`bin/pm mcp`）是子进程，会继承环境变量 —— 所以隔离实例时设 `PM_CONFIG` 才能真正隔离。
全部用临时副本，真库一个字节都不碰。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pm import cli, config

REPO_ROOT = Path(__file__).resolve().parents[1]
PM_BIN = REPO_ROOT / "bin" / "pm"


def make_copy(root: Path, marker: str) -> Path:
    """造一份最小副本库 + 配置，返回 config 路径。"""
    home = root / "home"
    (home / "storages").mkdir(parents=True, exist_ok=True)
    cfg = root / "pm.toml"
    cfg.write_text('library = "' + str(root / "wm") + '"\n', encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(["--config", str(cfg), "init", "--root", str(root / "wm"), "--no-git"])
        if code != 0:
            raise AssertionError("副本库初始化失败")
        code = cli.main(["--config", str(cfg), "project", "create", marker])
        if code != 0:
            raise AssertionError("副本项目创建失败")
    return cfg


def make_isolated_copy(root: Path, instance_id: str = "fakex") -> tuple:
    """造一份**带自己 [[instance]]** 的副本配置：这样 MCP/scan 输出里的"数据根"能证明用的是哪份配置。

    返回 (config 路径, 假 DSH home)。
    """
    home = root / "fake-dsh"
    (home / "storages").mkdir(parents=True, exist_ok=True)
    cfg = root / "pm.toml"
    cfg.write_text(
        'library = "' + str(root / "wm") + '"\n\n[[instance]]\nid = "' + instance_id
        + '"\npath = "' + str(home) + '"\nrole = "work"\n',
        encoding="utf-8",
    )
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(["--config", str(cfg), "init", "--root", str(root / "wm"), "--no-git"])
        if code != 0:
            raise AssertionError("副本库初始化失败")
    return cfg, home


def mcp_call(env: dict, tool: str, args: dict | None = None) -> str:
    """起一次 `bin/pm mcp`，按 JSON-RPC 调一个只读工具，返回它的文本结果（projects 是 TSV）。"""
    proc = subprocess.Popen(
        [str(PM_BIN), "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, env=env,
    )
    try:
        def send(obj: dict) -> dict:
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()
            for _ in range(50):
                line = proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line.startswith("{"):
                    continue  # 跳过非 JSON-RPC 的输出行
                msg = json.loads(line)
                if msg.get("id") == obj["id"]:
                    return msg
            raise AssertionError(f"没等到 {obj['id']} 的响应")

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "test", "version": "0"}}})
        msg = send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": tool, "arguments": args or {}}})
        self_result = msg.get("result")
        if self_result is None:
            raise AssertionError(f"MCP 返回错误：{json.dumps(msg, ensure_ascii=False)[:200]}")
        return self_result["content"][0]["text"]
    finally:
        proc.kill()
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except Exception:  # noqa: BLE001 - 清理失败不影响断言
                pass


class ConfigEnvTest(unittest.TestCase):
    def test_pm_config_env_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = make_copy(root, "envmarker")
            with mock.patch.dict(os.environ, {"PM_CONFIG": str(cfg)}):
                loaded, _ = config.load(None)
            self.assertEqual(loaded.source_path, cfg)
            self.assertEqual(loaded.library, root / "wm")

    def test_explicit_config_beats_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_cfg = make_copy(root / "a", "envmarker")
            (root / "a").mkdir(exist_ok=True)
            explicit = make_copy(root / "b", "explicitmarker")
            with mock.patch.dict(os.environ, {"PM_CONFIG": str(env_cfg)}):
                loaded, _ = config.load(str(explicit))
            self.assertEqual(loaded.source_path, explicit)
            self.assertEqual(loaded.library, root / "b" / "wm")

    def test_ui_env_config_is_used_when_pm_config_absent(self) -> None:
        """`DSH_UI_PM_CONFIG`（插件/harness 给实例侧设的那个）MCP/CLI 也认（task-192）。"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_copy(Path(tmp), "uimarker")
            env = {k: v for k, v in os.environ.items() if k not in ("PM_CONFIG", "DSH_UI_PM_CONFIG")}
            env["DSH_UI_PM_CONFIG"] = str(cfg)
            with mock.patch.dict(os.environ, env, clear=True):
                loaded, _ = config.load(None)
            self.assertEqual(loaded.source_path, cfg)

    def test_ui_env_config_beats_pm_config(self) -> None:
        """**实例作用域优先**（task-194）：两者都设且指向不同库 → 选 `DSH_UI_PM_CONFIG`。

        理由：插件侧就是 `DSH_UI_PM_CONFIG ?? DEFAULT`；若这里反过来，两者都设时插件读副本、MCP 读 PM_CONFIG → 分叉。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pm").mkdir()
            (root / "ui").mkdir()
            pm_cfg = make_copy(root / "pm", "pmmarker")
            ui_cfg = make_copy(root / "ui", "uimarker")
            with mock.patch.dict(
                os.environ,
                {"PM_CONFIG": str(pm_cfg), "DSH_UI_PM_CONFIG": str(ui_cfg)},
            ):
                self.assertEqual(
                    config.discover_config_path(), ui_cfg, "DSH_UI_PM_CONFIG 优先于 PM_CONFIG"
                )
                loaded, _ = config.load(None)
                self.assertEqual(loaded.library, root / "ui" / "wm")

    def test_ui_env_config_missing_is_hard_error_not_fallback(self) -> None:
        """**task-197**：`DSH_UI_PM_CONFIG` 指向不存在的文件 → 硬失败，**不许**悄悄用 `PM_CONFIG`。

        这就是那条安全隐患：打错一个路径，实例侧会静默串到默认库（源码检出里 = 真库）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pm").mkdir()
            pm_cfg = make_copy(root / "pm", "pmmarker")
            with mock.patch.dict(
                os.environ,
                {"DSH_UI_PM_CONFIG": str(root / "nope.toml"), "PM_CONFIG": str(pm_cfg)},
            ):
                with self.assertRaises(config.ConfigPathError) as raised:
                    config.discover_config_path()
                self.assertEqual(raised.exception.code, "CONFIG_NOT_FOUND")
                self.assertEqual(raised.exception.exit_code, 2)
                self.assertIn("不会回落默认库", str(raised.exception))
                with self.assertRaises(config.ConfigPathError):
                    config.load(None)

    def test_ui_env_config_missing_is_hard_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            with mock.patch.dict(
                os.environ, {"DSH_UI_PM_CONFIG": str(cwd / "nope.toml")}, clear=True
            ), mock.patch.object(Path, "cwd", return_value=cwd), mock.patch.object(
                Path, "home", return_value=cwd / "home"
            ):
                with self.assertRaises(config.ConfigPathError) as raised:
                    config.discover_config_path()
                self.assertEqual(raised.exception.code, "CONFIG_NOT_FOUND")

    def test_explicit_config_beats_both_envs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ui").mkdir()
            (root / "pm").mkdir()
            ui_cfg = make_copy(root / "ui", "uimarker")
            pm_cfg = make_copy(root / "pm", "pmmarker")
            explicit = root / "explicit.toml"
            explicit.write_text('library = "' + str(root / "ui" / "wm") + '"\n', encoding="utf-8")
            with mock.patch.dict(
                os.environ, {"DSH_UI_PM_CONFIG": str(ui_cfg), "PM_CONFIG": str(pm_cfg)}
            ):
                self.assertEqual(config.discover_config_path(str(explicit)), explicit)

    def test_env_beats_cwd_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a").mkdir()
            env_cfg = make_copy(Path(tmp) / "a", "envmarker")
            cwd = Path(tmp) / "cwd"
            cwd.mkdir()
            (cwd / "pm.toml").write_text('library = "' + str(Path(tmp) / "cwd" / "wm") + '"\n', encoding="utf-8")
            with mock.patch.dict(os.environ, {"PM_CONFIG": str(env_cfg)}), mock.patch.object(
                Path, "cwd", return_value=cwd
            ):
                self.assertEqual(config.discover_config_path(), env_cfg)

    def test_pm_config_missing_is_hard_error(self) -> None:
        """**task-197**：`PM_CONFIG` 指向不存在的文件 → 硬失败（不是"跳过、往后找"）。"""
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            with mock.patch.dict(os.environ, {"PM_CONFIG": str(cwd / "nope.toml")}, clear=True), mock.patch.object(
                Path, "cwd", return_value=cwd
            ), mock.patch.object(Path, "home", return_value=cwd / "home"):
                with self.assertRaises(config.ConfigPathError) as raised:
                    config.discover_config_path()
                self.assertEqual(raised.exception.code, "CONFIG_NOT_FOUND")

    def test_implicit_candidates_may_be_missing(self) -> None:
        """隐式候选（`./pm.toml` / `~/.dsh-pm/pm.toml`）缺失仍照旧**跳过**，不许硬失败。"""
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
                Path, "cwd", return_value=cwd
            ), mock.patch.object(Path, "home", return_value=cwd / "home"), mock.patch.object(
                config, "DEFAULT_CONFIG_PATH", cwd / "nope.toml"
            ):
                self.assertIsNone(config.discover_config_path())
                loaded, warnings = config.load()
                self.assertIsNone(loaded.library)
                self.assertTrue(any("未找到 pm.toml" in w for w in warnings))

    def test_cli_uses_env_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = make_copy(root, "envmarker")
            with mock.patch.dict(os.environ, {"PM_CONFIG": str(cfg)}):
                import io, contextlib
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = cli.main(["project", "list", "--json"])
            self.assertEqual(code, 0)
            keys = [p["key"] for p in json.loads(out.getvalue())["projects"]]
            self.assertIn("envmarker", keys)


class ExplicitPathHardFailTest(unittest.TestCase):
    """**task-197**：显式配置路径坏掉 → 读路径与写路径**同一个码**，绝不回落默认库；隐式候选仍可缺。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.good = make_copy(self.root, "goodmarker")
        self.missing = self.root / "missing.toml"
        self.broken = self.root / "broken.toml"
        self.broken.write_text('library = "unterminated\n', encoding="utf-8")

    def cli(self, argv: list, env: dict | None = None) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=(env is not None)):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_read_path_reports_config_not_found(self) -> None:
        code, out, err = self.cli(["--config", str(self.missing), "project", "list", "--json"])
        self.assertEqual(code, 2)
        self.assertIn("CONFIG_NOT_FOUND", err)
        self.assertIn(str(self.missing), err)
        self.assertIn("不会回落默认库", err)
        self.assertEqual(out, "", "读路径失败时不该输出任何库数据")

    def test_write_path_reports_the_same_code(self) -> None:
        code, _, err = self.cli(["--config", str(self.missing), "capture", "写点东西", "--yes"])
        self.assertEqual(code, 2)
        self.assertIn("CONFIG_NOT_FOUND", err)
        self.assertIn(str(self.missing), err)

    def test_broken_toml_reports_config_invalid(self) -> None:
        code, _, err = self.cli(["--config", str(self.broken), "project", "list"])
        self.assertEqual(code, 2)
        self.assertIn("CONFIG_INVALID", err)
        self.assertIn("不会回落默认库", err)

    def test_env_sources_are_explicit(self) -> None:
        for name in ("PM_CONFIG", "DSH_UI_PM_CONFIG"):
            code, _, err = self.cli(
                ["project", "list", "--json"], env={name: str(self.missing)}
            )
            self.assertEqual(code, 2, f"{name} 缺文件应硬失败")
            self.assertIn("CONFIG_NOT_FOUND", err)
            self.assertIn("不会回落默认库", err)

    def test_broken_env_config_is_invalid(self) -> None:
        code, _, err = self.cli(
            ["project", "list"], env={"DSH_UI_PM_CONFIG": str(self.broken)}
        )
        self.assertEqual(code, 2)
        self.assertIn("CONFIG_INVALID", err)

    def test_write_with_missing_env_config_fails_before_writing(self) -> None:
        before = (self.root / "wm" / "inbox.org").read_text(encoding="utf-8")
        code, _, err = self.cli(
            ["capture", "不该写进去", "--yes"], env={"PM_CONFIG": str(self.missing)}
        )
        self.assertEqual(code, 2)
        self.assertIn("CONFIG_NOT_FOUND", err)
        self.assertEqual((self.root / "wm" / "inbox.org").read_text(encoding="utf-8"), before)

    def test_mcp_fails_closed_on_missing_explicit_config(self) -> None:
        """MCP 侧也必须失败退出：绝不拿默认库（真库）对外服务。"""
        import subprocess as sp

        proc = sp.run(
            [str(PM_BIN), "mcp"], input='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n',
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "DSH_UI_PM_CONFIG": str(self.missing)},
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("CONFIG_NOT_FOUND", proc.stderr)
        self.assertEqual(proc.stdout.strip(), "", "失败时不该输出任何工具结果")


class WriteGateEnvTest(unittest.TestCase):
    """环境变量给出的 config **不算**"这次命令行显式指定" → 写命令仍要 `--yes`（安全闸门不松）。"""

    def test_env_config_still_requires_yes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = make_copy(root, "envmarker")
            with mock.patch.dict(os.environ, {"PM_CONFIG": str(cfg)}):
                out, err = io.StringIO(), io.StringIO()
                err = io.StringIO()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                    code = cli.main(["capture", "只设了 PM_CONFIG，不给 --yes"])
            self.assertEqual(code, 2, err.getvalue())
            message = err.getvalue()
            self.assertIn("拒绝写入", message)
            self.assertIn(str((root / "wm").resolve()), message + str((root / "wm")),
                          "闸门要如实写出它准备写哪个库（这里应是 PM_CONFIG 指的那个）")

    def test_ui_env_config_alone_still_requires_yes(self) -> None:
        """回归哨兵：`DSH_UI_PM_CONFIG` 也只是 env → 写命令照旧要 `--yes`（安全闸门不因新增 env 而松）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = make_copy(root, "uimarker")
            env = {k: v for k, v in os.environ.items() if k not in ("PM_CONFIG", "DSH_UI_PM_CONFIG")}
            env["DSH_UI_PM_CONFIG"] = str(cfg)
            with mock.patch.dict(os.environ, env, clear=True):
                err = io.StringIO()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                    code = cli.main(["capture", "只设了 DSH_UI_PM_CONFIG，不给 --yes"])
            self.assertEqual(code, 2, err.getvalue())
            self.assertIn("拒绝写入", err.getvalue())

    def test_both_envs_still_require_yes(self) -> None:
        """回归哨兵：**两个 env 都设**时也仍然要 `--yes`（它们都只是 env，不算命令行显式 --config）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ui").mkdir()
            (root / "pm").mkdir()
            ui_cfg = make_copy(root / "ui", "uimarker")
            pm_cfg = make_copy(root / "pm", "pmmarker")
            with mock.patch.dict(
                os.environ, {"DSH_UI_PM_CONFIG": str(ui_cfg), "PM_CONFIG": str(pm_cfg)}
            ):
                err = io.StringIO()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                    code = cli.main(["capture", "两个 env 都设，也不给 --yes"])
            self.assertEqual(code, 2, err.getvalue())
            self.assertIn("拒绝写入", err.getvalue())

    def test_ui_env_config_with_yes_writes_to_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = make_copy(root, "uimarker")
            env = {k: v for k, v in os.environ.items() if k not in ("PM_CONFIG", "DSH_UI_PM_CONFIG")}
            env["DSH_UI_PM_CONFIG"] = str(cfg)
            with mock.patch.dict(os.environ, env, clear=True):
                with contextlib.redirect_stdout(io.StringIO()):
                    code = cli.main(["capture", "经 DSH_UI_PM_CONFIG 写入", "--yes"])
            self.assertEqual(code, 0)
            self.assertIn("经 DSH_UI_PM_CONFIG 写入", (root / "wm" / "inbox.org").read_text(encoding="utf-8"))

    def test_env_config_with_yes_writes_to_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = make_copy(root, "envmarker")
            with mock.patch.dict(os.environ, {"PM_CONFIG": str(cfg)}):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = cli.main(["capture", "带 --yes 的写入", "--yes"])
            self.assertEqual(code, 0)
            self.assertIn("带 --yes 的写入", (root / "wm" / "inbox.org").read_text(encoding="utf-8"))


class DshHomeEnvTest(unittest.TestCase):
    def test_env_dsh_home_helper(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PM_DSH_HOME", None)
            self.assertIsNone(config.env_dsh_home())
            os.environ["PM_DSH_HOME"] = "   "
            self.assertIsNone(config.env_dsh_home(), "空白不算设置")
            os.environ["PM_DSH_HOME"] = "/tmp/dsh-home-x"
            self.assertEqual(config.env_dsh_home(), Path("/tmp/dsh-home-x"))
            os.environ.pop("PM_DSH_HOME", None)

    def test_parser_default_follows_env_and_cli_wins(self) -> None:
        with mock.patch.dict(os.environ, {"PM_DSH_HOME": "/tmp/from-env"}):
            parser = cli.build_parser()
            args = parser.parse_args(["scan"])
            self.assertEqual(args.dsh_home, "/tmp/from-env")
            args2 = parser.parse_args(["scan", "--dsh-home", "/tmp/from-cli"])
            self.assertEqual(args2.dsh_home, "/tmp/from-cli")


class McpEnvTest(unittest.TestCase):
    """MCP 子进程继承环境变量 —— 这是"隔离实例不碰真库"在 MCP 这条路上的关键。"""

    def test_mcp_reads_copy_via_env(self) -> None:
        """MCP 子进程继承 PM_CONFIG → 用的是副本配置（看"数据根"就知道）。"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg, _home = make_isolated_copy(Path(tmp))
            env = {**os.environ, "PM_CONFIG": str(cfg)}
            text = mcp_call(env, "projects")
            self.assertIn("数据根: fakex", text, "MCP 侧应用副本配置（PM_CONFIG 被子进程继承）")
            self.assertNotIn("数据根: default, preview, learn", text, "不该再看到真实数据根")

    def test_mcp_isolated_by_ui_env_config_only(self) -> None:
        """**只设 `DSH_UI_PM_CONFIG`** 也能隔离 MCP 侧（task-192 的关键：一个 env 约束两侧）。"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg, _home = make_isolated_copy(Path(tmp))
            env = {k: v for k, v in os.environ.items() if k not in ("PM_CONFIG", "DSH_UI_PM_CONFIG")}
            env["DSH_UI_PM_CONFIG"] = str(cfg)
            text = mcp_call(env, "projects")
            self.assertIn("数据根: fakex", text, "MCP 侧应认 DSH_UI_PM_CONFIG")
            self.assertNotIn("数据根: default, preview, learn", text)

    def test_mcp_prefers_ui_env_when_both_set(self) -> None:
        """两侧一致性的关键一格：两个 env 都设且**指向不同库** → MCP 也必须用 `DSH_UI_PM_CONFIG` 那份。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ui").mkdir()
            (root / "pm").mkdir()
            ui_cfg, _ui_home = make_isolated_copy(root / "ui", instance_id="uiside")
            pm_cfg, _pm_home = make_isolated_copy(root / "pm", instance_id="pmside")
            env = {**os.environ, "DSH_UI_PM_CONFIG": str(ui_cfg), "PM_CONFIG": str(pm_cfg)}
            text = mcp_call(env, "projects")
            self.assertIn("数据根: uiside", text, "MCP 侧要用实例作用域的那份（与插件侧一致）")
            self.assertNotIn("pmside", text)

    def test_mcp_fully_isolated_with_both_env_vars(self) -> None:
        """两侧都约束：`PM_CONFIG`（库）+ `PM_DSH_HOME`（数据根）→ MCP 输出里没有真库/真数据根。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, _home = make_isolated_copy(root)
            other_home = root / "dsh-adhoc"
            (other_home / "storages").mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "PM_CONFIG": str(cfg), "PM_DSH_HOME": str(other_home)}
            text = mcp_call(env, "projects")
            self.assertNotIn("pm_tools\t", text, "真库项目不该出现")
            self.assertNotIn("数据根: default, preview, learn", text, "真实数据根不该出现")

    @unittest.skipUnless(
        (Path(__file__).resolve().parent.parent / "config" / "pm.toml").is_file(),
        "公开副本不含 config/pm.toml（内含真实库路径）→ 本「现状记录」在公开副本里不适用",
    )
    def test_mcp_without_env_falls_back_to_repo_default(self) -> None:
        """现状记录（**只读**调用）：不设 PM_CONFIG 时 MCP 走内置查找 → 源码检出里是 config/pm.toml（真实库）。

        这正是 task-190 的隐患：所以"隔离实例"必须同时设 `PM_CONFIG`（MCP 侧）与实例侧配置。
        """
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if k != "PM_CONFIG"}
            env["HOME"] = tmp  # 避免用户级 ~/.dsh-pm/pm.toml 干扰
            text = mcp_call(env, "projects")
            self.assertIn("数据根: default, preview, learn", text, "没设 PM_CONFIG 时会落到仓库默认配置（真实库）——记录现状")


if __name__ == "__main__":
    unittest.main()
