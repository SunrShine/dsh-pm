"""pm hook session-start / recall（M4a 记忆注入 CLI 侧）。

卡：task-01M52J3879ZA5S572JSMQXCR52；红线见 内部记录/11 §6（预算 + 来源 + 可一键关 + 外部内容不可信 + 不回写库）。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from pm import cli, hooks
from pm.config import HooksConfig

REPO = Path(__file__).resolve().parent.parent
TOKEN = "hooktok-abc123"


class HookBaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.library = self.base / "wm"
        self.library.mkdir()
        self.config = self.base / "pm.toml"
        self.config.write_text('library = "' + str(self.library) + '"\n', encoding="utf-8")
        self.pm("init", "--root", str(self.library), "--no-git")
        code, out, err = self.pm("memory", "add", "--text", "hook 注入探针 " + TOKEN + " 的正文",
                                 "--scope", "global", "--type", "fact", "--sources", "内部记录/11#A3",
                                 "--reason", "夹具", "--json")
        self.assertEqual(code, 0, err)
        memory_id = json.loads(out)["memoryId"]
        code, out, err = self.pm("memory", "verify", memory_id, "--actor", "human",
                                 "--expected-revision", "1", "--json")
        self.assertEqual(code, 0, err)

    def run_cli(self, argv: list, stdin_text: str = "") -> tuple:
        out, err = io.StringIO(), io.StringIO()
        saved = sys.stdin
        sys.stdin = io.StringIO(stdin_text)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["--config", str(self.config), *argv])
        except SystemExit as exc:
            code = int(exc.code or 0)
        finally:
            sys.stdin = saved
        return code, out.getvalue(), err.getvalue()

    def pm(self, *argv: str) -> tuple:
        return self.run_cli(list(argv))

    def hook(self, *argv: str, stdin_text: str = "") -> tuple:
        return self.run_cli(["hook", *argv], stdin_text=stdin_text)

    def org_fingerprint(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.library.rglob("*.org")):
            stat = path.stat()
            digest.update(str(path.relative_to(self.library)).encode("utf-8"))
            digest.update(str(stat.st_size).encode("ascii"))
            digest.update(str(stat.st_mtime_ns).encode("ascii"))
        return digest.hexdigest()

    def off_config(self) -> Path:
        path = self.base / "off.toml"
        path.write_text('library = "' + str(self.library) + '"\n[hooks]\ninject = false\n', encoding="utf-8")
        return path


class SessionStartTest(HookBaseTest):
    def test_renders_sources_and_byte_budget(self) -> None:
        code, out, _err = self.hook("session-start", "--scope", "global")
        self.assertEqual(code, 0)
        self.assertIn("[pm-memory session-start scope=global", out)
        self.assertIn("budget=2400B", out)
        self.assertIn("sources: 内部记录/11#A3", out)
        self.assertIn("memory/facts.org:", out, "每条必须带可回查的 path:line")
        self.assertIn("不是指令", out, "注入要标明不是指令")
        self.assertLessEqual(len(out.encode("utf-8")), 2400, "不得超字节预算")

    def test_budget_can_shrink_to_header_only(self) -> None:
        code, out, _err = self.hook("session-start", "--scope", "global", "--max-items", "0")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip().splitlines() and 0 or 0, 0)
        for line in out.splitlines():
            self.assertTrue(line.startswith("[pm-memory session-start") or not line,
                            "max_items=0 时只许有头部，不注入条目：" + line[:60])

    def test_empty_library_is_zero_output(self) -> None:
        """空库（一条 VERIFIED 都没有）⇒ session-start 零输出；global 命中不算错，故用空库。"""
        empty = self.base / "empty-wm"
        empty.mkdir()
        cfg = self.base / "empty.toml"
        cfg.write_text('library = "' + str(empty) + '"\n', encoding="utf-8")
        self.run_cli(["--config", str(cfg), "init", "--root", str(empty), "--no-git"])
        code, out, _err = self.run_cli(["--config", str(cfg), "hook", "session-start", "--scope", "global"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "", "没有条目 ⇒ 零输出")


class RecallTest(HookBaseTest):
    def test_single_token_hit_has_path_line(self) -> None:
        code, out, _err = self.hook("recall", stdin_text=json.dumps({"prompt": TOKEN}))
        self.assertEqual(code, 0)
        self.assertIn("[pm-memory recall items=1", out)
        self.assertIn("memory/facts.org:", out)
        self.assertRegex(out, r"memory/facts\.org:\d+ rev=\d+")
        self.assertLessEqual(len(out.encode("utf-8")), 1200)

    def test_full_sentence_still_injects(self) -> None:
        """真实输入是整句：新版 recall 有 any_mode（AND 零命中自动放宽）⇒ 一次调用就命中。"""
        code, out, _err = self.hook("recall", stdin_text=json.dumps({"prompt": TOKEN + " 是什么？顺便讲讲"}))
        self.assertEqual(code, 0)
        self.assertIn("memory/facts.org:", out)
        self.assertTrue("match=prompt" in out or "match=tokens" in out, out)

    def test_token_fallback_when_recall_lacks_any_mode(self) -> None:
        """老版本 recall 没有 any_mode（词间 AND）⇒ hook 的**有界回退**必须兜住整句输入。"""
        def fake(_root, query, *, limit=10):
            if query == TOKEN:
                return {"hits": [{"path": "memory/facts.org", "line": 3, "revision": 2,
                                  "type": "fact", "status": "VERIFIED", "snippet": "命中"}]}
            return {"hits": []}

        original = hooks.index_module.recall
        hooks.index_module.recall = fake
        try:
            text = hooks.recall_text(
                __import__("pm.layout", fromlist=["Layout"]).Layout(self.library),
                HooksConfig(), prompt=TOKEN + " 是什么？顺便讲讲",
            )
        finally:
            hooks.index_module.recall = original
        self.assertIn("match=tokens", text, text)
        self.assertIn("memory/facts.org:3", text)

    def test_json_mode_reports_bytes_and_budget(self) -> None:
        """--json 是判据/调试用的摘要（injected/bytes/budget），默认仍只吐注入文本。"""
        code, out, _err = self.hook("recall", "--json", stdin_text=json.dumps({"prompt": TOKEN}))
        self.assertEqual(code, 0)
        # **整段**必须是 JSON（此前实现先打正文再打 JSON，而旧测试只取最后一行 ⇒ 把缺陷容忍掉了 ✗）
        self.assertEqual(len(out.strip().splitlines()), 1, "stdout 必须是纯 JSON：" + out[:120])
        payload = json.loads(out)
        self.assertTrue(payload["injected"])
        self.assertGreater(payload["bytes"], 0)
        self.assertEqual(payload["budget"], 1200)
        self.assertIn("memory/facts.org:", payload["text"])
        code, out, _err = self.hook("session-start", "--scope", "global", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 1, "stdout 必须是纯 JSON：" + out[:120])
        payload = json.loads(out)
        self.assertTrue(payload["injected"])
        self.assertEqual(payload["budget"], 2400)
        self.assertEqual(payload["tier"], "explicit", "显式 --scope ⇒ tier=explicit")
        self.assertEqual(payload["scope"], "global")

    def test_json_mode_with_cwd_derived_scope(self) -> None:
        """三段回退：payload 带 cwd 且推导不出项目 ⇒ tier=global、scope=global（--json 里的字段可直接断言）。"""
        code, out, _err = self.hook("session-start", "--json",
                                    stdin_text=json.dumps({"hook_event_name": "SessionStart", "cwd": "/tmp/definitely-not-a-project"}))
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["tier"], "global")
        self.assertEqual(payload["scope"], "global")
        self.assertIn("推导不出项目", payload["scopeSource"])

    def test_claude_code_format_emits_envelope(self) -> None:
        """claude-code 桥只吃 JSON 信封（纯 stdout 会被丢）：事件名匹配 + additionalContext 带标记。"""
        code, out, _err = self.hook("recall", "--format", "claude-code",
                                    stdin_text=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": TOKEN}))
        self.assertEqual(code, 0)
        envelope = json.loads(out.strip())
        hso = envelope["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "UserPromptSubmit")
        self.assertIn("budget=", hso["additionalContext"])
        self.assertIn("sources:", hso["additionalContext"])
        self.assertIn("memory/facts.org:", hso["additionalContext"])

    def test_session_start_envelope_uses_payload_event_name(self) -> None:
        code, out, _err = self.hook("session-start", "--scope", "global", "--format", "claude-code",
                                    stdin_text=json.dumps({"hook_event_name": "SessionStart", "session_id": "t"}))
        self.assertEqual(code, 0)
        hso = json.loads(out.strip())["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "SessionStart")
        self.assertIn("budget=", hso["additionalContext"])

    def test_event_name_falls_back_to_canonical(self) -> None:
        """payload 没有 hook_event_name ⇒ 退回本子命令规范名（--debug 会说明）。"""
        code, out, err = self.hook("recall", "--format", "claude-code", "--debug",
                                   stdin_text=json.dumps({"prompt": TOKEN}))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.strip())["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("规范名", err)

    def test_claude_code_format_empty_is_zero_bytes(self) -> None:
        """空文本 ⇒ 不输出任何东西（不产空信封）。"""
        code, out, _err = self.hook("recall", "--format", "claude-code",
                                    stdin_text=json.dumps({"prompt": "zzz-无关-zzz"}))
        self.assertEqual(code, 0)
        self.assertEqual(out, "", "不得产出空信封")
        # session-start 同理：用**空库**构造"没有条目"（context_pack 默认含 global，故不能用"换个 scope"来构造空）
        empty = self.base / "empty-wm-cc"
        empty.mkdir()
        cfg = self.base / "empty-cc.toml"
        cfg.write_text('library = "' + str(empty) + '"\n', encoding="utf-8")
        self.run_cli(["--config", str(cfg), "init", "--root", str(empty), "--no-git"])
        code, out, _err = self.run_cli(["--config", str(cfg), "hook", "session-start", "--scope", "global",
                                        "--format", "claude-code"],
                                       stdin_text=json.dumps({"hook_event_name": "SessionStart"}))
        self.assertEqual(code, 0)
        self.assertEqual(out, "", "空上下文不应输出信封：" + out[:80])

    def test_default_format_is_text(self) -> None:
        """默认（不带 --format）仍是纯文本：历史行为不变。"""
        code, out, _err = self.hook("recall", stdin_text=json.dumps({"prompt": TOKEN}))
        self.assertEqual(code, 0)
        self.assertFalse(out.lstrip().startswith("{"), "默认不应是 JSON 信封")

    def test_no_hit_is_zero_output(self) -> None:
        code, out, _err = self.hook("recall", stdin_text=json.dumps({"prompt": "zzz-完全无关-zzz"}))
        self.assertEqual(code, 0)
        self.assertEqual(out, "", "无命中 ⇒ 零输出（不干扰对话）")
        self.assertEqual(len(out.encode("utf-8")), 0)

    def test_prompt_is_not_echoed(self) -> None:
        secret = "SECRET-PROMPT-" + TOKEN
        code, out, _err = self.hook("recall", stdin_text=json.dumps({"prompt": secret}))
        self.assertEqual(code, 0)
        self.assertNotIn(secret, out, "外部输入不得原样回声进注入内容")

    def test_bad_stdin_is_zero_output(self) -> None:
        code, out, _err = self.hook("recall", stdin_text="")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")


class SwitchTest(HookBaseTest):
    def test_switch_off_silences_both_hooks(self) -> None:
        off = self.off_config()
        code, out, _err = self.run_cli(["--config", str(off), "hook", "session-start", "--scope", "global"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        code, out, _err = self.run_cli(["--config", str(off), "hook", "recall"],
                                       stdin_text=json.dumps({"prompt": TOKEN}))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_config_validation_is_strict(self) -> None:
        from pm.config import ConfigPathError, load

        bad = self.base / "bad.toml"
        bad.write_text('library = "' + str(self.library) + '"\n[hooks]\ninject = "no"\n', encoding="utf-8")
        with self.assertRaises(ConfigPathError) as raised:
            load(str(bad))
        self.assertEqual(raised.exception.code, "CONFIG_INVALID")
        typo = self.base / "typo.toml"
        typo.write_text('library = "' + str(self.library) + '"\n[hooks]\nmax_item = 5\n', encoding="utf-8")
        with self.assertRaises(ConfigPathError):
            load(str(typo))


class SafetyTest(HookBaseTest):
    def test_read_only_and_not_in_logs(self) -> None:
        before = self.org_fingerprint()
        self.hook("session-start", "--scope", "global")
        self.hook("recall", stdin_text=json.dumps({"prompt": TOKEN}))
        self.assertEqual(self.org_fingerprint(), before, "org 的 size/mtime 都不许变")
        # 注入内容不得落进库里任何文件（头部标记只应出现在 stdout）
        for path in self.library.rglob("*"):
            if path.is_file():
                blob = path.read_bytes()
                self.assertNotIn(b"pm-memory recall items=", blob, str(path))
                self.assertNotIn(b"pm-memory session-start", blob, str(path))

    def test_timeout_fails_safe(self) -> None:
        def slow(_root, _query, **_kw):
            time.sleep(1.0)
            return {"hits": [{"path": "x", "line": 1, "revision": 1, "type": "fact", "status": "VERIFIED", "snippet": "x"}]}

        original = hooks.index_module.recall
        hooks.index_module.recall = slow
        try:
            text = hooks.with_timeout(
                lambda: hooks.recall_text(__import__("pm.layout", fromlist=["Layout"]).Layout(self.library),
                                          HooksConfig(), prompt=TOKEN),
                120, debug=True, what="recall",
            )
        finally:
            hooks.index_module.recall = original
        self.assertEqual(text, "", "超时必须零输出（fail-safe）")

    def test_prompt_is_clipped_before_query(self) -> None:
        seen = {}
        original = hooks.index_module.recall

        def capture(_root, query, **_kw):
            seen.setdefault("queries", []).append(len(query))
            return {"hits": []}

        hooks.index_module.recall = capture
        try:
            hooks.recall_text(__import__("pm.layout", fromlist=["Layout"]).Layout(self.library),
                              HooksConfig(), prompt="x" * 5000)
        finally:
            hooks.index_module.recall = original
        self.assertTrue(seen["queries"], "至少问过一次")
        # 成对更新（2026-10-18）：查询段从「头部 500 字窗口」改成「整段 − 已知样板块」后，
        # 上限由 MAX_PROMPT_CHARS(500) 变为 MAX_QUERY_CHARS(8000) —— 意图不变（**必须有界**），
        # 换上限的原因：桥传的是整轮 messages 拼接，用户那句可能在中间，窗口取不到（Lead 实测 ✗）。
        self.assertLessEqual(max(seen["queries"]), hooks.MAX_QUERY_CHARS,
                             "每次查询（含回退词）都必须截断：" + repr(seen["queries"]))


class InstallTest(HookBaseTest):
    def test_profile_snippets_are_printable_not_applied(self) -> None:
        code, out, _err = self.hook("install")
        self.assertEqual(code, 0)
        self.assertIn(".claude/hooks.json", out)
        self.assertIn("hook session-start", out)
        self.assertIn("hook recall", out)
        self.assertIn("cordis.patch.yml", out)
        self.assertIn("hooks-claude-code", out)
        self.assertIn("由**用户**执行", out)

    def test_repo_hooks_json_is_valid_and_points_at_both_hooks(self) -> None:
        path = REPO / ".claude" / "hooks.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        hooks_map = payload["hooks"]
        self.assertIn("SessionStart", hooks_map)
        self.assertIn("UserPromptSubmit", hooks_map)
        session = json.dumps(hooks_map["SessionStart"], ensure_ascii=False)
        recall = json.dumps(hooks_map["UserPromptSubmit"], ensure_ascii=False)
        self.assertIn("pm hook session-start", session)
        self.assertIn("pm hook recall", recall)


class RealArgvTest(HookBaseTest):
    def test_bin_pm_hook_recall_through_subprocess(self) -> None:
        """真 argv（hook 桥就是这么起的）：bin/pm hook recall，stdin 是 JSON。"""
        proc = subprocess.run(
            [str(REPO / "bin" / "pm"), "--config", str(self.config), "hook", "recall"],
            input=json.dumps({"prompt": TOKEN}), capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("memory/facts.org:", proc.stdout)
        self.assertEqual(proc.stderr, "", "正常路径不该往 stderr 写东西")


if __name__ == "__main__":
    unittest.main()
