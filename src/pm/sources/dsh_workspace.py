"""读取 ~/.dsh/storages/workspace.json —— DSH 的工作区注册表。

这是 DSH 侧**权威的**工作区/会话归属来源：
- tables.workspaces[*] = { path, title, sessionIds, createdAt, updatedAt }
- global.archivedSessionIds = 被用户归档的会话（不应显示为活跃 agent）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_RELPATH = ("storages", "workspace.json")


@dataclass(frozen=True)
class Workspace:
    id: str
    path: str
    title: str
    session_ids: tuple[str, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class WorkspaceRegistry:
    workspaces: tuple[Workspace, ...] = ()
    archived_session_ids: frozenset[str] = field(default_factory=frozenset)
    warnings: list[str] = field(default_factory=list)

    def by_path(self) -> dict[str, Workspace]:
        return {ws.path: ws for ws in self.workspaces}

    def title_for_path(self, path: str) -> str:
        ws = self.by_path().get(path)
        return ws.title if ws else ""


def _parse_ms(value: object) -> datetime | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).astimezone()
    except (OverflowError, OSError, ValueError):
        return None


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load(dsh_home: Path) -> WorkspaceRegistry:
    """读取工作区注册表；文件缺失或损坏时返回空注册表 + warning。"""
    path = Path(dsh_home).joinpath(*WORKSPACE_RELPATH)
    if not path.is_file():
        return WorkspaceRegistry(warnings=[f"找不到工作区注册表: {path}"])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return WorkspaceRegistry(warnings=[f"工作区注册表无法解析: {path}: {exc}"])

    tables = raw.get("tables") or {}
    rows = tables.get("workspaces") or {}
    workspaces: list[Workspace] = []
    if isinstance(rows, dict):
        for ws_id, row in rows.items():
            if not isinstance(row, dict):
                continue
            path_value = row.get("path")
            if not isinstance(path_value, str) or not path_value:
                continue
            session_ids = row.get("sessionIds")
            workspaces.append(
                Workspace(
                    id=str(ws_id),
                    path=path_value,
                    title=str(row.get("title") or "").strip() or Path(path_value).name,
                    session_ids=tuple(
                        str(s) for s in session_ids if isinstance(s, str)
                    )
                    if isinstance(session_ids, list)
                    else (),
                    created_at=_parse_iso(row.get("createdAt")),
                    updated_at=_parse_iso(row.get("updatedAt")),
                )
            )

    global_block = raw.get("global") or {}
    archived = global_block.get("archivedSessionIds")
    archived_ids = (
        frozenset(str(s) for s in archived if isinstance(s, str))
        if isinstance(archived, list)
        else frozenset()
    )

    workspaces.sort(key=lambda w: w.title)
    return WorkspaceRegistry(workspaces=tuple(workspaces), archived_session_ids=archived_ids)
