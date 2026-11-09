"""Memory 模型（backend-design §5.4）：候选 / 正式内容分离、冲突、supersede、上下文包。

全部用临时库；真实库 ~/my-work-memory 一个字节都不碰。
写路径复用 pm.entities（CAS / 原子写 / 审计 / 幂等），这里只验证 memory 语义。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pm import cli, entities, memory

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=TZ)


def make_entry(entry_id: str, **overrides) -> memory.MemoryEntry:
    fields = dict(
        id=entry_id,
        status=memory.STATUS_VERIFIED,
        scope="demo",
        type=memory.TYPE_FACT,
        text="参考模型版本是 v3",
        sources=("session-a",),
        revision=1,
        topic="",
        task_id=None,
        created_at="2026-10-11T09:00:00+08:00",
        created_by="ai",
        verified_at="2026-10-12T10:00:00+08:00",
        verified_by="human",
        deprecated_at=None,
        supersedes=None,
        superseded_by=None,
    )
    fields.update(overrides)
    return memory.MemoryEntry(**fields)


class MemoryBaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.library = self.base / "wm"
        self.library.mkdir()
        self.config = self.base / "pm.toml"
        self.config.write_text('library = "' + str(self.library) + '"\n', encoding="utf-8")
        self.candidates = self.library / "memory-candidates.org"

    # ---- 通用工具 ----

    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(argv)
        except SystemExit as exc:  # argparse 参数错误
            code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def pm(self, *argv: str) -> tuple[int, str, str]:
        return self.run_cli(["--config", str(self.config), *argv])

    def add(self, text: str, *, scope: str = "demo", type: str = "fact", sources=("session-a",),
            topic: str = "", created_by: str = "ai", extra=()) -> dict:
        argv = ["memory", "add", "--text", text, "--scope", scope, "--type", type, "--json"]
        if topic:
            argv += ["--topic", topic]
        for ref in sources:
            argv += ["--sources", ref]
        argv += ["--created-by", created_by, *extra]
        code, stdout, stderr = self.pm(*argv)
        self.assertEqual(code, 0, stderr)
        return json.loads(stdout)

    def add_candidate(self, text: str, **kwargs) -> memory.MemoryEntry:
        payload = self.add(text, **kwargs)
        return next(entry for entry in memory.parse_candidates(self.library) if entry.id == payload["entityId"])

    def seed_memory(self, type: str = "fact", entries=()) -> Path:
        path = memory.type_path(self.library, type)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(memory.render_memory_text(type, entries), encoding="utf-8")
        return path

    def seed_candidates(self, entries=()) -> Path:
        self.candidates.write_text(memory.render_candidates_text(entries), encoding="utf-8")
        return self.candidates


# ================================================================ 解析 / 序列化

class RoundTripTest(MemoryBaseTest):
    def test_round_trip_preserves_every_field(self) -> None:
        entries = [
            make_entry(
                "memory-1", status=memory.STATUS_VERIFIED, scope="demo", type=memory.TYPE_DECISION,
                text="决定：输入范围锁定 v3\n\n原因：v4 还在改", sources=("inbox-1", "session-b"),
                revision=7, topic="input-scope", task_id="task-9", created_by="human",
                supersedes="memory-0", superseded_by="memory-2",
            ),
            make_entry(
                "memory-2", status=memory.STATUS_DEPRECATED, type=memory.TYPE_GOTCHA,
                text="坑：不要用行号关联", sources=(), deprecated_at="2026-10-12T11:00:00+08:00",
            ),
        ]
        text = memory.render_candidates_text(entries)
        parsed = memory.parse_entries_text(text)
        self.assertEqual(parsed, entries)

    def test_round_trip_multiline_with_internal_blank_and_star_lines(self) -> None:
        text_value = "标题行\n\n* 第 0 列星号不该被当成标题\n最后一行"
        entry = make_entry("memory-star", text=text_value)
        parsed = memory.parse_entries_text(memory.render_candidates_text([entry]))
        self.assertEqual(parsed[0].text, text_value)
        self.assertEqual(len(parsed), 1)

    def test_round_trip_empty_text_entry(self) -> None:
        entry = make_entry("memory-empty", text="", sources=())
        parsed = memory.parse_entries_text(memory.render_memory_text("fact", [entry]))
        self.assertEqual(parsed, [entry])

    def test_unsourced_entry_round_trips_with_explicit_marker(self) -> None:
        entry = make_entry("memory-nosrc", status=memory.STATUS_CANDIDATE, sources=())
        rendered = memory.render_candidates_text([entry])
        self.assertIn(":PM_UNSOURCED: t", rendered)
        self.assertTrue(memory.parse_entries_text(rendered)[0].unsourced)

    def test_parse_skips_logbook_so_text_is_lossless(self) -> None:
        text = (
            "#+TITLE: Memory Candidates\n\n* Memory Candidates\n\n"
            "** 正文首行\n   :PROPERTIES:\n   :ID: memory-log\n   :PM_KIND: memory\n"
            "   :PM_STATUS: CANDIDATE\n   :PM_REVISION: 2\n   :END:\n"
            "   :LOGBOOK:\n   - State \"VERIFIED\" from \"CANDIDATE\" [2026-10-12 Mon 12:00] id=memory-log audit=audit-x\n   :END:\n"
            "   正文第二行\n"
        )
        entry = memory.parse_entries_text(text)[0]
        self.assertEqual(entry.text, "正文首行\n正文第二行")
        self.assertNotIn("audit-x", entry.text)
        self.assertEqual(entry.revision, 2)

    def test_legacy_entry_without_id_is_visible_not_crashing(self) -> None:
        text = "* Memory Candidates\n\n** 没有 ID 的旧条目\n   正文\n"
        entry = memory.parse_entries_text(text)[0]
        self.assertIsNone(entry.id)
        self.assertTrue(entry.legacy)
        self.assertEqual(entry.text, "没有 ID 的旧条目\n正文")

    def test_bare_property_block_without_marker(self) -> None:
        text = (
            "* Facts\n\n** 裸属性条目\n:ID: memory-bare\n:PM_STATUS: VERIFIED\n:PM_TYPE: fact\n"
            ":PM_SCOPE: global\n:END:\n   正文\n"
        )
        entry = memory.parse_entries_text(text)[0]
        self.assertEqual(entry.id, "memory-bare")
        self.assertEqual(entry.status, memory.STATUS_VERIFIED)
        self.assertEqual(entry.scope, "global")
        self.assertEqual(entry.text, "裸属性条目\n正文")

    def test_parse_handles_crlf_and_bom_and_missing_revision(self) -> None:
        text = "\ufeff* Facts\r\n\r\n** 旧机器写的条目\r\n   :PROPERTIES:\r\n   :ID: memory-crlf\r\n   :END:\r\n   正文\r\n"
        entry = memory.parse_entries_text(text)[0]
        self.assertEqual(entry.id, "memory-crlf")
        self.assertEqual(entry.revision, 1)
        self.assertEqual(entry.text, "旧机器写的条目\n正文")

    def test_parse_ignores_level1_and_level3_headlines(self) -> None:
        text = "* Facts\n\n*** 三层是正文\n** 真正的条目\n   :PROPERTIES:\n   :ID: memory-l2\n   :END:\n"
        parsed = memory.parse_entries_text(text)
        self.assertEqual([entry.id for entry in parsed], ["memory-l2"])

    def test_missing_files_give_empty_lists(self) -> None:
        self.assertEqual(memory.parse_candidates(self.library), [])
        self.assertEqual(memory.parse_memory(self.library), [])
        self.assertFalse(self.candidates.exists())

    def test_parse_memory_filters_by_type(self) -> None:
        self.seed_memory("fact", [make_entry("memory-f", type="fact")])
        self.seed_memory("decision", [make_entry("memory-d", type="decision")])
        self.assertEqual([entry.id for entry in memory.parse_memory(self.library)], ["memory-f", "memory-d"])
        self.assertEqual([entry.id for entry in memory.parse_memory(self.library, type="decision")], ["memory-d"])

    def test_line_number_does_not_affect_equality(self) -> None:
        first = memory.parse_entries_text(memory.render_candidates_text([make_entry("memory-eq")]))[0]
        second = memory.parse_entries_text("\n\n" + memory.render_candidates_text([make_entry("memory-eq")]))[0]
        self.assertNotEqual(first.line, second.line)
        self.assertEqual(first, second)


# ================================================================ 纯逻辑 / 校验

class ValidationTest(unittest.TestCase):
    def test_build_candidate_defaults_to_candidate_and_marks_unsourced(self) -> None:
        entry = memory.build_candidate("一条事实", scope="demo", type="fact", now=NOW)
        self.assertTrue(entry.id.startswith("memory-"))
        self.assertEqual(entry.status, memory.STATUS_CANDIDATE)
        self.assertEqual(entry.revision, 1)
        self.assertTrue(entry.unsourced)
        self.assertEqual(entry.created_at, NOW.isoformat(timespec="seconds"))
        self.assertEqual(entry.created_by, "ai")

    def test_build_candidate_rejects_empty_text(self) -> None:
        with self.assertRaises(memory.MemoryError) as raised:
            memory.build_candidate("   \n\n ", scope="global", type="fact")
        self.assertEqual(raised.exception.code, "TEXT_REQUIRED")

    def test_build_candidate_rejects_bad_type_and_scope(self) -> None:
        with self.assertRaises(memory.MemoryError) as bad_type:
            memory.build_candidate("x", scope="global", type="note")
        self.assertEqual(bad_type.exception.code, "INVALID_TYPE")
        with self.assertRaises(memory.MemoryError) as bad_scope:
            memory.build_candidate("x", scope="有两个 词", type="fact")
        self.assertEqual(bad_scope.exception.code, "INVALID_SCOPE")

    def test_validate_sources_normalizes_and_rejects_whitespace(self) -> None:
        self.assertEqual(memory.validate_sources("a,b  a"), ("a", "b"))
        self.assertEqual(memory.validate_sources(["x", "x", "y"]), ("x", "y"))
        with self.assertRaises(memory.MemoryError) as raised:
            memory.validate_sources(["有 空格"])
        self.assertEqual(raised.exception.code, "INVALID_SOURCE")

    def test_new_memory_id_shape(self) -> None:
        self.assertRegex(memory.new_memory_id(), r"^memory-[0-9A-HJKMNP-TV-Z]{26}$")

    def test_require_human_actor(self) -> None:
        self.assertEqual(memory.require_human_actor("human"), "human")
        self.assertEqual(memory.require_human_actor(" HUMAN "), "human")
        for actor in ("ai", "system", ""):
            with self.assertRaises(memory.MemoryError) as raised:
                memory.require_human_actor(actor)
            self.assertEqual(raised.exception.code, "AI_CANNOT_VERIFY")
            self.assertEqual(raised.exception.exit_code, 2)

    def test_clean_text_normalizes_newlines_and_edges(self) -> None:
        self.assertEqual(memory.clean_text("  \r\n第一行  \r\n\r\n第二行\r\n\r\n"), "第一行\n\n第二行")


# ================================================================ 冲突检测

class ConflictTest(unittest.TestCase):
    def test_same_topic_different_text_conflicts(self) -> None:
        candidate = make_entry("memory-new", status=memory.STATUS_CANDIDATE, topic="input-scope", text="v4", sources=("s",))
        existing = [make_entry("memory-old", topic="input-scope", text="v3")]
        conflicts = memory.detect_conflicts(candidate, existing)
        self.assertEqual([(item.entry_id, item.reason) for item in conflicts], [("memory-old", "same-topic")])

    def test_duplicate_text_conflicts(self) -> None:
        candidate = make_entry("memory-new", status=memory.STATUS_CANDIDATE, text="同样的内容", sources=("s",))
        existing = [make_entry("memory-old", topic="", text="同样的内容")]
        self.assertEqual(memory.detect_conflicts(candidate, existing)[0].reason, "duplicate-text")

    def test_different_scope_or_type_does_not_conflict(self) -> None:
        candidate = make_entry("memory-new", status=memory.STATUS_CANDIDATE, topic="t", text="a", sources=("s",))
        others = [
            make_entry("memory-1", scope="other", topic="t", text="b"),
            make_entry("memory-2", type="decision", topic="t", text="b"),
        ]
        self.assertEqual(memory.detect_conflicts(candidate, others), [])

    def test_deprecated_and_self_are_ignored(self) -> None:
        candidate = make_entry("memory-new", status=memory.STATUS_CANDIDATE, topic="t", text="a", sources=("s",))
        others = [
            make_entry("memory-new", topic="t", text="a" + "x"),  # 同 id
            make_entry("memory-old", status=memory.STATUS_DEPRECATED, topic="t", text="b"),
        ]
        self.assertEqual(memory.detect_conflicts(candidate, others), [])

    def test_explicit_ids_are_honoured(self) -> None:
        candidate = make_entry("memory-new", status=memory.STATUS_CANDIDATE, text="a", sources=("s",))
        existing = [make_entry("memory-old", scope="other", text="zzz")]
        conflicts = memory.detect_conflicts(candidate, existing, explicit_ids=["memory-old"])
        self.assertEqual(conflicts[0].reason, "explicit")

    def test_conflict_to_dict_is_stable(self) -> None:
        conflict = memory.Conflict("memory-x", "same-topic", "why")
        self.assertEqual(conflict.to_dict(), {"entryId": "memory-x", "reason": "same-topic", "detail": "why"})


# ================================================================ 上下文包

class ContextPackTest(MemoryBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.seed_memory("fact", [
            make_entry("memory-p1", scope="demo", text="项目事实"),
            make_entry("memory-g", scope="global", text="全局事实"),
            make_entry("memory-dep", scope="demo", status=memory.STATUS_DEPRECATED, text="废弃事实"),
            make_entry("memory-other", scope="other_proj", text="别项目事实"),
            make_entry("memory-t9", scope="demo", text="任务 9 的事实", task_id="task-9"),
            make_entry("memory-t8", scope="demo", text="任务 8 的事实", task_id="task-8"),
        ])
        self.seed_candidates([
            make_entry("memory-cand", status=memory.STATUS_CANDIDATE, scope="demo", text="候选不该出现"),
        ])

    def test_only_verified_entries_are_returned(self) -> None:
        pack = memory.context_pack(self.library, "demo")
        ids = {entry["id"] for entry in pack["entries"]}
        self.assertNotIn("memory-cand", ids, "候选绝不能进上下文包")
        self.assertNotIn("memory-dep", ids)
        self.assertEqual(pack["excluded"]["candidate"], 1)
        self.assertEqual(pack["excluded"]["deprecated"], 1)
        self.assertTrue(pack["onlyVerified"])

    def test_global_included_other_scope_excluded(self) -> None:
        pack = memory.context_pack(self.library, "demo")
        ids = {entry["id"] for entry in pack["entries"]}
        self.assertIn("memory-g", ids)
        self.assertNotIn("memory-other", ids)
        self.assertEqual(pack["excluded"]["otherScope"], 1)

    def test_no_global_flag_excludes_global(self) -> None:
        pack = memory.context_pack(self.library, "demo", include_global=False)
        self.assertNotIn("memory-g", {entry["id"] for entry in pack["entries"]})

    def test_task_filter_excludes_other_task(self) -> None:
        pack = memory.context_pack(self.library, "demo", task_id="task-9")
        ids = {entry["id"] for entry in pack["entries"]}
        self.assertIn("memory-t9", ids)
        self.assertNotIn("memory-t8", ids)
        self.assertEqual(pack["excluded"]["otherTask"], 1)

    def test_cross_scope_requires_explicit_authorization(self) -> None:
        other = make_entry("memory-task-global", scope="other_proj", text="跨项目任务事实", task_id="task-9")
        self.seed_memory("decision", [other])
        without = memory.context_pack(self.library, "demo", task_id="task-9")
        self.assertNotIn("memory-task-global", {entry["id"] for entry in without["entries"]})
        with_auth = memory.context_pack(self.library, "demo", task_id="task-9", allow_cross_scope=True)
        self.assertIn("memory-task-global", {entry["id"] for entry in with_auth["entries"]})

    def test_pack_shape_counts_and_sources(self) -> None:
        pack = memory.context_pack(self.library, "demo", now=NOW)
        self.assertEqual(pack["scope"], "demo")
        self.assertEqual(pack["generatedAt"], NOW.isoformat(timespec="seconds"))
        self.assertEqual(pack["counts"]["fact"], len(pack["entries"]))
        self.assertEqual(pack["counts"]["total"], len(pack["entries"]))
        self.assertIn("session-a", pack["sources"])
        types = [entry["type"] for entry in pack["entries"]]
        self.assertEqual(types, sorted(types, key=memory.TYPES.index), "按 fact/decision/gotcha 稳定排序")
        self.assertNotIn("line", pack["entries"][0], "上下文包给 AI 用，不带展示行号")

    def test_context_rejects_empty_scope(self) -> None:
        with self.assertRaises(memory.MemoryError):
            memory.context_pack(self.library, "  ")


# ================================================================ 写入：add_candidate

class AddCandidateTest(MemoryBaseTest):
    def test_add_writes_candidate_with_audit_and_unsourced_mark(self) -> None:
        result = memory.add_candidate(self.library, text="一条事实", scope="demo", type="fact", now=NOW)
        self.assertTrue(result.changed)
        self.assertEqual(result.status, memory.STATUS_CANDIDATE)
        self.assertEqual(result.revision, 1)
        self.assertEqual(result.audit_event_id.startswith("audit-"), True)
        text = self.candidates.read_text(encoding="utf-8")
        self.assertIn(":PM_KIND: memory", text)
        self.assertIn(":PM_STATUS: CANDIDATE", text)
        self.assertIn(":PM_UNSOURCED: t", text)
        self.assertIn("id=" + result.entity_id, text)
        self.assertNotEqual(result.entity_id, "")
        self.assertFalse((self.library / "memory").exists(), "候选绝不写进 memory/")

    def test_add_never_enters_verified_area(self) -> None:
        memory.add_candidate(self.library, text="x", scope="global", type="gotcha", now=NOW)
        self.assertFalse((self.library / "memory").exists())

    def test_add_dry_run_writes_nothing_but_plans_position(self) -> None:
        result = memory.add_candidate(self.library, text="x", scope="global", type="fact", dry_run=True, now=NOW)
        self.assertTrue(result.dry_run)
        self.assertGreater(result.extra["line"], 0, "dry-run 要能报出将写入的行号")
        self.assertTrue(result.audit_event_id.startswith("audit-"))
        self.assertFalse(self.candidates.exists())

    def test_add_idempotency_replay_uses_create_entity_semantics(self) -> None:
        first = memory.add_candidate(self.library, text="x", scope="global", type="fact",
                                     idempotency_key="key-1", now=NOW)
        self.assertTrue(first.changed)
        self.assertFalse(first.idempotent)
        second = memory.add_candidate(self.library, text="x", scope="global", type="fact",
                                      idempotency_key="key-1", now=NOW)
        self.assertFalse(second.changed, "重放不产生第二次变更")
        self.assertTrue(second.idempotent)
        self.assertEqual(second.entity_id, first.entity_id)
        self.assertEqual(second.audit_event_id, first.audit_event_id)
        self.assertEqual(len(memory.parse_candidates(self.library)), 1, "重放不产生第二个候选")
        text = self.candidates.read_text(encoding="utf-8")
        self.assertIn("key=key-1", text, "key 写进创建审计行")
        self.assertNotIn("PM_IDEMPOTENCY_KEY", text, "不再需要自定义幂等属性")

    def test_add_replay_observed_at_comes_from_first_write(self) -> None:
        first = memory.add_candidate(self.library, text="x", scope="global", type="fact",
                                     idempotency_key="k", now=NOW)
        later = NOW + timedelta(hours=3)
        second = memory.add_candidate(self.library, text="x", scope="global", type="fact",
                                      idempotency_key="k", now=later)
        self.assertEqual(second.observed_at, first.observed_at, "observedAt 必须是首次写入的时间")
        self.assertNotEqual(second.observed_at, later.isoformat(timespec="seconds"))

    def test_add_same_key_with_different_text_still_replays_first(self) -> None:
        """key 标识「一次逻辑新增」：重试即便正文不同也返回首次结果，不产生第二条候选。"""
        first = memory.add_candidate(self.library, text="甲", scope="global", type="fact",
                                     idempotency_key="k-dup", now=NOW)
        again = memory.add_candidate(self.library, text="乙", scope="global", type="fact",
                                     idempotency_key="k-dup", now=NOW)
        self.assertTrue(again.idempotent)
        self.assertFalse(again.changed)
        self.assertEqual(again.entity_id, first.entity_id)
        self.assertEqual(len(memory.parse_candidates(self.library)), 1)
        self.assertEqual(memory.parse_candidates(self.library)[0].text, "甲")

    def test_add_cli_json_shape(self) -> None:
        payload = self.add("一条候选", sources=("inbox-1",))
        for key in ("ok", "entityId", "memoryId", "status", "revision", "source", "observedAt", "auditEventId", "path"):
            self.assertIn(key, payload)
        self.assertEqual(payload["status"], "CANDIDATE")
        self.assertEqual(payload["source"], "org")
        self.assertEqual(payload["path"], "memory-candidates.org")
        self.assertRegex(payload["observedAt"], r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T")


# ================================================================ 写入：verify

class VerifyTest(MemoryBaseTest):
    def candidate(self, text="候选内容", **kwargs) -> memory.MemoryEntry:
        return self.add_candidate(text, **kwargs)

    def test_ai_verify_is_rejected_and_writes_nothing(self) -> None:
        entry = self.candidate()
        before = self.candidates.read_bytes()
        with self.assertRaises(memory.MemoryError) as raised:
            memory.verify(self.library, entry.id, expected_revision=1, actor="ai", now=NOW)
        self.assertEqual(raised.exception.code, "AI_CANNOT_VERIFY")
        self.assertEqual(raised.exception.exit_code, 2)
        self.assertEqual(self.candidates.read_bytes(), before)
        self.assertFalse((self.library / "memory").exists())

    def test_ai_verify_via_cli_exits_2(self) -> None:
        payload = self.add("候选")
        code, stdout, _ = self.pm("memory", "verify", payload["entityId"],
                                  "--expected-revision", "1", "--actor", "ai", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "AI_CANNOT_VERIFY")

    def test_human_verify_promotes_candidate_and_publishes_body(self) -> None:
        entry = self.candidate("正文第一行\n正文第二行")
        result = memory.verify(self.library, entry.id, expected_revision=1, actor="human",
                               reason="人工确认", idempotency_key="verify-1", now=NOW)
        self.assertTrue(result.changed)
        self.assertEqual(result.status, memory.STATUS_VERIFIED)
        self.assertEqual(result.revision, 2)
        self.assertEqual(result.previous_revision, 1)

        candidate = memory.parse_candidates(self.library)[0]
        self.assertEqual(candidate.status, memory.STATUS_VERIFIED, "候选在候选文件里标 VERIFIED")
        verified = memory.parse_memory(self.library, type="fact")
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0].id, entry.id, "正式副本同 ID，便于追溯")
        self.assertEqual(verified[0].text, "正文第一行\n正文第二行")
        self.assertEqual(verified[0].verified_by, "human")
        self.assertEqual(verified[0].sources, ("session-a",))
        self.assertEqual(verified[0].revision, 2, "正式副本与候选同 revision（verify 的返回可直接用于 CAS）")

        verified_text = memory.type_path(self.library, "fact").read_text(encoding="utf-8")
        self.assertIn(":PM_STATUS: VERIFIED", verified_text)
        self.assertIn(":PM_VERIFIED_BY: human", verified_text)
        # 状态迁移与原因写在候选文件（状态唯一真相在候选文件，② 的原子写）
        candidate_text = self.candidates.read_text(encoding="utf-8")
        self.assertIn('State "VERIFIED" from "CANDIDATE"', candidate_text)
        self.assertIn("reason=人工确认", candidate_text)

    def test_published_revision_matches_candidate_after_verify(self) -> None:
        entry = self.candidate("revision 同步")
        result = memory.verify(self.library, entry.id, expected_revision=1, now=NOW)
        published = memory.parse_memory(self.library, type="fact")[0]
        candidate = memory.parse_candidates(self.library)[0]
        self.assertEqual(result.revision, 2)
        self.assertEqual(published.revision, result.revision, "verify 返回的 revision 必须能直接用于正式条目的 CAS")
        self.assertEqual(candidate.revision, result.revision)
        self.assertEqual(result.extra["verifiedRevision"], result.revision)
        # create_entity 一次写成：不再有兜底 promote（无 :PM_PROMOTED_AT:、无第二条审计）
        text = memory.type_path(self.library, "fact").read_text(encoding="utf-8")
        self.assertNotIn("PM_PROMOTED_AT", text)
        self.assertEqual(text.count("- State "), 1, "正式副本只应有创建那一条审计")
        done = memory.deprecate(self.library, entry.id, expected_revision=result.revision,
                                reason="过时", now=NOW)
        self.assertEqual(done.status, memory.STATUS_DEPRECATED, "verify → deprecate 必须连续可用")

    def test_rerun_after_crash_does_not_duplicate_or_resync(self) -> None:
        """① 写完、② 前崩溃：正式副本已在目标 revision；重跑不重复追加、不再多写。"""
        entry = self.candidate("崩溃")
        vpath = memory.type_path(self.library, "fact")
        entities.create_entity(
            vpath, entity_id=entry.id, kind="memory", status=memory.STATUS_VERIFIED,
            headline="崩溃", section="Facts",
            properties={"PM_SCOPE": "demo", "PM_TYPE": "fact", "PM_SOURCES": "session-a",
                        "PM_REVISION": "2"},
            body_lines=[], actor="human", now=NOW,
        )
        before = vpath.read_bytes()
        result = memory.verify(self.library, entry.id, expected_revision=1, now=NOW)
        self.assertFalse(result.extra["verifiedCopyWritten"])
        self.assertEqual(vpath.read_bytes(), before, "已有正式副本时不得再写它")
        published = memory.parse_memory(self.library, type="fact")
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].revision, result.revision)
        self.assertEqual(published[0].revision, 2)

    def test_stale_published_revision_is_flagged_not_hidden(self) -> None:
        """正式副本 revision 落后（旧版流程/人工改动）时：照常发布，但如实标注，不假装同步。"""
        entry = self.candidate("落后副本")
        vpath = memory.type_path(self.library, "fact")
        entities.create_entity(
            vpath, entity_id=entry.id, kind="memory", status=memory.STATUS_VERIFIED,
            headline="落后副本", section="Facts",
            properties={"PM_SCOPE": "demo", "PM_TYPE": "fact", "PM_SOURCES": "session-a"},
            body_lines=[], actor="human", now=NOW,
        )
        result = memory.verify(self.library, entry.id, expected_revision=1, now=NOW)
        self.assertFalse(result.extra["verifiedCopyWritten"])
        self.assertEqual(result.extra["verifiedRevision"], 1)
        self.assertEqual(result.extra["revisionOutOfSync"]["candidateRevisionAfterVerify"], 2)
        self.assertEqual(len(memory.parse_memory(self.library, type="fact")), 1)
        self.assertEqual(memory.parse_candidates(self.library)[0].status, memory.STATUS_VERIFIED)

    def test_verify_cas_conflict_writes_nothing(self) -> None:
        entry = self.candidate()
        before = self.candidates.read_bytes()
        with self.assertRaises(entities.EntityError) as raised:
            memory.verify(self.library, entry.id, expected_revision=99, actor="human", now=NOW)
        self.assertEqual(raised.exception.code, "REVISION_CONFLICT")
        self.assertEqual(raised.exception.exit_code, 3)
        self.assertEqual(self.candidates.read_bytes(), before, "CAS 冲突时逐字节不变")
        self.assertFalse((self.library / "memory").exists(), "预检拦住后不得先写正式副本")

    def test_verify_idempotency_key_replays_first_result(self) -> None:
        entry = self.candidate()
        first = memory.verify(self.library, entry.id, expected_revision=1, idempotency_key="k1", now=NOW)
        second = memory.verify(self.library, entry.id, expected_revision=2, idempotency_key="k1", now=NOW)
        self.assertTrue(second.idempotent)
        self.assertEqual(second.audit_event_id, first.audit_event_id)
        self.assertEqual(len(memory.parse_memory(self.library, type="fact")), 1)

    def test_verify_reusing_the_add_key_is_rejected(self) -> None:
        """一个 key = 一次逻辑写入：创建 key 不能拿来 verify，否则统一机制会当重放、留下半写状态。"""
        created = memory.add_candidate(self.library, text="同 key 候选", scope="demo", type="fact",
                                       idempotency_key="shared-key", now=NOW)
        before = self.candidates.read_bytes()
        with self.assertRaises(entities.EntityError) as raised:
            memory.verify(self.library, created.entity_id, expected_revision=1,
                          idempotency_key="shared-key", now=NOW)
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(self.candidates.read_bytes(), before)
        self.assertFalse((self.library / "memory").exists(), "拒绝时连 VERIFIED 副本都不写")
        self.assertEqual(memory.parse_candidates(self.library)[0].status, memory.STATUS_CANDIDATE)

    def test_verify_idempotency_key_reuse_on_other_candidate_is_rejected(self) -> None:
        first = self.candidate("候选一")
        second = self.candidate("候选二")
        memory.verify(self.library, first.id, expected_revision=1, idempotency_key="k-shared", now=NOW)
        with self.assertRaises(entities.EntityError) as raised:
            memory.verify(self.library, second.id, expected_revision=1, idempotency_key="k-shared", now=NOW)
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_KEY_REUSED")
        candidates = {item.id: item for item in memory.parse_candidates(self.library)}
        self.assertEqual(candidates[second.id].status, memory.STATUS_CANDIDATE, "被拒绝的候选不得被改动")

    def test_verify_twice_without_key_is_idempotent(self) -> None:
        entry = self.candidate()
        memory.verify(self.library, entry.id, expected_revision=1, now=NOW)
        again = memory.verify(self.library, entry.id, expected_revision=2, now=NOW)
        self.assertFalse(again.changed)
        self.assertTrue(again.idempotent)
        self.assertEqual(len(memory.parse_memory(self.library, type="fact")), 1, "不得重复追加正式副本")

    def test_verify_conflict_is_rejected_and_files_unchanged(self) -> None:
        self.seed_memory("fact", [make_entry("memory-old", topic="input-scope", text="v3")])
        entry = self.candidate("v4", topic="input-scope")
        memory_before = memory.type_path(self.library, "fact").read_bytes()
        candidates_before = self.candidates.read_bytes()
        with self.assertRaises(memory.MemoryError) as raised:
            memory.verify(self.library, entry.id, expected_revision=1, now=NOW)
        self.assertEqual(raised.exception.code, "MEMORY_CONFLICT")
        self.assertEqual(raised.exception.extra["conflicts"][0]["entryId"], "memory-old")
        self.assertEqual(memory.type_path(self.library, "fact").read_bytes(), memory_before)
        self.assertEqual(self.candidates.read_bytes(), candidates_before)

    def test_verify_with_supersedes_closes_the_chain(self) -> None:
        self.seed_memory("fact", [make_entry("memory-old", topic="input-scope", text="v3")])
        entry = self.candidate("v4", topic="input-scope")
        result = memory.verify(self.library, entry.id, expected_revision=1, supersedes="memory-old",
                               reason="升级到 v4", now=NOW)
        self.assertEqual(result.status, memory.STATUS_VERIFIED)
        entries = memory.parse_memory(self.library, type="fact")
        by_id = {item.id: item for item in entries}
        self.assertEqual(by_id["memory-old"].status, memory.STATUS_DEPRECATED)
        self.assertEqual(by_id["memory-old"].superseded_by, entry.id)
        self.assertEqual(by_id[entry.id].supersedes, "memory-old")
        self.assertEqual(by_id[entry.id].status, memory.STATUS_VERIFIED)
        self.assertEqual(memory.follow_supersessions(entries, "memory-old"), [entry.id])
        pack = memory.context_pack(self.library, "demo")
        self.assertEqual({item["id"] for item in pack["entries"]}, {entry.id})
        self.assertEqual(pack["excluded"]["deprecated"], 1)

    def test_supersede_never_verified_candidate(self) -> None:
        old = self.candidate("旧候选", topic="t")
        new = self.candidate("新候选", topic="t")
        memory.verify(self.library, new.id, expected_revision=1, supersedes=old.id, now=NOW)
        candidates = {item.id: item for item in memory.parse_candidates(self.library)}
        self.assertEqual(candidates[old.id].status, memory.STATUS_DEPRECATED)
        self.assertEqual(candidates[old.id].superseded_by, new.id)
        self.assertEqual(memory.parse_memory(self.library, type="fact")[0].supersedes, old.id)

    def test_supersede_self_is_rejected(self) -> None:
        entry = self.candidate()
        with self.assertRaises(memory.MemoryError) as raised:
            memory.verify(self.library, entry.id, expected_revision=1, supersedes=entry.id, now=NOW)
        self.assertEqual(raised.exception.code, "SUPERSEDE_SELF")

    def test_supersede_deprecated_target_is_rejected(self) -> None:
        self.seed_memory("fact", [make_entry("memory-old", status=memory.STATUS_DEPRECATED, topic="t", text="a")])
        entry = self.candidate("b", topic="t")
        with self.assertRaises(memory.MemoryError) as raised:
            memory.verify(self.library, entry.id, expected_revision=1, supersedes="memory-old", now=NOW)
        self.assertEqual(raised.exception.code, "SUPERSEDE_TARGET_DEPRECATED")

    def test_supersede_requires_matching_scope_and_type(self) -> None:
        self.seed_memory("decision", [make_entry("memory-dec", type="decision", topic="t", text="a")])
        entry = self.candidate("b", topic="t")
        with self.assertRaises(memory.MemoryError) as raised:
            memory.verify(self.library, entry.id, expected_revision=1, supersedes="memory-dec", now=NOW)
        self.assertEqual(raised.exception.code, "SUPERSEDE_SCOPE_MISMATCH")

    def test_supersede_unknown_target_is_rejected(self) -> None:
        entry = self.candidate()
        with self.assertRaises(memory.MemoryError) as raised:
            memory.verify(self.library, entry.id, expected_revision=1, supersedes="memory-nope", now=NOW)
        self.assertEqual(raised.exception.code, "SUPERSEDE_TARGET_NOT_FOUND")

    def test_verify_crash_recovery_converges_without_duplicate(self) -> None:
        """模拟步骤 ① 完成、② 前崩溃：正式副本已存在但候选仍是 CANDIDATE。"""
        entry = self.candidate("崩溃恢复")
        vpath = memory.type_path(self.library, "fact")
        entities.create_entity(
            vpath, entity_id=entry.id, kind="memory", status=memory.STATUS_VERIFIED,
            headline="崩溃恢复", section="Facts",
            properties={"PM_SCOPE": "demo", "PM_TYPE": "fact", "PM_SOURCES": "session-a"},
            body_lines=[], actor="human", now=NOW,
        )
        result = memory.verify(self.library, entry.id, expected_revision=1, now=NOW)
        self.assertFalse(result.extra["verifiedCopyWritten"], "已有同 ID 正式副本 → 不重复追加")
        self.assertEqual(len(memory.parse_memory(self.library, type="fact")), 1)
        self.assertEqual(memory.parse_candidates(self.library)[0].status, memory.STATUS_VERIFIED)

    def test_verify_without_sources_keeps_unsourced_marker_visible(self) -> None:
        entry = self.add_candidate("没有来源的事实", sources=())
        memory.verify(self.library, entry.id, expected_revision=1, now=NOW)
        verified = memory.parse_memory(self.library, type="fact")[0]
        self.assertTrue(verified.unsourced)
        self.assertIn(":PM_UNSOURCED: t", memory.type_path(self.library, "fact").read_text(encoding="utf-8"))
        pack = memory.context_pack(self.library, "demo")
        self.assertTrue(pack["entries"][0]["unsourced"], "无来源的正式条目在上下文包里也可见")

    def test_verify_can_correct_sources(self) -> None:
        entry = self.add_candidate("无来源候选", sources=())
        self.assertTrue(entry.unsourced)
        memory.verify(self.library, entry.id, expected_revision=1, sources=["inbox-9"], now=NOW)
        candidate = memory.parse_candidates(self.library)[0]
        self.assertEqual(candidate.sources, ("inbox-9",))
        self.assertFalse(candidate.unsourced)
        self.assertNotIn(":PM_UNSOURCED:", self.candidates.read_text(encoding="utf-8"))

    def test_step2_failure_reports_partial_and_keeps_verified_copy(self) -> None:
        """补偿式事务：② CAS 失败时，① 写下的同 ID 副本保留，并如实报出已写/未写。"""
        entry = self.candidate("部分写")
        real_apply = entities.apply_change

        def boom(path, entity_id, **kwargs):
            # 只让「② 改候选文件」那一步失败；① 的 create 正常走（模拟并发 CAS 冲突）。
            if Path(path) == self.candidates:
                raise entities.EntityError("REVISION_CONFLICT", "并发修改", exit_code=3, extra={})
            return real_apply(path, entity_id, **kwargs)

        with mock.patch.object(entities, "apply_change", side_effect=boom):
            with self.assertRaises(entities.EntityError) as raised:
                memory.verify(self.library, entry.id, expected_revision=1, now=NOW)
        exc = raised.exception
        self.assertEqual(exc.code, "REVISION_CONFLICT")
        self.assertTrue(exc.extra["partial"])
        self.assertTrue(exc.extra["verifiedCopyWritten"])
        self.assertIn("候选 :PM_STATUS: → VERIFIED", exc.extra["notWritten"])
        self.assertEqual(len(memory.parse_memory(self.library, type="fact")), 1, "① 的副本保留、可追溯")
        self.assertEqual(memory.parse_candidates(self.library)[0].status, memory.STATUS_CANDIDATE)

    def test_step3_failure_reports_partial_chain(self) -> None:
        """补偿式事务：③ 失败时新条目与候选状态已落地，但链未闭合，必须如实说明。"""
        self.seed_memory("fact", [make_entry("memory-old", topic="t", text="v3")])
        entry = self.candidate("v4", topic="t")
        real_apply = entities.apply_change

        def fake(path, entity_id, **kwargs):
            if entity_id == "memory-old":
                raise entities.EntityError("REVISION_CONFLICT", "并发修改", exit_code=3, extra={})
            return real_apply(path, entity_id, **kwargs)

        with mock.patch.object(entities, "apply_change", side_effect=fake):
            with self.assertRaises(entities.EntityError) as raised:
                memory.verify(self.library, entry.id, expected_revision=1, supersedes="memory-old", now=NOW)
        exc = raised.exception
        self.assertEqual(exc.code, "REVISION_CONFLICT")
        self.assertTrue(exc.extra["partial"])
        self.assertEqual(exc.extra["candidateStatus"], "VERIFIED")
        self.assertIn("链未闭合", exc.extra["notWritten"][0])
        by_id = {item.id: item for item in memory.parse_memory(self.library, type="fact")}
        self.assertEqual(by_id[entry.id].status, memory.STATUS_VERIFIED)
        self.assertEqual(by_id["memory-old"].status, memory.STATUS_VERIFIED, "旧条目未被改动")

    def test_verify_unknown_id_is_rejected(self) -> None:
        with self.assertRaises(entities.EntityError) as raised:
            memory.verify(self.library, "memory-missing", expected_revision=1, now=NOW)
        self.assertEqual(raised.exception.code, "NOT_FOUND")

    def test_verify_dry_run_plans_without_writing(self) -> None:
        entry = self.candidate()
        before = self.candidates.read_bytes()
        result = memory.verify(self.library, entry.id, expected_revision=1, dry_run=True, now=NOW)
        self.assertTrue(result.dry_run)
        self.assertTrue(result.extra["verifiedCopyPlanned"])
        self.assertFalse(result.extra["verifiedCopyWritten"])
        self.assertGreater(result.extra["verifiedLine"], 0)
        self.assertEqual(self.candidates.read_bytes(), before)
        self.assertFalse((self.library / "memory").exists(), "dry-run 不得创建 memory/ 目录")
        self.assertEqual(memory.parse_candidates(self.library)[0].status, memory.STATUS_CANDIDATE)

    def test_verify_dry_run_via_cli(self) -> None:
        payload = self.add("候选")
        code, stdout, _ = self.pm("memory", "verify", payload["entityId"],
                                  "--expected-revision", "1", "--dry-run", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout)["dry_run"])
        self.assertFalse((self.library / "memory").exists())


# ================================================================ 写入：deprecate

class DeprecateTest(MemoryBaseTest):
    def test_deprecate_requires_reason(self) -> None:
        self.seed_memory("fact", [make_entry("memory-a")])
        with self.assertRaises(memory.MemoryError) as raised:
            memory.deprecate(self.library, "memory-a", expected_revision=1, reason="  ")
        self.assertEqual(raised.exception.code, "REASON_REQUIRED")

    def test_deprecate_keeps_history_and_audits(self) -> None:
        self.seed_memory("fact", [make_entry("memory-a", text="保留这段历史")])
        result = memory.deprecate(self.library, "memory-a", expected_revision=1, reason="被新结论取代", now=NOW)
        self.assertEqual(result.status, memory.STATUS_DEPRECATED)
        self.assertEqual(result.revision, 2)
        entry = memory.parse_memory(self.library, type="fact")[0]
        self.assertEqual(entry.status, memory.STATUS_DEPRECATED)
        self.assertEqual(entry.text, "保留这段历史", "废弃只改状态，不删历史")
        self.assertIsNotNone(entry.deprecated_at)
        text = memory.type_path(self.library, "fact").read_text(encoding="utf-8")
        self.assertIn("reason=被新结论取代", text)

    def test_deprecate_with_successor_writes_backlink(self) -> None:
        self.seed_memory("fact", [make_entry("memory-a"), make_entry("memory-b", text="新结论")])
        memory.deprecate(self.library, "memory-a", expected_revision=1, reason="更新",
                         superseded_by="memory-b", now=NOW)
        by_id = {item.id: item for item in memory.parse_memory(self.library, type="fact")}
        self.assertEqual(by_id["memory-a"].superseded_by, "memory-b")
        self.assertEqual(memory.follow_supersessions(list(by_id.values()), "memory-a"), ["memory-b"])

    def test_deprecate_can_target_unverified_candidate(self) -> None:
        entry = self.add_candidate("还没确认就不要了")
        result = memory.deprecate(self.library, entry.id, expected_revision=1, reason="不需要", now=NOW)
        self.assertEqual(result.status, memory.STATUS_DEPRECATED)
        self.assertEqual(result.path, self.candidates)
        self.assertEqual(memory.parse_candidates(self.library)[0].status, memory.STATUS_DEPRECATED)

    def test_deprecate_unknown_id(self) -> None:
        with self.assertRaises(entities.EntityError) as raised:
            memory.deprecate(self.library, "memory-nope", expected_revision=1, reason="x")
        self.assertEqual(raised.exception.code, "NOT_FOUND")

    def test_deprecate_cas_conflict_writes_nothing(self) -> None:
        self.seed_memory("fact", [make_entry("memory-a")])
        before = memory.type_path(self.library, "fact").read_bytes()
        with self.assertRaises(entities.EntityError) as raised:
            memory.deprecate(self.library, "memory-a", expected_revision=5, reason="x", now=NOW)
        self.assertEqual(raised.exception.code, "REVISION_CONFLICT")
        self.assertEqual(memory.type_path(self.library, "fact").read_bytes(), before)


class DeprecateKeyGuardTest(MemoryBaseTest):
    """一个 key = 一次逻辑写入：别的操作的 key 不能拿来 deprecate（否则退 0 的假成功）。"""

    def _seed_verified_with_creation_key(self, key: str) -> Path:
        path = memory.type_path(self.library, "fact")
        path.parent.mkdir(parents=True, exist_ok=True)
        block, _audit = entities.build_entity_block(
            entity_id="memory-a", kind="memory", status=memory.STATUS_VERIFIED,
            headline="保留这段历史",
            properties={"PM_SCOPE": "demo", "PM_TYPE": "fact", "PM_SOURCES": "session-a"},
            body_lines=["正文"], actor="human", at=NOW, idempotency_key=key,
        )
        path.write_text("* Facts\n\n" + block + "\n", encoding="utf-8")
        return path

    def test_key_operations_classification(self) -> None:
        region = "\n".join([
            '- State "CANDIDATE" from "(created)" [2026-10-12 Mon 12:00] id=x audit=a1 key=k1',
            '- State "VERIFIED" from "CANDIDATE" [2026-10-12 Mon 12:00] id=x audit=a2 key=k2',
            '- State "DEPRECATED" from "VERIFIED" [2026-10-12 Mon 12:00] id=x audit=a3 key=k3',
            "- 无状态行但带 key=k4",
        ])
        self.assertEqual(memory._key_operations(region, "k1"), {"create"})
        self.assertEqual(memory._key_operations(region, "k2"), {"verify"})
        self.assertEqual(memory._key_operations(region, "k3"), {"deprecate"})
        self.assertEqual(memory._key_operations(region, "k4"), {"other"})
        self.assertEqual(memory._key_operations(region, "nope"), set())

    def test_deprecate_reusing_creation_key_is_rejected(self) -> None:
        path = self._seed_verified_with_creation_key("create-key")
        before = path.read_bytes()
        with self.assertRaises(entities.EntityError) as raised:
            memory.deprecate(self.library, "memory-a", expected_revision=1, reason="过时",
                             idempotency_key="create-key", now=NOW)
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(raised.exception.exit_code, 2)
        self.assertEqual(path.read_bytes(), before, "被拒时逐字节不变")
        self.assertEqual(memory.parse_memory(self.library, type="fact")[0].status, memory.STATUS_VERIFIED)

    def test_deprecate_reusing_creation_key_via_cli_exits_2(self) -> None:
        path = self._seed_verified_with_creation_key("create-key")
        before = path.read_bytes()
        code, stdout, _ = self.pm("memory", "deprecate", "memory-a", "--expected-revision", "1",
                                  "--reason", "过时", "--idempotency-key", "create-key", "--json")
        self.assertEqual(code, 2, "机器读的退出码必须是失败，而不是 0")
        self.assertEqual(json.loads(stdout)["error"]["code"], "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(path.read_bytes(), before)

    def test_deprecate_reusing_verify_key_is_rejected(self) -> None:
        created = memory.add_candidate(self.library, text="候选", scope="demo", type="fact", now=NOW)
        memory.verify(self.library, created.entity_id, expected_revision=1,
                      idempotency_key="verify-key", now=NOW)
        memory.type_path(self.library, "fact").unlink()  # 只在候选文件里留下 VERIFIED + verify 键
        before = self.candidates.read_bytes()
        with self.assertRaises(entities.EntityError) as raised:
            memory.deprecate(self.library, created.entity_id, expected_revision=2, reason="过时",
                             idempotency_key="verify-key", now=NOW)
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(self.candidates.read_bytes(), before)
        self.assertEqual(memory.parse_candidates(self.library)[0].status, memory.STATUS_VERIFIED)

    def test_deprecate_with_its_own_key_still_replays(self) -> None:
        self.seed_memory("fact", [make_entry("memory-a")])
        first = memory.deprecate(self.library, "memory-a", expected_revision=1, reason="过时",
                                 idempotency_key="dep-key", now=NOW)
        second = memory.deprecate(self.library, "memory-a", expected_revision=2, reason="过时",
                                  idempotency_key="dep-key", now=NOW)
        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertTrue(second.idempotent)
        self.assertEqual(second.audit_event_id, first.audit_event_id)
        self.assertEqual(memory.parse_memory(self.library, type="fact")[0].status, memory.STATUS_DEPRECATED)


# ================================================================ CLI 读命令 / 闸门

class MemoryCliTest(MemoryBaseTest):
    def test_candidates_and_list_json(self) -> None:
        entry = self.add_candidate("候选甲")
        code, stdout, _ = self.pm("memory", "candidates", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["unsourcedCount"], 0)
        self.assertEqual(payload["entries"][0]["id"], entry.id)

        memory.verify(self.library, entry.id, expected_revision=1, now=NOW)
        code, stdout, _ = self.pm("memory", "list", "--json")
        self.assertEqual(code, 0)
        listing = json.loads(stdout)
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["entries"][0]["status"], "VERIFIED")
        self.assertEqual(listing["entries"][0]["type"], "fact")
        self.assertIn("line", listing["entries"][0])

    def test_context_command_json_only_verified(self) -> None:
        entry = self.add_candidate("候选")
        memory.verify(self.library, entry.id, expected_revision=1, now=NOW)
        self.add_candidate("另一个候选")
        code, stdout, _ = self.pm("memory", "context", "--scope", "demo", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual([row["id"] for row in payload["entries"]], [entry.id])
        self.assertEqual(payload["excluded"]["candidate"], 1)

    def test_read_commands_do_not_need_the_write_gate(self) -> None:
        code, stdout, _ = self.pm("memory", "candidates", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout)["ok"])

    def test_deprecate_without_reason_via_cli_exits_2(self) -> None:
        entry = self.add_candidate("候选")
        code, stdout, _ = self.pm("memory", "deprecate", entry.id, "--expected-revision", "1", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "REASON_REQUIRED")

    def test_verify_cas_conflict_via_cli_exits_3(self) -> None:
        payload = self.add("候选")
        code, stdout, _ = self.pm("memory", "verify", payload["entityId"],
                                  "--expected-revision", "99", "--json")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(stdout)["error"]["code"], "REVISION_CONFLICT")

    def test_cli_partial_write_reports_written_and_not_written(self) -> None:
        payload = self.add("部分写")
        real_apply = entities.apply_change

        def boom(path, entity_id, **kwargs):
            if Path(path) == self.candidates:
                raise entities.EntityError("REVISION_CONFLICT", "并发修改", exit_code=3, extra={})
            return real_apply(path, entity_id, **kwargs)

        with mock.patch.object(entities, "apply_change", side_effect=boom):
            code, stdout, _ = self.pm("memory", "verify", payload["entityId"],
                                      "--expected-revision", "1", "--json")
        self.assertEqual(code, 3)
        body = json.loads(stdout)
        self.assertTrue(body["partial"])
        self.assertTrue(body["verifiedCopyWritten"])
        self.assertIn("候选 :PM_STATUS: → VERIFIED", body["notWritten"])
        self.assertEqual(len(memory.parse_memory(self.library, type="fact")), 1)

    def test_invalid_type_is_an_argparse_error(self) -> None:
        code, _stdout, _stderr = self.pm("memory", "add", "--text", "x", "--scope", "global", "--type", "note")
        self.assertEqual(code, 2)

    def test_missing_library_dir_is_rejected(self) -> None:
        config = self.base / "missing.toml"
        config.write_text('library = "' + str(self.base / "nope") + '"\n', encoding="utf-8")
        code, stdout, _ = self.run_cli(["--config", str(config), "memory", "add", "--text", "x",
                                        "--scope", "global", "--type", "fact", "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "LIBRARY_MISSING")


class MemoryWriteGateTest(MemoryBaseTest):
    """写入闸门：没显式 --config 又不是 --dry-run 时必须 --yes（用 PM_CONFIG 模拟默认配置）。"""

    def run_gated(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"PM_CONFIG": str(self.config)}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_gate_blocks_without_config_or_yes(self) -> None:
        code, stdout, stderr = self.run_gated(
            ["memory", "add", "--text", "探针", "--scope", "global", "--type", "fact", "--json"])
        self.assertEqual(code, 2)
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("--yes", payload["error"]["message"])
        self.assertFalse(self.candidates.exists(), "被闸门拒绝时一个字节都不能写")

    def test_gate_allows_with_yes(self) -> None:
        code, stdout, _ = self.run_gated(
            ["memory", "add", "--text", "确认写入", "--scope", "global", "--type", "fact", "--yes", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(self.candidates.exists())

    def test_dry_run_needs_no_yes_and_writes_nothing(self) -> None:
        code, stdout, _ = self.run_gated(
            ["memory", "add", "--text", "预演", "--scope", "global", "--type", "fact", "--dry-run", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout)["dry_run"])
        self.assertFalse(self.candidates.exists())


if __name__ == "__main__":
    unittest.main()
