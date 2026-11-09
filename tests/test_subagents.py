"""子 agent 判定测试。

覆盖三层：
1. bin/subagent-probe.cjs 真解 zstd 第一帧（需要 node，缺则跳过）；
2. pm.subagents 的批量注解与保守回退（注入假探针，不依赖 node）；
3. pm ui-cards 的默认排除 / --include-subagents / 聚合一致性（patch 探针）。
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from pm import cli, sessions, subagents
from pm.config import Instance, derive_source_instance
from pm.model import Agent

import fixtures

NODE = sessions.find_node()

NORMAL_FRAME = '{"type":"session","version":3,"id":"session-bbb","cwd":"/w"}'
SUBAGENT_FRAME = (
    '{"type":"session","version":3,"id":"session-aaa",'
    '"cwd":"/w","parentSession":"session-parent"}'
)


def write_zstd(path: Path, text: str) -> None:
    """用 node 写一个真实 zstd 文件（Python 标准库没有 zstd）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    code = (
        "const z=require('zlib'),fs=require('fs');"
        "fs.writeFileSync(process.argv[1], z.zstdCompressSync(Buffer.from(process.argv[2],'utf8')))"
    )
    subprocess.run([NODE, "-e", code, str(path), text], check=True, capture_output=True)


@unittest.skipUnless(NODE, "需要 node 才能读写 zstd")
class ProbeToolTest(unittest.TestCase):
    """bin/subagent-probe.cjs：第一帧标记 → SUBAGENT / normal / unknown。"""

    def test_classifies_batch_in_one_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normal = root / "normal.jsonl.zstd"
            sub = root / "sub.jsonl.zstd"
            broken = root / "broken.jsonl.zstd"
            write_zstd(normal, NORMAL_FRAME + "\n")
            write_zstd(sub, SUBAGENT_FRAME + "\n")
            broken.write_bytes(b"\x28\xb5\x2f\xfd" + b"garbage-not-zstd")
            missing = root / "missing.jsonl.zstd"

            verdicts = subagents.probe_paths([str(sub), str(normal), str(broken), str(missing)])
            self.assertEqual(verdicts[str(sub)], subagents.SUBAGENT)
            self.assertEqual(verdicts[str(normal)], subagents.NORMAL)
            self.assertEqual(verdicts[str(broken)], subagents.UNKNOWN)
            self.assertEqual(verdicts[str(missing)], subagents.UNKNOWN)

    def test_empty_input_is_empty_mapping(self) -> None:
        self.assertEqual(subagents.probe_paths([]), {})


class AnnotateTest(unittest.TestCase):
    """注入假探针验证注解与保守回退。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "dsh"
        self.instance = Instance(id="default", path=self.home, role="work")
        self.agents = [
            Agent(session_id="session-11111111-1111-4111-8111-111111111111", source_instance="default"),
            Agent(session_id="session-22222222-2222-4222-8222-222222222222", source_instance="default"),
            Agent(session_id="session-33333333-3333-4333-8333-333333333333", source_instance="default"),
        ]
        for agent in self.agents[:2]:
            case = self.home / "sessions" / "ws" / agent.session_id / "session.jsonl.zstd"
            case.parent.mkdir(parents=True)
            case.write_bytes(b"placeholder")
        # 第三个 agent 故意没有日志

    def test_marks_subagent_normal_and_unknown_conservatively(self) -> None:
        def probe(paths):
            out = {}
            for path in paths:
                if "11111111" in path:
                    out[path] = subagents.SUBAGENT
                elif "22222222" in path:
                    out[path] = subagents.UNKNOWN
            return out

        hits = subagents.annotate_subagents(self.agents, (self.instance,), probe=probe)
        self.assertEqual(hits, 1)
        self.assertTrue(self.agents[0].is_subagent)
        self.assertFalse(self.agents[1].is_subagent, "unknown 保守当作非子 agent")
        self.assertFalse(self.agents[2].is_subagent, "没有日志 → 保守保留")

    def test_probe_failure_leaves_everything_visible(self) -> None:
        hits = subagents.annotate_subagents(self.agents, (self.instance,), probe=lambda paths: {})
        self.assertEqual(hits, 0)
        self.assertFalse(any(a.is_subagent for a in self.agents))

    def test_unknown_instance_is_skipped(self) -> None:
        stray = Agent(session_id="session-44444444-4444-4444-8444-444444444444", source_instance="nope")
        hits = subagents.annotate_subagents([stray], (self.instance,), probe=lambda paths: {})
        self.assertEqual(hits, 0)
        self.assertFalse(stray.is_subagent)

    # ---- task-170：投影事实优先，缺字段才回退日志探针 ----

    def test_projection_mode_wins_over_probe(self) -> None:
        probed: list[list[str]] = []

        def probe(paths):
            probed.append(sorted(paths))
            return {path: subagents.SUBAGENT for path in paths}

        # 投影说：第 1 个是普通会话（哪怕探针会说 SUBAGENT）；第 2 个是队友。
        self.agents[0].session_mode = "one-shot"
        self.agents[1].session_mode = subagents.MODE_CONTINUABLE
        hits = subagents.annotate_subagents(self.agents, (self.instance,), probe=probe)

        self.assertFalse(self.agents[0].is_subagent, "投影 one-shot 必须覆盖探针结论")
        self.assertTrue(self.agents[1].is_subagent, "投影 continuable 直接定论")
        self.assertFalse(self.agents[2].is_subagent, "缺 mode 且探针没给 verdict → 保守保留")
        self.assertEqual(hits, 1)
        self.assertEqual(probed, [], "两个有 log 的会话都由投影定论了；第 3 个没日志 → 连探针都不必跑")

    def test_missing_mode_still_uses_probe(self) -> None:
        """缺 mode 的会话保持既有行为：探针说 SUBAGENT 就标上（不因新字段而丢判定）。"""
        probed: list[str] = []

        def probe(paths):
            probed.extend(paths)
            return {path: (subagents.SUBAGENT if "11111111" in path else subagents.NORMAL) for path in paths}

        hits = subagents.annotate_subagents(self.agents, (self.instance,), probe=probe)
        self.assertEqual(hits, 1)
        self.assertTrue(self.agents[0].is_subagent, "缺 mode → 仍按探针判定")
        self.assertFalse(self.agents[1].is_subagent)
        self.assertEqual(len(probed), 2, "两个有日志的会话都送去探针了")


@unittest.skipUnless(NODE, "需要 node 才能生成 zstd 夹具")
class AnnotateEndToEndTest(unittest.TestCase):
    def test_real_probe_flags_only_the_subagent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "dsh"
            sub = Agent(session_id="session-aaaa1111-1111-4111-8111-111111111111", source_instance="default")
            normal = Agent(session_id="session-bbbb2222-2222-4222-8222-222222222222", source_instance="default")
            nolog = Agent(session_id="session-cccc3333-3333-4333-8333-333333333333", source_instance="default")
            write_zstd(home / "sessions" / "ws" / sub.session_id / "session.jsonl.zstd", SUBAGENT_FRAME + "\n")
            write_zstd(home / "sessions" / "ws" / normal.session_id / "session.jsonl.zstd", NORMAL_FRAME + "\n")
            hits = subagents.annotate_subagents(
                [sub, normal, nolog], (Instance(id="default", path=home),)
            )
            self.assertEqual(hits, 1)
            self.assertTrue(sub.is_subagent)
            self.assertFalse(normal.is_subagent)
            self.assertFalse(nolog.is_subagent)


class UiCardsSubagentTest(unittest.TestCase):
    """pm ui-cards 默认排除子 agent；--include-subagents 包含；聚合与保留集合一致。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = fixtures.build_dsh_home(Path(self._tmp.name))
        self.config = Path(self._tmp.name) / "pm.toml"
        self.config.write_text(
            fixtures.fixture_config_toml().replace("REPLACED", str(self.home)), encoding="utf-8"
        )
        # 给被判定为子 agent 的夹具会话造一个日志文件，让 find_log 能找到它
        case = self.home / "sessions" / "w-alpha" / fixtures.STALLED / "session.jsonl.zstd"
        case.parent.mkdir(parents=True)
        case.write_bytes(b"placeholder")

    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def fake_probe(self, paths):
        """夹具里只有 STALLED 这张卡被标成子 agent。"""
        return {path: (subagents.SUBAGENT if fixtures.STALLED in path else subagents.NORMAL) for path in paths}

    def payload(self, *extra: str, probe=None):
        from unittest import mock

        with mock.patch("pm.subagents.probe_paths", probe or self.fake_probe):
            code, stdout, _ = self.run_cli(
                ["--config", str(self.config), "ui-cards", *extra, "--dsh-home", str(self.home)]
            )
        self.assertEqual(code, 0)
        return json.loads(stdout)

    def test_subagent_card_excluded_by_default(self) -> None:
        payload = self.payload()
        alpha = next(p for p in payload["projects"] if p["key"] == "alpha_beta")
        self.assertEqual(alpha["cards"], 5)
        self.assertEqual(alpha["attention"], 2)
        self.assertEqual(alpha["stale_busy"], 0)
        self.assertNotIn(fixtures.STALLED, [c["session_id"] for c in payload["cards"]])
        for card in payload["cards"]:
            self.assertFalse(card["is_subagent"])

    def test_include_subagents_restores_card_and_aggregates(self) -> None:
        payload = self.payload("--include-subagents")
        alpha = next(p for p in payload["projects"] if p["key"] == "alpha_beta")
        self.assertEqual(alpha["cards"], 6)
        self.assertEqual(alpha["attention"], 3)
        self.assertEqual(alpha["stale_busy"], 1)
        card = next(c for c in payload["cards"] if c["session_id"] == fixtures.STALLED)
        self.assertTrue(card["is_subagent"])
        self.assertEqual(card["observation"], "STALE_BUSY")

    def test_aggregates_only_cover_kept_cards(self) -> None:
        payload = self.payload()
        for project in payload["projects"]:
            rows = [c for c in payload["cards"] if c["project"] == project["key"]]
            self.assertEqual(project["cards"], len(rows))
            self.assertEqual(project["attention"], sum(1 for c in rows if c["needs_attention"]))
            self.assertEqual(project["open_todos"], sum(c["open_todos"] for c in rows))

    def test_project_fields_match_cards_in_both_views(self) -> None:
        """项目级字段必须与同一次输出的 cards 数组自洽（默认与 --include-subagents 各自成立）。"""
        for extra in ((), ("--include-subagents",)):
            payload = self.payload(*extra)
            for project in payload["projects"]:
                rows = [c for c in payload["cards"] if c["project"] == project["key"]]
                stamps = [c["recorded_at"] for c in rows if c["recorded_at"]]
                self.assertEqual(project["last_recorded"], max(stamps) if stamps else None, extra)
                self.assertEqual(
                    project["paths"], sorted({c["cwd"] for c in rows if c["cwd"]}), extra
                )
                self.assertEqual(project["cards"], len(rows), extra)

    def test_probe_failure_keeps_subagent_card(self) -> None:
        payload = self.payload(probe=lambda paths: {})
        alpha = next(p for p in payload["projects"] if p["key"] == "alpha_beta")
        self.assertEqual(alpha["cards"], 6, "判定失败必须保守保留")
        self.assertIn(fixtures.STALLED, [c["session_id"] for c in payload["cards"]])


if __name__ == "__main__":
    unittest.main()
