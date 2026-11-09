"""写入计划：干跑优先，幂等判定。

设计约束（对齐 alpha 方案 §8.5）：
- 默认干跑，--write 才落盘。
- 生成文件的 action 由「磁盘内容 vs 新内容」逐字节比较决定，因此
  "再跑一次" 的结果必须是全部 unchanged。
- 人工文件一律 skip_if_exists：已存在就永不覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pm.layout import Layout
from pm.model import Agent
from pm.org import write_atomic
from pm.render import org as org_render
from pm.scan import ScanResult
from pm.scaffold import plan_for as scaffold_plan
from pm.summaries import SummaryEntry, resolve

GENERATED = "generated"
HUMAN = "human"


@dataclass(frozen=True)
class WriteOp:
    path: Path
    content: str
    kind: str
    skip_if_exists: bool = False


@dataclass
class PlanItem:
    path: Path
    kind: str
    action: str  # create | update | unchanged | keep
    relative: str

    @property
    def writes(self) -> bool:
        return self.action in ("create", "update")


def _by_identity(result: ScanResult) -> dict[str, Agent]:
    return {agent.identity_key: agent for project in result.projects for agent in project.agents}


def resolve_summaries(
    result: ScanResult,
    human: dict[str, SummaryEntry],
    ai: dict[str, SummaryEntry],
) -> dict[str, SummaryEntry | None]:
    """逐卡解析摘要：人工 > AI > None。人工摘要永远优先。"""
    return {
        agent.identity_key: resolve(agent.identity_key, human, ai)
        for project in result.projects
        for agent in project.agents
    }


def build_plan(
    layout: Layout,
    result: ScanResult,
    resolved: dict[str, SummaryEntry | None],
    *,
    now: datetime,
    include_scaffold: bool = False,
) -> list[WriteOp]:
    active_hours = result.config.active_hours
    by_key = _by_identity(result)
    sources = {key: (entry.source if entry else 'not_generated') for key, entry in resolved.items()}
    pending = [agent for agent in by_key.values() if resolved.get(agent.identity_key) is None]
    ops: list[WriteOp] = []

    for project in result.projects:
        for agent in project.agents:
            ops.append(
                WriteOp(
                    path=layout.session_card(agent.source_instance, agent.session_id),
                    content=org_render.session_card_text(
                        agent,
                        project=project.id,
                        project_key=project.key,
                        summary=resolved.get(agent.identity_key),
                        now=now,
                        active_hours=active_hours,
                    ),
                    kind=GENERATED,
                )
            )


    # 库根看板。只链接真实存在的人工文件，避免在 Emacs 里留死链。
    human_links: dict[str, str] = {}
    for name, label in (
        ("README.org", "说明与目录约定"),
        ("inbox.org", "Inbox —— 随手记"),
        ("overrides.org", "人工摘要覆盖"),
        ("ai-summaries.org", "AI 摘要"),
    ):
        if (layout.root / name).is_file():
            human_links[name] = label
    for project in result.projects:
        for name, label in (
            ("project.org", "目标 / 范围 / 验收"),
            ("tasks.org", "任务"),
            ("memory.org", "记忆 / 决策 / 坑"),
        ):
            if (layout.project_dir(project.id) / name).is_file():
                human_links[f"projects/{project.id}/{name}"] = f"{project.title} — {label}"
    # 每个项目一个页面：避免所有项目挤在 index.org 里读不动。
    for project in result.projects:
        ops.append(
            WriteOp(
                path=layout.project_page(project.key),
                content=org_render.project_page_text(
                    project,
                    resolved=resolved,
                    human_links=human_links,
                    now=now,
                    active_hours=active_hours,
                ),
                kind=GENERATED,
            )
        )
    ops.append(
        WriteOp(
            path=layout.index,
            content=org_render.index_text(
                result,
                resolved=resolved,
                human_links=human_links,
                now=now,
                active_hours=active_hours,
            ),
            kind=GENERATED,
        )
    )

    ops.append(
        WriteOp(
            path=layout.agents_index,
            content=org_render.agents_index_text(
                result, by_key=by_key, sources=sources, now=now, active_hours=active_hours
            ),
            kind=GENERATED,
        )
    )
    counts: dict[str, tuple[int, int]] = {}
    for project in result.projects:
        total = len(project.agents)
        missing = sum(
            1 for a in project.agents if resolved.get(a.identity_key) is None
        )
        counts[project.key] = (total, missing)
    ops.append(
        WriteOp(
            path=layout.projects_index,
            content=org_render.projects_index_text(result, counts=counts),
            kind=GENERATED,
        )
    )
    ops.append(
        WriteOp(
            path=layout.summary_queue,
            content=org_render.summary_queue_text(result, pending=pending),
            kind=GENERATED,
        )
    )

    if include_scaffold:
        for path, content in scaffold_plan(layout, result.projects):
            ops.append(WriteOp(path=path, content=content, kind=HUMAN, skip_if_exists=True))
    return ops


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def find_orphans(ops: list[WriteOp], layout: Layout) -> list[Path]:
    """generated/ 下存在、但本次计划不再涉及的文件。

    **只报告，绝不自动删除** —— 数据源暂时不可用（例如某个实例没挂载）时，
    自动删除会毁掉重建所需的产物。
    """
    planned = {op.path.resolve() for op in ops}
    if not layout.generated_dir.is_dir():
        return []
    return sorted(
        path
        for path in layout.generated_dir.rglob("*.org")
        if path.resolve() not in planned
    )


def preview(ops: list[WriteOp], layout: Layout) -> list[PlanItem]:
    items: list[PlanItem] = []
    for op in ops:
        existing = _read(op.path)
        if existing is None:
            action = "create"
        elif op.skip_if_exists:
            action = "keep"
        elif existing == op.content:
            action = "unchanged"
        else:
            action = "update"
        items.append(
            PlanItem(
                path=op.path,
                kind=op.kind,
                action=action,
                relative=_relative(op.path, layout.root),
            )
        )
    for orphan in find_orphans(ops, layout):
        items.append(
            PlanItem(
                path=orphan,
                kind=GENERATED,
                action="orphan",
                relative=_relative(orphan, layout.root),
            )
        )
    return items


def apply(ops: list[WriteOp], layout: Layout, *, write: bool) -> list[PlanItem]:
    items = preview(ops, layout)
    if not write:
        return items
    for op, item in zip(ops, items):
        if item.writes:
            write_atomic(op.path, op.content)
    for item in items:
        item.action = "created" if item.action == "create" else ("updated" if item.action == "update" else item.action)
    return items


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
