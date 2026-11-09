"""tests/test_index_readonly.py —— **只读环境电池**（Lead 2026-10-18 复现的发布前缺口）。

机制：只读环境（会话沙箱把库置为不可写）下，普通 sqlite 连接会尝试建 journal/WAL/shm 或加写锁
⇒ OperationalError ⇒ hook 的 fail-safe 吞掉 ⇒ **静默零注入** ✗；CLI 面则抛 traceback ✗。
修法：① 严格只读连接（mode=ro&immutable=1 + query_only）；② 索引层**直读回退 org-scan**（同口径、排序不同、如实标注）；
      ③ CLI 把 sqlite 错误翻成人话（不抛 traceback）。

判据（对应 Lead 的 C-ro 四条）：
  ① 库 chmod -R a-w ⇒ hook **bytes>0** 且不抛异常；
  ② 同场景 CLI **无 traceback**（rc 0 + 有结果）；
  ③ 再加"没有索引"⇒ 仍能出结果（org-scan），且**对原库零写入**（无 sidecar）；
  ④ trace sink 写不进去也不能影响 hook（留痕失败只吞，不冒成非零）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pm import hooks, index
from pm.config import HooksConfig
from pm.layout import Layout

MEMORY = """* Facts
** 代码评审时最容易漏掉的检查
   :PROPERTIES:
   :ID: memory-ro-001
   :PM_STATUS: VERIFIED
   :PM_SCOPE: demo01
   :PM_TYPE: fact
   :PM_REVISION: 1
   :END:
   代码评审时最容易漏掉的检查：口令 = MAPLE-3c9d1e。
"""


def _freeze(root: Path) -> None:
    """把整棵库目录变成只读（模拟会话沙箱）。"""
    for path in sorted(root.rglob("*"), reverse=True):
        mode = path.stat().st_mode
        path.chmod(mode & ~0o222)
    root.chmod(root.stat().st_mode & ~0o222)


def _thaw(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        try:
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
        except OSError:
            pass
    try:
        root.chmod(root.stat().st_mode | stat.S_IWUSR)
    except OSError:
        pass


@unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root 会绕过只读位，判据在这没意义")
class ReadOnlyLibraryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "memory").mkdir(parents=True)
        (self.root / "memory" / "facts.org").write_text(MEMORY, encoding="utf-8")
        (self.root / "pm.toml").write_text('library = "' + str(self.root) + '"\n', encoding="utf-8")
        self.layout = Layout(self.root)
        index._FTS5_CACHE = None
        index.build(self.root, rebuild=True)          # 先正常建好索引（冻结后它只读可查）
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(_thaw, self.root)

    def _fingerprint(self) -> str:
        parts = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                parts.append(str(path.relative_to(self.root)) + ":" + hashlib.sha256(path.read_bytes()).hexdigest())
        return "|".join(parts)

    def test_readonly_library_hook_still_injects(self) -> None:
        """① 库只读 ⇒ hook 仍必须出结果（不是静默 0 字节）。"""
        _freeze(self.root)
        info: dict = {}
        text = hooks.recall_text(self.layout, HooksConfig(), prompt="代码评审时最容易漏掉的检查", query_out=info)
        self.assertTrue(text, "只读库下 hook 不能零注入")
        self.assertIn("MAPLE-3c9d1e", text)
        # 可解释性走结构化面（--json/trace），不混进给模型看的正文：
        self.assertTrue(info.get("readOnlyFallback"), "必须记录走了只读回退：" + repr(info))

    def test_readonly_library_is_not_written(self) -> None:
        """只读库跑 recall 后，库内文件集合与内容一字不变（无 journal/WAL/shm）。"""
        _freeze(self.root)
        before = self._fingerprint()
        index.recall(self.root, "代码评审时最容易漏掉的检查")
        index.recall(self.root, "代码评审时最容易漏掉的检查")
        self.assertEqual(self._fingerprint(), before)
        self.assertEqual([p.name for p in (self.root / ".local").glob("*.sqlite-*")], [])

    def test_org_scan_when_index_missing(self) -> None:
        """③ 没有索引 + 库只读 ⇒ 走 org-scan 直读，仍命中且标注 how。"""
        shutil.rmtree(self.root / ".local", ignore_errors=True)
        _freeze(self.root)
        result = index.recall(self.root, "代码评审时最容易漏掉的检查")
        self.assertEqual(result["mode"], "org-scan")
        self.assertGreaterEqual(result["count"], 1)
        self.assertIn("MAPLE-3c9d1e", result["hits"][0]["snippet"])
        self.assertTrue(result["readOnlyFallback"])
        self.assertIn("org-scan", result["note"])

    def test_cli_readonly_has_no_traceback(self) -> None:
        """② CLI 在只读库下要么给结果、要么给人话 —— 不许 traceback。"""
        _freeze(self.root)
        env = {k: v for k, v in os.environ.items() if k not in ("DSH_UI_PM_CONFIG", "PM_CONFIG", "PM_DSH_HOME")}
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
        proc = subprocess.run([sys.executable, "-m", "pm", "recall", "--query", "代码评审时最容易漏掉的检查",
                               "--config", str(self.root / "pm.toml"), "--json"],
                              capture_output=True, text=True, env=env, cwd=str(Path(__file__).resolve().parent.parent))
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("MAPLE-3c9d1e", proc.stdout)

    def test_readonly_query_failure_falls_back_to_org_scan(self) -> None:
        """**索引在、但只读查询失败** ⇒ 仍必须并入 org-scan（Lead 2026-10-18 的怀疑点）。

        这条与"无索引 ⇒ org-scan"不同：那里连索引都没有；这里索引已建好、只读打开也成功，
        只是查询跑不动（严格沙箱里 FTS 可能需要临时结构）⇒ 不能让它冒成静默零注入。
        """
        import sqlite3
        import unittest.mock as mock

        with mock.patch.object(index, "_dir_writable", return_value=False), \
             mock.patch.object(index, "probe_read_only",
                               side_effect=sqlite3.OperationalError("attempt to write a readonly database")):
            result = index.recall(self.root, "代码评审时最容易漏掉的检查")
        self.assertEqual(result["mode"], "org-scan")
        self.assertGreaterEqual(result["count"], 1)
        self.assertIn("只读查询失败", result["readOnlyFallback"] or "")

    def test_hook_json_exposes_readonly_fallback(self) -> None:
        """观测面：hook 的 --json 必须能看到 mode / readOnlyFallback（否则"为什么 0 字节"没法定位）。"""
        _freeze(self.root)
        env = {k: v for k, v in os.environ.items() if k not in ("DSH_UI_PM_CONFIG", "PM_CONFIG", "PM_DSH_HOME")}
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
        proc = subprocess.run([sys.executable, "-m", "pm", "hook", "recall", "--config", str(self.root / "pm.toml"), "--json"],
                              input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "代码评审时最容易漏掉的检查"}),
                              capture_output=True, text=True, env=env, cwd=str(Path(__file__).resolve().parent.parent))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        line = [l for l in proc.stdout.splitlines() if l.startswith("{")]
        self.assertTrue(line, proc.stdout)
        payload = json.loads(line[-1])
        self.assertTrue(payload["injected"], payload)
        self.assertTrue(payload.get("readOnlyFallback"), payload)

    def test_trace_failure_never_breaks_hook(self) -> None:
        """④ 留痕 sink 写不进去（只读）也不能影响 hook：只吞，不冒成非零。"""
        sink = Path(tempfile.mkdtemp(prefix="pm-trace-ro-"))
        (sink / ".local").mkdir()
        (sink / ".local" / "hook-trace.enabled").write_text("", encoding="utf-8")
        _freeze(sink)
        original = hooks.repo_root
        hooks.repo_root = lambda: sink          # type: ignore[assignment]
        try:
            hooks.trace_best_effort("recall", {"prompt": "x"}, "out")   # 不应抛
        finally:
            hooks.repo_root = original          # type: ignore[assignment]
            _thaw(sink)
            shutil.rmtree(sink, ignore_errors=True)
        text = hooks.recall_text(self.layout, HooksConfig(), prompt="代码评审时最容易漏掉的检查")
        self.assertIn("MAPLE-3c9d1e", text)


if __name__ == "__main__":
    unittest.main()
