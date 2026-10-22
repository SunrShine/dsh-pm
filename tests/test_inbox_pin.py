"""inbox 置顶 / 取消置顶 + 两个投影暴露 pinned（task-48）。

口径：pin = 写 :PM_PIN: t；unpin = 删掉它。不改状态、CAS + 审计 op=pin/unpin + 幂等 +
dry-run；LEGACY 明确拒绝。pinned 永远是 bool（缺属性 = false），与计数的 null/0 口径不同。
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
from pm import inbox as inbox_module

import fixtures


class InboxPinBaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.library = self.base / "wm"
        self.library.mkdir()
        self.config = self.base / "pm.toml"
        self.config.write_text('library = "' + str(self.library) + '"\n', encoding="utf-8")
        self.inbox = self.library / "inbox.org"

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

    def seed(self, text: str = "要置顶的随手记") -> str:
        return self.ok("capture", text, "--json")["inboxId"]

    def sha(self) -> str:
        return hashlib.sha256(self.inbox.read_bytes()).hexdigest()

    def row(self, inbox_id: str) -> dict:
        payload = self.ok("inbox", "list", "--json")
        return next(entry for entry in payload["entries"] if entry["id"] == inbox_id)

    def ui_row(self, library: Path, index: int = 0) -> dict:
        payload = inbox_module.read_inbox(library)
        return payload["entries"][index]


class PinTest(InboxPinBaseTest):
    def test_pin_writes_property_audit_and_exposes_pinned(self) -> None:
        inbox_id = self.seed()
        payload = self.ok(
            "inbox", "pin", inbox_id, "--expected-revision", "1", "--actor", "human", "--json"
        )
        for key in ("entityId", "revision", "source", "observedAt", "auditEventId"):
            self.assertIn(key, payload)
        self.assertEqual(payload["op"], "pin")
        self.assertTrue(payload["pinned"])
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["status"], "CAPTURED", "置顶不改状态")
        self.assertEqual(payload["previousStatus"], "CAPTURED")

        text = self.inbox.read_text(encoding="utf-8")
        self.assertIn(":PM_PIN: t", text)
        self.assertIn("op=pin", text)
        self.assertIn("audit=" + payload["auditEventId"], text)
        self.assertEqual(text.count(":LOGBOOK:"), 1)

        self.assertTrue(self.row(inbox_id)["pinned"])
        self.assertTrue(self.ui_row(self.library)["pinned"], "ui-cards 也要暴露 pinned")

    def test_unpin_clears_property(self) -> None:
        inbox_id = self.seed()
        self.ok("inbox", "pin", inbox_id, "--expected-revision", "1", "--json")
        payload = self.ok(
            "inbox", "unpin", inbox_id, "--expected-revision", "2", "--actor", "human", "--json"
        )
        self.assertEqual(payload["op"], "unpin")
        self.assertFalse(payload["pinned"])
        self.assertEqual(payload["revision"], 3)
        text = self.inbox.read_text(encoding="utf-8")
        self.assertNotIn(":PM_PIN:", text, "unpin 要把属性删掉")
        self.assertIn("op=unpin", text)
        self.assertFalse(self.row(inbox_id)["pinned"])
        self.assertFalse(self.ui_row(self.library)["pinned"])

    def test_missing_property_is_false_not_null(self) -> None:
        inbox_id = self.seed()
        row = self.row(inbox_id)
        self.assertIs(row["pinned"], False, "缺 :PM_PIN: = False（不是 null）")
        self.assertIs(self.ui_row(self.library)["pinned"], False)
        # 对照：同一行里的计数是 0（已知道没有），旧条目的计数才是 null
        self.assertEqual(row["annotationCount"], 0)

    def test_truthy_variants(self) -> None:
        for value, expected in (("t", True), ("true", True), ("YES", True), ("1", True), ("no", False)):
            with self.subTest(value=value):
                self.inbox.write_text(
                    "#+TITLE: Inbox\n\n* Inbox\n** INBOX 手写的\n"
                    "   :PROPERTIES:\n   :ID: inbox-x1\n   :PM_STATUS: CAPTURED\n"
                    "   :PM_PIN: %s\n   :PM_REVISION: 1\n   :END:\n" % value,
                    encoding="utf-8",
                )
                self.assertIs(self.ui_row(self.library)["pinned"], expected)

    def test_cas_conflict_exit_3_and_unchanged(self) -> None:
        inbox_id = self.seed()
        before = self.sha()
        code, stdout, _ = self.pm("inbox", "pin", inbox_id, "--expected-revision", "9", "--json")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(stdout)["error"]["code"], "REVISION_CONFLICT")
        self.assertEqual(self.sha(), before)

    def test_idempotency_replay_changed_false(self) -> None:
        inbox_id = self.seed()
        first = self.ok(
            "inbox", "pin", inbox_id, "--expected-revision", "1",
            "--idempotency-key", "pin-1", "--json",
        )
        after = self.sha()
        replay = self.ok(
            "inbox", "pin", inbox_id, "--expected-revision", "2",
            "--idempotency-key", "pin-1", "--json",
        )
        self.assertTrue(replay["idempotent"])
        self.assertFalse(replay["changed"], "幂等重放 changed:false")
        self.assertEqual(replay["auditEventId"], first["auditEventId"])
        self.assertEqual(replay["revision"], first["revision"])
        self.assertEqual(self.sha(), after)

    def test_repeat_pin_without_key_is_noop(self) -> None:
        inbox_id = self.seed()
        self.ok("inbox", "pin", inbox_id, "--expected-revision", "1", "--json")
        before = self.sha()
        again = self.ok("inbox", "pin", inbox_id, "--expected-revision", "2", "--json")
        self.assertFalse(again["changed"], "已经是置顶 → 不再写")
        self.assertEqual(again["revision"], 2)
        self.assertEqual(self.sha(), before)
        # unpin 同理
        self.ok("inbox", "unpin", inbox_id, "--expected-revision", "2", "--json")
        after = self.sha()
        again = self.ok("inbox", "unpin", inbox_id, "--expected-revision", "3", "--json")
        self.assertFalse(again["changed"])
        self.assertEqual(self.sha(), after)

    def test_dry_run_writes_nothing(self) -> None:
        inbox_id = self.seed()
        before = self.sha()
        payload = self.ok(
            "inbox", "pin", inbox_id, "--expected-revision", "1", "--dry-run", "--json"
        )
        self.assertTrue(payload["dry_run"])
        self.assertTrue(payload["pinned"], "计划值也要能看出会被置顶")
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(self.sha(), before)
        self.assertFalse(self.row(inbox_id)["pinned"])

    def test_legacy_entry_rejected(self) -> None:
        self.inbox.write_text("#+TITLE: Inbox\n\n* Inbox\n\n- 旧条目\n", encoding="utf-8")
        before = self.sha()
        for action in ("pin", "unpin"):
            code, stdout, _ = self.pm(
                "inbox", action, "inbox-nope", "--expected-revision", "1", "--json"
            )
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(stdout)["error"]["code"], "LEGACY_UNTRACKED")
        self.assertEqual(self.sha(), before)

    def test_unknown_id_exit_2(self) -> None:
        self.seed()
        code, stdout, _ = self.pm("inbox", "pin", "inbox-missing", "--expected-revision", "1", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["error"]["code"], "NOT_FOUND")

    def test_pin_does_not_touch_status_or_other_entries(self) -> None:
        first = self.seed("第一条")
        second = self.seed("第二条")
        first_status_before = self.row(first)["status"]
        self.ok("inbox", "pin", first, "--expected-revision", "1", "--json")
        self.assertEqual(self.row(first)["status"], first_status_before)
        other = self.row(second)
        self.assertFalse(other["pinned"])
        self.assertEqual(other["revision"], 1, "另一条没被写过")
        self.assertEqual(other["status"], "CAPTURED")


class UiCardsPinTest(InboxPinBaseTest):
    def test_ui_cards_projection_has_pinned_and_stays_lean(self) -> None:
        home = fixtures.build_dsh_home(self.base / "dsh")
        config = self.base / "with_dsh.toml"
        config.write_text(
            fixtures.fixture_config_toml(library=str(self.library)).replace("REPLACED", str(home)),
            encoding="utf-8",
        )
        inbox_id = self.seed()
        code, stdout, stderr = self.run_cli(["--config", str(config), "ui-cards", "--dsh-home", str(home)])
        self.assertEqual(code, 0, stderr)
        row = json.loads(stdout)["inbox"]["entries"][0]
        self.assertIs(row["pinned"], False)
        self.assertNotIn("annotations", row)

        self.ok("inbox", "pin", inbox_id, "--expected-revision", "1", "--json")
        code, stdout, _ = self.run_cli(["--config", str(config), "ui-cards", "--dsh-home", str(home)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertIs(payload["inbox"]["entries"][0]["pinned"], True)
        self.assertEqual(payload["schemaVersion"], "ui-cards-v1", "纯增量，不升版本")


class RegistrationTest(unittest.TestCase):
    def test_pin_commands_registered(self) -> None:
        import argparse

        parser = cli.build_parser()
        root = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)][0]
        inbox_parser = root.choices["inbox"]
        sub = [action for action in inbox_parser._actions if isinstance(action, argparse._SubParsersAction)][0]
        self.assertIn("pin", sub.choices)
        self.assertIn("unpin", sub.choices)
        for name in ("pin", "unpin"):
            flags = {option for action in sub.choices[name]._actions for option in action.option_strings}
            self.assertIn("--expected-revision", flags)
            self.assertIn("--idempotency-key", flags)
            self.assertIn("--dry-run", flags)
            self.assertIn("--json", flags)


if __name__ == "__main__":
    unittest.main()
