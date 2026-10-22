from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pm.sources import dsh_projcache, dsh_workspace

import fixtures


class CanonicalSessionIdTest(unittest.TestCase):
    def test_forms(self) -> None:
        raw = "11111111-1111-4111-8111-111111111111"
        self.assertEqual(dsh_projcache.canonical_session_id(raw), f"session-{raw}")
        self.assertEqual(dsh_projcache.canonical_session_id(f"session-{raw}"), f"session-{raw}")
        self.assertEqual(dsh_projcache.canonical_session_id(f"session-{raw}.json"), f"session-{raw}")
        self.assertEqual(dsh_projcache.canonical_session_id(f".{raw}.tmp"), f"session-{raw}.tmp")


class WorkspaceRegistryTest(unittest.TestCase):
    def test_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = fixtures.build_dsh_home(Path(tmp))
            registry = dsh_workspace.load(home)
            self.assertEqual(len(registry.workspaces), 5)
            self.assertIn(fixtures.ALPHA_ARCHIVED, registry.archived_session_ids)
            self.assertEqual(registry.title_for_path(fixtures.ALPHA), "alpha")
            self.assertEqual(registry.title_for_path("/nope"), "")

    def test_missing_file_is_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = dsh_workspace.load(Path(tmp))
            self.assertEqual(registry.workspaces, ())
            self.assertTrue(registry.warnings)


class ProjCacheTest(unittest.TestCase):
    def load(self) -> dsh_projcache.CacheLoad:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = fixtures.build_dsh_home(Path(tmp.name))
        registry = dsh_workspace.load(home)
        return dsh_projcache.load(
            registry_path(home),
            archived_ids=registry.archived_session_ids,
            title_for_path=registry.title_for_path,
        )

    def test_skips_temp_and_broken_files(self) -> None:
        cache = self.load()
        # 目录里共 10 个文件：9 个 .json（其中 1 个非法 JSON）+ 1 个 .tmp 临时文件。
        # .tmp 在列举阶段就被排除，不计入 scanned；非法 JSON 计入 skipped。
        self.assertEqual(cache.scanned_files, 9)
        by_id = {a.session_id: a for a in cache.agents}
        self.assertNotIn(dsh_projcache.canonical_session_id(fixtures.BAD_JSON), by_id)
        self.assertEqual(len(cache.agents), 8)
        self.assertEqual(cache.skipped_files, 1)

    def test_warns_on_unknown_projection_version(self) -> None:
        cache = self.load()
        self.assertIn(9, cache.versions)
        self.assertTrue(any("未验证的 session_projcache 版本" in w for w in cache.warnings))

    def test_fields(self) -> None:
        cache = self.load()
        by_id = {a.session_id: a for a in cache.agents}
        agent = by_id[fixtures.ALPHA_RECENT]
        self.assertEqual(agent.title, "alpha work")
        self.assertEqual(agent.cwd, fixtures.ALPHA)
        self.assertEqual(agent.turns, 10)
        self.assertEqual(agent.todo_counts, (1, 3))
        self.assertEqual(agent.recent_action(), ("正在做的步骤", False))
        self.assertIsNotNone(agent.goal)
        assert agent.goal is not None
        self.assertEqual(agent.goal.phase, "active")
        self.assertTrue(agent.goal.is_active)

    def test_missing_last_prompt_falls_back_to_created_at(self) -> None:
        cache = self.load()
        by_id = {a.session_id: a for a in cache.agents}
        agent = by_id[fixtures.BETA_OLD]
        self.assertIsNotNone(agent.last_active)
        self.assertTrue(any("lastPromptAt" in w for w in agent.warnings))

    def test_null_goal_current_is_tolerated(self) -> None:
        cache = self.load()
        by_id = {a.session_id: a for a in cache.agents}
        self.assertIsNone(by_id[fixtures.BETA_OLD].goal)

    def test_archived_flag(self) -> None:
        cache = self.load()
        by_id = {a.session_id: a for a in cache.agents}
        self.assertTrue(by_id[fixtures.ALPHA_ARCHIVED].archived)
        self.assertFalse(by_id[fixtures.ALPHA_RECENT].archived)


def registry_path(home: Path) -> Path:
    return home / "storages" / "session_projcache" / "sessions"


if __name__ == "__main__":
    unittest.main()
