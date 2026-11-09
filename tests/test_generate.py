"""tests/test_generate.py —— M3 第二切片（确定性部分）：extract/condense/distill。

判据照着 内部记录/20 §9 的五条写，另外补：失败不静默、skeleton（方案 C）、--stale-only、
预算、以及「VERIFIED 不自动降级」这条安全策略。
LLM 一律用**假命令**（写进临时目录的小脚本）⇒ 不联网、可复现。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from pm import generate, index, memory
from pm.cli import load_config
from pm.config import ConfigPathError, GenerateConfig

DECISIONS = """* Decisions
** 构建一律走 bin/test
   :PROPERTIES:
   :ID: memory-gen-001
   :PM_STATUS: VERIFIED
   :PM_SCOPE: pm_tools
   :PM_TYPE: decision
   :PM_REVISION: 2
   :END:
   任何改动必须 bin/test 全绿。
** 派生索引可删可重建
   :PROPERTIES:
   :ID: memory-gen-002
   :PM_STATUS: VERIFIED
   :PM_SCOPE: pm_tools
   :PM_TYPE: decision
   :PM_REVISION: 1
   :END:
   索引是派生物。
"""

FAKE_LLM = '''import json, os, sys
payload_path = sys.argv[1]
sys.stdin.read()
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "fail":
    sys.exit(3)
if mode == "badjson":
    print("not json"); sys.exit(0)
if mode == "empty":
    sys.exit(0)
if mode == "badschema":
    print(json.dumps({"candidates": [{"title": "x", "whoops": 1}]})); sys.exit(0)
if mode == "badtype":
    print(json.dumps({"candidates": [{"title": "x", "type": "nope"}]})); sys.exit(0)
if mode == "notobject":
    print(json.dumps([{"title": "x"}])); sys.exit(0)
if mode == "nosources":
    print(json.dumps({"candidates": [{"title": "t", "body": "b"}]})); sys.exit(0)
print(open(payload_path, encoding="utf-8").read())
'''


class GenerateBaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "memory").mkdir(parents=True, exist_ok=True)
        (self.root / "memory" / "decisions.org").write_text(DECISIONS, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)
        self.llm_payload = self.root / "payload.json"
        self.llm_script = self.root / "fake_llm.py"
        self.llm_script.write_text(FAKE_LLM, encoding="utf-8")
        self.set_payload([{"title": "场景：构建流程", "body": "版本一：构建走 bin/test",
                           "type": "decision", "topic": "build"}])
        self.cfg = GenerateConfig()

    def set_payload(self, items: list[dict]) -> None:
        self.llm_payload.write_text(json.dumps({"candidates": items}, ensure_ascii=False), encoding="utf-8")

    @property
    def llm(self) -> str:
        return "python3 " + str(self.llm_script) + " " + str(self.llm_payload)

    def run_condense(self, **kwargs):
        params = dict(scope="pm_tools", topic="build", config=self.cfg, llm=self.llm, actor="ai")
        params.update(kwargs)
        return generate.generate(self.root, "condense", **params)

    def candidates_text(self) -> str:
        path = self.root / memory.CANDIDATES_RELATIVE
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def org_fingerprints(self) -> dict:
        out = {}
        for path in sorted(self.root.rglob("*.org")):
            if path == self.root / memory.CANDIDATES_RELATIVE:
                continue
            out[path.relative_to(self.root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return out


class CandidateOnlyTest(GenerateBaseTest):
    def test_condense_writes_only_candidates(self) -> None:
        """§9-1：只产候选 —— memory/*.org 与 memory/l2/** 一字不改，候选区有新增。"""
        before = self.org_fingerprints()
        report = self.run_condense()
        self.assertEqual(len(report["written"]), 1)
        self.assertTrue(report["changed"])
        self.assertEqual(before, self.org_fingerprints())
        text = self.candidates_text()
        self.assertIn(":PM_STATUS: CANDIDATE", text)
        self.assertIn(":PM_LAYER: L2", text)
        self.assertIn(":PM_SOURCES: memory-gen-001@2 memory-gen-002@1", text)
        self.assertIn(":PM_TOPIC: build", text)

    def test_skeleton_needs_no_llm(self) -> None:
        """方案 C：不调 LLM 只产「待归纳清单」，且不编造正文。"""
        report = self.run_condense(llm="", skeleton=True, config=GenerateConfig(llm=""))
        self.assertEqual(report["generatedBy"], "skeleton")
        self.assertEqual(len(report["written"]), 1)
        self.assertIn("待归纳清单", self.candidates_text())
        self.assertIn("memory-gen-001@2", self.candidates_text())


class IdempotencyTest(GenerateBaseTest):
    def test_same_input_rerun_is_idempotent(self) -> None:
        """§9-2：同输入重跑 ⇒ changed:false、条目数不变。"""
        first = self.run_condense()
        self.assertEqual(len(first["written"]), 1)
        second = self.run_condense()
        self.assertFalse(second["changed"])
        self.assertTrue(second.get("idempotent"))
        self.assertEqual(second["written"], [])
        self.assertEqual(self.candidates_text().count(":PM_STATUS: CANDIDATE"), 1)

    def test_stale_only_skips_fresh_target(self) -> None:
        self.run_condense()
        report = self.run_condense(stale_only=True)
        self.assertFalse(report["changed"])
        self.assertIn("stale-only", report["note"])
        self.assertEqual(self.candidates_text().count(":PM_STATUS: CANDIDATE"), 1)


class SupersedeTest(GenerateBaseTest):
    def test_rerun_with_new_content_supersedes_old_candidate(self) -> None:
        """§9-3：旧候选转 DEPRECATED + 双向 SUPERSEDES 链。"""
        first = self.run_condense()
        self.set_payload([{"title": "场景：构建流程", "body": "版本二：构建走 bin/test -v",
                           "type": "decision", "topic": "build"}])
        second = self.run_condense()
        text = self.candidates_text()
        self.assertEqual(len(second["superseded"]), 1)
        self.assertIn(":PM_STATUS: DEPRECATED", text)
        self.assertIn(":PM_SUPERSEDES: " + first["written"][0], text)
        self.assertIn(":PM_SUPERSEDED_BY: " + second["written"][0], text)
        self.assertEqual(text.count(":PM_STATUS: CANDIDATE"), 1)

    def test_verified_entry_is_never_auto_deprecated(self) -> None:
        """安全策略：AI 不得把人确认过的 VERIFIED 自动降级 ⇒ 只挂链 + 给出人的命令。"""
        memory.write_scene(self.root, scope="pm_tools", scene="build", title="场景：构建流程",
                           body="已确认的版本", sources=["memory-gen-001@2"], type="decision",
                           status=memory.STATUS_VERIFIED, actor="human")
        # 让 L2 文件带上目标键（生成命令用 topic 作为目标键）
        path = memory.scene_path(self.root, "pm_tools", "build")
        text = path.read_text(encoding="utf-8").replace(":PM_REVISION: 1", ":PM_TOPIC: build\n   :PM_REVISION: 1")
        path.write_text(text, encoding="utf-8")
        # ① 产出与既有 VERIFIED **逐字一致** ⇒ 幂等：既不改文件，也不应该有取代动作
        self.set_payload([{"title": "场景：构建流程", "body": "已确认的版本", "type": "decision",
                           "sources": ["memory-gen-001@2"]}])
        report = self.run_condense()
        self.assertFalse(report["changed"])
        self.assertEqual(report["pendingHumanSupersede"], [])
        # ② 内容变了 ⇒ 只挂 pending（旧的是 VERIFIED，AI 不得自动降级）
        self.set_payload([{"title": "场景：构建流程", "body": "另一个版本", "type": "decision"}])
        report = self.run_condense()
        pending = report["pendingHumanSupersede"]
        self.assertEqual(len(pending), 1)
        self.assertIn("pm memory deprecate", pending[0]["command"])
        self.assertIn(":PM_STATUS: VERIFIED", path.read_text(encoding="utf-8"))


class FailureTest(GenerateBaseTest):
    def _assert_fails_clean(self, expected_code: str, **kwargs) -> None:
        before = self.candidates_text()
        with self.assertRaises(generate.GenerateError) as ctx:
            self.run_condense(**kwargs)
        self.assertEqual(ctx.exception.code, expected_code)
        self.assertEqual(self.candidates_text(), before)   # 一字节不写

    def test_no_llm_is_refused(self) -> None:
        self._assert_fails_clean("LLM_REQUIRED", llm="", config=GenerateConfig(llm=""))

    def test_llm_failure(self) -> None:
        os.environ["FAKE_MODE"] = "fail"
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)
        self._assert_fails_clean("LLM_FAILED")

    def test_llm_bad_json(self) -> None:
        os.environ["FAKE_MODE"] = "badjson"
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)
        self._assert_fails_clean("LLM_BAD_JSON")

    def test_llm_empty_output(self) -> None:
        os.environ["FAKE_MODE"] = "empty"
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)
        self._assert_fails_clean("LLM_EMPTY")

    def test_llm_schema_unknown_key(self) -> None:
        os.environ["FAKE_MODE"] = "badschema"
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)
        self._assert_fails_clean("LLM_SCHEMA")

    def test_llm_schema_bad_type(self) -> None:
        os.environ["FAKE_MODE"] = "badtype"
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)
        self._assert_fails_clean("LLM_SCHEMA")

    def test_llm_top_level_not_object(self) -> None:
        os.environ["FAKE_MODE"] = "notobject"
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)
        self._assert_fails_clean("LLM_SCHEMA")

    def test_budget_max_candidates(self) -> None:
        self.set_payload([{"title": "a"}, {"title": "b"}, {"title": "c"}])
        self._assert_fails_clean("TOO_MANY_CANDIDATES", config=GenerateConfig(max_candidates=2))

    def test_budget_max_input_bytes(self) -> None:
        self._assert_fails_clean("INPUT_TOO_LARGE", config=GenerateConfig(max_input_bytes=256))

    def test_no_material(self) -> None:
        with self.assertRaises(generate.GenerateError) as ctx:
            generate.generate(self.root, "condense", scope="nobody", config=self.cfg, llm=self.llm)
        self.assertEqual(ctx.exception.code, "NO_MATERIAL")

    def test_extract_needs_real_session(self) -> None:
        with self.assertRaises(generate.GenerateError) as ctx:
            generate.generate(self.root, "extract", session="does-not-exist", instances=[])
        self.assertEqual(ctx.exception.code, "INSTANCE_NOT_FOUND")


class AnchorAndStaleTest(GenerateBaseTest):
    def test_candidate_anchors_are_revision_pins_and_stale_works(self) -> None:
        """§9-5：L2 候选的锚点是 id@rev；L1 变了 ⇒ 该候选被 stale 指出。"""
        self.run_condense()
        report = index.stale_check(self.root)
        self.assertEqual(report["fresh"], 1)
        self.assertEqual(report["stale"], [])
        from pm import entities
        entities.apply_change(self.root / "memory" / "decisions.org", "memory-gen-002",
                              expected_revision=1, replace_body=["改过。"], actor="ai", reason="测试抬版本")
        report = index.stale_check(self.root)
        self.assertEqual(len(report["stale"]), 1)
        self.assertIn("memory-gen-002 revision 1 → 2", report["stale"][0]["problems"][0])

    def test_dropped_sources_are_reported_not_silent(self) -> None:
        """LLM 给了材料外的来源 ⇒ 丢弃但必须报出来（不静默）。"""
        self.set_payload([{"title": "t", "body": "b", "type": "fact",
                           "sources": ["memory-gen-001@2", "memory-hallucinated@9"]}])
        report = self.run_condense()
        self.assertEqual(report["droppedSources"], ["memory-hallucinated@9"])
        self.assertIn(":PM_SOURCES: memory-gen-001@2", self.candidates_text())

    def test_empty_candidate_list_is_a_clean_noop(self) -> None:
        self.set_payload([])
        report = self.run_condense()
        self.assertEqual(report["candidates"], 0)
        self.assertFalse(report["changed"])
        self.assertEqual(self.candidates_text(), "")


class ConfigSectionTest(unittest.TestCase):
    def test_generate_section_defaults_and_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pm.toml"
            path.write_text('library = "' + tmp + '"\n\n[memory.generate]\nllm = "my-llm --json"\n'
                            'timeout_s = 60\nmax_input_bytes = 4096\nmax_candidates = 5\n', encoding="utf-8")
            config, _warnings = load_config(str(path))
            self.assertEqual(config.generate.llm, "my-llm --json")
            self.assertEqual(config.generate.timeout_s, 60)
            self.assertEqual(config.generate.max_input_bytes, 4096)
            self.assertEqual(config.generate.max_candidates, 5)
            self.assertFalse(config.generate.allow_network)

    def test_generate_section_rejects_bad_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pm.toml"
            path.write_text('library = "' + tmp + '"\n\n[memory.generate]\ntimeout_s = 0\n', encoding="utf-8")
            with self.assertRaises(ConfigPathError) as ctx:
                load_config(str(path))
            self.assertEqual(ctx.exception.code, "CONFIG_INVALID")

    def test_generate_section_rejects_unknown_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pm.toml"
            path.write_text('library = "' + tmp + '"\n\n[memory.generate]\nwhoops = 1\n', encoding="utf-8")
            with self.assertRaises(ConfigPathError) as ctx:
                load_config(str(path))
            self.assertEqual(ctx.exception.code, "CONFIG_INVALID")


if __name__ == "__main__":
    unittest.main()
