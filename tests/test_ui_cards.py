"""pm ui-cards 契约测试。

契约冻结在 task-1：字段名、排序、needs_attention 谓词、聚合口径。
插件 ui-pm 按这份 JSON 渲染，所以这里既测行为也测字段形状。
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from pm import cli
from pm.config import Config, derive_source_instance
from pm.inbox import parse_entries, read_inbox
from pm.model import Agent, CacheObservation, Project, Todo
from pm.scan import ScanResult, scan as run_scan
from pm.sources.dsh_projcache import CacheLoad
from pm.sources.dsh_workspace import WorkspaceRegistry
from pm.ui_cards import build_cards_payload, needs_attention

import fixtures

TOP_KEYS = {
    "schemaVersion",
    "capabilities",
    "generated_at",
    "library",
    "inbox",
    "instances",
    "runtime_status",
    "projects",
    "cards",
}
PROJECT_KEYS = {
    "key",
    "title",
    "paths",
    "cards",
    "missing_summary",
    "open_todos",
    "total_todos",
    "last_recorded",
    "attention",
    "stale_busy",
}
CARD_KEYS = {
    "session_id",
    "instance",
    "project",
    "observation",
    "observation_label",
    "summary",
    "summary_source",
    "turns",
    "steps",
    "recorded_at",
    "cwd",
    "open_todos",
    "total_todos",
    "needs_attention",
    "is_subagent",
    "session_mode",
    "session_label",
    "session_title",
    "session_name",
    "card_file",
}


class UiCardsCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = fixtures.build_dsh_home(Path(self._tmp.name))
        self.config = Path(self._tmp.name) / "pm.toml"
        self.config.write_text(
            fixtures.fixture_config_toml().replace("REPLACED", str(self.home)), encoding="utf-8"
        )

    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def payload(self, *extra: str) -> dict:
        code, stdout, _ = self.run_cli(
            ["--config", str(self.config), "ui-cards", *extra, "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 0)
        return json.loads(stdout)

    # ---- 契约形状 ----

    def test_payload_shape_matches_frozen_contract(self) -> None:
        payload = self.payload()
        self.assertEqual(set(payload), TOP_KEYS)
        self.assertEqual(payload["schemaVersion"], "ui-cards-v1")
        self.assertEqual(payload["capabilities"], ["cards", "inbox", "subagents"])
        self.assertEqual(payload["runtime_status"], "unknown")
        self.assertEqual(set(payload["projects"][0]), PROJECT_KEYS)
        self.assertEqual(set(payload["cards"][0]), CARD_KEYS)
        self.assertEqual(payload["instances"], [derive_source_instance(self.home)])
        # 诚实性：任何地方都不能出现「运行中」的推断
        raw = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("正在运行", raw)
        self.assertNotIn("RUNNING", raw)
        for card in payload["cards"]:
            self.assertNotIn(card["observation"], {"RUNNING", "DONE"})

    def test_project_aggregates_cover_all_cards(self) -> None:
        payload = self.payload()
        project = next(p for p in payload["projects"] if p["key"] == "alpha_beta")
        cards = [c for c in payload["cards"] if c["project"] == "alpha_beta"]
        self.assertEqual(project["cards"], 6)
        self.assertEqual(project["cards"], len(cards))
        self.assertEqual(project["missing_summary"], 6)
        self.assertEqual(project["open_todos"], 4)
        self.assertEqual(project["total_todos"], 5)
        self.assertEqual(project["attention"], 3)   # needs_attention 卡数
        self.assertEqual(project["stale_busy"], 1)  # 仅 STALE_BUSY
        self.assertEqual(
            project["open_todos"], sum(c["open_todos"] for c in cards)
        )
        self.assertEqual(project["total_todos"], sum(c["total_todos"] for c in cards))
        stamps = [c["recorded_at"] for c in cards if c["recorded_at"]]
        self.assertEqual(project["last_recorded"], max(stamps))
        self.assertEqual(project["paths"], sorted({c["cwd"] for c in cards if c["cwd"]}))

    # ---- needs_attention 判定 ----

    def test_needs_attention_predicate(self) -> None:
        """STALE_BUSY 或有未完成 todo 才算需要关注；纯 unit 级验证两个分支。"""
        idle = SimpleNamespace(open_todos=[])
        busy = SimpleNamespace(open_todos=[Todo("卡住的步骤", "in_progress")])
        self.assertTrue(needs_attention(idle, CacheObservation.STALE_BUSY))
        self.assertTrue(needs_attention(busy, CacheObservation.RECENT))
        self.assertTrue(needs_attention(busy, CacheObservation.IDLE))
        self.assertFalse(needs_attention(idle, CacheObservation.RECENT))
        self.assertFalse(needs_attention(idle, CacheObservation.ARCHIVED))
        self.assertFalse(needs_attention(idle, CacheObservation.EMPTY))

    def test_needs_attention_flag_follows_predicate_in_payload(self) -> None:
        payload = self.payload()
        by_id = {c["session_id"]: c for c in payload["cards"]}
        stalled = by_id[fixtures.STALLED]
        self.assertEqual(stalled["observation"], "STALE_BUSY")
        self.assertTrue(stalled["needs_attention"])
        recent = by_id[fixtures.ALPHA_RECENT]
        # RECENT/IDLE 的分界依赖**真实时钟**（fixture 的时间戳是固定绝对时刻，
        # 而这里走的是真实 CLI），所以只断言与时钟无关的性质。
        # RECENT/IDLE 的判定本身由 test_scan.py 用冻结的 now 单独覆盖。
        self.assertIn(recent["observation"], ("RECENT", "IDLE"))
        self.assertEqual(recent["open_todos"], 2)
        self.assertTrue(recent["needs_attention"])
        empty = by_id[fixtures.ALPHA_EMPTY]
        self.assertEqual(empty["observation"], "EMPTY")
        self.assertFalse(empty["needs_attention"])
        for card in payload["cards"]:
            expected = card["observation"] == "STALE_BUSY" or card["open_todos"] > 0
            self.assertEqual(card["needs_attention"], expected)

    def test_attention_count_equals_needs_attention_cards(self) -> None:
        """回归：项目级 attention 必须与卡片级 needs_attention 用同一条谓词。"""
        payload = self.payload()
        for project in payload["projects"]:
            rows = [c for c in payload["cards"] if c["project"] == project["key"]]
            self.assertEqual(project["attention"], sum(1 for c in rows if c["needs_attention"]))
            self.assertEqual(
                project["stale_busy"], sum(1 for c in rows if c["observation"] == "STALE_BUSY")
            )

    # ---- 排序 ----

    def test_cards_sorted_by_attention_then_recorded_desc(self) -> None:
        cards = self.payload()["cards"]
        self.assertTrue(any(c["needs_attention"] for c in cards))
        flags = [c["needs_attention"] for c in cards]
        self.assertEqual(flags, sorted(flags, reverse=True), "needs_attention 必须优先")
        for prev, cur in zip(cards, cards[1:]):
            if prev["needs_attention"] != cur["needs_attention"]:
                continue
            if prev["recorded_at"] is not None and cur["recorded_at"] is not None:
                self.assertGreaterEqual(prev["recorded_at"], cur["recorded_at"])
        # 夹具里最近记录的卡（有未完成 todo）排最前
        self.assertEqual(cards[0]["session_id"], fixtures.ALPHA_RECENT)

    def test_projects_sorted_by_attention_then_last_recorded(self) -> None:
        projects = self.payload()["projects"]
        attention_flags = [p["attention"] > 0 for p in projects]
        self.assertEqual(attention_flags, sorted(attention_flags, reverse=True))

    # ---- --project / --limit ----

    def test_project_filter_keeps_only_requested_project(self) -> None:
        payload = self.payload("--project", "alpha_beta")
        self.assertEqual([p["key"] for p in payload["projects"]], ["alpha_beta"])
        self.assertTrue(payload["cards"])
        self.assertTrue(all(c["project"] == "alpha_beta" for c in payload["cards"]))

    def test_unknown_project_exits_nonzero(self) -> None:
        code, _, stderr = self.run_cli(
            ["--config", str(self.config), "ui-cards", "--project", "nope", "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 2)
        self.assertIn("未知项目", stderr)

    def test_limit_caps_cards_per_project_but_not_aggregates(self) -> None:
        payload = self.payload("--limit", "2")
        for project in payload["projects"]:
            rows = [c for c in payload["cards"] if c["project"] == project["key"]]
            self.assertLessEqual(len(rows), 2)
        alpha = next(p for p in payload["projects"] if p["key"] == "alpha_beta")
        self.assertEqual(alpha["cards"], 6, "聚合仍应基于全部卡")
        kept = [c["session_id"] for c in payload["cards"] if c["project"] == "alpha_beta"]
        self.assertEqual(kept, [fixtures.ALPHA_RECENT, fixtures.STALLED])

    # ---- 库与摘要 ----

    def test_library_and_card_file_null_without_library(self) -> None:
        empty = Path(self._tmp.name) / "no-dsh"
        code, stdout, _ = self.run_cli(["--config", str(self.config), "ui-cards", "--dsh-home", str(empty)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["projects"], [])
        self.assertEqual(payload["cards"], [])
        self.assertIsNone(payload["library"])
        self.assertIsNone(payload["inbox"], "无库时 inbox 必须为 null")
        self.assertEqual(payload["runtime_status"], "unknown")

    def test_summary_and_card_file_come_from_library(self) -> None:
        library = Path(self._tmp.name) / "wm"
        library.mkdir()
        instance = derive_source_instance(self.home)
        sid = fixtures.ALPHA_RECENT
        (library / "ai-summaries.org").write_text(
            "#+TITLE: AI\n\n* AI 摘要\n** " + sid + "\n"
            "   :PROPERTIES:\n"
            "   :PM_SESSION: " + sid + "\n"
            "   :PM_SOURCE_INSTANCE: " + instance + "\n"
            "   :PM_SUMMARY_SOURCE: ai\n"
            "   :END:\n"
            "   夹具生成的摘要\n",
            encoding="utf-8",
        )
        config_path = Path(self._tmp.name) / "pm_lib.toml"
        config_path.write_text(
            fixtures.fixture_config_toml(library=str(library)).replace("REPLACED", str(self.home)),
            encoding="utf-8",
        )
        code, stdout, _ = self.run_cli(
            ["--config", str(config_path), "ui-cards", "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["library"], str(library))
        card = next(c for c in payload["cards"] if c["session_id"] == sid)
        self.assertEqual(card["summary"], "夹具生成的摘要")
        self.assertEqual(card["summary_source"], "ai")
        self.assertEqual(
            card["card_file"], f"generated/sessions/{instance}/{sid}.org"
        )
        alpha = next(p for p in payload["projects"] if p["key"] == "alpha_beta")
        self.assertEqual(alpha["missing_summary"], 5)
        self.assertIsNone(payload["inbox"], "库存在但没有 inbox.org → null")

    def test_cli_payload_includes_inbox_entries(self) -> None:
        library = Path(self._tmp.name) / "wm-inbox"
        library.mkdir()
        (library / "inbox.org").write_text(
            "#+TITLE: Inbox\n\n* Inbox\n  随手记\n\n- 甲\n- 乙\n", encoding="utf-8"
        )
        config_path = Path(self._tmp.name) / "pm_inbox.toml"
        config_path.write_text(
            fixtures.fixture_config_toml(library=str(library)).replace("REPLACED", str(self.home)),
            encoding="utf-8",
        )
        code, stdout, _ = self.run_cli(
            ["--config", str(config_path), "ui-cards", "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(
            payload["inbox"],
            {
                "path": "inbox.org",
                "count": 2,
                "files": [{"path": "inbox.org", "origin": "human", "count": 2, "legacy": True}],
                "counts": {"human": 2, "ai": 0},
                "entries": [
                    {"text": "甲", "line": 6, "id": None, "status": "LEGACY_UNTRACKED", "capturedAt": None, "source": None, "projectHint": None, "annotationCount": None, "revisionCount": None, "lastAnnotationText": None, "pinned": False, "origin": "human", "file": "inbox.org"},
                    {"text": "乙", "line": 7, "id": None, "status": "LEGACY_UNTRACKED", "capturedAt": None, "source": None, "projectHint": None, "annotationCount": None, "revisionCount": None, "lastAnnotationText": None, "pinned": False, "origin": "human", "file": "inbox.org"},
                ],
            },
        )


INBOX_SAMPLE = """#+TITLE: Inbox
#+TODO: INBOX(i) TODO(t)

* Inbox
  随手记在这里，不要求完整字段。

- 第一条笔记 [[https://example.com][链接]] 中文
    - 嵌套子项，不算条目
- 第二条笔记
** INBOX [2026-10-10 Sat] 第三条 capture
   :PROPERTIES:
   :PM_SOURCE: ai
   :END:
   正文第一行
   - 正文里的列表，不算条目

# 示例（可删）：
# ** INBOX [2026-10-10 Sat] 注释掉的假笔记
"""


class InboxParseTest(unittest.TestCase):
    """inbox.org 解析：① capture 的 ** 标题 + ② 顶层列表项，且绝不把注释当笔记。"""

    def test_bullets_and_capture_parsed_nested_and_comments_skipped(self) -> None:
        entries = parse_entries(INBOX_SAMPLE)
        self.assertEqual(
            entries,
            [
                {"text": "第一条笔记 [[https://example.com][链接]] 中文", "line": 7, "id": None, "status": "LEGACY_UNTRACKED", "capturedAt": None, "source": None, "projectHint": None, "annotationCount": None, "revisionCount": None, "lastAnnotationText": None, "pinned": False},
                {"text": "第二条笔记", "line": 9, "id": None, "status": "LEGACY_UNTRACKED", "capturedAt": None, "source": None, "projectHint": None, "annotationCount": None, "revisionCount": None, "lastAnnotationText": None, "pinned": False},
                {"text": "INBOX [2026-10-10 Sat] 第三条 capture", "line": 10, "id": None, "status": "LEGACY_UNTRACKED", "capturedAt": None, "source": "ai", "projectHint": None, "annotationCount": None, "revisionCount": None, "lastAnnotationText": None, "pinned": False},
            ],
        )
        self.assertEqual(len(entries), 3)
        joined = " ".join(e["text"] for e in entries)
        self.assertNotIn("注释掉", joined, "以 # 开头的注释行不得成为条目")
        self.assertNotIn("嵌套子项", joined, "嵌套缩进项不计入")
        self.assertNotIn("正文里的列表", joined, "标题正文区的列表不独立成条")
        self.assertNotIn(18, [e["line"] for e in entries])

    def test_count_equals_len_through_read_inbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inbox.org").write_text(INBOX_SAMPLE, encoding="utf-8")
            payload = read_inbox(root)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["path"], "inbox.org")
        self.assertEqual(payload["count"], len(payload["entries"]))

    def test_missing_file_and_no_library_are_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(read_inbox(Path(tmp)), "目录存在但没有 inbox.org → null")
        self.assertIsNone(read_inbox(None), "无库 → null")

    def test_empty_file_has_zero_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inbox.org").write_text("", encoding="utf-8")
            payload = read_inbox(root)
        self.assertEqual(payload, {"path": "inbox.org", "count": 0, "files": [], "counts": {"human": 0, "ai": 0}, "entries": []})

    def test_invalid_utf8_returns_null_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inbox.org").write_bytes(b"\xff\xfe\x00 not utf-8")
            self.assertIsNone(read_inbox(root))

    def test_without_inbox_section_parses_whole_file(self) -> None:
        """capture 在小节缺失时会追加到文件末尾，这些条目同样是笔记。"""
        entries = parse_entries("- 甲\n- 乙\n")
        self.assertEqual(
            entries,
            [
                {"text": "甲", "line": 1, "id": None, "status": "LEGACY_UNTRACKED", "capturedAt": None, "source": None, "projectHint": None, "annotationCount": None, "revisionCount": None, "lastAnnotationText": None, "pinned": False},
                {"text": "乙", "line": 2, "id": None, "status": "LEGACY_UNTRACKED", "capturedAt": None, "source": None, "projectHint": None, "annotationCount": None, "revisionCount": None, "lastAnnotationText": None, "pinned": False},
            ],
        )

    def test_capture_without_title_falls_back_to_first_body_line(self) -> None:
        text = "* Inbox\n**\n   :PROPERTIES:\n   :PM_SOURCE: ai\n   :END:\n   正文才是内容\n"
        self.assertEqual(
            parse_entries(text),
            [{"text": "正文才是内容", "line": 2, "id": None, "status": "LEGACY_UNTRACKED", "capturedAt": None, "source": "ai", "projectHint": None, "annotationCount": None, "revisionCount": None, "lastAnnotationText": None, "pinned": False}],
        )

    def test_link_and_cjk_line_does_not_crash(self) -> None:
        entries = parse_entries("- [[file:~/notes.org][链接]] 中文 ✓\n")
        self.assertEqual(
            entries,
            [{"text": "[[file:~/notes.org][链接]] 中文 ✓", "line": 1, "id": None, "status": "LEGACY_UNTRACKED", "capturedAt": None, "source": None, "projectHint": None, "annotationCount": None, "revisionCount": None, "lastAnnotationText": None, "pinned": False}],
        )


class BuildPayloadUnitTest(unittest.TestCase):
    """直接调纯函数，验证空库与排序不依赖真实数据源。"""

    def _result(self):
        return run_scan(
            config=Config(),
            registry=WorkspaceRegistry(),
            cache=CacheLoad(),
            now=datetime(2026, 10, 10, tzinfo=timezone.utc),
            include_all=True,
            limit=0,
        )

    def test_empty_scan_result_does_not_crash(self) -> None:
        payload = build_cards_payload(self._result())
        self.assertEqual(payload["projects"], [])
        self.assertEqual(payload["cards"], [])
        self.assertEqual(payload["runtime_status"], "unknown")
        self.assertIsNone(payload["library"])
        self.assertIsNone(payload["inbox"], "默认不读文件，inbox 由调用方传入")
        json.dumps(payload)  # 必须可序列化

    def _result_with_subagent_newest(self) -> ScanResult:
        now = datetime(2026, 10, 10, 20, 30, tzinfo=timezone.utc)
        sub = Agent(
            session_id="session-sub",
            cwd="/w/sub-only",
            title="sub",
            turns=1,
            steps=1,
            last_active=datetime(2026, 10, 10, 20, 0, tzinfo=timezone.utc),
            is_subagent=True,
        )
        normal = Agent(
            session_id="session-normal",
            cwd="/w/main",
            title="normal",
            turns=1,
            steps=1,
            last_active=datetime(2026, 10, 10, 19, 0, tzinfo=timezone.utc),
        )
        project = Project(
            key="p", title="P", paths=["/w/main", "/w/sub-only"], agents=[sub, normal]
        )
        return ScanResult(
            generated_at=now,
            config=Config(),
            projects=[project],
            all_agents=[sub, normal],
            source_instances=("default",),
        )

    def test_last_recorded_ignores_newer_subagent(self) -> None:
        """回归：最新的卡是子 agent 时，默认视图的项目 last_recorded 不能取它的时间。

        verifier 的 C4 校验就是这样抓到 demo-chip 不一致的。
        """
        result = self._result_with_subagent_newest()

        default = build_cards_payload(result)
        row = default["projects"][0]
        self.assertEqual(row["cards"], 1)
        self.assertEqual(
            row["last_recorded"],
            datetime(2026, 10, 10, 19, 0, tzinfo=timezone.utc).isoformat(),
            "必须取保留集合（普通卡）的最大时间，而不是子 agent 的 20:00",
        )
        self.assertEqual([c["session_id"] for c in default["cards"]], ["session-normal"])
        self.assertEqual(row["paths"], ["/w/main"], "子 agent 独有的 cwd 不应出现在 paths")

        full = build_cards_payload(result, include_subagents=True)
        row_full = full["projects"][0]
        self.assertEqual(row_full["cards"], 2)
        self.assertEqual(
            row_full["last_recorded"],
            datetime(2026, 10, 10, 20, 0, tzinfo=timezone.utc).isoformat(),
        )
        self.assertEqual(row_full["paths"], ["/w/main", "/w/sub-only"])


class SessionIdentityTest(unittest.TestCase):
    """task-170：子 agent 判定改用**投影事实**（rows.subagent.val.identity.mode），并把信息分开给字段。

    三种 fixture：continuable（队友，带 label）/ one-shot（普通会话）/ 缺 subagent 行（老实 null）。
    """

    TITLE_INJECTED = '<system-reminder> You are teammate "pm-frontend"'
    LABEL = "按设计示例实现 PM 工作台前端（frontend_impl）"
    TITLE_NORMAL = "你是负责对抗式复核的芯片架构助手"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = fixtures.build_dsh_home(Path(self._tmp.name))
        sessions = self.home / "storages" / "session_projcache" / "sessions"
        ws_path = self.home / "storages" / "workspace.json"
        data = json.loads(ws_path.read_text(encoding="utf-8"))
        alpha = data["tables"]["workspaces"]["w-alpha"]
        extra = {
            "session-17000000-0000-4000-8000-000000000001": dict(
                title=self.TITLE_INJECTED, subagent_mode="continuable", subagent_label=self.LABEL
            ),
            "session-17000000-0000-4000-8000-000000000002": dict(
                title=self.TITLE_NORMAL, subagent_mode="one-shot"
            ),
            "session-17000000-0000-4000-8000-000000000003": dict(title="没有 subagent 行的老会话"),
        }
        for session_id, kwargs in extra.items():
            doc = fixtures.session_doc(
                cwd=fixtures.ALPHA,
                created=fixtures.ms(2026, 10, 9),
                last_prompt_at=fixtures.ms(2026, 10, 10, 5),
                **kwargs,
            )
            (sessions / (session_id + ".json")).write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8"
            )
            alpha["sessionIds"].append(session_id)
        ws_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.config = Path(self._tmp.name) / "pm.toml"
        self.config.write_text(
            fixtures.fixture_config_toml().replace("REPLACED", str(self.home)), encoding="utf-8"
        )

    def cards(self, *extra: str) -> dict:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                ["--config", str(self.config), "ui-cards", "--limit", "0",
                 "--dsh-home", str(self.home), *extra]
            )
        self.assertEqual(code, 0)
        return {card["session_id"]: card for card in json.loads(out.getvalue())["cards"]}

    def test_continuable_session_carries_mode_label_and_name(self) -> None:
        card = self.cards("--include-subagents")["session-17000000-0000-4000-8000-000000000001"]
        self.assertTrue(card["is_subagent"], "continuable 必须判为子 agent（原来恒 false 是 bug）")
        self.assertEqual(card["session_mode"], "continuable")
        self.assertEqual(card["session_label"], self.LABEL)
        self.assertEqual(card["session_title"], self.TITLE_INJECTED, "title 原样给出，清洗是另一层的事")
        self.assertEqual(card["session_name"], self.LABEL, "标签优先当名字")

    def test_one_shot_session_is_not_a_subagent(self) -> None:
        card = self.cards("--include-subagents")["session-17000000-0000-4000-8000-000000000002"]
        self.assertFalse(card["is_subagent"])
        self.assertEqual(card["session_mode"], "one-shot")
        self.assertIsNone(card["session_label"], "普通会话没有 label → null，不猜")
        self.assertEqual(card["session_name"], self.TITLE_NORMAL, "没有 label 时用非注入型 title")

    def test_missing_subagent_row_is_null_not_guessed(self) -> None:
        card = self.cards("--include-subagents")["session-17000000-0000-4000-8000-000000000003"]
        self.assertFalse(card["is_subagent"], "缺字段时保守当作非子 agent")
        self.assertIsNone(card["session_mode"])
        self.assertIsNone(card["session_label"])
        self.assertEqual(card["session_name"], "没有 subagent 行的老会话")

    def test_injected_title_is_not_used_as_name(self) -> None:
        # 队友会话没有 label 时，注入型 title 不当名字（不猜）
        sessions = self.home / "storages" / "session_projcache" / "sessions"
        ws_path = self.home / "storages" / "workspace.json"
        data = json.loads(ws_path.read_text(encoding="utf-8"))
        sid = "session-17000000-0000-4000-8000-000000000004"
        doc = fixtures.session_doc(
            cwd=fixtures.ALPHA, created=fixtures.ms(2026, 10, 9),
            last_prompt_at=fixtures.ms(2026, 10, 10, 5),
            title='<system-reminder> You are teammate "pm-x"', subagent_mode="continuable",
        )
        (sessions / (sid + ".json")).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        data["tables"]["workspaces"]["w-alpha"]["sessionIds"].append(sid)
        ws_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        card = self.cards("--include-subagents")[sid]
        self.assertTrue(card["is_subagent"])
        self.assertIsNone(card["session_label"])
        self.assertIsNone(card["session_name"], "注入型 title 不能当名字 → null")
        self.assertTrue(card["session_title"].startswith("<system-reminder>"), "原文仍保留给前端")

    def test_default_view_excludes_subagents_only(self) -> None:
        default = self.cards()
        self.assertNotIn("session-17000000-0000-4000-8000-000000000001", default, "子 agent 默认不列")
        self.assertIn("session-17000000-0000-4000-8000-000000000002", default, "普通会话默认保留")
        self.assertIn("session-17000000-0000-4000-8000-000000000003", default, "缺字段保守保留")


if __name__ == "__main__":
    unittest.main()
