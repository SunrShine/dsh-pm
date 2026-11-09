"""tests/test_prompt_exports.py —— 导出记录（派生物 .local/prompt-exports.json）的判据。

依据 内部记录/25 §5.1 / §6 / §7（用户领地，只读）：
- 记录是派生物：绝不写 projects/**；文件缺失 ⇒ 空列表；损坏 ⇒ 显式报错码（不许静默清空）；
- 字段严格 {id, project, path, name, fmt, bytes, blocks, savedAt, snapshot, blocksData}；
- snapshot 可截断但必须标注 snapshotTruncated；
- 同 idempotencyKey 重放 ⇒ 同一条记录、不新增；--q 匹配 name/path/snapshot（大小写不敏感）；--scope ALL 不筛；
- 删除只删记录：不动导出文件、不动 prompt.org。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pm import prompt as prompt_module

FIELDS = ("id", "project", "path", "name", "fmt", "bytes", "blocks", "savedAt", "snapshot", "blocksData")
NL = chr(10)


class ExportsStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "projects" / "proj-demo01").mkdir(parents=True)
        (self.root / "projects" / "proj-demo01" / "prompt.org").write_text("#+TITLE: d" + NL + "** 背景" + NL + "正文" + NL, encoding="utf-8")
        (self.root / "pm.toml").write_text("library = " + chr(34) + str(self.root) + chr(34) + NL, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def _projects_fingerprint(self) -> str:
        parts = []
        for path in sorted((self.root / "projects").rglob("*")):
            if path.is_file():
                parts.append(str(path.relative_to(self.root)) + ":" + hashlib.sha256(path.read_bytes()).hexdigest())
        return "|".join(parts)

    def _payload(self, **over) -> dict:
        payload = {"scope": "demo01", "path": "/tmp/prompt.md", "name": "prompt.md", "fmt": "md",
                   "text": "导出的提示词正文" + NL, "blocks": [{"name": "背景", "text": "正文"}]}
        payload.update(over)
        return payload

    def test_missing_file_is_empty_list(self) -> None:
        listed = prompt_module.list_exports(self.root)
        self.assertEqual(listed["count"], 0)
        self.assertEqual(listed["items"], [])
        self.assertFalse(prompt_module.exports_path(self.root).exists())

    def test_add_fields_and_no_projects_write(self) -> None:
        before = self._projects_fingerprint()
        result = prompt_module.add_export(self.root, self._payload())
        record = result["record"]
        self.assertEqual(tuple(record.keys()), FIELDS)
        self.assertEqual(record["project"], "demo01")
        self.assertEqual(record["fmt"], "md")
        self.assertEqual(record["blocks"], 1)
        self.assertEqual(record["bytes"], len("导出的提示词正文".encode("utf-8")) + 1)
        self.assertRegex(record["savedAt"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertEqual(record["blocksData"], [{"name": "背景", "text": "正文"}])
        stored = json.loads(prompt_module.exports_path(self.root).read_text(encoding="utf-8"))
        self.assertEqual(len(stored["exports"]), 1)
        self.assertEqual(self._projects_fingerprint(), before, "导出记录绝不能写 projects/")

    def test_idempotent_add(self) -> None:
        first = prompt_module.add_export(self.root, self._payload(idempotencyKey="k-1"))
        second = prompt_module.add_export(self.root, self._payload(idempotencyKey="k-1", text="不同正文"))
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"], "同 key 重放必须判定为幂等")
        self.assertEqual(second["record"]["id"], first["record"]["id"])
        self.assertEqual(prompt_module.list_exports(self.root)["count"], 1)

    def test_filter_and_search(self) -> None:
        prompt_module.add_export(self.root, self._payload(name="alpha.md", path="/x/alpha.md"))
        prompt_module.add_export(self.root, self._payload(scope="beta", name="beta.txt", fmt="txt",
                                                         path="/y/beta.txt", text="Beta 内容" + NL))
        prompt_module.add_export(self.root, self._payload(name="gamma.org", fmt="org", path="/z/gamma.org",
                                                         text="Gamma 内容" + NL))
        self.assertEqual(prompt_module.list_exports(self.root)["count"], 3)
        self.assertEqual(prompt_module.list_exports(self.root, scope="ALL")["count"], 3)
        self.assertEqual(prompt_module.list_exports(self.root, scope="beta")["count"], 1)
        self.assertEqual(prompt_module.list_exports(self.root, q="ALPHA")["count"], 1, "q 大小写不敏感且匹配 name")
        self.assertEqual(prompt_module.list_exports(self.root, q="/z/")["count"], 1, "q 匹配 path")
        self.assertEqual(prompt_module.list_exports(self.root, q="gamma 内容")["count"], 1, "q 匹配 snapshot")
        self.assertEqual(prompt_module.list_exports(self.root, q="完全匹配不到")["count"], 0)

    def test_delete_only_record(self) -> None:
        before = self._projects_fingerprint()
        record = prompt_module.add_export(self.root, self._payload())["record"]
        result = prompt_module.delete_export(self.root, record["id"])
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(prompt_module.list_exports(self.root)["count"], 0)
        self.assertEqual(self._projects_fingerprint(), before, "删除记录不得动 projects/")
        self.assertTrue((self.root / "projects" / "proj-demo01" / "prompt.org").is_file())
        with self.assertRaises(prompt_module.PromptError) as ctx:
            prompt_module.delete_export(self.root, "exp-does-not-exist")
        self.assertEqual(ctx.exception.code, "PROMPT_EXPORT_NOT_FOUND")

    def test_corrupt_storage_is_explicit(self) -> None:
        path = prompt_module.exports_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(prompt_module.PromptError) as ctx:
            prompt_module.list_exports(self.root)
        self.assertEqual(ctx.exception.code, "PROMPT_EXPORTS_CORRUPT")
        self.assertEqual(path.read_text(encoding="utf-8"), "{ not json", "损坏文件不得被静默清空/覆盖")
        with self.assertRaises(prompt_module.PromptError) as ctx2:
            prompt_module.add_export(self.root, self._payload())
        self.assertEqual(ctx2.exception.code, "PROMPT_EXPORTS_CORRUPT")
        self.assertEqual(path.read_text(encoding="utf-8"), "{ not json")

    def test_snapshot_truncation_flag(self) -> None:
        long_text = ("很长的导出正文" * 60) + NL
        record = prompt_module.add_export(self.root, self._payload(text=long_text))["record"]
        self.assertLessEqual(len(record["snapshot"]), prompt_module.SNAPSHOT_LIMIT)
        stored = json.loads(prompt_module.exports_path(self.root).read_text(encoding="utf-8"))["exports"][0]
        self.assertTrue(stored["snapshotTruncated"], "截断必须显式标注，不许偷偷截")

    def test_cli_argv_only_end_to_end(self) -> None:
        """CLI 只靠 argv（无 stdin）：--payload-b64 传长文本 ⇒ list --q ⇒ delete --id。"""
        env = {k: v for k, v in os.environ.items() if k not in ("DSH_UI_PM_CONFIG", "PM_CONFIG", "PM_DSH_HOME")}
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
        repo = str(Path(__file__).resolve().parent.parent)
        payload = self._payload(text="长正文 MARKER-EXPORT " + ("内容" * 100) + NL, idempotencyKey="cli-1")
        b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
        added = subprocess.run([sys.executable, "-m", "pm", "prompt", "exports", "add",
                                "--config", str(self.root / "pm.toml"), "--payload-b64", b64, "--json"],
                               capture_output=True, text=True, env=env, cwd=repo)
        self.assertEqual(added.returncode, 0, added.stderr)
        record = json.loads(added.stdout)["data"]["record"]
        self.assertEqual(record["project"], "demo01")
        listed = subprocess.run([sys.executable, "-m", "pm", "prompt", "exports", "list",
                                 "--config", str(self.root / "pm.toml"), "--scope", "ALL", "--q", "marker-export", "--json"],
                                capture_output=True, text=True, env=env, cwd=repo)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(json.loads(listed.stdout)["data"]["count"], 1)
        deleted = subprocess.run([sys.executable, "-m", "pm", "prompt", "exports", "delete",
                                  "--config", str(self.root / "pm.toml"), "--id", record["id"], "--json"],
                                 capture_output=True, text=True, env=env, cwd=repo)
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        self.assertEqual(json.loads(deleted.stdout)["data"]["deleted"], 1)


if __name__ == "__main__":
    unittest.main()
