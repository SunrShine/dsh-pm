"""tests/test_memory_l2.py —— M3 第一切片：L2 场景文件读写 + 索引 layer 扩展 + stale 判定。

依据 内部记录/13 §2/§3.2/§7-B：一块一文件（路径即 id）、:PM_SOURCES: 用 id@revision 作版本锚点、
stale 是纯计算（只读索引，不改文件）。
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pm import entities, index, memory

FACTS = """* Facts
** L1 锚点事实
   :PROPERTIES:
   :ID: memory-m3-001
   :PM_STATUS: VERIFIED
   :PM_SCOPE: pm_tools
   :PM_TYPE: fact
   :PM_REVISION: 3
   :END:
   被 L2 归纳的原始事实。
** 另一条 L1
   :PROPERTIES:
   :ID: memory-m3-002
   :PM_STATUS: VERIFIED
   :PM_REVISION: 1
   :END:
   与场景无关的一条。
"""


class L2BaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "memory").mkdir(parents=True, exist_ok=True)
        (self.root / "memory" / "facts.org").write_text(FACTS, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)
        index._FTS5_CACHE = None

    def _scene(self, **kwargs):
        params = dict(scope="pm_tools", scene="demo", title="演示场景摘要",
                      body="摘要正文：来自 memory-m3-001@3。", sources=["memory-m3-001@3"], actor="ai")
        params.update(kwargs)
        return memory.write_scene(self.root, **params)

    def _bump_l1(self, memory_id="memory-m3-001", expected=3):
        return entities.apply_change(self.root / "memory" / "facts.org", memory_id,
                                     expected_revision=expected, replace_body=["改过的正文。"], actor="ai",
                                     reason="测试：抬 revision")


class SceneWriteTest(L2BaseTest):
    def test_write_creates_scene_file_with_layer_and_pins(self) -> None:
        result = self._scene()
        path = memory.scene_path(self.root, "pm_tools", "demo")
        self.assertTrue(path.is_file())
        self.assertEqual(result.status, memory.STATUS_CANDIDATE)
        text = path.read_text(encoding="utf-8")
        self.assertIn(":PM_LAYER: L2", text)
        self.assertIn(":PM_SOURCES: memory-m3-001@3", text)
        self.assertIn(":ID: memory-l2-pm_tools-demo", text)

    def test_read_scenes_reports_layer_l2_and_scope(self) -> None:
        self._scene()
        scenes = memory.read_scenes(self.root)
        self.assertEqual(len(scenes), 1)
        self.assertEqual(scenes[0].layer, memory.LAYER_L2)
        self.assertEqual(scenes[0].scope, "pm_tools")
        self.assertIn("memory-m3-001@3", scenes[0].sources)

    def test_update_requires_cas_and_conflict_writes_nothing(self) -> None:
        self._scene()
        path = memory.scene_path(self.root, "pm_tools", "demo")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(entities.EntityError) as ctx:
            memory.write_scene(self.root, scope="pm_tools", scene="demo", title="改标题",
                               expected_revision=99, actor="ai")
        self.assertEqual(ctx.exception.code, "REVISION_CONFLICT")
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        # 正确 revision ⇒ 更新成功且 revision 单调 +1
        updated = memory.write_scene(self.root, scope="pm_tools", scene="demo", title="改标题",
                                     body="新摘要", sources=["memory-m3-001@3"],
                                     expected_revision=1, actor="ai", reason="更新场景")
        self.assertEqual(updated.revision, 2)
        self.assertIn("新摘要", path.read_text(encoding="utf-8"))

    def test_scene_name_is_validated(self) -> None:
        with self.assertRaises(memory.MemoryError) as ctx:
            memory.scene_path(self.root, "pm_tools", "../escape")
        self.assertEqual(ctx.exception.code, "BAD_NAME")


class L2IndexTest(L2BaseTest):
    def test_index_picks_up_l2_with_source_rev(self) -> None:
        self._scene()
        stats = index.build(self.root, rebuild=True)
        self.assertIn("memory/l2/pm_tools/demo.org", stats["filesChanged"])
        rows = index.recall(self.root, "演示场景", include_candidate=True)
        self.assertEqual(rows["count"], 1)
        hit = rows["hits"][0]
        self.assertEqual(hit["layer"], "L2")
        self.assertEqual(hit["path"], "memory/l2/pm_tools/demo.org")
        self.assertEqual(hit["line"], 3)
        self.assertEqual(hit["revision"], 1)

    def test_index_auto_updates_after_scene_rewrite(self) -> None:
        self._scene()
        index.build(self.root, rebuild=True)
        self.assertEqual(index.recall(self.root, "第二版摘要", include_candidate=True)["count"], 0)
        memory.write_scene(self.root, scope="pm_tools", scene="demo", title="演示场景摘要",
                           body="第二版摘要出现了新的词", sources=["memory-m3-001@3"],
                           expected_revision=1, actor="ai", reason="重写摘要")
        # 不显式跑 index：recall 自己按 sha 刷新
        self.assertEqual(index.recall(self.root, "第二版摘要", include_candidate=True)["count"], 1)

    def test_default_scope_hides_l2_candidate_but_shows_verified(self) -> None:
        self._scene()
        self.assertEqual(index.recall(self.root, "演示场景")["count"], 0)  # CANDIDATE 默认不出现
        self.assertEqual(index.recall(self.root, "演示场景", include_candidate=True)["count"], 1)
        self._scene(scene="verified", status=memory.STATUS_VERIFIED)
        self.assertEqual(index.recall(self.root, "演示场景")["count"], 1)  # VERIFIED 默认出现

    def test_rebuild_deterministic_with_l2(self) -> None:
        self._scene()
        index.build(self.root, rebuild=True)
        before = json.dumps(index.recall(self.root, "演示场景", include_candidate=True), ensure_ascii=False, sort_keys=True)
        index.index_path(self.root).unlink()
        index.build(self.root, rebuild=True)
        after = json.dumps(index.recall(self.root, "演示场景", include_candidate=True), ensure_ascii=False, sort_keys=True)
        self.assertEqual(before, after)


class StaleTest(L2BaseTest):
    def test_fresh_when_anchor_matches(self) -> None:
        self._scene()
        report = index.stale_check(self.root)
        self.assertEqual(report["checked"], 1)
        self.assertEqual(report["fresh"], 1)
        self.assertEqual(report["stale"], [])
        self.assertEqual(report["unpinned"], [])

    def test_stale_after_l1_revision_changes(self) -> None:
        self._scene()
        self.assertEqual(index.stale_check(self.root)["stale"], [])
        self._bump_l1()
        report = index.stale_check(self.root)
        self.assertEqual(len(report["stale"]), 1)
        self.assertEqual(report["fresh"], 0)
        self.assertIn("revision 3 → 4", report["stale"][0]["problems"][0])

    def test_unpinned_sources_are_separate_from_fresh(self) -> None:
        self._scene(sources=[])
        report = index.stale_check(self.root)
        self.assertEqual(report["fresh"], 0)
        self.assertEqual(len(report["unpinned"]), 1)
        self.assertIn("没有 :PM_SOURCES:", report["unpinned"][0]["reason"])

    def test_stale_when_target_disappears(self) -> None:
        self._scene(sources=["memory-does-not-exist@1"])
        report = index.stale_check(self.root)
        self.assertEqual(len(report["stale"]), 1)
        self.assertIn("已不在 L1 索引里", report["stale"][0]["problems"][0])

    def test_stale_is_read_only_for_org(self) -> None:
        self._scene()
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.root.rglob("*.org"))}
        index.stale_check(self.root)
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.root.rglob("*.org"))}
        self.assertEqual(before, after)

    def test_parse_source_pins(self) -> None:
        self.assertEqual(memory.parse_source_pins(["memory-a@3", "memory-b", "x@bad"]),
                         [("memory-a", 3), ("memory-b", None), ("x@bad", None)])


if __name__ == "__main__":
    unittest.main()
