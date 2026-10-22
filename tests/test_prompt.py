"""tests/test_prompt.py —— pm prompt（初始系统提示词）数据层判据。

依据 内部记录/25 §6/§7 与 Lead 2026-10-18 裁定 (a)：
- 布局：一个节 + 实体块（** prompt-meta 与每个内容块各带 :ID: 抽屉）⇒ 写路径复用 entities（CAS/原子写/审计/幂等）；
- 六字段 GET（不含 prompt-meta）；CAS 冲突 ⇒ exit 3 + error.currentRevision；已存在 + actor=ai ⇒ AI_CANNOT_EDIT(2)；
  已存在缺 expected-revision ⇒ REVISION_REQUIRED(2)；保留名 prompt-meta ⇒ 报错；同 idempotency-key 重放不二次变更。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pm import prompt as prompt_module


class PromptDataTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "projects" / "proj-demo01").mkdir(parents=True)
        (self.root / "projects" / "proj-demo01" / "project.org").write_text(
            "#+TITLE: demo01\n#+PM_PATH: " + str(self.root / "ws") + "\n", encoding="utf-8")
        (self.root / "ws").mkdir()
        (self.root / "ws" / "README.md").write_text("# 标题\n正文\n", encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def test_missing_is_revision_zero(self) -> None:
        data = prompt_module.get_prompt_v2(self.root, "demo01")
        self.assertFalse(data["exists"])
        self.assertEqual(data["revision"], 0)
        self.assertEqual(data["blocks"], [])

    def test_create_then_roundtrip(self) -> None:
        prompt_module.set_prompt(self.root, "demo01",
                                 [{"name": "项目背景", "text": "正文一"},
                                  {"name": "硬约束", "text": "不要改写人工文件。"}],
                                 expected_revision=None, actor="human", reason="首次")
        data = prompt_module.get_prompt_v2(self.root, "demo01")
        self.assertTrue(data["exists"])
        self.assertEqual(data["revision"], 1)
        self.assertEqual([b["name"] for b in data["blocks"]], ["项目背景", "硬约束"])
        self.assertEqual(data["blocks"][0]["text"], "正文一")          # 逐字节（dedent 后）
        self.assertTrue(data["blocks"][0]["id"])                        # 有 :ID:
        self.assertNotIn("prompt-meta", [b["name"] for b in data["blocks"]])   # 不变量 i

    def test_cas_conflict_and_required(self) -> None:
        prompt_module.set_prompt(self.root, "demo01", [{"name": "A", "text": "1"}],
                                 expected_revision=None, actor="human")
        with self.assertRaises(prompt_module.PromptError) as ctx:
            prompt_module.set_prompt(self.root, "demo01", [{"id": "x", "name": "A", "text": "2"}],
                                     expected_revision=99, actor="human")
        self.assertEqual(ctx.exception.code, "REVISION_CONFLICT")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertEqual(ctx.exception.extra.get("currentRevision"), 1)
        with self.assertRaises(prompt_module.PromptError) as ctx2:
            prompt_module.set_prompt(self.root, "demo01", [{"id": "x", "name": "A", "text": "3"}],
                                     expected_revision=None, actor="human")
        self.assertEqual(ctx2.exception.code, "REVISION_REQUIRED")

    def test_ai_cannot_edit_existing(self) -> None:
        prompt_module.set_prompt(self.root, "demo01", [{"name": "A", "text": "1"}],
                                 expected_revision=None, actor="human")
        with self.assertRaises(prompt_module.PromptError) as ctx:
            prompt_module.set_prompt(self.root, "demo01", [{"name": "A", "text": "2"}],
                                     expected_revision=1, actor="ai")
        self.assertEqual(ctx.exception.code, "AI_CANNOT_EDIT")

    def test_reserved_block_name(self) -> None:
        with self.assertRaises(prompt_module.PromptError) as ctx:
            prompt_module.set_prompt(self.root, "demo01", [{"name": "prompt-meta", "text": "x"}],
                                     expected_revision=None, actor="human")
        self.assertEqual(ctx.exception.code, "RESERVED_BLOCK_NAME")

    def test_idempotent_replay(self) -> None:
        prompt_module.set_prompt(self.root, "demo01", [{"name": "A", "text": "1"}],
                                 expected_revision=None, actor="human")
        first = prompt_module.get_prompt_v2(self.root, "demo01")
        block = {"id": first["blocks"][0]["id"], "name": "A", "text": "2"}
        one = prompt_module.set_prompt(self.root, "demo01", [block], expected_revision=1,
                                       actor="human", idempotency_key="k-1")
        two = prompt_module.set_prompt(self.root, "demo01", [block], expected_revision=1,
                                       actor="human", idempotency_key="k-1")
        self.assertTrue(two["idempotent"])
        self.assertEqual(one["revision"], two["revision"])

    def test_render_skips_meta_block(self) -> None:
        """不变量 ii：渲染**跳过** prompt-meta（元数据块不进提示词）。"""
        prompt_module.set_prompt(self.root, "demo01", [{"name": "项目背景", "text": "正文一"}],
                                 expected_revision=None, actor="human")
        data = prompt_module.get_prompt_v2(self.root, "demo01")
        rendered = prompt_module.render_blocks(self.root, "demo01", data["blocks"])
        self.assertNotIn("prompt-meta", rendered["text"])
        self.assertIn("项目背景", rendered["text"])

    def test_id_stable_on_content_edit(self) -> None:
        """id 稳定性：内容编辑时客户端回带旧 :ID: ⇒ **原地改**（id 不变、不新建块）。"""
        prompt_module.set_prompt(self.root, "demo01", [{"name": "旧名", "text": "正文"}],
                                 expected_revision=None, actor="human")
        first = prompt_module.get_prompt_v2(self.root, "demo01")
        block_id = first["blocks"][0]["id"]
        prompt_module.set_prompt(self.root, "demo01",
                                 [{"id": block_id, "name": "旧名", "text": "改过的正文"}],
                                 expected_revision=first["revision"], actor="human")
        second = prompt_module.get_prompt_v2(self.root, "demo01")
        self.assertEqual(len(second["blocks"]), 1, "编辑不该新建块")
        self.assertEqual(second["blocks"][0]["id"], block_id, "id 必须稳定")
        self.assertEqual(second["blocks"][0]["text"], "改过的正文")

    def test_rename_keeps_id_and_changes_name(self) -> None:
        """⒜ 改名（用户设计 内部记录/25 §3：身份是 :ID:）：只改标题行 ⇒ **同一 :ID:** + 新名字，且能往返读回。"""
        prompt_module.set_prompt(self.root, "demo01", [{"name": "旧名", "text": "正文"}],
                                 expected_revision=None, actor="human")
        first = prompt_module.get_prompt_v2(self.root, "demo01")
        block_id = first["blocks"][0]["id"]
        result = prompt_module.set_prompt(self.root, "demo01",
                                          [{"id": block_id, "name": "新名", "text": "正文"}],
                                          expected_revision=first["revision"], actor="human")
        self.assertGreaterEqual(result["changed"], 1)
        again = prompt_module.get_prompt_v2(self.root, "demo01")
        self.assertEqual(len(again["blocks"]), 1, "改名不该新建块")
        self.assertEqual(again["blocks"][0]["id"], block_id, "身份（:ID:）必须不变")
        self.assertEqual(again["blocks"][0]["name"], "新名")
        self.assertEqual(again["blocks"][0]["text"], "正文")

    def test_same_key_different_content_never_half_writes(self) -> None:
        """RUN C 形态的**不变量**判据：绝不允许出现「内容变了但文件级 revision 不动」✗。

        旧实现（38d2aa3 之前）：客户端 key 被直接交给 meta 的 apply_change ⇒ 该 key 在本文件里有重放记录时，
        meta 写被判重放 ⇒ bump 跳过；而块写用派生键照常落盘 ⇒ 内容变了、rev 停在 1 ✗（CAS 护栏失效）。
        现在的语义（两种情况都自洽，二者必居其一）：
          · 同 key（=重放）⇒ **内容不变**、rev 不变、changed=0 ✓
          · 新 key（非重放）⇒ 内容变 ⇒ rev **必 +1** ✓
        """
        key = "pv-k1"
        first = prompt_module.set_prompt(self.root, "demo01", [{"name": "块", "text": "第一版"}],
                                         expected_revision=None, actor="human", idempotency_key=key)
        before = prompt_module.get_prompt_v2(self.root, "demo01")
        block_id = before["blocks"][0]["id"]
        same_key = prompt_module.set_prompt(self.root, "demo01",
                                            [{"id": block_id, "name": "块", "text": "第二版（不同内容）"}],
                                            expected_revision=before["revision"], actor="human",
                                            idempotency_key=key)
        after_same = prompt_module.get_prompt_v2(self.root, "demo01")
        self.assertEqual(after_same["blocks"][0]["text"], "第一版", "同 key = 重放 ⇒ 内容不得改变 ✗")
        self.assertEqual(after_same["revision"], before["revision"], "重放 ⇒ revision 不变")
        self.assertEqual(same_key["changed"], 0)
        self.assertTrue(same_key["idempotent"])
        new_key = prompt_module.set_prompt(self.root, "demo01",
                                           [{"id": block_id, "name": "块", "text": "第三版"}],
                                           expected_revision=after_same["revision"], actor="human",
                                           idempotency_key="pv-k2")
        after_new = prompt_module.get_prompt_v2(self.root, "demo01")
        self.assertEqual(after_new["blocks"][0]["text"], "第三版")
        self.assertEqual(after_new["revision"], after_same["revision"] + 1,
                         "内容变了 ⇒ 文件级 revision 必 +1")
        self.assertEqual(new_key["changed"], 1)
        self.assertFalse(new_key["idempotent"])

    def test_idempotency_is_library_scoped(self) -> None:
        """幂等记录**按库隔离**（存在本文件 LOGBOOK 里）：库 A 用过的 key 不得让库 B 判重放。

        反例形态（Lead/dsh-plugin 2026-10-18 报的疑虑）：每次 run 重建临时库 + 复用早先的 key ⇒
        库 B **必须真的写进去**（changed>=1、idempotent=False、GET 能读到），不能 changed=0 ✗。
        """
        import shutil

        other = Path(tempfile.mkdtemp(prefix="prompt-lib-b-"))
        try:
            (other / "projects" / "proj-demo01").mkdir(parents=True)
            (other / "projects" / "proj-demo01" / "project.org").write_text(
                "#+TITLE: demo01\n#+PM_PATH: " + str(other / "ws") + "\n", encoding="utf-8")
            (other / "ws").mkdir()
            key = "pv-k1"
            first = prompt_module.set_prompt(self.root, "demo01", [{"name": "块A", "text": "库A"}],
                                             expected_revision=None, actor="human", idempotency_key=key)
            self.assertFalse(first["idempotent"])
            second = prompt_module.set_prompt(other, "demo01", [{"name": "块B", "text": "库B"}],
                                              expected_revision=None, actor="human", idempotency_key=key)
            self.assertFalse(second["idempotent"], "另一个库不能把同一个 key 判成重放")
            self.assertGreaterEqual(second["changed"], 1)
            got = prompt_module.get_prompt_v2(other, "demo01")
            self.assertTrue(got["exists"])
            self.assertEqual([b["name"] for b in got["blocks"]], ["块B"])
            replay = prompt_module.set_prompt(self.root, "demo01",
                                              [{"name": "块A", "text": "库A"}],
                                              expected_revision=prompt_module.get_prompt_v2(self.root, "demo01")["revision"],
                                              actor="human", idempotency_key=key)
            self.assertTrue(replay["idempotent"], "同一库同 key ⇒ 仍按重放")
            self.assertEqual(replay["changed"], 0)
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_every_save_bumps_revision(self) -> None:
        """CAS 护栏（Lead 2026-10-18 报的 RUN A/C）：每次**成功**保存 ⇒ 文件级 revision 必增 1、updatedAt 不降。"""
        prompt_module.set_prompt(self.root, "demo01", [{"name": "块", "text": "一"}],
                                 expected_revision=None, actor="human", idempotency_key="s1")
        seen = [prompt_module.get_prompt_v2(self.root, "demo01")]
        block_id = seen[0]["blocks"][0]["id"]
        for index, text in enumerate(("二", "三"), start=2):
            prompt_module.set_prompt(self.root, "demo01", [{"id": block_id, "name": "块", "text": text}],
                                     expected_revision=seen[-1]["revision"], actor="human",
                                     idempotency_key="s" + str(index))
            seen.append(prompt_module.get_prompt_v2(self.root, "demo01"))
        self.assertEqual([d["revision"] for d in seen], [1, 2, 3], "每次保存 revision 必增 1")
        stamps = [d["updatedAt"] for d in seen]
        self.assertEqual(stamps, sorted(stamps), "updatedAt 必须单调不降")
        replay = prompt_module.set_prompt(self.root, "demo01",
                                          [{"id": block_id, "name": "块", "text": "三"}],
                                          expected_revision=seen[-1]["revision"], actor="human",
                                          idempotency_key="s3")
        self.assertTrue(replay["idempotent"])
        self.assertEqual(replay["changed"], 0, "幂等重放必须 changed=0")

    def test_duplicate_block_name_is_allowed_with_warning(self) -> None:
        """⒞ 重名：**保存必须成功**（用户设计：身份是 :ID: ⇒ 同名也能区分），只给提醒 ✓。"""
        result = prompt_module.set_prompt(self.root, "demo01",
                                          [{"name": "同名", "text": "a"}, {"name": "同名", "text": "b"}],
                                          expected_revision=None, actor="human")
        self.assertEqual(result["changed"], 2)
        self.assertTrue(result["warnings"], "重名要给提醒（只提醒不拦）")
        got = prompt_module.get_prompt_v2(self.root, "demo01")
        self.assertEqual([b["name"] for b in got["blocks"]], ["同名", "同名"])
        self.assertEqual(len({b["id"] for b in got["blocks"]}), 2, "同名块必须靠 :ID: 区分")

    def test_empty_block_name_is_rejected_with_index(self) -> None:
        """⒝ 空名 ⇒ 保存前拦下并**指出第几块**（不静默写无名字标题 ✗）。"""
        with self.assertRaises(prompt_module.PromptError) as ctx:
            prompt_module.set_prompt(self.root, "demo01",
                                     [{"name": "有名字", "text": "a"}, {"name": "   ", "text": "b"}],
                                     expected_revision=None, actor="human")
        self.assertEqual(ctx.exception.code, "EMPTY_BLOCK_NAME")
        self.assertIn("第 2 块", ctx.exception.message)
        self.assertFalse(prompt_module.get_prompt_v2(self.root, "demo01")["exists"], "报错时不得留下半成品")

    def test_list_saved_prompts(self) -> None:
        """② 只读清单：只列**已保存**的（global 与项目都算），字段够页面做复制源 ✓。"""
        empty = prompt_module.list_saved_prompts(self.root)
        self.assertTrue(empty["onlySaved"])
        self.assertEqual(empty["count"], 0)
        prompt_module.set_prompt(self.root, "demo01", [{"name": "A", "text": "1"}],
                                 expected_revision=None, actor="human")
        listed = prompt_module.list_saved_prompts(self.root)
        self.assertEqual(listed["count"], 1)
        item = listed["items"][0]
        self.assertEqual(item["scope"], "demo01")
        self.assertEqual(item["revision"], 1)
        self.assertEqual(item["blockCount"], 1)
        self.assertTrue(item["path"].endswith("projects/proj-demo01/prompt.org"))

    def test_file_stdin_entry_end_to_end(self) -> None:
        """③ --file - 端到端：stdin 给 org 文本 ⇒ 落库 ⇒ GET 读回（终端入口，与路由入口同一条写路径）。"""
        import os
        import subprocess
        import sys

        config = self.root / "pm.toml"
        config.write_text('library = "' + str(self.root) + '"\n', encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in ("DSH_UI_PM_CONFIG", "PM_CONFIG", "PM_DSH_HOME")}
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
        cwd = str(Path(__file__).resolve().parent.parent)
        org = "** 项目背景\n正文一\n\n** 硬约束\n不要改写人工文件。\n"
        proc = subprocess.run([sys.executable, "-m", "pm", "prompt", "set", "--scope", "demo01", "--file", "-",
                               "--actor", "human", "--config", str(config), "--json"],
                              input=org, capture_output=True, text=True, env=env, cwd=cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = subprocess.run([sys.executable, "-m", "pm", "prompt", "get", "--scope", "demo01",
                              "--config", str(config), "--json"], capture_output=True, text=True, env=env, cwd=cwd)
        payload = json.loads(got.stdout)["data"]
        self.assertEqual([b["name"] for b in payload["blocks"]], ["项目背景", "硬约束"])
        self.assertEqual(payload["blocks"][0]["text"], "正文一")

    def test_reference_red_lines_and_render(self) -> None:
        blocks = [{"name": "项目概览", "text": "#+PM_INCLUDE: " + "$" + "{path}/README.md"},
                  {"name": "越界", "text": "#+PM_INCLUDE: ../../.ssh/id_rsa"}]
        rendered = prompt_module.render_blocks(self.root, "demo01", blocks)
        text = rendered["text"]
        self.assertIn("已展开 2 行", text)
        self.assertIn("⚠ 展开失败：路径越界：含 ..", text)
        self.assertIn("正文", text)


if __name__ == "__main__":
    unittest.main()
