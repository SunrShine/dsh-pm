"""构造用于测试的 DSH 目录快照。

不依赖真实 ~/.dsh：所有会话 JSON 都按 projcache 的**实测结构**生成，
并特意包含几类真实遇到过的坏数据（0 字节临时文件、非法 JSON、未知版本、
缺 lastPromptAt、goal.current 为 null）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ALPHA_RECENT = "session-11111111-1111-4111-8111-111111111111"
BETA_OLD = "session-22222222-2222-4222-8222-222222222222"
ALPHA_EMPTY = "session-33333333-3333-4333-8333-333333333333"
ALPHA_ARCHIVED = "session-44444444-4444-4444-8444-444444444444"
UNKNOWN_CWD = "session-55555555-5555-4555-8555-555555555555"
HOME_CWD = "session-66666666-6666-4666-8666-666666666666"
STALLED = "session-77777777-7777-4777-8777-777777777777"
BAD_JSON = "session-99999999-9999-4999-8999-999999999999"
FUTURE_VERSION = "session-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TEMP_FILE = ".88888888-8888-4888-8888-888888888888.tmp"

ALPHA = "/work/alpha"
BETA = "/work/beta"
ALPHA_SIBLING = "/work/alpha_sibling"
OTHER = "/work/other/demo01"
HOME = "/home/tester"

#: 测试统一使用的「现在」。
NOW = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)


def ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def session_doc(
    *,
    cwd: str,
    title: str,
    created: int,
    last_prompt_at: int | None = None,
    first_text: str = "first prompt",
    turns: int = 1,
    steps: int = 10,
    open_step: object | None = None,
    todos: list[dict] | None = None,
    goal: dict | None = None,
    version: int = 7,
    subagent_mode: str | None = None,
    subagent_label: str | None = None,
) -> dict:
    """造一份 projcache 会话 JSON。

    `subagent_mode` / `subagent_label` 是 **task-170** 的读模型事实（默认不给 → 投影里没有该行）：
    `continuable` = 被 spawn 的 subagent/队友，`one-shot` = 普通会话。
    """
    metrics: dict = {"turns": turns, "steps": steps, "lastTurn": turns, "openStep": open_step, "pendingCalls": {}}
    list_meta: dict = {} if last_prompt_at is None else {"lastPromptAt": last_prompt_at}
    subagent_identity: dict | None = None
    if subagent_mode is not None:
        subagent_identity = {"mode": subagent_mode, "seq": 0}
        if subagent_label:
            subagent_identity["label"] = subagent_label
    doc: dict = {
        "version": version,
        "record": {
            "identity": {"formatVersion": 3, "createdAt": created, "cwd": cwd, "isSeeded": False, "inheritedEventCount": 0},
            "rows": {
                "title": {"ver": 1, "seq": 20, "val": title},
                "titleInput": {
                    "ver": 3,
                    "seq": 20,
                    "val": {"first": {"seq": 1, "text": first_text}, "count": turns, "lastSeq": 20},
                },
                "sessionStats": {"ver": 1, "seq": 20, "val": metrics},
                "sessionListMetadata": {"ver": 1, "seq": 20, "val": list_meta},
                "todos": {"ver": 2, "seq": 20, "val": todos},
                "goal": {"ver": 6, "seq": 20, "val": goal},
            },
        },
    }
    if subagent_identity is not None:
        doc["record"]["rows"]["subagent"] = {"ver": 1, "seq": 21, "val": {"identity": subagent_identity}}
    return doc


def _goal(objective: str, phase: str) -> dict:
    return {
        "current": {
            "goal": {"id": "goal-fixture", "revision": 1, "objective": objective, "phase": phase},
            "roundsStarted": 1,
        },
        "seenGoalIds": ["goal-fixture"],
        "failure": None,
    }


def build_dsh_home(root: Path) -> Path:
    """在 root 下生成一份完整的 DSH 目录快照，返回该 root。"""
    storages = root / "storages"
    sessions = storages / "session_projcache" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)

    workspaces = {
        "w-alpha": {"path": ALPHA, "title": "alpha", "sessionIds": [ALPHA_RECENT, ALPHA_ARCHIVED]},
        "w-beta": {"path": BETA, "title": "beta", "sessionIds": [BETA_OLD]},
        "w-sibling": {"path": ALPHA_SIBLING, "title": "alpha_sibling", "sessionIds": []},
        "w-other": {"path": OTHER, "title": "demo01", "sessionIds": []},
        "w-home": {"path": HOME, "title": "home", "sessionIds": []},
    }
    for row in workspaces.values():
        row["createdAt"] = "2026-08-01T00:00:00.000Z"
        row["updatedAt"] = "2026-09-01T00:00:00.000Z"

    (storages / "workspace.json").write_text(
        json.dumps(
            {
                "unit": {"name": "workspace", "version": 2},
                "global": {
                    "initialized": True,
                    "workspaceIds": list(workspaces),
                    "archivedSessionIds": [ALPHA_ARCHIVED],
                },
                "tables": {"workspaces": workspaces},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    docs: dict[str, dict] = {
        ALPHA_RECENT: session_doc(
            cwd=ALPHA,
            title="alpha work",
            created=ms(2026, 9, 1),
            last_prompt_at=ms(2026, 10, 10, 5),
            turns=10,
            steps=100,
            todos=[
                {"content": "已完成的步骤", "status": "completed"},
                {"content": "正在做的步骤", "status": "in_progress"},
                {"content": "待办步骤", "status": "pending"},
            ],
            goal=_goal("把 alpha 做完", "active"),
        ),
        BETA_OLD: session_doc(
            cwd=BETA,
            title="beta work",
            created=ms(2026, 8, 15),
            last_prompt_at=None,
            turns=4,
            steps=40,
            todos=[{"content": "遗留的待办", "status": "pending"}],
            goal={"current": None, "seenGoalIds": [], "failure": None},
        ),
        ALPHA_EMPTY: session_doc(
            cwd=ALPHA, title="", created=ms(2026, 10, 9), last_prompt_at=ms(2026, 10, 9), turns=0, steps=0
        ),
        ALPHA_ARCHIVED: session_doc(
            cwd=ALPHA,
            title="archived work",
            created=ms(2026, 9, 20),
            last_prompt_at=ms(2026, 10, 9),
            goal=_goal("早已结束", "complete"),
        ),
        UNKNOWN_CWD: session_doc(
            cwd="/work/unknown", title="unknown cwd", created=ms(2026, 10, 1), last_prompt_at=ms(2026, 10, 9)
        ),
        HOME_CWD: session_doc(
            cwd=HOME, title="home chat", created=ms(2026, 10, 1), last_prompt_at=ms(2026, 10, 9)
        ),
        STALLED: session_doc(
            cwd=ALPHA,
            title="stalled work",
            created=ms(2026, 9, 1),
            last_prompt_at=ms(2026, 9, 5),
            turns=3,
            steps=30,
            open_step="step-1",
            todos=[{"content": "卡住的步骤", "status": "in_progress"}],
        ),
        FUTURE_VERSION: session_doc(
            cwd=ALPHA,
            title="future schema",
            created=ms(2026, 10, 1),
            last_prompt_at=ms(2026, 10, 9),
            version=9,
        ),
    }

    for session_id, doc in docs.items():
        (sessions / f"{session_id}.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )

    (sessions / TEMP_FILE).write_bytes(b"")
    (sessions / f"{BAD_JSON}.json").write_text('{"version": 7, "record": ', encoding="utf-8")
    return root


def fixture_config_toml(library: str | None = None) -> str:
    head = ['dsh_home = "REPLACED"']
    if library:
        # TOML 顶层键必须在所有 [[table]] 之前
        head.append(f'library = "{library}"')
    return "\n".join(
        head
        + [
            'active_days = 14',
            'active_hours = 24',
            'row_limit = 8',
            'exclude_paths = ["/home/tester"]',
            "pins = []",
            "",
            "[[merge]]",
            'key = "alpha_beta"',
            'title = "Alpha Beta"',
            f'paths = ["{ALPHA}", "{BETA}"]',
            "",
        ]
    )
