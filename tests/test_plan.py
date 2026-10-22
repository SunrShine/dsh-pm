from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pm.config import Config, MergeRule
from pm.layout import Layout
from pm.render import plan as plan_mod
from pm.render.plan import HUMAN, WriteOp, resolve_summaries
from pm.scan import scan
from pm.scaffold import plan_for
from pm.sources import dsh_projcache, dsh_workspace

import fixtures

NOW = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)
NOW_LATER = datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc)


def build(case: unittest.TestCase):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    base = Path(tmp.name)
    home = fixtures.build_dsh_home(base / "dsh")
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
    result = scan(
        config=config, registry=registry, cache=cache, now=NOW, include_all=True, limit=0
    )
    layout = Layout(base / "work-memory")
    for directory in layout.directories():
        directory.mkdir(parents=True, exist_ok=True)
    return layout, result


class GeneratedPlanTest(unittest.TestCase):
    def plans(self, layout, result, now=NOW):
        resolved = resolve_summaries(result, {}, {})
        return plan_mod.build_plan(layout, result, resolved, now=now)

    def test_all_ops_target_machine_owned_paths(self) -> None:
        layout, result = build(self)
        for op in self.plans(layout, result):
            self.assertTrue(layout.is_machine_owned(op.path), str(op.path))
            self.assertEqual(op.kind, "generated")

    def test_write_then_rewrite_is_unchanged(self) -> None:
        layout, result = build(self)
        ops = self.plans(layout, result)
        first = plan_mod.apply(ops, layout, write=True)
        self.assertTrue(first)
        self.assertTrue(all(item.action == "created" for item in first))
        second = plan_mod.apply(self.plans(layout, result), layout, write=True)
        self.assertTrue(all(item.action == "unchanged" for item in second))

    def test_dry_run_writes_nothing(self) -> None:
        layout, result = build(self)
        items = plan_mod.apply(self.plans(layout, result), layout, write=False)
        self.assertTrue(all(item.action == "create" for item in items))
        self.assertFalse(any(layout.generated_dir.rglob("*.org")))

    def test_content_is_deterministic_for_same_now(self) -> None:
        layout, result = build(self)
        a = {op.path: op.content for op in self.plans(layout, result)}
        b = {op.path: op.content for op in self.plans(layout, result)}
        self.assertEqual(a, b)

    def test_observation_can_flip_when_time_moves(self) -> None:
        # 同一份数据、不同的 now，只允许「观察」类字段变化，不允许出现墙钟时间串
        layout, result = build(self)
        a = {op.path: op.content for op in self.plans(layout, result, NOW)}
        b = {op.path: op.content for op in self.plans(layout, result, NOW_LATER)}
        self.assertEqual(set(a), set(b))

    def test_prompt_text_never_leaks_into_generated_files(self) -> None:
        layout, result = build(self)
        for op in self.plans(layout, result):
            self.assertNotIn("first prompt", op.content)
            self.assertNotIn("target prompt", op.content)

    def test_card_records_runtime_status_unknown(self) -> None:
        layout, result = build(self)
        cards = [op for op in self.plans(layout, result) if "/sessions/" in str(op.path)]
        self.assertTrue(cards)
        for card in cards:
            self.assertIn(":PM_RUNTIME_STATUS: unknown", card.content, "契约 token 不许动")
            # task-212：卡片文案改人话（快照口径）—— 判据随行为一起改，不长不短地钉住新句，
            # 并加一条"不许出现黑话「心跳」"的硬断言（比原来只有一句子串更强）。
            self.assertIn("快照里没有「此刻是否还在跑」的信号", card.content)
            self.assertNotIn("心跳", card.content)


class ScaffoldTest(unittest.TestCase):
    def test_existing_human_files_are_never_overwritten(self) -> None:
        layout, result = build(self)
        for path, _content in plan_for(layout, result.projects):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("我的内容，不许动\n", encoding="utf-8")
        ops = [
            WriteOp(path=path, content=content, kind=HUMAN, skip_if_exists=True)
            for path, content in plan_for(layout, result.projects)
        ]
        items = plan_mod.apply(ops, layout, write=True)
        self.assertTrue(all(item.action == "keep" for item in items))
        for path, _content in plan_for(layout, result.projects):
            self.assertEqual(path.read_text(encoding="utf-8"), "我的内容，不许动\n")

    def test_missing_human_files_are_created(self) -> None:
        layout, result = build(self)
        ops = [
            WriteOp(path=path, content=content, kind=HUMAN, skip_if_exists=True)
            for path, content in plan_for(layout, [result.projects[0]])
        ]
        items = plan_mod.apply(ops, layout, write=True)
        self.assertTrue(all(item.action == "created" for item in items))
        self.assertTrue(layout.overrides.is_file())
        self.assertTrue(layout.inbox.is_file())

    def test_scaffold_does_not_touch_generated_dir(self) -> None:
        layout, result = build(self)
        for path, _content in plan_for(layout, result.projects):
            self.assertFalse(layout.is_machine_owned(path), str(path))


class PrecedenceIntegrationTest(unittest.TestCase):
    def test_human_summary_wins_in_rendered_card(self) -> None:
        from pm.summaries import AI, HUMAN, SummaryEntry

        layout, result = build(self)
        key = result.projects[0].agents[0].identity_key
        human = {key: SummaryEntry(key, "人工摘要", HUMAN)}
        ai = {key: SummaryEntry(key, "AI 摘要", AI)}
        resolved = resolve_summaries(result, human, ai)
        ops = plan_mod.build_plan(layout, result, resolved, now=NOW)
        card = next(op for op in ops if key.split("/")[1] in str(op.path))
        self.assertIn("人工摘要", card.content)
        self.assertNotIn("AI 摘要", card.content)
        self.assertIn(":PM_SUMMARY_SOURCE: human", card.content)

    def test_ai_summary_used_when_no_human(self) -> None:
        from pm.summaries import AI, SummaryEntry

        layout, result = build(self)
        key = result.projects[0].agents[0].identity_key
        ai = {key: SummaryEntry(key, "AI 摘要", AI, generated_by="m", generated_at="2026-10-10T12:00:00+0800")}
        resolved = resolve_summaries(result, {}, ai)
        ops = plan_mod.build_plan(layout, result, resolved, now=NOW)
        card = next(op for op in ops if key.split("/")[1] in str(op.path))
        self.assertIn("AI 摘要", card.content)
        self.assertIn(":PM_SUMMARY_SOURCE: ai", card.content)


class LinkIntegrityTest(unittest.TestCase):
    """生成物里的 file: 链接必须能解析到真实文件。

    链接是相对**所在文件目录**解析的。之前 agents.org 写成
    generated/sessions/... 而它自己在 generated/ 下，结果 Emacs 点开全是死链。
    """

    def test_every_generated_link_resolves(self) -> None:
        import re

        layout, result = build(self)
        # 人工文件也先建出来，看板里的链接才齐全
        for path, content in plan_for(layout, result.projects):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        resolved = resolve_summaries(result, {}, {})
        ops = plan_mod.build_plan(layout, result, resolved, now=NOW)
        plan_mod.apply(ops, layout, write=True)

        pattern = re.compile(r"\[\[file:([^\]]+)\]")
        checked = 0
        for op in ops:
            for match in pattern.finditer(op.content):
                target = match.group(1).split("::")[0]
                actual = (op.path.parent / target).resolve()
                self.assertTrue(
                    actual.is_file(),
                    f"{op.path.name} 的链接解析不到文件: {target} -> {actual}",
                )
                checked += 1
        self.assertGreater(checked, 3, "应当至少有几条链接被检查")

    def test_dashboard_is_planned(self) -> None:
        layout, result = build(self)
        resolved = resolve_summaries(result, {}, {})
        ops = plan_mod.build_plan(layout, result, resolved, now=NOW)
        self.assertIn(layout.index, [op.path for op in ops])


class ProjectPageTest(unittest.TestCase):
    """项目页拆分：index.org 只放总览，卡片表在各项目页上。

    之前十个项目、上百张卡全塞在 index.org，人直接读不动。
    """

    def plan(self, layout, result):
        resolved = resolve_summaries(result, {}, {})
        return plan_mod.build_plan(layout, result, resolved, now=NOW)

    def test_each_project_gets_its_own_page(self) -> None:
        layout, result = build(self)
        paths = {op.path for op in self.plan(layout, result)}
        self.assertTrue(result.projects)
        for project in result.projects:
            self.assertIn(layout.project_page(project.key), paths)

    def test_index_links_to_every_project_page(self) -> None:
        layout, result = build(self)
        ops = self.plan(layout, result)
        index = next(op for op in ops if op.path == layout.index)
        for project in result.projects:
            self.assertIn(f"generated/projects/{project.key}.org", index.content)

    def test_index_is_only_an_overview(self) -> None:
        layout, result = build(self)
        index = next(op for op in self.plan(layout, result) if op.path == layout.index)
        # 总览页不该出现单张卡
        for project in result.projects:
            for agent in project.agents:
                self.assertNotIn(agent.session_id, index.content)

    def test_every_page_except_index_links_back(self) -> None:
        """每个生成页都要能回看板，否则点进去就回不来了。"""
        layout, result = build(self)
        pages = [op for op in self.plan(layout, result) if op.path != layout.index]
        self.assertTrue(pages)
        for op in pages:
            self.assertIn("index.org", op.content, op.path.name + " 缺少返回链接")

    def test_project_page_carries_the_card_table(self) -> None:
        layout, result = build(self)
        ops = self.plan(layout, result)
        project = result.projects[0]
        page = next(op for op in ops if op.path == layout.project_page(project.key))
        self.assertIn("观察", page.content)
        self.assertIn("工作卡", page.content)
        for agent in project.agents:
            self.assertIn(agent.session_id, page.content)


if __name__ == "__main__":
    unittest.main()
