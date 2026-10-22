from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pm.config import Config, MergeRule
from pm.model import RUNTIME_UNKNOWN, Agent, CacheObservation, Goal, Todo
from pm.scan import scan, slugify, suggest_merges
from pm.sources import dsh_projcache, dsh_workspace

import fixtures

NOW = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)


def build(case: unittest.TestCase):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    home = fixtures.build_dsh_home(Path(tmp.name))
    config = Config(
        dsh_home=home,
        active_days=14,
        active_hours=24,
        merges=(MergeRule(key="alpha_beta", title="Alpha Beta", paths=(fixtures.ALPHA, fixtures.BETA)),),
        exclude_paths=("/home/tester",),
        row_limit=8,
    )
    registry = dsh_workspace.load(home)
    cache = dsh_projcache.load(
        home / "storages" / "session_projcache" / "sessions",
        archived_ids=registry.archived_session_ids,
        title_for_path=registry.title_for_path,
    )
    return config, registry, cache


def run(case: unittest.TestCase, **kw):
    config, registry, cache = build(case)
    return scan(config=config, registry=registry, cache=cache, now=NOW, **kw)


class GroupingTest(unittest.TestCase):
    def test_merge_rule_and_buckets(self) -> None:
        result = run(self)
        self.assertEqual([p.key for p in result.projects], ["alpha_beta"])
        self.assertEqual(result.projects[0].title, "Alpha Beta")
        self.assertEqual(result.projects[0].id, "proj-alpha_beta")
        self.assertEqual(len(result.projects[0].paths), 2)
        self.assertEqual([a.session_id for a in result.unregistered], [fixtures.UNKNOWN_CWD])
        self.assertEqual([a.session_id for a in result.ignored], [fixtures.HOME_CWD])

    def test_noise_filter_hides_empty_and_archived(self) -> None:
        result = run(self)
        shown = {a.session_id for a in result.projects[0].agents}
        self.assertIn(fixtures.ALPHA_RECENT, shown)
        self.assertIn(fixtures.BETA_OLD, shown)      # 有未完成任务，即使很久没记录
        self.assertIn(fixtures.STALLED, shown)
        self.assertIn(fixtures.FUTURE_VERSION, shown)
        self.assertNotIn(fixtures.ALPHA_EMPTY, shown)
        self.assertNotIn(fixtures.ALPHA_ARCHIVED, shown)
        self.assertEqual(result.hidden_agents, 2)

    def test_include_all_shows_everything(self) -> None:
        result = run(self, include_all=True, limit=0)
        self.assertEqual(len(result.projects[0].agents), 6)
        self.assertEqual(result.hidden_agents, 0)

    def test_row_limit_folds_extra_agents(self) -> None:
        result = run(self, include_all=True, limit=2)
        project = result.projects[0]
        self.assertEqual(len(project.agents), 2)
        self.assertEqual(project.hidden_agents, 4)
        self.assertEqual(result.hidden_by_limit, 4)

    def test_observation_and_ordering(self) -> None:
        result = run(self)
        seen = {
            a.session_id: a.observation_at(NOW) for a in result.projects[0].agents
        }
        self.assertIs(seen[fixtures.ALPHA_RECENT], CacheObservation.RECENT)
        self.assertIs(seen[fixtures.BETA_OLD], CacheObservation.IDLE)
        self.assertIs(seen[fixtures.STALLED], CacheObservation.STALE_BUSY)
        # 陈旧·忙碌 排在最前：卡住的会话比正常运转的更需要注意
        self.assertEqual(result.projects[0].agents[0].session_id, fixtures.STALLED)

    def test_source_instance_is_propagated(self) -> None:
        # 身份键 = (instance, session)；实例 id 在加载缓存时写进 agent
        from pm.config import Instance
        from pm.instances import load_all

        config, _registry, _cache = build(self)
        sources = load_all((Instance(id="test01", path=config.dsh_home),))
        result = scan(
            config=config,
            registry=sources.registry,
            cache=sources.cache,
            now=NOW,
            source_instances=sources.instance_ids,
        )
        self.assertEqual(result.source_instances, ("test01",))
        for agent in result.projects[0].agents:
            self.assertEqual(agent.source_instance, "test01")
            self.assertTrue(agent.identity_key.startswith("test01/"))
        self.assertEqual(result.source_versions, (7, 9))
        self.assertEqual(result.cache_files_skipped, 1)

    def test_only_project_filter(self) -> None:
        result = run(self, only_project="nope")
        self.assertEqual(result.projects, [])


class SuggestionTest(unittest.TestCase):
    def test_sibling_with_shared_token(self) -> None:
        config, registry, _ = build(self)
        paths = {s.workspace_path: s for s in suggest_merges(registry, config)}
        self.assertIn(fixtures.ALPHA_SIBLING, paths)
        self.assertEqual(paths[fixtures.ALPHA_SIBLING].candidate_project, "alpha_beta")
        self.assertNotIn(fixtures.OTHER, paths)  # demo01 与 alpha/beta 无共同词元

    def test_no_suggestion_for_merged_paths(self) -> None:
        config, registry, _ = build(self)
        suggested = {s.workspace_path for s in suggest_merges(registry, config)}
        self.assertNotIn(fixtures.ALPHA, suggested)
        self.assertNotIn(fixtures.BETA, suggested)


class HonestyTest(unittest.TestCase):
    """对齐 alpha 方案 §3 的硬约束：不允许把缓存观察包装成运行事实。"""

    def agent(self, **kw) -> Agent:
        base = dict(session_id="session-x", cwd="/w", title="t", turns=1)
        base.update(kw)
        return Agent(**base)

    def test_runtime_status_is_always_unknown(self) -> None:
        now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
        busy = self.agent(open_step="s1", last_active=now)
        self.assertIs(busy.observation_at(now), CacheObservation.BUSY)
        self.assertEqual(busy.runtime_status, RUNTIME_UNKNOWN)

    def test_busy_requires_recent_records(self) -> None:
        now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
        fresh = self.agent(open_step="s1", last_active=now - timedelta(hours=1))
        stale = self.agent(open_step="s1", last_active=now - timedelta(days=20))
        self.assertIs(fresh.observation_at(now), CacheObservation.BUSY)
        self.assertIs(stale.observation_at(now), CacheObservation.STALE_BUSY)
        self.assertTrue(stale.is_stale(now))

    def test_goal_complete_is_closed_not_done(self) -> None:
        now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
        agent = self.agent(
            last_active=now - timedelta(days=10),
            goal=Goal(id="g", objective="o", phase="complete"),
            todos=[Todo(content="a", status="completed")],
        )
        self.assertIs(agent.observation_at(now), CacheObservation.CLOSED)
        self.assertNotIn("DONE", {m.name for m in CacheObservation})

    def test_title_is_not_a_summary(self) -> None:
        agent = self.agent(title="You are working in the")
        self.assertEqual(agent.summary_status, "not_generated")
        self.assertEqual(agent.summary_text, "[待生成摘要]")
        # 标题仍可作为「卡标签」用于辨认，但不能冒充摘要
        self.assertEqual(agent.card_label, "You are working in the")
        agent.human_summary = "给 session-outbox 做连续推送合并"
        self.assertEqual(agent.summary_status, "human")
        self.assertEqual(agent.summary_text, "给 session-outbox 做连续推送合并")

    def test_recent_action_flags_prompt_sourced_text(self) -> None:
        from_goal = self.agent(goal=Goal(id="g", objective="目标文本", phase="active"))
        self.assertEqual(from_goal.recent_action(), ("目标文本", False))
        from_prompt = self.agent(first_prompt="第一行\n第二行")
        self.assertEqual(from_prompt.recent_action(), ("第一行", True))
        from_todo = self.agent(
            todos=[Todo("待办", "pending"), Todo("进行中", "in_progress")],
            goal=Goal(id="g", objective="目标", phase="active"),
        )
        self.assertEqual(from_todo.recent_action(), ("进行中", False))

    def test_empty_session(self) -> None:
        now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
        agent = self.agent(title="", turns=0, last_active=now)
        self.assertIs(agent.observation_at(now), CacheObservation.EMPTY)

    def test_archived_wins(self) -> None:
        now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
        agent = self.agent(archived=True, last_active=now, open_step="s1")
        self.assertIs(agent.observation_at(now), CacheObservation.ARCHIVED)


class SupportCheckTest(unittest.TestCase):
    def test_unknown_version_and_broken_file_are_reported(self) -> None:
        _, _, cache = build(self)
        problems = dsh_projcache.check_supported(cache)
        self.assertTrue(any("未经验证" in p for p in problems))
        self.assertTrue(any("无法解析" in p for p in problems))


class SlugTest(unittest.TestCase):
    def test_slugify(self) -> None:
        self.assertEqual(slugify("PeTree 张量处理器"), "petree")
        self.assertEqual(slugify("fix_deepseek-harness"), "fix_deepseek-harness")
        self.assertEqual(slugify("---"), "unnamed")


if __name__ == "__main__":
    unittest.main()
