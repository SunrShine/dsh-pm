"""tests/test_hook_prompt_delivery.py —— SessionStart 投递 prompt.org 的 c1–c6 判据。

依据：用户 2026-10-19 裁定「这批一起上」+ Lead 冻结规格。
  c1 token 句端到端 · c2 无记录负例 · c3 只读指纹 · c4 三态+预算不变量 ·
  c5 三段回退且绝不回退全库 · c6 prompt=false 与今天逐字节一致。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pm import hooks, index
from pm.config import HooksConfig
from pm.layout import Layout

NL = chr(10)
QUOTE = chr(34)
TOKEN = "DELIVER-9f8e7d"


def make_library(root: Path, *, with_prompt: bool = True, with_memory: bool = True,
                 prompt_body: str | None = None) -> Layout:
    (root / "memory").mkdir(parents=True, exist_ok=True)
    (root / "ws-demo01").mkdir(parents=True, exist_ok=True)
    (root / "ws-beta").mkdir(parents=True, exist_ok=True)
    proj = root / "projects" / "proj-demo01"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "project.org").write_text("#+TITLE: demo01" + NL + "#+PM_PATH: " + str(root / "ws-demo01") + NL, encoding="utf-8")
    beta = root / "projects" / "proj-beta"
    beta.mkdir(parents=True, exist_ok=True)
    (beta / "project.org").write_text("#+TITLE: beta" + NL + "#+PM_PATH: " + str(root / "ws-beta") + NL, encoding="utf-8")
    if with_memory:
        facts = ["* Facts", "** 事实", "   :PROPERTIES:", "   :ID: m1", "   :PM_STATUS: VERIFIED",
                 "   :PM_SCOPE: demo01", "   :PM_TYPE: fact", "   :PM_REVISION: 1", "   :END:", "   记忆正文", ""]
        (root / "memory" / "facts.org").write_text(NL.join(facts), encoding="utf-8")
    if with_prompt:
        body = prompt_body if prompt_body is not None else "** 背景" + NL + "人写提示词 " + TOKEN + NL
        doc = "#+TITLE: demo01 · 初始系统提示词" + NL + "#+PM_SCOPE: demo01" + NL + NL + body
        (proj / "prompt.org").write_text(doc, encoding="utf-8")
    index._FTS5_CACHE = None
    return Layout(root)


class PromptDeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_c1_token_sentence_end_to_end(self) -> None:
        """c1：prompt.org 里的令牌必须经 SessionStart 通路到达输出（含 CLI 信封）。"""
        layout = make_library(self.root)
        text = hooks.session_start_text(layout, HooksConfig(), scope="demo01")
        self.assertIn(TOKEN, text)
        self.assertIn("[pm-memory prompt scope=demo01 source=projects/proj-demo01/prompt.org", text)
        (self.root / "pm.toml").write_text("library = " + QUOTE + str(self.root) + QUOTE + NL, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in ("DSH_UI_PM_CONFIG", "PM_CONFIG", "PM_DSH_HOME")}
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
        proc = subprocess.run([sys.executable, "-m", "pm", "hook", "session-start", "--format", "claude-code",
                               "--config", str(self.root / "pm.toml")],
                              input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(self.root / "ws-demo01")}),
                              capture_output=True, text=True, env=env,
                              cwd=str(Path(__file__).resolve().parent.parent))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertIn(TOKEN, payload["hookSpecificOutput"]["additionalContext"])

    def test_c2_no_prompt_is_unchanged_negative(self) -> None:
        """c2：没有 prompt.org ⇒ 提示词节不出现；记忆也没有 ⇒ 零输出。"""
        layout = make_library(self.root, with_prompt=False)
        text = hooks.session_start_text(layout, HooksConfig(), scope="demo01")
        self.assertTrue(text)
        self.assertNotIn("[pm-memory prompt", text)
        empty_root = Path(tempfile.mkdtemp())
        make_library(empty_root, with_prompt=False, with_memory=False)
        self.assertEqual(hooks.session_start_text(Layout(empty_root), HooksConfig(), scope="demo01"), "")

    def test_c3_read_only(self) -> None:
        """c3：投递只读 —— 跑前跑后库内 *.org 指纹不变。"""
        layout = make_library(self.root)
        def fingerprint() -> str:
            parts = []
            for path in sorted(self.root.rglob("*.org")):
                parts.append(str(path.relative_to(self.root)) + ":" + hashlib.sha256(path.read_bytes()).hexdigest())
            return "|".join(parts)
        before = fingerprint()
        hooks.session_start_text(layout, HooksConfig(), scope="demo01")
        hooks.session_start_text(layout, HooksConfig(prompt=False), scope="demo01")
        self.assertEqual(fingerprint(), before)

    def test_c4_three_states_and_budget_invariant(self) -> None:
        """c4：全文 / 截断（<= budget 且标注数字=最终预算）/ 不出节（含原因）。"""
        long_body = "** 背景" + NL + ("很长的提示词正文" * 40) + NL
        layout = make_library(self.root, prompt_body=long_body)
        seen = {}
        for budget in (4000, 300, 100, 0):
            text, state = hooks.prompt_section_text(layout, "demo01", budget=budget)
            seen[budget] = state
            if state in ("full", "truncated"):
                self.assertLessEqual(len(text.encode("utf-8")), budget, "非 skipped 必须 <= budget")
                self.assertIn("[pm-memory prompt", text)
                if state == "truncated":
                    self.assertIn("超过 " + str(budget) + "B", text, "标注数字必须=最终预算")
        self.assertEqual(seen[4000], "full")
        self.assertEqual(seen[300], "truncated")
        self.assertEqual(seen[100], "skipped:budget-too-small")
        self.assertEqual(seen[0], "skipped:budget-too-small")
        empty_src = make_library(Path(tempfile.mkdtemp()), prompt_body="")
        self.assertEqual(hooks.prompt_section_text(empty_src, "demo01", budget=4000)[1], "skipped:empty-source")
        no_file = make_library(Path(tempfile.mkdtemp()), with_prompt=False)
        self.assertEqual(hooks.prompt_section_text(no_file, "demo01", budget=4000)[1], "skipped:no-file")

    def test_c5_scope_fallback_never_falls_back(self) -> None:
        """c5：三段回退沿用；cwd 属于没有 prompt.org 的项目 ⇒ 不出节（绝不回退别项目/全库）。"""
        layout = make_library(self.root)
        explicit = hooks.session_start_text(layout, HooksConfig(scope="demo01"), payload_cwd=str(self.root / "ws-beta"))
        self.assertIn(TOKEN, explicit)
        derived = hooks.session_start_text(layout, HooksConfig(), payload_cwd=str(self.root / "ws-demo01"))
        self.assertIn(TOKEN, derived)
        negative = hooks.session_start_text(layout, HooksConfig(), payload_cwd=str(self.root / "ws-beta"))
        self.assertNotIn(TOKEN, negative, "beta 没有 prompt.org ⇒ 一条都不许注入")
        global_fallback = hooks.session_start_text(layout, HooksConfig(), payload_cwd="/tmp/not-a-project")
        self.assertNotIn(TOKEN, global_fallback, "global 档不得回退去拿别项目的 prompt")

    def test_c6_prompt_false_is_byte_identical(self) -> None:
        """c6：prompt=false ⇒ 与今天逐字节一致；inject=false 下 prompt 开关不产生差异。"""
        layout = make_library(self.root)
        today = hooks.session_start_text(layout, HooksConfig(prompt=False), scope="demo01")
        self.assertNotIn("[pm-memory prompt", today)
        self.assertTrue(today.startswith("[pm-memory session-start scope=demo01 items=1/3 budget=2400B]"))
        with_prompt_on = hooks.session_start_text(layout, HooksConfig(), scope="demo01")
        self.assertTrue(with_prompt_on.startswith(today), "记忆节必须逐字节不变（提示词节是纯增量）")
        self.assertEqual(with_prompt_on[len(today)], NL)
        off_a = hooks.session_start_text(layout, HooksConfig(inject=False, prompt=True), scope="demo01")
        off_b = hooks.session_start_text(layout, HooksConfig(inject=False, prompt=False), scope="demo01")
        self.assertEqual(off_a, "")
        self.assertEqual(off_a, off_b, "inject=false 下 prompt 开关不得产生任何差异")


if __name__ == "__main__":
    unittest.main()
