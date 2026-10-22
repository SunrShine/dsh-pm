"""tests/test_memory_status.py —— 小卡：pm memory list --status（VERIFIED / DEPRECATED）。

口径与状态机一致；**不带参数时行为与今天完全一致**；非法值明确报错（不静默忽略）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pm import memory

FACTS = """* Facts
** 一条正式记忆
   :PROPERTIES:
   :ID: memory-l1-001
   :PM_STATUS: VERIFIED
   :PM_SCOPE: pm_tools
   :PM_TYPE: fact
   :PM_REVISION: 1
   :END:
   正式正文。
** 一条历史记忆
   :PROPERTIES:
   :ID: memory-l1-002
   :PM_STATUS: DEPRECATED
   :PM_SCOPE: pm_tools
   :PM_TYPE: fact
   :PM_REVISION: 2
   :END:
   历史正文。
** 别的 scope
   :PROPERTIES:
   :ID: memory-l1-003
   :PM_STATUS: VERIFIED
   :PM_SCOPE: other
   :PM_TYPE: fact
   :PM_REVISION: 1
   :END:
   别处正文。
"""


class MemoryListStatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "memory").mkdir(parents=True, exist_ok=True)
        (self.root / "memory" / "facts.org").write_text(FACTS, encoding="utf-8")
        (self.root / "pm.toml").write_text('library = "' + str(self.root) + '"\n', encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(__file__).resolve().parent.parent

    def _cli(self, *args: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in __import__("os").environ.items()
               if k not in ("DSH_UI_PM_CONFIG", "PM_CONFIG", "PM_DSH_HOME")}
        env["PYTHONPATH"] = str(self.repo / "src")
        return subprocess.run([sys.executable, "-m", "pm", "memory", "list", "--config", str(self.root / "pm.toml"), *args],
                              cwd=str(self.repo), capture_output=True, text=True, env=env)

    def _payload(self, *args: str) -> dict:
        proc = self._cli("--json", *args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_default_behaviour_is_unchanged(self) -> None:
        """不带 --status：条目与键都与今天一致（不多一个 status 键）。"""
        payload = self._payload()
        self.assertEqual(payload["count"], 3)
        self.assertEqual(sorted(payload.keys()), ["count", "entries", "ok", "path"])
        self.assertNotIn("status", payload)
        statuses = [entry["status"] for entry in payload["entries"]]
        self.assertIn("VERIFIED", statuses)
        self.assertIn("DEPRECATED", statuses)

    def test_filter_verified(self) -> None:
        payload = self._payload("--status", "VERIFIED")
        self.assertEqual(payload["status"], "VERIFIED")
        self.assertEqual(payload["count"], 2)
        self.assertTrue(all(entry["status"] == "VERIFIED" for entry in payload["entries"]))

    def test_filter_deprecated_and_lowercase(self) -> None:
        payload = self._payload("--status", "deprecated")
        self.assertEqual(payload["status"], "DEPRECATED")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["entries"][0]["id"], "memory-l1-002")

    def test_status_combines_with_scope_and_type(self) -> None:
        payload = self._payload("--status", "VERIFIED", "--scope", "pm_tools", "--type", "fact")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["entries"][0]["id"], "memory-l1-001")

    def test_invalid_status_errors_loudly(self) -> None:
        """非法值必须明确报错（exit 2），不静默忽略。"""
        proc = self._cli("--status", "BOGUS")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("invalid choice", proc.stderr)

    def test_candidate_is_not_a_valid_status_for_formal_list(self) -> None:
        """正式区没有 CANDIDATE（候选在 memory-candidates.org）⇒ 这里也不该接受。"""
        proc = self._cli("--status", "CANDIDATE")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("invalid choice", proc.stderr)


if __name__ == "__main__":
    unittest.main()
