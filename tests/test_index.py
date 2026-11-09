"""tests/test_index.py —— 记忆内容索引（P0）判据。

覆盖卡片的验收口径：
0. 索引是派生物：删 .local/index.sqlite 后重建，recall 结果逐条一致；
1. 命中带 path:line + revision；
2. 默认口径：L3 不出现；CANDIDATE / DEPRECATED 要靠显式开关；
3. FTS5 不可用 → LIKE 降级并在输出里说明（PM_INDEX_FORCE_LIKE=1 真跑这条路径）；
4. 增量：文件未变则跳过刷新，结果与全量重建一致；
5. 只读：跑完 index/recall 后 *.org 的 sha/mtime/size 不变。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pm import index, memory

FACTS_ORG = """* Facts
** 记忆检索用 SQLite FTS5 做派生物索引
   :PROPERTIES:
   :ID: memory-p0-001
   :PM_STATUS: VERIFIED
   :PM_SCOPE: pm_tools
   :PM_TYPE: fact
   :PM_REVISION: 7
   :END:
   索引落 .local/index.sqlite，可删可重建，永不回写 Org。
** 一条被废弃的旧事实
   :PROPERTIES:
   :ID: memory-p0-002
   :PM_STATUS: DEPRECATED
   :PM_SCOPE: pm_tools
   :PM_TYPE: fact
   :PM_REVISION: 3
   :END:
   这条已经废弃，默认不该出现。
"""

CANDIDATES_ORG = """* Memory Candidates
** 候选：命中必须带来源行号
   :PROPERTIES:
   :ID: memory-p0-003
   :PM_STATUS: CANDIDATE
   :PM_LAYER: L1
   :PM_SCOPE: pm_tools
   :PM_TYPE: fact
   :PM_REVISION: 4
   :END:
   命中必须带 path:line 与 revision。
** 一条 L2 候选（P0 不收）
   :PROPERTIES:
   :ID: memory-p0-004
   :PM_STATUS: CANDIDATE
   :PM_LAYER: L2
   :PM_REVISION: 1
   :END:
   L2 的候选这一阶段不索引。
** 一条 L3 候选（永不进召回）
   :PROPERTIES:
   :ID: memory-p0-005
   :PM_STATUS: CANDIDATE
   :PM_LAYER: L3
   :PM_REVISION: 1
   :END:
   常驻准则关键词：紫罗兰协议，永远不该出现在召回里。
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fingerprint(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*.org")):
        stat = path.stat()
        out[str(path.relative_to(root))] = (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            stat.st_mtime_ns,
            stat.st_size,
        )
    return out


class IndexBaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root / "memory" / "facts.org", FACTS_ORG)
        _write(self.root / "memory-candidates.org", CANDIDATES_ORG)
        self.addCleanup(self._tmp.cleanup)
        # 每个用例都从"没有索引"开始（索引是派生物）
        self._reset_fts_cache()

    def _reset_fts_cache(self) -> None:
        index._FTS5_CACHE = None

    def _recall_json(self, query: str, **kwargs) -> str:
        return json.dumps(index.recall(self.root, query, **kwargs), ensure_ascii=False, sort_keys=True)


class BuildAndDeterminismTest(IndexBaseTest):
    def test_rebuild_is_deterministic_after_delete(self) -> None:
        """判据 0：删掉 .local/index.sqlite 后重建，recall 结果逐条一致。"""
        index.build(self.root, rebuild=True)
        before = self._recall_json("检索", include_candidate=True)
        db = index.index_path(self.root)
        self.assertTrue(db.is_file())
        db.unlink()
        index.build(self.root, rebuild=True)
        after = self._recall_json("检索", include_candidate=True)
        self.assertEqual(before, after)
        self.assertIn("memory/facts.org:2", before)

    def test_only_l1_and_l2_are_indexed(self) -> None:
        """索引只收 L1 与 L2（M3 起 L2 纳入）；**L3 连索引都不建**。"""
        index.build(self.root, rebuild=True)
        con = sqlite3.connect(str(index.index_path(self.root)))
        try:
            layers = {row[0] for row in con.execute("SELECT DISTINCT layer FROM entries")}
            ids = {row[0] for row in con.execute("SELECT id FROM entries")}
        finally:
            con.close()
        self.assertEqual(layers, {"L1", "L2"})
        self.assertIn("memory-p0-004", ids)      # L2 候选自 M3 起进索引
        self.assertNotIn("memory-p0-005", ids)   # L3 永不进

    def test_incremental_skips_unchanged_files(self) -> None:
        """判据 4：第二次 index 不重刷未变文件，且结果与重建一致。"""
        first = index.build(self.root, rebuild=True)
        self.assertEqual(sorted(first["filesChanged"]), ["memory-candidates.org", "memory/facts.org"])
        second = index.build(self.root)
        self.assertEqual(second["filesChanged"], [])
        self.assertEqual(sorted(second["filesSkipped"]), ["memory-candidates.org", "memory/facts.org"])
        self.assertEqual(self._recall_json("检索", include_candidate=True), self._recall_json("检索", include_candidate=True, auto_build=False))

    def test_touch_file_triggers_refresh(self) -> None:
        index.build(self.root, rebuild=True)
        _write(self.root / "memory" / "facts.org", FACTS_ORG.replace("可删可重建", "可随时删除重建"))
        stats = index.build(self.root)
        self.assertEqual(stats["filesChanged"], ["memory/facts.org"])
        con = sqlite3.connect(str(index.index_path(self.root)))
        try:
            body = con.execute("SELECT body FROM entries WHERE id = ?", ("memory-p0-001",)).fetchone()[0]
        finally:
            con.close()
        self.assertIn("可随时删除重建", body)
        self.assertNotIn("可删可重建", body)


class RecallDefaultsTest(IndexBaseTest):
    def setUp(self) -> None:
        super().setUp()
        index.build(self.root, rebuild=True)

    def test_hit_carries_path_line_and_revision(self) -> None:
        """判据 1：命中必带 path:line 与 revision。"""
        result = index.recall(self.root, "检索")
        self.assertEqual(result["count"], 1)
        hit = result["hits"][0]
        self.assertEqual(hit["path"], "memory/facts.org")
        self.assertEqual(hit["line"], 2)
        self.assertEqual(hit["revision"], 7)
        self.assertEqual(hit["source"], "memory/facts.org:2")
        self.assertEqual(hit["status"], "VERIFIED")

    def test_candidate_hidden_by_default(self) -> None:
        """判据 2 反例：不加开关时候选不出现。"""
        self.assertEqual(index.recall(self.root, "来源")["count"], 0)
        shown = index.recall(self.root, "来源", include_candidate=True)
        self.assertEqual(shown["count"], 1)
        self.assertEqual(shown["hits"][0]["status"], "CANDIDATE")

    def test_deprecated_hidden_by_default(self) -> None:
        """判据 2：默认排除 DEPRECATED，显式开关才出现。"""
        self.assertEqual(index.recall(self.root, "废弃")["count"], 0)
        self.assertEqual(index.recall(self.root, "废弃", include_deprecated=True)["count"], 1)

    def test_l3_never_returned_even_with_flags(self) -> None:
        """判据 2 反例：L3 关键词在任何开关下都不出现。"""
        for kwargs in ({}, {"include_candidate": True}, {"include_candidate": True, "include_deprecated": True}):
            self.assertEqual(index.recall(self.root, "紫罗兰协议", **kwargs)["count"], 0, kwargs)

    def test_scope_and_type_filters(self) -> None:
        self.assertEqual(index.recall(self.root, "检索", scope="pm_tools")["count"], 1)
        self.assertEqual(index.recall(self.root, "检索", scope="nope")["count"], 0)
        self.assertEqual(index.recall(self.root, "检索", type="decision")["count"], 0)

    def test_limit_applies(self) -> None:
        result = index.recall(self.root, "检索", include_candidate=True, limit=1)
        self.assertEqual(result["count"], 1)


class DegradationTest(IndexBaseTest):
    def test_force_like_builds_without_fts_and_announces(self) -> None:
        """判据 3：FTS5 不可用时走 LIKE，并在输出里明说降级（真跑，不是纸上）。"""
        with mock.patch.dict(os.environ, {index.FORCE_LIKE_ENV: "1"}):
            self._reset_fts_cache()
            stats = index.build(self.root, rebuild=True)
            self.assertEqual(stats["mode"], "like")
            self.assertTrue(stats["degraded"])
            con = sqlite3.connect(str(index.index_path(self.root)))
            try:
                has_fts = con.execute("SELECT name FROM sqlite_master WHERE name='entries_fts'").fetchone()
            finally:
                con.close()
            self.assertIsNone(has_fts)
            result = index.recall(self.root, "检索", include_candidate=True)
            self.assertTrue(result["degraded"])
            self.assertEqual(result["mode"], "like")
            self.assertIsNotNone(result["note"])
            self.assertIn("降级", result["note"])
            self.assertGreaterEqual(result["count"], 1)
        self._reset_fts_cache()

    def test_prefix_and_midtoken_both_hit_via_fts(self) -> None:
        """v2（unigram）后：词首前缀与**词中**匹配都走 FTS；LIKE 只在 FTS5 不可用时兜底。

        这条是从旧断言成对更新来的：v1 时「检索」在「记忆检索用」中间只能退 LIKE（已知限制），
        v2 把连续 CJK 按字拆开索引 + 查询同拆 ⇒ 词中也走 FTS。
        """
        index.build(self.root, rebuild=True)
        # 「记忆检索」是 token「记忆检索用」的前缀 ⇒ FTS5 前缀命中
        prefix = index.recall(self.root, "记忆检索")
        self.assertEqual(prefix["mode"], "fts5")
        self.assertEqual(prefix["count"], 1)
        self.assertEqual(prefix["hits"][0]["source"], "memory/facts.org:2")
        # 「检索」在「记忆检索用」中间 ⇒ v2 起同样走 FTS（不再退 LIKE）
        mid = index.recall(self.root, "检索", include_candidate=True)
        self.assertEqual(mid["mode"], "fts5")
        self.assertIsNone(mid["note"])
        self.assertGreaterEqual(mid["count"], 1)

    def test_index_missing_is_reported(self) -> None:
        with self.assertRaises(index.IndexError_) as ctx:
            index.recall(self.root, "检索", auto_build=False)
        self.assertEqual(ctx.exception.code, "INDEX_MISSING")

    def test_empty_query_is_rejected(self) -> None:
        with self.assertRaises(index.IndexError_) as ctx:
            index.recall(self.root, "   ")
        self.assertEqual(ctx.exception.code, "QUERY_REQUIRED")


class ReadOnlyTest(IndexBaseTest):
    def test_org_files_untouched_by_index_and_recall(self) -> None:
        """判据 5：跑完 index/recall 后所有 *.org 的 sha/mtime/size 不变。"""
        before = _fingerprint(self.root)
        index.build(self.root, rebuild=True)
        index.recall(self.root, "检索", include_candidate=True)
        index.build(self.root)
        self.assertEqual(_fingerprint(self.root), before)

    def test_index_lives_under_local_and_is_rebuildable(self) -> None:
        index.build(self.root, rebuild=True)
        db = index.index_path(self.root)
        self.assertEqual(db.relative_to(self.root).as_posix(), ".local/index.sqlite")
        self.assertTrue(db.is_file())
        index.build(self.root, rebuild=True)
        self.assertTrue(db.is_file())


class FreshLibraryTest(IndexBaseTest):
    """全新库 / 陈旧索引 / 空库 —— 这三条是"静默空结果"防线（Lead 2026-10-16 复现后加硬）。"""

    def test_first_recall_on_fresh_library_hits(self) -> None:
        """全新库（还没有 .local）首次 recall：按需建索引并命中，不能返回空。"""
        self.assertFalse(index.index_path(self.root).is_file())
        result = index.recall(self.root, "记忆检索")
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["indexBuiltNow"])
        self.assertEqual(result["library"], str(self.root))
        self.assertGreaterEqual(result["indexEntries"], 1)

    def test_empty_library_errors_instead_of_silent_zero(self) -> None:
        """空库（或库选错）必须非零退出并说明，绝不允许 count=0 且不说明。"""
        empty = self.root.parent / (self.root.name + "-empty")
        empty.mkdir()
        with self.assertRaises(index.IndexError_) as ctx:
            index.recall(empty, "任意查询")
        self.assertEqual(ctx.exception.code, "INDEX_EMPTY")
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertIn(str(empty), ctx.exception.message)

    def test_stale_index_is_refreshed_before_query(self) -> None:
        """索引旧了（文件后来才改）也必须刷新 —— verify/render 之后立刻查就要是对读数。"""
        index.build(self.root, rebuild=True)
        self.assertEqual(index.recall(self.root, "追加的新判据")["count"], 0)
        _write(
            self.root / "memory" / "facts.org",
            FACTS_ORG + """** 追加的新判据条目
   :PROPERTIES:
   :ID: memory-p0-006
   :PM_STATUS: VERIFIED
   :PM_SCOPE: pm_tools
   :PM_TYPE: fact
   :PM_REVISION: 1
   :END:
   这条是追加的新判据，索引必须自己刷新。
""",
        )
        result = index.recall(self.root, "追加的新判据")  # 不显式跑 index
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["hits"][0]["source"], index.recall(self.root, "追加的新判据")["hits"][0]["source"])


class CliContractTest(unittest.TestCase):
    def test_index_json_error_path_never_traces_back(self) -> None:
        """pm index --json：无论走到哪条路径，都必须是干净结论（0 或 2）+ 无 traceback。

        这条判据防的是原缺陷：错误路径上 _fail 参数串位 → TypeError + traceback + exit 1。
        不断言"一定是 NEEDS_YES"—— 环境里若真有可用配置（DSH_UI_PM_CONFIG/PM_CONFIG/./pm.toml），
        走到"真写索引"也是合法结论（exit 0）；但**绝不能**出现 traceback/exit 1。
        """
        import subprocess
        repo = Path(__file__).resolve().parent.parent
        env = {k: v for k, v in os.environ.items() if k not in {"DSH_UI_PM_CONFIG", "PM_CONFIG", "PM_DSH_HOME"}}
        env["PYTHONPATH"] = str(repo / "src")
        proc = subprocess.run(
            [sys.executable, "-m", "pm", "index", "--json"],
            cwd=str(repo), capture_output=True, text=True, env=env,
        )
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn(proc.returncode, (0, 2), proc.stderr)
        payload = json.loads(proc.stdout)
        if proc.returncode == 2:
            self.assertFalse(payload["ok"])
            self.assertIn(payload["error"]["code"], {"NEEDS_YES", "CONFIG_NOT_FOUND", "NO_LIBRARY", "LIBRARY_MISSING"})
        else:
            self.assertTrue(payload["ok"])
            self.assertIn("data", payload)


class ConfigPositionTest(unittest.TestCase):
    """默认形态 = 打包安装形态：env 里没有 DSH_UI_PM_CONFIG/PM_CONFIG，库【只由 --config 指定】。

    这条是 dsh-plugin / pm-api 在真机上撞出来的生产缺陷（2026-10-16）：
    子命令的 --config 默认值把父级解析结果冲成 None ⇒ 静默读默认库 ⇒ count=0 看起来像"没这条记忆"。
    """

    TOKEN = "青枫判据"
    ENV_KEYS = ("DSH_UI_PM_CONFIG", "PM_CONFIG", "PM_DSH_HOME")

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self._tmp.name)
        _write(self.lib / "memory" / "facts.org", """* Facts
** 只在配置库里存在的记忆 token: """ + self.TOKEN + """
   :PROPERTIES:
   :ID: memory-cfg-001
   :PM_STATUS: VERIFIED
   :PM_SCOPE: pm_tools
   :PM_TYPE: fact
   :PM_REVISION: 5
   :END:
   这条记忆只在夹具库里，默认真库里没有。
""")
        _write(self.lib / "pm.toml", 'library = "' + str(self.lib) + '"\n')
        self.cfg = self.lib / "pm.toml"
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(__file__).resolve().parent.parent

    def _run(self, argv, *, with_env=False):
        import subprocess
        env = {k: v for k, v in os.environ.items() if k not in self.ENV_KEYS}
        env["PYTHONPATH"] = str(self.repo / "src")
        if with_env:
            env["DSH_UI_PM_CONFIG"] = str(self.cfg)
            env["PM_CONFIG"] = str(self.cfg)
        return subprocess.run([sys.executable, "-m", "pm"] + argv, cwd=str(self.repo),
                              capture_output=True, text=True, env=env)

    def test_recall_config_only_parent_position(self) -> None:
        """D-prime（默认形态）：清 env + 只用父级 --config ⇒ 必须命中且 library 指向该库。"""
        proc = self._run(["--config", str(self.cfg), "recall", "--query", self.TOKEN, "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)["data"]
        self.assertEqual(data["library"], str(self.lib))
        self.assertGreaterEqual(data["count"], 1)
        self.assertEqual(data["hits"][0]["source"], "memory/facts.org:2")

    def test_recall_config_only_subcommand_position(self) -> None:
        proc = self._run(["recall", "--config", str(self.cfg), "--query", self.TOKEN, "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)["data"]
        self.assertEqual(data["library"], str(self.lib))
        self.assertGreaterEqual(data["count"], 1)

    def test_index_config_only_never_needs_yes(self) -> None:
        """子命令位置与父级位置的 --config 都算"显式指定"，不得报 NEEDS_YES。"""
        for argv in (["--config", str(self.cfg), "index", "--rebuild"],
                     ["index", "--rebuild", "--config", str(self.cfg)]):
            proc = self._run(argv)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertNotIn("NEEDS_YES", proc.stdout + proc.stderr)

    def test_env_variant_still_works(self) -> None:
        """附加变体（导出两个 env）不能被这次修复弄坏。"""
        proc = self._run(["recall", "--query", self.TOKEN, "--json"], with_env=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)["data"]
        self.assertEqual(data["library"], str(self.lib))
        self.assertGreaterEqual(data["count"], 1)


class SentenceMatchTest(IndexBaseTest):
    """整句输入（真实消费者：前端搜索框 / hook 的 prompt / M4 注入）。

    Lead + pm-api 2026-10-16 实测：词间 AND 会让「多一个对不上的词」整条丢掉 ⇒ 需要
    ① 整句输入能命中（防漏）② 无关输入仍 0 命中（防滥）③ 输出标明用了哪种匹配。
    """

    def setUp(self) -> None:
        super().setUp()
        index.build(self.root, rebuild=True)

    def test_plain_query_reports_and(self) -> None:
        result = index.recall(self.root, "记忆检索")
        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["match"], "and")

    def test_full_sentence_with_stopword_hits_strictly(self) -> None:
        """成对更新（2026-10-18，自然语言 bug 修复后）：停用词被剥离 ⇒ 不必放宽就命中。

        改前：整句被当成一个 term ⇒ AND 要求整句命中 ⇒ 只能靠自动放宽到 match=any；
        改后：query_runs 去掉「是/什么」⇒ 内容 run=[记忆检索] ⇒ 严格路径直接命中（match=and）。
        """
        result = index.recall(self.root, "记忆检索 是什么")
        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["match"], "and")
        self.assertIsNone(result["note"])

    def test_full_sentence_falls_back_to_any(self) -> None:
        """真正放不进去的整句（含一个库里没有的内容词）⇒ 自动放宽为任一命中并说明。"""
        result = index.recall(self.root, "记忆检索 完全不存在zzz")
        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["match"], "any")
        self.assertIn("AND", result["note"])

    def test_irrelevant_query_still_returns_zero(self) -> None:
        """防滥：完全无关的词仍然 0 命中，而且 note 说的是「仍 0 命中」而不是假降级。"""
        result = index.recall(self.root, "zzzzqqqq 完全不存在xyz")
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["match"], "like")
        self.assertIn("仍 0 命中", result["note"])
        self.assertNotIn("FTS5 不可用", result["note"])

    def test_any_flag_forces_or(self) -> None:
        result = index.recall(self.root, "记忆检索 完全不存在xyz", any_mode=True)
        self.assertEqual(result["match"], "any")
        self.assertGreaterEqual(result["count"], 1)

    def test_and_mode_requires_all_terms(self) -> None:
        both = index.recall(self.root, "记忆检索 索引")
        self.assertEqual(both["match"], "and")
        self.assertGreaterEqual(both["count"], 1)


class UnigramIndexTest(IndexBaseTest):
    """词中匹配（Lead 2026-10-16 批）：连续 CJK 按字拆开进索引、查询侧同样拆 ⇒ 词中也走 FTS。

    改造前：unicode61 把「记忆检索用」当一个 token ⇒ 查「检索」FTS 永不命中，只能退 LIKE。
    """

    def setUp(self) -> None:
        super().setUp()
        index.build(self.root, rebuild=True)

    def test_normalize_splits_cjk_only(self) -> None:
        self.assertEqual(index.normalize_for_fts("记忆检索用 SQLite FTS5"),
                         "记 忆 检 索 用 SQLite FTS5")
        self.assertEqual(index.normalize_for_fts(""), "")

    def test_mid_token_query_hits_via_fts(self) -> None:
        """「检索」在「记忆检索用」中间 —— 现在必须走 FTS（不再退 LIKE）。"""
        result = index.recall(self.root, "检索")
        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["mode"], "fts5")
        self.assertEqual(result["match"], "and")
        self.assertNotIn("LIKE", result["note"] or "")
        self.assertEqual(result["hits"][0]["path"], "memory/facts.org")

    def test_mid_token_in_sentence_still_any(self) -> None:
        """成对更新（2026-10-18）：句尾「是什么」被当停用词剥离 ⇒ 严格路径直接命中。

        改前：整句一个 term ⇒ 靠自动放宽到 match=any；改后：run=[检索] ⇒ match=and。
        """
        result = index.recall(self.root, "检索 是什么")
        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["match"], "and")

    def test_irrelevant_still_zero(self) -> None:
        self.assertEqual(index.recall(self.root, "zzzzqqqq 完全不存在xyz")["count"], 0)

    def test_old_schema_index_is_rebuilt_with_explanation(self) -> None:
        """盘上放一份 v1 形态的索引：必须自动整份重建 + 说明原因 + 结果与正常索引一致。"""
        expected = json.dumps(index.recall(self.root, "检索"), ensure_ascii=False, sort_keys=True)
        db = index.index_path(self.root)
        db.unlink()
        con = sqlite3.connect(str(db))
        con.executescript(
            "CREATE TABLE entries(rowid INTEGER PRIMARY KEY, id TEXT, layer TEXT NOT NULL, scope TEXT NOT NULL,"
            " type TEXT, status TEXT NOT NULL, revision INTEGER NOT NULL, path TEXT NOT NULL, line INTEGER NOT NULL,"
            " title TEXT, body TEXT, sources TEXT, source_rev TEXT, ts TEXT, file TEXT NOT NULL, file_sha TEXT NOT NULL);"
            "CREATE TABLE files(file TEXT PRIMARY KEY, sha TEXT NOT NULL, mtime REAL NOT NULL, size INTEGER NOT NULL, entries INTEGER NOT NULL);"
            "CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);"
            "INSERT INTO meta VALUES('schema_version','1');"
            "INSERT INTO entries(id, layer, scope, status, revision, path, line, title, body, file, file_sha)"
            " VALUES('stale-row','L1','pm_tools','VERIFIED',1,'memory/old.org',1,'旧索引残留','旧', 'memory/old.org','x');"
        )
        con.commit()
        con.close()
        stats = index.build(self.root)
        self.assertIn("schemaRebuilt", stats)
        self.assertIn("索引 schema 旧", stats["schemaRebuilt"])
        self.assertIn("整份重建", stats["schemaRebuilt"])
        con = sqlite3.connect(str(db))
        try:
            rows = [r[0] for r in con.execute("SELECT id FROM entries")]
            version = con.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()[0]
        finally:
            con.close()
        self.assertNotIn("stale-row", rows)      # 旧索引的残留被重建清掉（证明真的整份重建）
        self.assertEqual(version, index.SCHEMA_VERSION)
        after = json.dumps(index.recall(self.root, "检索", auto_build=False), ensure_ascii=False, sort_keys=True)
        self.assertEqual(expected, after)        # 重建不是改口径：同一查询结果逐字节一致

    def test_schema_version_mismatch_triggers_rebuild(self) -> None:
        db = index.index_path(self.root)
        con = sqlite3.connect(str(db))
        con.execute("UPDATE meta SET v = '1' WHERE k = 'schema_version'")
        con.commit()
        con.close()
        stats = index.build(self.root)
        self.assertIn("schemaRebuilt", stats)


class NaturalLanguageQueryTest(IndexBaseTest):
    """自然语言问句（用户真实输入）：查询侧去停用词取内容 run + 短语匹配。

    发布前 bug（Lead 2026-10-18 复现）：看板卡片被裁的真机制是什么？ ⇒ 0 字节
    （查询侧把整句当一个 term、LIKE 又要求整段是子串）；改用 run 切分后同句必须命中。
    """

    def setUp(self) -> None:
        super().setUp()
        index.build(self.root, rebuild=True)

    def test_plain_phrase(self) -> None:
        result = index.recall(self.root, "记忆检索")
        self.assertEqual(result["match"], "and")
        self.assertGreaterEqual(result["count"], 1)

    def test_natural_question_hits(self) -> None:
        """② 本次 bug 用例：句尾疑问词不得把整条丢掉。"""
        result = index.recall(self.root, "记忆检索是什么？")
        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["match"], "and")

    def test_natural_question_with_filler(self) -> None:
        """③ 「X 那到底是为啥呢」⇒ 命中。"""
        result = index.recall(self.root, "记忆检索 那到底是为啥呢")
        self.assertGreaterEqual(result["count"], 1)

    def test_irrelevant_sentence_zero(self) -> None:
        """④ 完全无关句 ⇒ 0（防滥）。"""
        self.assertEqual(index.recall(self.root, "完全无关zzz 到底咋回事呢")["count"], 0)

    def test_any_flag_on_multi_run(self) -> None:
        """⑤ 全句 AND 失败时 --any ⇒ 命中。"""
        result = index.recall(self.root, "记忆检索 完全不存在的词zzz", any_mode=True)
        self.assertEqual(result["match"], "any")
        self.assertGreaterEqual(result["count"], 1)

    def test_latin_sentence_with_stopwords(self) -> None:
        result = index.recall(self.root, "FTS5 是什么")
        self.assertGreaterEqual(result["count"], 1)

    def test_stopword_only_query_errors_loudly(self) -> None:
        """纯停用词 ⇒ 明确错误码，不静默 0。"""
        with self.assertRaises(index.IndexError_) as ctx:
            index.recall(self.root, "是什么？")
        self.assertEqual(ctx.exception.code, "QUERY_NO_TERMS")
        self.assertEqual(ctx.exception.exit_code, 2)

    def test_query_runs_contract(self) -> None:
        self.assertEqual(index.query_runs("看板卡片被裁的真机制是什么？"), ["看板卡片被裁", "真机制"])
        # 标识符内的 - 不拆（hooktok-abc123 整体一个 run）；只有停用词/标点才切分
        self.assertEqual(index.query_runs("hooktok-abc123 是什么"), ["hooktok-abc123"])
        self.assertEqual(index.query_runs("是什么？"), [])

    def test_salient_tokens_are_short_runs(self) -> None:
        """hook 的回退探测也要用短 run（原来挑最长的整句 ⇒ 救不回来）。"""
        from pm import hooks
        tokens = hooks.salient_tokens("看板卡片被裁的真机制是什么？")
        self.assertIn("看板卡片被裁", tokens)
        self.assertNotIn("看板卡片被裁的真机制是什么？", tokens)


if __name__ == "__main__":
    unittest.main()
