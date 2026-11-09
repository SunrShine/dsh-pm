"""执行准备向导的 CLI 测试（契约 内部记录（未随仓库发布） §0/§1）。

覆盖：workspace/project/workspace context 读取、execution-config get/set、
link-session / unlink-session、handoff，以及 CAS/审计/幂等/写入门禁。

红线：dispatchStatus 只允许 NOT_READY / HANDOFF_READY；任何输出不得声称已派发/已启动。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pm import cli
from pm.config import derive_source_instance

import fixtures

VERIFIED_ID = "memory-01M4Q0000000000000000000AA"
CANDIDATE_ID = "memory-01M4Q0000000000000000000AB"
DEPRECATED_ID = "memory-01M4Q0000000000000000000AC"
GLOBAL_ID = "memory-01M4Q0000000000000000000AD"
OTHER_SCOPE_ID = "memory-01M4Q0000000000000000000AE"

_ENTRY = """** {title}
   :PROPERTIES:
   :ID: {id}
   :PM_KIND: memory
   :PM_STATUS: {status}
   :PM_SCOPE: {scope}
   :PM_TYPE: fact
   :PM_REVISION: 1
   :END:
"""


class ExecutionBaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.home = fixtures.build_dsh_home(self.base / "dsh")
        self.instance = derive_source_instance(self.home)
        self.library = self.base / "wm"
        (self.library / "memory").mkdir(parents=True)
        (self.library / "memory" / "facts.org").write_text(
            "* 事实\n\n"
            + _ENTRY.format(title="验证要先定输入范围", id=VERIFIED_ID, status="VERIFIED", scope="alpha_beta")
            + "\n"
            + _ENTRY.format(title="已被取代的旧结论", id=DEPRECATED_ID, status="DEPRECATED", scope="alpha_beta")
            + "\n"
            + _ENTRY.format(title="全局约定", id=GLOBAL_ID, status="VERIFIED", scope="global")
            + "\n"
            + _ENTRY.format(title="别的项目的记忆", id=OTHER_SCOPE_ID, status="VERIFIED", scope="other_project"),
            encoding="utf-8",
        )
        (self.library / "memory-candidates.org").write_text(
            "* Memory 候选\n\n"
            + _ENTRY.format(title="还没确认的猜测", id=CANDIDATE_ID, status="CANDIDATE", scope="alpha_beta"),
            encoding="utf-8",
        )
        self.config = self.base / "pm.toml"
        self.config.write_text(
            fixtures.fixture_config_toml(library=str(self.library)).replace("REPLACED", str(self.home)),
            encoding="utf-8",
        )

    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def pm(self, *argv: str) -> tuple[int, str, str]:
        return self.run_cli(["--config", str(self.config), *argv])

    def ok(self, *argv: str) -> dict:
        code, stdout, stderr = self.pm(*argv)
        self.assertEqual(code, 0, "命令失败 %r: %s" % (list(argv), stderr))
        return json.loads(stdout)

    def make_task(self, title: str = "执行配置测试任务") -> str:
        payload = self.ok("task", "create", "--project", "alpha_beta", "--title", title, "--json")
        return payload["entityId"]

    def task_file(self) -> Path:
        return self.library / "projects" / "proj-alpha_beta" / "tasks.org"

    # ---- 读取命令 ----

    def test_commands_are_registered(self) -> None:
        parser = cli.build_parser()
        import argparse

        root = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)][0]
        self.assertIn("workspace", root.choices)
        self.assertIn("project", root.choices)
        task = root.choices["task"]
        task_sub = [a for a in task._actions if isinstance(a, argparse._SubParsersAction)][0]
        for name in ("execution-config", "link-session", "unlink-session", "handoff"):
            self.assertIn(name, task_sub.choices)

    def test_workspace_list_shape(self) -> None:
        payload = self.ok("workspace", "list", "--project", "alpha_beta", "--json")
        self.assertEqual(set(payload), {"project", "workspaces"})
        self.assertEqual(payload["project"], "alpha_beta")
        by_path = {row["path"]: row for row in payload["workspaces"]}
        self.assertIn("/work/alpha", by_path)
        self.assertIn("/work/beta", by_path)
        alpha = by_path["/work/alpha"]
        self.assertEqual(set(alpha), {"path", "title", "instance", "sessionCount"})
        self.assertEqual(alpha["title"], "alpha")
        self.assertEqual(alpha["instance"], self.instance)
        self.assertGreater(alpha["sessionCount"], 0)

    def test_workspace_list_unknown_project_exit_2(self) -> None:
        code, stdout, _ = self.pm("workspace", "list", "--project", "nope", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "UNKNOWN_PROJECT")

    def test_project_context_only_verified(self) -> None:
        payload = self.ok("project", "context", "alpha_beta", "--json")
        self.assertEqual(set(payload), {"project", "memories"})
        ids = {row["id"] for row in payload["memories"]}
        self.assertEqual(ids, {VERIFIED_ID, GLOBAL_ID}, "本 scope + global，且只含 VERIFIED")
        for row in payload["memories"]:
            self.assertEqual(row["status"], "VERIFIED")
            self.assertEqual(set(row), {"id", "type", "scope", "text", "status"}, "每条必须带 scope")
        self.assertNotIn(CANDIDATE_ID, ids, "candidate 永不出现")
        self.assertNotIn(DEPRECATED_ID, ids, "deprecated 永不出现")
        self.assertNotIn(OTHER_SCOPE_ID, ids, "绝不出现其它项目的记忆")

    def test_project_context_no_global(self) -> None:
        payload = self.ok("project", "context", "alpha_beta", "--no-global", "--json")
        self.assertEqual([row["id"] for row in payload["memories"]], [VERIFIED_ID])
        self.assertEqual(payload["memories"][0]["scope"], "alpha_beta")

    def test_workspace_context_no_global_and_scope_present(self) -> None:
        payload = self.ok("workspace", "context", "/work/alpha", "--no-global", "--json")
        self.assertEqual([row["id"] for row in payload["memories"]], [VERIFIED_ID])
        for row in payload["memories"]:
            self.assertIn("scope", row)
            self.assertEqual(row["scope"], "alpha_beta")
        full = self.ok("workspace", "context", "/work/alpha", "--json")
        self.assertEqual({row["id"] for row in full["memories"]}, {VERIFIED_ID, GLOBAL_ID})

    def test_workspace_context_shape(self) -> None:
        payload = self.ok("workspace", "context", "/work/alpha", "--json")
        self.assertEqual(set(payload), {"path", "project", "memories", "sessions"})
        self.assertEqual(payload["path"], "/work/alpha")
        self.assertEqual(payload["project"], "alpha_beta")
        self.assertEqual({row["id"] for row in payload["memories"]}, {VERIFIED_ID, GLOBAL_ID})
        self.assertTrue(payload["sessions"])
        observations = set()
        for row in payload["sessions"]:
            self.assertEqual(set(row), {"id", "instance", "observation", "summary"})
            observations.add(row["observation"])
        allowed = {"BUSY", "STALE_BUSY", "RECENT", "IDLE", "CLOSED", "ARCHIVED", "EMPTY"}
        self.assertTrue(observations <= allowed, observations)
        self.assertNotIn("RUNNING", json.dumps(payload))

    # ---- execution-config ----

    def test_get_defaults_to_not_ready(self) -> None:
        task_id = self.make_task()
        payload = self.ok("task", "execution-config", "get", task_id, "--json")
        self.assertEqual(
            set(payload),
            {
                "taskId", "revision", "project", "workspace", "instance", "memoryRefs",
                "session", "note", "setAt", "setBy", "dispatchStatus",
            },
        )
        self.assertEqual(payload["taskId"], task_id)
        self.assertEqual(payload["revision"], 1)
        self.assertEqual(payload["project"], "alpha_beta")
        self.assertIsNone(payload["workspace"])
        self.assertIsNone(payload["instance"])
        self.assertIsNone(payload["session"])
        self.assertIsNone(payload["note"])
        self.assertEqual(payload["memoryRefs"], [])
        self.assertEqual(payload["dispatchStatus"], "NOT_READY")

    def test_set_writes_props_audit_and_keeps_status(self) -> None:
        task_id = self.make_task()
        payload = self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha",
            "--memory", VERIFIED_ID,
            "--session", fixtures.ALPHA_RECENT,
            "--note", "交接说明",
            "--actor", "human",
            "--expected-revision", "1",
            "--json",
        )
        for key in ("entityId", "revision", "source", "observedAt", "auditEventId"):
            self.assertIn(key, payload)
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["workspace"], "/work/alpha")
        self.assertEqual(payload["session"], fixtures.ALPHA_RECENT)
        self.assertEqual(payload["memoryRefs"], [VERIFIED_ID])
        self.assertEqual(payload["dispatchStatus"], "HANDOFF_READY")

        text = self.task_file().read_text(encoding="utf-8")
        for expected in (
            ":PM_EXEC_PROJECT: alpha_beta",
            ":PM_EXEC_WORKSPACE: /work/alpha",
            ":PM_EXEC_SESSION: " + fixtures.ALPHA_RECENT,
            ":PM_EXEC_MEMORY: " + VERIFIED_ID,
            ":PM_EXEC_NOTE: 交接说明",
            ":PM_EXEC_SET_BY: human",
        ):
            self.assertIn(expected, text)
        self.assertIn(":LOGBOOK:", text)
        self.assertIn("audit=" + payload["auditEventId"], text)
        # 绝不改任务状态
        self.assertIn("** TODO 执行配置测试任务", text)
        self.assertIn(":PM_STATUS: TODO", text)

    def test_set_replaces_optional_fields(self) -> None:
        task_id = self.make_task()
        self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha", "--memory", VERIFIED_ID,
            "--session", fixtures.ALPHA_RECENT, "--note", "第一次",
            "--expected-revision", "1", "--json",
        )
        payload = self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/beta", "--expected-revision", "2", "--json",
        )
        self.assertEqual(payload["workspace"], "/work/beta")
        self.assertIsNone(payload["session"], "set 是替换语义：未给的可选字段被清空")
        self.assertEqual(payload["memoryRefs"], [])
        self.assertIsNone(payload["note"])
        self.assertEqual(payload["dispatchStatus"], "NOT_READY")
        text = self.task_file().read_text(encoding="utf-8")
        self.assertNotIn(":PM_EXEC_SESSION:", text)
        self.assertNotIn(":PM_EXEC_MEMORY:", text)

    def test_set_rejects_candidate_memory(self) -> None:
        task_id = self.make_task()
        before = hashlib.sha256(self.task_file().read_bytes()).hexdigest()
        code, stdout, _ = self.pm(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha", "--memory", CANDIDATE_ID,
            "--expected-revision", "1", "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "INVALID_MEMORY_REF")
        self.assertEqual(hashlib.sha256(self.task_file().read_bytes()).hexdigest(), before)

    def test_set_conflict_exit_3_and_file_unchanged(self) -> None:
        task_id = self.make_task()
        before = self.task_file().read_bytes()
        code, stdout, _ = self.pm(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha", "--expected-revision", "9", "--json",
        )
        self.assertEqual(code, 3)
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "REVISION_CONFLICT")
        self.assertEqual(self.task_file().read_bytes(), before, "冲突时逐字节不变")

    def test_set_dry_run_writes_nothing(self) -> None:
        task_id = self.make_task()
        before = hashlib.sha256(self.task_file().read_bytes()).hexdigest()
        payload = self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha", "--session", fixtures.ALPHA_RECENT,
            "--expected-revision", "1", "--dry-run", "--json",
        )
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["dispatchStatus"], "HANDOFF_READY", "计划值也要能看出可 handoff")
        self.assertEqual(hashlib.sha256(self.task_file().read_bytes()).hexdigest(), before)
        current = self.ok("task", "execution-config", "get", task_id, "--json")
        self.assertEqual(current["revision"], 1)
        self.assertIsNone(current["workspace"])

    def test_set_idempotency_key(self) -> None:
        task_id = self.make_task()
        first = self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha", "--expected-revision", "1",
            "--idempotency-key", "ec-1", "--json",
        )
        after = hashlib.sha256(self.task_file().read_bytes()).hexdigest()
        replay = self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/beta", "--expected-revision", "2",
            "--idempotency-key", "ec-1", "--json",
        )
        self.assertTrue(replay["idempotent"])
        self.assertEqual(replay["auditEventId"], first["auditEventId"])
        self.assertEqual(hashlib.sha256(self.task_file().read_bytes()).hexdigest(), after)

    # ---- link / unlink ----

    def test_link_and_unlink_session(self) -> None:
        task_id = self.make_task()
        payload = self.ok(
            "task", "link-session", task_id,
            "--session", fixtures.ALPHA_RECENT,
            "--actor", "human", "--expected-revision", "1", "--json",
        )
        self.assertEqual(payload["session"], fixtures.ALPHA_RECENT)
        self.assertEqual(payload["instance"], self.instance, "实例从会话反查")
        self.assertEqual(payload["dispatchStatus"], "NOT_READY", "只有会话、还没有工作区")

        # 缺 reason 必须拒绝
        code, stdout, _ = self.pm(
            "task", "unlink-session", task_id, "--actor", "human",
            "--expected-revision", "2", "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "REASON_REQUIRED")

        payload = self.ok(
            "task", "unlink-session", task_id, "--reason", "换人接手",
            "--actor", "human", "--expected-revision", "2", "--json",
        )
        self.assertIsNone(payload["session"])
        self.assertEqual(payload["dispatchStatus"], "NOT_READY")
        self.assertNotIn(":PM_EXEC_SESSION:", self.task_file().read_text(encoding="utf-8"))

    # ---- handoff ----

    def test_handoff_deterministic_and_never_claims_dispatch(self) -> None:
        task_id = self.make_task()
        first = self.ok("task", "handoff", task_id, "--json")
        second = self.ok("task", "handoff", task_id, "--json")
        self.assertEqual(first["handoff"], second["handoff"], "同一 revision 输出必须一致")
        self.assertEqual(first["dispatchStatus"], "NOT_READY")
        text = first["handoff"]
        for forbidden in ("已派发", "已启动", "正在执行", "RUNNING", "dispatch 成功"):
            self.assertNotIn(forbidden, text)
        self.assertIn("运行状态仍为 unknown", text)

        self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha", "--session", fixtures.ALPHA_RECENT,
            "--expected-revision", "1", "--json",
        )
        ready = self.ok("task", "handoff", task_id, "--json")
        self.assertEqual(ready["dispatchStatus"], "HANDOFF_READY")
        self.assertIn("HANDOFF_READY", ready["handoff"])
        self.assertIn("/work/alpha", ready["handoff"])
        self.assertIn(fixtures.ALPHA_RECENT, ready["handoff"])

    # ---- 写入门禁 ----

    def test_write_gate_requires_yes_without_explicit_config(self) -> None:
        task_id = self.make_task()
        before = self.task_file().read_bytes()
        with mock.patch.dict(os.environ, {"PM_CONFIG": str(self.config)}):
            code, stdout, _ = self.run_cli(
                [
                    "task", "link-session", task_id,
                    "--session", fixtures.ALPHA_RECENT,
                    "--expected-revision", "1", "--json",
                ]
            )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "NEEDS_YES")
        self.assertEqual(self.task_file().read_bytes(), before)


    # ---- execution-config set 的 --reason（verifier FAIL 1 的回归）----

    def test_set_accepts_reason_and_writes_it_to_audit(self) -> None:
        """HTTP 路由会转发 reason；CLI 必须接受它，并让理由进审计。"""
        task_id = self.make_task()
        payload = self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha",
            "--reason", "因果要在 alpha 工作区跑",
            "--expected-revision", "1",
            "--actor", "human",
            "--json",
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["revision"], 2)
        for key in ("entityId", "source", "observedAt", "auditEventId"):
            self.assertIn(key, payload)
        text = self.task_file().read_text(encoding="utf-8")
        self.assertIn("reason=因果要在 alpha 工作区跑", text, "理由必须进审计")
        self.assertIn("audit=" + payload["auditEventId"], text)

    def test_set_reason_is_optional(self) -> None:
        task_id = self.make_task()
        payload = self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha", "--expected-revision", "1", "--json",
        )
        self.assertTrue(payload["ok"])
        self.assertIn("reason=execution-config set", self.task_file().read_text(encoding="utf-8"))

    def test_set_reason_with_dry_run_writes_nothing(self) -> None:
        task_id = self.make_task()
        before = self.task_file().read_bytes()
        payload = self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha", "--reason", "预演也要看理由",
            "--expected-revision", "1", "--dry-run", "--json",
        )
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(self.task_file().read_bytes(), before)
        self.assertNotIn("预演也要看理由", self.task_file().read_text(encoding="utf-8"))

    def test_set_reason_with_idempotency_key(self) -> None:
        task_id = self.make_task()
        first = self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha", "--reason", "第一次",
            "--expected-revision", "1", "--idempotency-key", "ec-r1", "--json",
        )
        after = self.task_file().read_bytes()
        replay = self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/beta", "--reason", "改了内容也不该再写",
            "--expected-revision", "2", "--idempotency-key", "ec-r1", "--json",
        )
        self.assertTrue(replay["idempotent"])
        self.assertEqual(replay["auditEventId"], first["auditEventId"])
        self.assertEqual(self.task_file().read_bytes(), after)

    def test_set_reason_does_not_weaken_cas(self) -> None:
        task_id = self.make_task()
        before = self.task_file().read_bytes()
        code, stdout, _ = self.pm(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha", "--reason", "冲突试试",
            "--expected-revision", "9", "--json",
        )
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(stdout)["error"]["code"], "REVISION_CONFLICT")
        self.assertEqual(self.task_file().read_bytes(), before, "冲突时逐字节不变")

    def test_set_reason_flag_order_is_flexible(self) -> None:
        """verifier 的复现命令把 --reason 放在 --workspace 与 --expected-revision 之间。"""
        task_id = self.make_task()
        payload = self.ok(
            "task", "execution-config", "set", task_id,
            "--workspace", "/work/alpha", "--reason", "R",
            "--expected-revision", "1", "--actor", "human",
            "--instance", self.instance, "--note", "n", "--json",
        )
        self.assertEqual(payload["workspace"], "/work/alpha")
        self.assertEqual(payload["note"], "n")
        self.assertIn("reason=R", self.task_file().read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
