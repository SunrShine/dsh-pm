"""entities.py 通用骨架：replace_lines 安全约束 / create_entity(indent_body, dry_run)。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pm import entities

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=TZ)

ENTITY_ID = "task-01M4Q0000000000000000000AA"

DOC = """* Tasks

** TODO 写验收标准
   :PROPERTIES:
   :ID: task-01M4Q0000000000000000000AA
   :PM_KIND: task
   :PM_STATUS: TODO
   :PM_REVISION: 1
   :END:
   :LOGBOOK:
   - State "TODO" from "(created)" [2026-10-12 Mon 10:00] id=task-01M4Q0000000000000000000AA audit=audit-01M4Q0000000000000000000BB at=2026-10-12T10:00:00+08:00 actor=human rev=1
   :END:
   目标：把输入范围写清楚。
*** 验收标准
   - [ ] 列出输入版本
"""


class EntityReplaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "tasks.org"
        self.path.write_text(DOC, encoding="utf-8")

    def offset_of(self, needle: str) -> int:
        text = self.path.read_text(encoding="utf-8")
        lines = text.split("\n")
        block = next(
            block
            for block in entities.iter_entity_blocks(text)
            if block["props"].get("ID") == ENTITY_ID
        )
        for index in range(block["start"], block["end"]):
            if needle in lines[index]:
                return index - block["start"]
        raise AssertionError("needle not found: " + needle)

    def apply(self, **kwargs):
        return entities.apply_change(
            self.path, ENTITY_ID, expected_revision=kwargs.pop("expected_revision", 1),
            now=NOW, **kwargs,
        )

    def test_replace_body_line_bumps_revision_and_audits(self) -> None:
        offset = self.offset_of("- [ ] 列出输入版本")
        result = self.apply(replace_lines={offset: "   - [x] 列出输入版本"})
        self.assertTrue(result.changed)
        self.assertEqual(result.revision, 2)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("   - [x] 列出输入版本", text)
        self.assertNotIn("- [ ] 列出输入版本", text)
        self.assertIn(":PM_REVISION: 2", text)
        self.assertIn('- State "TODO" from "TODO"', text)
        self.assertIn("rev=2", text)

    def test_replace_headline_same_level_ok(self) -> None:
        result = self.apply(status="DONE", replace_lines={0: "** DONE 写验收标准"})
        self.assertEqual(result.revision, 2)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("** DONE 写验收标准", text)
        self.assertIn('- State "DONE" from "TODO"', text)
        self.assertIn(":PM_STATUS: DONE", text)
        # 只写了一条审计行（同一次原子写）
        self.assertEqual(text.count('- State "DONE" from "TODO"'), 1)

    def test_replace_headline_level_change_rejected(self) -> None:
        for replacement in ("*** DONE 写验收标准", "写验收标准", "* DONE"):
            before = self.path.read_bytes()
            with self.assertRaises(entities.EntityError) as ctx:
                self.apply(replace_lines={0: replacement})
            self.assertEqual(ctx.exception.code, "INVALID_REPLACE_LINE")
            self.assertEqual(self.path.read_bytes(), before)

    def test_replace_out_of_range_rejected(self) -> None:
        for offset in (-1, 99):
            before = self.path.read_bytes()
            with self.assertRaises(entities.EntityError) as ctx:
                self.apply(replace_lines={offset: "   x"})
            self.assertEqual(ctx.exception.code, "INVALID_REPLACE_RANGE")
            self.assertEqual(self.path.read_bytes(), before)

    def test_replace_child_headline_allowed_sibling_rejected(self) -> None:
        offset = self.offset_of("目标：把输入范围写清楚")
        self.apply(replace_lines={offset: "*** 参考模型"})
        self.assertIn("*** 参考模型", self.path.read_text(encoding="utf-8"))

        self.path.write_text(DOC, encoding="utf-8")
        before = self.path.read_bytes()
        offset = self.offset_of("目标：把输入范围写清楚")
        with self.assertRaises(entities.EntityError) as ctx:
            self.apply(replace_lines={offset: "** 兄弟标题"})
        self.assertEqual(ctx.exception.code, "INVALID_REPLACE_LINE")
        self.assertEqual(self.path.read_bytes(), before)

    def test_replace_inside_drawer_or_logbook_rejected(self) -> None:
        for needle in (":ID: task-", '- State "TODO" from "(created)"'):
            before = self.path.read_bytes()
            with self.assertRaises(entities.EntityError) as ctx:
                self.apply(replace_lines={self.offset_of(needle): "   :X: y"})
            self.assertEqual(ctx.exception.code, "INVALID_REPLACE_RANGE")
            self.assertEqual(self.path.read_bytes(), before)

    def test_replace_lines_conflict_leaves_file_byte_identical(self) -> None:
        before = self.path.read_bytes()
        offset = self.offset_of("目标：把输入范围写清楚")
        with self.assertRaises(entities.EntityError) as ctx:
            self.apply(expected_revision=9, replace_lines={offset: "   改过了"})
        self.assertEqual(ctx.exception.code, "REVISION_CONFLICT")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertEqual(self.path.read_bytes(), before)

    def test_validate_sees_old_entity_before_replacement(self) -> None:
        seen: list[tuple] = []

        def validate(entity, target_status):
            seen.append((entity.status, entity.headline, target_status))

        self.apply(
            status="DONE", replace_lines={0: "** DONE 写验收标准"}, validate=validate
        )
        self.assertEqual(seen, [("TODO", "** TODO 写验收标准", "DONE")])


class CreateEntityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.path = self.root / "tasks.org"

    def test_indent_body_true_is_default(self) -> None:
        entities.create_entity(
            self.path, entity_id="task-1", kind="task", status="TODO",
            headline="TODO 写验收标准", section="任务",
            properties={"PM_PROJECT_ID": "demo"},
            body_lines=["目标：写清楚", "", "- [ ] 列出输入版本"],
            now=NOW,
        )
        lines = self.path.read_text(encoding="utf-8").split("\n")
        self.assertIn("   目标：写清楚", lines)
        self.assertIn("   - [ ] 列出输入版本", lines)
        self.assertIn("", lines)

    def test_indent_body_false_keeps_verbatim(self) -> None:
        entities.create_entity(
            self.path, entity_id="task-2", kind="task", status="TODO",
            headline="TODO 带验收标准", section="任务",
            body_lines=["*** 验收标准", "   - [ ] 列出输入版本"],
            indent_body=False, now=NOW,
        )
        text = self.path.read_text(encoding="utf-8")
        lines = text.split("\n")
        self.assertIn("*** 验收标准", lines)
        self.assertNotIn("   *** 验收标准", lines)
        self.assertIn("   - [ ] 列出输入版本", lines)

    def test_create_entity_dry_run_matches_real_write(self) -> None:
        kwargs = dict(
            entity_id="task-3", kind="task", status="TODO",
            headline="TODO 预演", section="任务", body_lines=["正文"], now=NOW,
        )
        line, audit_id = entities.create_entity(self.path, dry_run=True, **kwargs)
        self.assertFalse(self.path.exists(), "dry-run 不得创建文件")
        self.assertRegex(audit_id, r"^audit-[0-9A-HJKMNP-TV-Z]{26}$")

        real_line, _real_audit = entities.create_entity(self.path, **kwargs)
        self.assertEqual(line, real_line, "dry-run 的行号必须与真写一致")
        self.assertTrue(self.path.is_file())

    def test_create_entity_block_is_pure(self) -> None:
        block, audit_id = entities.build_entity_block(
            entity_id="task-4", kind="task", status="TODO", headline="TODO 纯函数",
            properties={"PM_PROJECT_ID": "demo"}, body_lines=["正文"], at=NOW,
        )
        self.assertIn(":ID: task-4", block)
        self.assertIn(":PM_KIND: task", block)
        self.assertIn(":PM_STATUS: TODO", block)
        self.assertIn(":PM_REVISION: 1", block)
        self.assertIn("audit=" + audit_id, block)
        self.assertIn("   正文", block)
        self.assertFalse(self.path.exists())


    def test_create_entity_idempotency_replay_returns_first_result(self) -> None:
        first = entities.create_entity(
            self.path, entity_id="task-5", kind="task", status="TODO",
            headline="TODO 幂等", section="任务", body_lines=["正文"],
            now=NOW, idempotency_key="ck-1",
        )
        self.assertTrue(first.created)
        self.assertFalse(first.idempotent)
        self.assertIn("key=ck-1", self.path.read_text(encoding="utf-8"))
        after_first = self.path.read_bytes()

        replay = entities.create_entity(
            self.path, entity_id="task-5", kind="task", status="TODO",
            headline="TODO 幂等", section="任务", body_lines=["正文"],
            now=NOW, idempotency_key="ck-1",
        )
        self.assertFalse(replay.created, "重放不得再创建")
        self.assertTrue(replay.idempotent)
        self.assertEqual(replay.line, first.line)
        self.assertEqual(replay.audit_event_id, first.audit_event_id, "重放要指向首次的审计事件")
        self.assertEqual(self.path.read_bytes(), after_first, "重放不得产生第二次写入")

    def test_create_entity_key_reuse_on_other_target_rejected(self) -> None:
        entities.create_entity(
            self.path, entity_id="task-6", kind="task", status="TODO",
            headline="TODO 甲", section="任务", now=NOW, idempotency_key="ck-2",
        )
        before = self.path.read_bytes()
        with self.assertRaises(entities.EntityError) as ctx:
            entities.create_entity(
                self.path, entity_id="task-7", kind="task", status="TODO",
                headline="TODO 乙", section="任务", now=NOW, idempotency_key="ck-2",
            )
        self.assertEqual(ctx.exception.code, "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertEqual(self.path.read_bytes(), before, "被拒时不得写入")

    def test_create_entity_without_key_is_unchanged(self) -> None:
        first = entities.create_entity(
            self.path, entity_id="task-8", kind="task", status="TODO",
            headline="TODO 无 key", section="任务", now=NOW,
        )
        second = entities.create_entity(
            self.path, entity_id="task-8", kind="task", status="TODO",
            headline="TODO 无 key", section="任务", now=NOW,
        )
        # 默认 None：没有去重，行为与以前一致（两次都创建）
        self.assertTrue(first.created and second.created)
        self.assertNotIn("key=", self.path.read_text(encoding="utf-8"))
        # 兼容旧的二元解包
        line, audit_id = first
        self.assertEqual(line, first.line)
        self.assertEqual(audit_id, first.audit_event_id)
        self.assertEqual(first[0], first.line)
        self.assertEqual(len(first), 2)

    def test_create_entity_dry_run_with_key_does_not_mark(self) -> None:
        plan = entities.create_entity(
            self.path, entity_id="task-9", kind="task", status="TODO",
            headline="TODO 预演 key", section="任务", now=NOW,
            dry_run=True, idempotency_key="ck-3",
        )
        self.assertTrue(plan.created)
        self.assertFalse(self.path.exists(), "dry-run 不得落盘")
        # dry-run 没写 marker，所以真写仍然是「新建」
        real = entities.create_entity(
            self.path, entity_id="task-9", kind="task", status="TODO",
            headline="TODO 预演 key", section="任务", now=NOW, idempotency_key="ck-3",
        )
        self.assertTrue(real.created)
        self.assertEqual(real.line, plan.line)


    def test_create_entity_respects_explicit_revision(self) -> None:
        result = entities.create_entity(
            self.path, entity_id="memory-1", kind="memory", status="VERIFIED",
            headline="MEMORY 正式副本", section="Memory",
            properties={"PM_REVISION": "7", "PM_SCOPE": "global"}, now=NOW,
        )
        self.assertEqual(result.revision, 7)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn(":PM_REVISION: 7", text)
        self.assertIn("rev=7", text, "审计行的 rev 也要用该 revision")
        self.assertNotIn(":PM_REVISION: 1", text)

    def test_create_entity_default_revision_is_one(self) -> None:
        result = entities.create_entity(
            self.path, entity_id="memory-2", kind="memory", status="CANDIDATE",
            headline="MEMORY 默认", section="Memory", now=NOW,
        )
        self.assertEqual(result.revision, 1)
        self.assertIn(":PM_REVISION: 1", self.path.read_text(encoding="utf-8"))

    def test_create_entity_rejects_bad_revision(self) -> None:
        with self.assertRaises(entities.EntityError) as ctx:
            entities.create_entity(
                self.path, entity_id="memory-3", kind="memory", status="CANDIDATE",
                headline="MEMORY 坏 revision", section="Memory",
                properties={"PM_REVISION": "abc"}, now=NOW,
            )
        self.assertEqual(ctx.exception.code, "INVALID_REVISION")
        self.assertFalse(self.path.exists(), "被拒时不得写文件")

    def test_create_entity_replay_returns_stored_revision(self) -> None:
        first = entities.create_entity(
            self.path, entity_id="memory-4", kind="memory", status="VERIFIED",
            headline="MEMORY 幂等 revision", section="Memory",
            properties={"PM_REVISION": "5"}, now=NOW, idempotency_key="mr-1",
        )
        self.assertEqual(first.revision, 5)
        replay = entities.create_entity(
            self.path, entity_id="memory-4", kind="memory", status="VERIFIED",
            headline="MEMORY 幂等 revision", section="Memory",
            properties={"PM_REVISION": "5"}, now=NOW, idempotency_key="mr-1",
        )
        self.assertTrue(replay.idempotent)
        self.assertEqual(replay.revision, 5)


PROPOSAL_DOC = """* 提案

** PENDING 一个提案
   :PROPERTIES:
   :ID: proposal-01M4Q0000000000000000000AA
   :PM_KIND: proposal
   :PM_STATUS: PENDING
   :PM_REVISION: 1
   :END:
   :LOGBOOK:
   - State "PENDING" from "(created)" [2026-10-12 Mon 10:00] id=proposal-01M4Q0000000000000000000AA audit=audit-01M4Q0000000000000000000BB at=2026-10-12T10:00:00+08:00 actor=human rev=1
   :END:

   原有正文第一行
   原有正文第二行


** PENDING 下一条
   :PROPERTIES:
   :ID: proposal-01M4Q0000000000000000000CC
   :PM_KIND: proposal
   :PM_STATUS: PENDING
   :PM_REVISION: 1
   :END:
"""

PROPOSAL_ID = "proposal-01M4Q0000000000000000000AA"
NEW_BODY = ["*** 变更", "- 新增：改一件事", "  - 验收：能看见"]


class ReplaceBodyTest(unittest.TestCase):
    """apply_change(replace_body=…)：原样替换正文区，与 append_body 互斥。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "proposals.org"
        self.path.write_text(PROPOSAL_DOC, encoding="utf-8")

    def apply(self, **kwargs):
        return entities.apply_change(
            self.path, PROPOSAL_ID, expected_revision=kwargs.pop("expected_revision", 1),
            now=NOW, actor="ai", **kwargs,
        )

    def blocks(self) -> list[dict]:
        return entities.iter_entity_blocks(self.path.read_text(encoding="utf-8"))

    def body_of(self, entity_id: str) -> list[str]:
        block = next(block for block in self.blocks() if block["props"].get("ID") == entity_id)
        text = self.path.read_text(encoding="utf-8").split("\n")
        return text[block["body_region_start"] : block["end"]]

    def test_replace_body_is_verbatim_and_no_indent(self) -> None:
        result = self.apply(replace_body=list(NEW_BODY))
        self.assertTrue(result.changed)
        self.assertEqual(result.revision, 2)
        body = self.body_of(PROPOSAL_ID)
        # 原样 + 保留尾部两行分隔空行；*** 子标题必须还在第 0 列
        self.assertEqual(body, NEW_BODY + ["", ""])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("\n*** 变更\n", text)
        self.assertNotIn("   原有正文第一行", text)
        self.assertNotIn("   原有正文第二行", text)
        self.assertIn(":PM_STATUS: PENDING", text, "不改状态")

    def test_replace_body_can_shrink(self) -> None:
        self.apply(replace_body=list(NEW_BODY))
        self.apply(expected_revision=2, replace_body=["*** 变更"])
        self.assertEqual(self.body_of(PROPOSAL_ID), ["*** 变更", "", ""])

    def test_replace_body_empty_clears_body(self) -> None:
        result = self.apply(replace_body=[])
        self.assertTrue(result.changed)
        self.assertEqual(self.body_of(PROPOSAL_ID), ["", ""], "空列表 = 清空正文（只留尾部空行）")
        self.assertNotIn("原有正文", self.path.read_text(encoding="utf-8"))

    def test_replace_body_preserves_tail_blank_separator_and_next_entry(self) -> None:
        before_next = [block for block in self.blocks() if block["props"].get("ID") != PROPOSAL_ID]
        next_before = self.path.read_text(encoding="utf-8").split("\n")[before_next[0]["start"] :]
        self.apply(replace_body=list(NEW_BODY))
        blocks = self.blocks()
        next_after = self.path.read_text(encoding="utf-8").split("\n")[blocks[1]["start"] :]
        self.assertEqual(next_after, next_before, "下一条目逐字节不动")
        self.assertEqual(self.body_of(PROPOSAL_ID)[-2:], ["", ""], "分隔空行保留")

    def test_append_body_and_replace_body_are_mutually_exclusive(self) -> None:
        before = self.path.read_bytes()
        with self.assertRaises(entities.EntityError) as ctx:
            self.apply(append_body=["补充"], replace_body=["替换"])
        self.assertEqual(ctx.exception.code, "BODY_MODE_CONFLICT")
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertEqual(self.path.read_bytes(), before, "互斥时不写任何字节")
        # revision 也不对时仍然先报互斥（输入错误优先于 CAS）
        with self.assertRaises(entities.EntityError) as ctx2:
            self.apply(expected_revision=99, append_body=["补充"], replace_body=["替换"])
        self.assertEqual(ctx2.exception.code, "BODY_MODE_CONFLICT")

    def test_replace_body_cas_conflict_bytes_unchanged(self) -> None:
        before = self.path.read_bytes()
        with self.assertRaises(entities.EntityError) as ctx:
            self.apply(expected_revision=9, replace_body=list(NEW_BODY))
        self.assertEqual(ctx.exception.code, "REVISION_CONFLICT")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertEqual(self.path.read_bytes(), before)

    def test_replace_body_identical_content_is_zero_change(self) -> None:
        first = self.apply(replace_body=list(NEW_BODY))
        after = self.path.read_bytes()
        again = self.apply(expected_revision=2, replace_body=list(NEW_BODY))
        self.assertFalse(again.changed, "同内容替换 = 零变更")
        self.assertEqual(again.revision, first.revision)
        self.assertEqual(self.path.read_bytes(), after)
        self.assertEqual(self.path.read_text(encoding="utf-8").count(":LOGBOOK:"), 1)

    def test_replace_body_dry_run_writes_nothing(self) -> None:
        before = self.path.read_bytes()
        result = self.apply(replace_body=list(NEW_BODY), dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.revision, 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_several_replacements_keep_one_logbook(self) -> None:
        for index in range(3):
            self.apply(expected_revision=index + 1, replace_body=["*** 变更", "- 第%d次" % (index + 1)])
        text = self.path.read_text(encoding="utf-8")
        self.assertEqual(text.count(":LOGBOOK:"), 1)
        self.assertEqual(text.count(":PM_REVISION: 4"), 1)
        self.assertEqual(text.count('- State "PENDING" from "PENDING"'), 3)
        self.assertEqual(self.body_of(PROPOSAL_ID), ["*** 变更", "- 第3次", "", ""])

    def test_indented_lines_are_kept_as_given(self) -> None:
        lines = ["*** 变更", "   四个空格开头的行", "\t制表符开头", ""]
        self.apply(replace_body=list(lines))
        self.assertEqual(self.body_of(PROPOSAL_ID), lines + ["", ""])


if __name__ == "__main__":
    unittest.main()
