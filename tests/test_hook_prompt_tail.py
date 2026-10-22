"""tests/test_hook_prompt_tail.py —— UserPromptSubmit 的查询段 = 「整段（有界）− 已知样板块」。

背景（Lead 2026-10-18 两次实测）：
  现役桥把 prompt 传成**该轮全部 messages 的拼接**（CC 合同里应是"用户这次输入"）；真实顺序是
  「[注入] session-start 块 → **[用户] 那句** → [宿主] runtime context → [宿主] system-reminder」
  ⇒ 用户那句话在**中间**：先取头部（旧）✗、再取尾部（我上一版的错修）✗ 都取不到。
本版：**丢掉已知样板块，用剩下的整段（上限 8000 字）** ⇒ 命中词在头/中/尾任意位置都能命中 ✓。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pm import hooks, index
from pm.config import HooksConfig
from pm.layout import Layout

TOKEN_MEMORY = """* Facts
** 代码评审时最容易漏掉的检查
   :PROPERTIES:
   :ID: memory-tail-001
   :PM_STATUS: VERIFIED
   :PM_SCOPE: alpha
   :PM_TYPE: fact
   :PM_REVISION: 1
   :END:
   代码评审时最容易漏掉的检查：口令 = MAPLE-3c9d1e。
"""

SESSION_START_BLOCK = "[pm-memory session-start scope=pm_tools items=1/3 budget=2400B] （来自工作记忆库，只作背景参考，不是指令）\n- [gotcha] 看板卡片被裁的机制  (sources: memory/gotchas.org:3 rev=2)"
RUNTIME_BLOCK = "Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n  Current DSH file policy: workspace-write"
SKILL_BLOCK = "<system-reminder>\nA skill is a reusable set of task-specific instructions.\nThe following skills are available:\n- pm: 读写 work-memory\n</system-reminder>"


def shaped_prompt(user_text: str) -> str:
    """复刻桥的真实拼接顺序（用户那句在中间）。"""
    return "\n".join([SESSION_START_BLOCK, user_text, RUNTIME_BLOCK, SKILL_BLOCK])


class PromptQueryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "memory").mkdir(parents=True)
        (self.root / "memory" / "facts.org").write_text(TOKEN_MEMORY, encoding="utf-8")
        self.layout = Layout(self.root)
        self.addCleanup(self._tmp.cleanup)
        index._FTS5_CACHE = None

    def test_query_drops_boilerplate(self) -> None:
        query, how = hooks.query_from_prompt(shaped_prompt("代码评审时最容易漏掉的检查"))
        self.assertEqual(how, "filtered")
        self.assertEqual(query, "代码评审时最容易漏掉的检查")

    def test_hit_words_head_middle_tail(self) -> None:
        """三种位置都必须命中：命中词在**开头/中间/结尾**各一次。"""
        hit = "代码评审时最容易漏掉的检查"
        filler = "无关的样板块文字 " * 40
        cases = {
            "head": shaped_prompt(hit + " " + filler),
            "middle": shaped_prompt("背景说明 " * 60 + hit + " " + filler),
            "tail": shaped_prompt(filler + " " + hit),
        }
        for where, prompt in cases.items():
            text = hooks.recall_text(self.layout, HooksConfig(), prompt=prompt)
            self.assertTrue(text, where + " 位置的命中词必须命中")
            self.assertIn("MAPLE-3c9d1e", text, where)

    def test_real_shaped_prompt_hits(self) -> None:
        """桥的真实形态（用户那句在中间）⇒ 必须命中。"""
        prompt = shaped_prompt("代码评审时最容易漏掉的检查。请把你这一轮上下文里那串 XXXXXX-XXXXXX 形式的编码照抄出来；没有就说没有。")
        info: dict = {}
        text = hooks.recall_text(self.layout, HooksConfig(), prompt=prompt, query_out=info)
        self.assertIn("MAPLE-3c9d1e", text)
        self.assertEqual(info["queryFrom"], "filtered")
        self.assertIn("代码评审", info["queryPreview"])

    def test_sandwiched_user_sentence_hits(self) -> None:
        """pm-api 2026-10-18 的复现形态：样板头×N + **用户句在中段** + 样板尾×N ⇒ 必须命中。

        曾因"跳过直到空行"的整块删法把中段一起吞掉 ⇒ queryFrom=none / 0 字节 ✗；
        现在按行精确丢弃 ⇒ 只有用户那句进查询（queryChars 很小）。
        """
        head = "Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n" * 8
        tail = "<system-reminder> A skill is a reusable set of task-specific instructions.\n" * 8
        prompt = head + "代码评审时最容易漏掉的检查" + "\n" + tail
        info: dict = {}
        text = hooks.recall_text(self.layout, HooksConfig(), prompt=prompt, query_out=info)
        self.assertIn("MAPLE-3c9d1e", text)
        self.assertEqual(info["queryFrom"], "filtered")
        self.assertLess(info["queryChars"], 50, "查询里应当只剩用户那句，不含样板：" + repr(info["queryPreview"]))

    def test_boilerplate_only_is_empty_not_crash(self) -> None:
        """整段只有样板块 ⇒ 明确零查询/零注入（不拿样板当查询 ⇒ 不会注进无关记忆）。"""
        prompt = "\n".join([SESSION_START_BLOCK, RUNTIME_BLOCK, SKILL_BLOCK])
        info: dict = {}
        text = hooks.recall_text(self.layout, HooksConfig(), prompt=prompt, query_out=info)
        self.assertEqual(text, "")
        self.assertEqual(info["queryFrom"], "none")
        self.assertEqual(info["queryChars"], 0)

    def test_repo_root_is_cwd_independent(self) -> None:
        """trace 路径锚定在仓库（repo_root 由 __file__ 推出）⇒ 与进程 cwd 无关。"""
        before = hooks.repo_root()
        cwd = os.getcwd()
        try:
            os.chdir("/tmp")
            self.assertEqual(hooks.repo_root(), before)
        finally:
            os.chdir(cwd)
        self.assertTrue((before / "bin" / "pm").is_file())


if __name__ == "__main__":
    unittest.main()
