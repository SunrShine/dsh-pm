"""读取 ~/.dsh/storages/session_projcache/sessions/*.json —— DSH 会话投影。

这是 M1 的主数据源：DSH 已经算好并通过投影持久化，读起来便宜且稳定。

实测坑（必须防御）：
1. 目录里会残留 0 字节的临时文件（形如 .<uuid>.tmp），不是 JSON；
2. 文件名有时带 session- 前缀、有时不带，需归一化才能和 workspace.json 对上；
3. 投影带 version（实测 7），DSH 升级后结构可能变化 —— 未知字段要容忍，缺失字段要降级；
4. 会话可能正在被另一个进程追加写入，读到半截 JSON 是正常现象，跳过即可。

权威兜底是 session.v3.jsonl.zstd，但那是**拼接的多帧 zstd**，
zstdDecompressSync 只解第一帧，且 DSH 正在做 v3→v4 迁移，故放到后续里程碑。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pm.model import Agent, Goal, Todo

CACHE_RELPATH = ("storages", "session_projcache", "sessions")

#: 我们验证过的投影版本。新版本不会导致失败，但会记一条 warning。
KNOWN_PROJECTION_VERSIONS = frozenset({7})

#: 单个 prompt 文本的截断上限，避免把整段会话读进内存。
PROMPT_MAX_CHARS = 4000


def canonical_session_id(raw: str) -> str:
    """把任意形式的会话标识归一化为 DSH 的 session-<uuid> 形式。"""
    text = raw.strip()
    if text.endswith(".json"):
        text = text[: -len(".json")]
    if text.startswith("."):
        text = text.lstrip(".")
    if not text.startswith("session-"):
        text = "session-" + text
    return text


def _timestamp_ms(value: object) -> datetime | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).astimezone()
    except (OverflowError, OSError, ValueError):
        return None


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


@dataclass
class ProjectionFile:
    path: Path
    version: int | None = None
    session_id: str = ""
    cwd: str = ""
    agent: Agent | None = None
    error: str = ""


@dataclass
class CacheLoad:
    agents: list[Agent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scanned_files: int = 0
    skipped_files: int = 0
    versions: tuple[int, ...] = ()


def _row(rows: dict[str, Any], name: str) -> dict[str, Any]:
    """取出 rows.<name>，并返回其 val 所在的投影行（含 ver/seq）。"""
    value = rows.get(name)
    return value if isinstance(value, dict) else {}


def _row_val(rows: dict[str, Any], name: str) -> Any:
    return _row(rows, name).get("val")


def _prompt_of(value: Any) -> str:
    if isinstance(value, str):
        return value[:PROMPT_MAX_CHARS]
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text[:PROMPT_MAX_CHARS]
    return ""


def parse_agent(
    data: dict[str, Any],
    *,
    path: Path,
    archived: bool,
    workspace_title: str,
    source_instance: str = "dsh-default",
) -> Agent | None:
    """把一份 projcache JSON 解析为 Agent；结构不可用时返回 None。"""
    record = data.get("record")
    if not isinstance(record, dict):
        return None
    rows = record.get("rows")
    if not isinstance(rows, dict):
        return None

    identity = record.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    cwd = _text(identity.get("cwd"))

    session_id = canonical_session_id(path.name)

    title_input = _row_val(rows, "titleInput")
    title_input = title_input if isinstance(title_input, dict) else {}
    first_prompt = _prompt_of(title_input.get("first"))
    last_prompt = _prompt_of(title_input.get("last"))

    stats = _row_val(rows, "sessionStats")
    stats = stats if isinstance(stats, dict) else {}
    pending_calls = stats.get("pendingCalls")
    if isinstance(pending_calls, dict):
        pending_count = sum(1 for v in pending_calls.values() if v)
    elif isinstance(pending_calls, list):
        pending_count = len(pending_calls)
    elif isinstance(pending_calls, int) and not isinstance(pending_calls, bool):
        pending_count = pending_calls
    else:
        pending_count = 0

    todos: list[Todo] = []
    raw_todos = _row_val(rows, "todos")
    if isinstance(raw_todos, list):
        for item in raw_todos:
            if not isinstance(item, dict):
                continue
            content = _text(item.get("content")).strip()
            status = _text(item.get("status")).strip() or "pending"
            if content:
                todos.append(Todo(content=content, status=status))

    goal: Goal | None = None
    raw_goal = _row_val(rows, "goal")
    if isinstance(raw_goal, dict):
        current = raw_goal.get("current")
        if isinstance(current, dict):
            inner = current.get("goal")
            if isinstance(inner, dict):
                goal = Goal(
                    id=_text(inner.get("id")),
                    objective=_text(inner.get("objective")),
                    phase=_text(inner.get("phase")),
                    revision=int(inner.get("revision") or 0) if isinstance(inner.get("revision"), (int, float)) else 0,
                    rounds_started=int(current.get("roundsStarted") or 0)
                    if isinstance(current.get("roundsStarted"), (int, float))
                    else 0,
                )

    list_meta = _row_val(rows, "sessionListMetadata")
    list_meta = list_meta if isinstance(list_meta, dict) else {}

    # 子 agent / 队友的事实来自投影本身：rows.subagent.val.identity.{mode,label}
    # mode: continuable = 被 spawn 的 subagent/队友；one-shot = 普通会话；缺字段 → None（不猜）
    subagent_val = _row_val(rows, "subagent")
    subagent_val = subagent_val if isinstance(subagent_val, dict) else {}
    sub_identity = subagent_val.get("identity")
    sub_identity = sub_identity if isinstance(sub_identity, dict) else {}
    session_mode = _text(sub_identity.get("mode")).strip() or None
    session_label = _text(sub_identity.get("label")).strip() or None

    warnings: list[str] = []
    last_active = _timestamp_ms(list_meta.get("lastPromptAt"))
    if last_active is None:
        last_active = _timestamp_ms(identity.get("createdAt"))
        if last_active is not None:
            warnings.append("缺少 lastPromptAt，用 createdAt 兜底")

    return Agent(
        session_id=session_id,
        source_instance=source_instance,
        cwd=cwd,
        workspace_title=workspace_title,
        title=_text(_row_val(rows, "title")).strip(),
        first_prompt=first_prompt,
        last_prompt=last_prompt,
        created_at=_timestamp_ms(identity.get("createdAt")),
        last_active=last_active,
        turns=int(stats.get("turns") or 0) if isinstance(stats.get("turns"), (int, float)) else 0,
        steps=int(stats.get("steps") or 0) if isinstance(stats.get("steps"), (int, float)) else 0,
        open_step=stats.get("openStep"),
        pending_calls=pending_count,
        todos=todos,
        goal=goal,
        archived=archived,
        session_mode=session_mode,
        session_label=session_label,
        warnings=warnings,
        raw_path=str(path),
    )


def iter_cache_files(cache_dir: Path) -> Iterable[Path]:
    """列出投影文件，跳过临时文件与目录。"""
    if not cache_dir.is_dir():
        return
    for entry in sorted(cache_dir.iterdir()):
        if not entry.is_file():
            continue
        if not entry.name.endswith(".json"):
            continue
        if entry.name.startswith("."):
            continue
        yield entry


def check_supported(cache: CacheLoad) -> list[str]:
    """返回「数据源是否可用」层面的问题清单（空 = 完全支持）。

    对齐 alpha 方案阶段 A 验收：版本不支持时明确报错，而不是静默降级。
    """
    problems: list[str] = []
    unknown = [v for v in cache.versions if v not in KNOWN_PROJECTION_VERSIONS]
    if unknown:
        problems.append(
            f"session_projcache 版本 {unknown} 未经验证"
            f"（已知 {sorted(KNOWN_PROJECTION_VERSIONS)}）；字段可能缺失，输出仅供参考"
        )
    if cache.skipped_files:
        problems.append(f"{cache.skipped_files} 个投影文件无法解析，已跳过")
    if not cache.versions and cache.scanned_files:
        problems.append("投影文件缺失 version 字段，无法确认格式兼容性")
    return problems


def load(
    cache_dir: Path,
    *,
    archived_ids: frozenset[str],
    title_for_path,
    source_instance: str = "dsh-default",
) -> CacheLoad:
    """读取全部会话投影。坏文件只记 warning，不影响其它会话。"""
    result = CacheLoad()
    if not cache_dir.is_dir():
        result.warnings.append(f"找不到会话投影目录: {cache_dir}")
        return result

    versions: set[int] = set()
    for path in iter_cache_files(cache_dir):
        result.scanned_files += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result.skipped_files += 1
            result.warnings.append(f"跳过无法解析的投影文件 {path.name}: {type(exc).__name__}")
            continue
        version = data.get("version")
        if isinstance(version, int):
            versions.add(version)
        session_id = canonical_session_id(path.name)
        cwd = ""
        record = data.get("record")
        if isinstance(record, dict):
            identity = record.get("identity")
            if isinstance(identity, dict):
                cwd = _text(identity.get("cwd"))
        agent = parse_agent(
            data,
            path=path,
            archived=session_id in archived_ids,
            workspace_title=title_for_path(cwd),
            source_instance=source_instance,
        )
        if agent is None:
            result.skipped_files += 1
            result.warnings.append(f"跳过结构不符的投影文件: {path.name}")
            continue
        result.agents.append(agent)

    result.versions = tuple(sorted(versions))
    unknown = sorted(v for v in versions if v not in KNOWN_PROJECTION_VERSIONS)
    if unknown:
        result.warnings.append(
            f"发现未验证的 session_projcache 版本 {unknown}（已知 {sorted(KNOWN_PROJECTION_VERSIONS)}），字段可能缺失"
        )
    return result
