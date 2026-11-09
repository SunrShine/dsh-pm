from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pm.config import Instance
from pm import sessions


def sample_events() -> list[dict]:
    return [
        {"type": "session", "cwd": "/w", "time": 1000},
        {"type": "turn/start", "time": 1000},
        {"type": "step/start", "time": 1000},
        {"type": "user/message", "time": 2000, "data": {"content": [{"type": "text", "text": "真实请求"}], "source": {"kind": "user"}}},
        {"type": "user/message", "time": 2100, "data": {"content": [{"type": "text", "text": "The approval policy changed"}], "source": {"kind": "plugin"}}},
        {"type": "user/message", "time": 2200, "data": {"content": [{"type": "text", "text": "<system-reminder> 别管我"}], "source": {"kind": "user"}}},
        {"type": "todo/write", "time": 3000, "data": {"todos": [{"content": "A", "status": "completed"}, {"content": "B", "status": "pending"}]}},
        {"type": "deliverables/presented", "time": 4000, "data": {"files": [{"path": "x/y.md", "description": "说明"}]}},
        {"type": "assistant/message", "time": 5000, "data": {"content": [{"type": "text", "text": "结论"}]}},
        {"type": "不知道的事件类型", "time": 6000},
    ]


class DigestTest(unittest.TestCase):
    def digest(self) -> sessions.Digest:
        return sessions.build_digest(
            iter(sample_events()), session_id="session-x", instance="default"
        )

    def test_fields(self) -> None:
        d = self.digest()
        self.assertEqual(d.cwd, "/w")
        self.assertEqual(d.turns, 1)
        self.assertEqual(d.steps, 1)
        self.assertEqual(d.first_at.timestamp(), 1.0)
        self.assertEqual(d.last_assistant, "结论")

    def test_only_real_user_requests(self) -> None:
        # plugin 注入的与 <system-reminder> 都不算用户请求
        d = self.digest()
        self.assertEqual([text for _at, text in d.user_requests], ["真实请求"])

    def test_todos_and_deliverables(self) -> None:
        d = self.digest()
        assert d.final_todos is not None
        self.assertEqual(len(d.final_todos.todos), 2)
        self.assertEqual(d.final_todos.done, 1)
        self.assertEqual([x.path for x in sessions.unique_deliverables(d)], ["x/y.md"])

    def test_unknown_event_types_are_tolerated(self) -> None:
        d = self.digest()
        self.assertIn("不知道的事件类型", d.counts)

    def test_deliverables_dedup_keeps_last_description(self) -> None:
        events = [
            {"type": "deliverables/presented", "time": 1, "data": {"files": [{"path": "a.md", "description": "旧"}]}},
            {"type": "deliverables/presented", "time": 2, "data": {"files": [{"path": "a.md", "description": "新"}]}},
        ]
        d = sessions.build_digest(iter(events), session_id="session-x")
        items = sessions.unique_deliverables(d)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].description, "新")


class RenderTest(unittest.TestCase):
    def digest(self) -> sessions.Digest:
        return sessions.build_digest(iter(sample_events()), session_id="session-x", instance="default")

    def test_renders_key_sections(self) -> None:
        text = sessions.render_digest(self.digest())
        for marker in ("会话 session-x", "用户请求", "AI 待办", "交付物", "AI 最后一段输出"):
            self.assertIn(marker, text)

    def test_no_prompts_hides_user_text(self) -> None:
        # 计数行里的「用户请求」是统计信息，可以留；正文与小节必须消失
        text = sessions.render_digest(self.digest(), show_prompts=False)
        self.assertNotIn("真实请求", text)
        self.assertNotIn("source.kind=user", text)

    def test_prompt_text_can_be_truncated(self) -> None:
        text = sessions.render_digest(self.digest(), prompt_chars=2)
        self.assertIn("真实…", text)


class FindLogTest(unittest.TestCase):
    def build(self, dirname: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        target = root / "sessions" / "--w--" / dirname
        target.mkdir(parents=True)
        (target / "session.v3.jsonl.zstd").write_bytes(b"")
        return root

    def test_prefixed_directory(self) -> None:
        root = self.build("session-abc")
        found = sessions.find_log(Instance(id="t", path=root), "session-abc")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.name, "session.v3.jsonl.zstd")

    def test_bare_directory(self) -> None:
        # 实测两种命名都存在：session-<uuid> 与裸 <uuid>
        root = self.build("abc")
        found = sessions.find_log(Instance(id="t", path=root), "session-abc")
        self.assertIsNotNone(found)

    def test_accepts_id_without_prefix(self) -> None:
        root = self.build("session-abc")
        self.assertIsNotNone(sessions.find_log(Instance(id="t", path=root), "abc"))

    def test_missing_returns_none(self) -> None:
        root = self.build("session-abc")
        self.assertIsNone(sessions.find_log(Instance(id="t", path=root), "session-nope"))

    def test_missing_sessions_dir_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(sessions.find_log(Instance(id="t", path=Path(tmp)), "session-abc"))


if __name__ == "__main__":
    unittest.main()
