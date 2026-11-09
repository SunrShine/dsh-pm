"""pm task evidence rm + 证据 id（库任务 task-01M4ZPRF…）。

验收标准对应：
0. rm 能移除该条证据，list 立刻不再列出（exit 0）；
1. 不存在的 id → 明确错误码（非 0），不静默成功；
2. list 输出每条证据的可核对 id；
3. 回归：add / list 行为不变（含 CAS、终态、写闸门）。

全部用临时库；真库一个字节都不碰。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from pm import cli

TASK_TITLE = "带证据的任务"


class EvidenceBaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.library = self.base / "wm"
        self.library.mkdir()
        self.config = self.base / "pm.toml"
        self.config.write_text('library = "' + str(self.library) + '"\n', encoding="utf-8")
        self.tasks_file = self.library / "projects" / "proj-demo" / "tasks.org"
        self.run_cli(["--config", str(self.config), "init", "--root", str(self.library), "--no-git"])
        self.run_cli(["--config", str(self.config), "project", "create", "demo"])
        payload = self.ok("task", "create", "--project", "demo", "--title", TASK_TITLE,
                          "--criterion", "第一条标准", "--criterion", "第二条标准", "--json")
        self.task_id = payload["entityId"]
        self.ok("task", "criteria", "init-ids", self.task_id, "--project", "demo",
                "--expected-revision", "1", "--json")
        ids = [c["id"] for c in self.show()["criteria"]]
        self.cid1, self.cid2 = ids[0], ids[1]

    def run_cli(self, argv: list) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def pm(self, *argv: str) -> tuple:
        return self.run_cli(["--config", str(self.config), *argv])

    def ok(self, *argv: str) -> dict:
        code, stdout, stderr = self.pm(*argv)
        self.assertEqual(code, 0, "命令失败 %r: %s" % (list(argv), stderr))
        return json.loads(stdout)

    def show(self) -> dict:
        return self.ok("task", "show", self.task_id, "--project", "demo", "--json")["task"]

    def revision(self) -> int:
        return self.show()["revision"]

    def add(self, criterion_id: str, ref: str, *, result: str = "pass", kind: str = "test") -> dict:
        return self.ok("task", "evidence", "add", self.task_id, "--project", "demo",
                       "--criterion-id", criterion_id, "--kind", kind, "--result", result,
                       "--ref", ref, "--actor", "ai", "--expected-revision", str(self.revision()), "--json")

    def listed(self) -> list:
        return self.ok("task", "evidence", "list", self.task_id, "--project", "demo", "--json")["evidence"]

    def file_bytes(self) -> bytes:
        return self.tasks_file.read_bytes()


class EvidenceIdTest(EvidenceBaseTest):
    def test_list_gives_a_checkable_id_per_evidence(self) -> None:
        self.add(self.cid1, "tests/a.py")
        self.add(self.cid2, "手工核对过界面", kind="manual", result="info")
        entries = self.listed()
        self.assertEqual(len(entries), 2)
        ids = [entry["id"] for entry in entries]
        self.assertTrue(all(item.startswith("e-") for item in ids), ids)
        self.assertEqual(len(set(ids)), 2, "两条证据的 id 必须不同")
        for entry in entries:  # 逐个字段给出，人能在 org 里对上
            for field in ("criterionId", "kind", "result", "ref", "at", "actor", "raw", "line", "id"):
                self.assertIn(field, entry)

    def test_id_is_content_addressed_and_stable(self) -> None:
        first = self.add(self.cid1, "tests/a.py")["evidence"]["id"]
        # 同一条证据重复提交（六字段相同）→ 不新增，id 不变
        again = self.add(self.cid1, "tests/a.py")["evidence"]["id"]
        self.assertEqual(first, again)
        self.assertEqual(len(self.listed()), 1)
        # 老证据（没有显式 id 字段的行）也能得到 id —— 行内容不变 → id 稳定
        self.assertEqual(self.listed()[0]["id"], first)

    def test_duplicate_lines_get_occurrence_suffix(self) -> None:
        self.add(self.cid1, "tests/a.py")
        entry = self.listed()[0]
        # 手工复制一行到证据节末尾，模拟历史重复行
        text = self.tasks_file.read_text(encoding="utf-8")
        self.tasks_file.write_text(text.rstrip("\n") + "\n" + entry["raw"].strip() + "\n", encoding="utf-8")
        ids = [item["id"] for item in self.listed()]
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])
        self.assertTrue(ids[1].startswith(ids[0] + "-"), ids)


class EvidenceRmTest(EvidenceBaseTest):
    def test_positive_remove_then_list_no_longer_shows_it(self) -> None:
        self.add(self.cid1, "tests/a.py")
        self.add(self.cid2, "手工核对过界面", kind="manual", result="info")
        keep = self.listed()[1]["id"]
        target = self.listed()[0]["id"]
        payload = self.ok("task", "evidence", "rm", self.task_id, target, "--project", "demo",
                          "--actor", "ai", "--reason", "这条不成立", "--expected-revision", str(self.revision()), "--json")
        self.assertTrue(payload["changed"])
        self.assertEqual(payload["evidenceId"], target)
        self.assertEqual(payload["evidenceCount"], 1)
        self.assertEqual(payload["removed"]["id"], target)
        left = [item["id"] for item in self.listed()]
        self.assertEqual(left, [keep], "list 立刻不再列出被删的那条、且不误删别的")

    def test_removed_line_is_gone_and_rest_stays_verbatim(self) -> None:
        """只动"那一条证据行"：它逐字消失，其余行逐字原序保留；另加一条审计行（净行数可能不变）。"""
        self.add(self.cid1, "tests/a.py")
        self.add(self.cid2, "手工核对过界面", kind="manual", result="info")
        before_lines = self.tasks_file.read_text(encoding="utf-8").split("\n")
        target = self.listed()[0]
        self.ok("task", "evidence", "rm", self.task_id, target["id"], "--project", "demo",
                "--actor", "ai", "--expected-revision", str(self.revision()), "--json")
        after_lines = self.tasks_file.read_text(encoding="utf-8").split("\n")
        self.assertNotIn(target["raw"], after_lines, "被删的那一行必须不在")
        added = [line for line in after_lines if line not in before_lines]
        new_audit = [line for line in added if "op=evidence-rm" in line]
        self.assertEqual(len(new_audit), 1, "只新增一条审计行")
        rest_added = [line for line in added if "op=evidence-rm" not in line]
        self.assertTrue(
            all(line.strip().startswith(":PM_REVISION:") for line in rest_added),
            "除审计行外，只允许 :PM_REVISION: 的值变化；实际多出：" + repr(rest_added),
        )

        def normalized(lines: list) -> list:
            """去掉"本就会变"的三类行：被删的证据行、revision 属性行、新审计行。"""
            return [
                line for line in lines
                if line != target["raw"]
                and not line.strip().startswith(":PM_REVISION:")
                and "op=evidence-rm" not in line
            ]

        self.assertEqual(normalized(after_lines), normalized(before_lines),
                         "除被删行/审计行/revision 属性行外，其余行逐字、原序保留")

    def test_unknown_id_is_an_explicit_error(self) -> None:
        self.add(self.cid1, "tests/a.py")
        before = self.file_bytes()
        code, stdout, stderr = self.pm("task", "evidence", "rm", self.task_id, "e-ffff",
                                       "--project", "demo", "--actor", "ai",
                                       "--expected-revision", str(self.revision()), "--json")
        self.assertEqual(code, 2)
        self.assertIn("EVIDENCE_NOT_FOUND", stdout + stderr)
        self.assertEqual(self.file_bytes(), before, "报错时零写入")

    def test_unknown_id_extra_lists_existing_ids(self) -> None:
        self.add(self.cid1, "tests/a.py")
        existing = self.listed()[0]["id"]
        code, stdout, _ = self.pm("task", "evidence", "rm", self.task_id, "e-ffff",
                                  "--project", "demo", "--actor", "ai",
                                  "--expected-revision", str(self.revision()), "--json")
        self.assertEqual(code, 2)
        self.assertIn(existing, stdout, "错误里要带现有 ids，便于核对")

    def test_stale_revision_conflicts_without_writing(self) -> None:
        self.add(self.cid1, "tests/a.py")
        target = self.listed()[0]["id"]
        before = self.file_bytes()
        code, _, stderr = self.pm("task", "evidence", "rm", self.task_id, target, "--project", "demo",
                                  "--actor", "ai", "--expected-revision", "999")
        self.assertEqual(code, 3)
        self.assertIn("REVISION_CONFLICT", stderr)
        self.assertEqual(self.file_bytes(), before, "CAS 不匹配 → 一字节不写")

    def test_dry_run_writes_nothing(self) -> None:
        self.add(self.cid1, "tests/a.py")
        target = self.listed()[0]["id"]
        before = self.file_bytes()
        code, stdout, _ = self.pm("task", "evidence", "rm", self.task_id, target, "--project", "demo",
                                  "--actor", "ai", "--dry-run",
                                  "--expected-revision", str(self.revision()), "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout)["dry_run"])
        self.assertEqual(self.file_bytes(), before, "--dry-run 零写入")
        self.assertEqual(len(self.listed()), 1, "干跑后证据还在")

    def test_terminal_task_is_rejected(self) -> None:
        self.add(self.cid1, "tests/a.py")
        target = self.listed()[0]["id"]
        self.ok("task", "transition", self.task_id, "--project", "demo", "--to", "NEXT",
                "--actor", "human", "--expected-revision", str(self.revision()), "--json")
        self.ok("task", "transition", self.task_id, "--project", "demo", "--to", "DOING",
                "--actor", "human", "--expected-revision", str(self.revision()), "--json")
        self.ok("task", "transition", self.task_id, "--project", "demo", "--to", "REVIEW",
                "--actor", "ai", "--expected-revision", str(self.revision()), "--json")
        self.ok("task", "transition", self.task_id, "--project", "demo", "--to", "DONE",
                "--actor", "human", "--expected-revision", str(self.revision()), "--json")
        before = self.file_bytes()
        code, stdout, stderr = self.pm("task", "evidence", "rm", self.task_id, target, "--project", "demo",
                                       "--actor", "ai", "--expected-revision", str(self.revision()), "--json")
        self.assertEqual(code, 2)
        self.assertIn("TASK_TERMINAL", stdout + stderr)
        self.assertEqual(self.file_bytes(), before, "终态任务零写入")

    def test_foreign_task_id_is_not_found_and_writes_nothing(self) -> None:
        before = self.file_bytes()
        code, stdout, stderr = self.pm("task", "evidence", "rm",
                                       "task-01M4ZZZZZZZZZZZZZZZZZZZZZZ", "e-ffff",
                                       "--project", "demo", "--actor", "ai",
                                       "--expected-revision", "1", "--json")
        self.assertEqual(code, 2)
        self.assertIn("NOT_FOUND", stdout + stderr)
        self.assertEqual(self.file_bytes(), before)

    def test_write_gate_needs_yes_without_explicit_config(self) -> None:
        default_config = Path(__file__).resolve().parent.parent / "config" / "pm.toml"
        if not default_config.is_file():
            self.skipTest("发布副本不含私有 config/pm.toml ⇒ 默认配置写入闸在本环境不适用（不是通过，是跳过）")
        self.add(self.cid1, "tests/a.py")
        target = self.listed()[0]["id"]
        before = self.file_bytes()
        code, _, stderr = self.run_cli(["task", "evidence", "rm", self.task_id, target,
                                        "--project", "demo", "--actor", "ai",
                                        "--expected-revision", str(self.revision())])
        self.assertEqual(code, 2)
        self.assertIn("拒绝写入", stderr)
        self.assertEqual(self.file_bytes(), before)


class EvidenceRegressionTest(EvidenceBaseTest):
    def test_add_and_list_behaviour_unchanged(self) -> None:
        payload = self.add(self.cid1, "tests/a.py")
        self.assertTrue(payload["changed"])
        self.assertEqual(payload["evidenceCount"], 1)
        entry = payload["evidence"]
        self.assertEqual(entry["criterionId"], self.cid1)
        self.assertEqual(entry["kind"], "test")
        self.assertEqual(entry["result"], "pass")
        self.assertEqual(entry["actor"], "ai")
        self.assertIsNone(entry["note"])
        duplicate = self.add(self.cid1, "tests/a.py")
        self.assertFalse(duplicate["changed"], "六字段相同的重复提交仍为 changed:false")
        self.assertEqual(len(self.listed()), 1)

    def test_task_list_shows_count_and_last_evidence(self) -> None:
        self.add(self.cid1, "tests/a.py")
        self.add(self.cid2, "手工核对过界面", kind="manual", result="info")
        row = [t for g in self.ok("task", "list", "--project", "demo", "--json")["groups"]
               for t in g["tasks"] if t["id"] == self.task_id][0]
        self.assertEqual(row["evidenceCount"], 2)
        self.assertNotIn("evidence", row, "list 仍不塞整个数组")
        last = row["lastEvidence"]
        self.assertEqual(last["kind"], "manual")
        self.assertEqual(last["result"], "info")
        self.assertTrue(last["id"].startswith("e-"))
        self.assertEqual(last["criterionId"], self.cid2)

    def test_task_show_keeps_old_evidence_fields(self) -> None:
        self.add(self.cid1, "tests/a.py")
        entry = self.show()["evidence"][0]
        for field in ("criterionId", "kind", "result", "ref", "at", "actor", "note", "raw", "line"):
            self.assertIn(field, entry, "既有字段一个都不能少")
        self.assertEqual(self.show()["evidenceCount"], 1)

    def test_audit_line_records_evidence_rm(self) -> None:
        self.add(self.cid1, "tests/a.py")
        target = self.listed()[0]["id"]
        self.ok("task", "evidence", "rm", self.task_id, target, "--project", "demo", "--actor", "ai",
                "--reason", "为什么不成立", "--expected-revision", str(self.revision()), "--json")
        text = self.tasks_file.read_text(encoding="utf-8")
        self.assertIn("op=evidence-rm", text)
        self.assertIn("evidence=" + target, text)
        self.assertIn("reason=为什么不成立", text)


if __name__ == "__main__":
    unittest.main()
