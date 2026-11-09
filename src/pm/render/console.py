"""终端输出：pm scan 的人类可读视图与 JSON 视图。

诚实性原则（对齐 上游设计 方案 §3）：
1. 运行状态一律 unknown —— 读到的只是快照，快照里没有「此刻是否还在跑」的信号，任何「正在运行」都是编造。
   「观察」列只描述**缓存记录了什么**，并附采样时间与新鲜度。
2. 未生成摘要时显示占位符，不拿 DSH 自动标题冒充「一句话摘要」。
3. 来自对话正文的文本默认不输出，需显式 --show-prompt。
"""

from __future__ import annotations

import json
from datetime import datetime

from pm.model import OBSERVATION_LABEL, RUNTIME_UNKNOWN, CacheObservation, Project
from pm.render.table import Column, render_table
from pm.scan import ScanResult
from pm.width import ellipsize_lines, pad

RESET = "\x1b[0m"

_OBSERVATION_STYLE: dict[CacheObservation, str] = {
    CacheObservation.STALE_BUSY: "1;31",
    CacheObservation.BUSY: "1;32",
    CacheObservation.RECENT: "0;32",
    CacheObservation.IDLE: "0;2",
    CacheObservation.CLOSED: "0;34",
    CacheObservation.ARCHIVED: "0;2",
    CacheObservation.EMPTY: "0;2",
}

OBSERVATION_LEGEND = (
    "观察图例   忙碌=缓存留有未完成步骤   陈旧·忙碌=该步骤已停滞超过 active_hours（可能中断）"
    "   沉寂=近期无记录   已结束=goal 标记结束（不等于验收通过）"
)

PROMPT_PLACEHOLDER = "[无结构化动作记录]"

_SUMMARY_MARK = {"human": "人", "ai": "AI"}
SUMMARY_COLUMN = "摘要 / 最近记录的动作"


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"\x1b[{code}m{text}{RESET}" if enabled else text


def _stamp(value: datetime | None) -> str:
    return value.strftime("%m-%d %H:%M") if value else "-"


def _age(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "从未"
    days = (now - value).total_seconds() / 86400.0
    if days < 0:
        return "时间戳异常"
    if days < 1:
        return "今天"
    return f"{int(days)} 天前"


def render_scan(
    result: ScanResult,
    *,
    width: int = 120,
    color: bool = True,
    show_warnings: bool = False,
    show_prompt: bool = False,
) -> str:
    config = result.config
    now = result.generated_at
    lines: list[str] = []

    title = "DSH → 工作卡（只读投影）"
    stamp = now.strftime("%Y-%m-%d %H:%M %Z").strip()
    lines.append(_paint(pad(title, max(0, width - len(stamp))), "1", color) + stamp)
    lines.append("")

    shown = result.visible_agents
    total = result.total_agents
    sources = "  ·  ".join(result.source_instances) or "（无数据根）"
    lines.append("  数据源   " + sources)
    lines.append(f"  配置     {config.source_path or '(未找到 pm.toml，使用默认值)'}")
    lines.append(
        f"  规模     {len(result.registry.workspaces)} 个工作区 → {len(result.projects)} 个项目"
        f" · {total} 张卡（显示 {shown}，隐藏 {total - shown}）"
    )
    if result.ignored:
        excluded = ", ".join(sorted({a.cwd for a in result.ignored}))
        lines.append(f"  已排除   {len(result.ignored)} 张卡（{excluded}）")
    if result.unregistered:
        lines.append(f"  未登记   {len(result.unregistered)} 张卡的 cwd 不在 workspace.json 中")
    if not result.projects and not result.unregistered:
        lines.append("")
        lines.append("  （没有符合过滤条件的工作卡；用 --all 查看全部）")
        return "\n".join(lines).rstrip() + "\n"

    if not result.include_all:
        lines.append(
            f"  过滤     近 {config.active_days} 天有记录 ∨ 有未完成任务 ∨ 有进行中的 goal ∨ 已 pin"
            "   （--all 显示全部）"
        )
    lines.append("")
    lines.append(
        _paint(f"  ! 运行状态 {RUNTIME_UNKNOWN}", "1;33", color)
        + " —— 读到的只是快照，快照里没有「此刻是否还在跑」的信号，所以不猜；下表为缓存观察值及其新鲜度。"
    )
    lines.append("")

    for project in result.projects:
        lines.extend(_render_project(project, result, color=color, show_prompt=show_prompt))
        lines.append("")

    if result.suggestions:
        lines.append(_paint("建议合并", "1", color))
        for item in result.suggestions:
            lines.append(f"  · {item.workspace_path}  →  {item.candidate_project}   （{item.reason}）")
        lines.append("")

    lines.append(f"  {OBSERVATION_LEGEND}")
    lines.append("")

    if show_warnings and result.warnings:
        lines.append(_paint("数据源警告", "1;31", color))
        for warning in result.warnings:
            lines.append(f"  ! {warning}")
    elif result.warnings:
        lines.append(f"  （{len(result.warnings)} 条数据源警告，用 --warnings 查看）")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_project(
    project: Project, result: ScanResult, *, color: bool, show_prompt: bool
) -> list[str]:
    now = result.generated_at
    config = result.config
    lines = [_paint(f"▓ {project.title}  ·  {project.key}", "1;36", color)]
    lines.append(f"    路径   {project.path_label}")
    observations = [a.observation_at(now, active_hours=config.active_hours) for a in project.agents]
    busy = sum(
        1 for o in observations if o in (CacheObservation.BUSY, CacheObservation.STALE_BUSY)
    )
    stalled = sum(1 for o in observations if o is CacheObservation.STALE_BUSY)
    scale = f"    规模   {len(project.paths)} 个工作区 · {len(project.agents)} 张卡"
    if busy:
        scale += f"（{busy} 留有未完成步骤"
        scale += f"，{stalled} 已陈旧）" if stalled else "）"
    lines.append(
        scale
        + f" · 缓存待办 {project.open_todo_total}/{project.open_todo_total + project.done_todo_total}"
        + f" · 最近记录 {_stamp(project.last_active)}（{_age(project.last_active, now)}）"
    )

    columns = [
        Column("观察", min_width=12),
        Column("卡标签", max_width=26, min_width=14),
        Column(SUMMARY_COLUMN, max_width=38, min_width=18),
        Column("缓存待办", align="right", min_width=8),
        Column("轮/步", align="right", min_width=10),
        Column("记录于", min_width=11),
    ]
    rows: list[list[str]] = []
    for agent in project.agents:
        observation = agent.observation_at(now, active_hours=config.active_hours)
        label = OBSERVATION_LABEL.get(observation, observation.value)
        action, from_prompt = agent.recent_action()
        if from_prompt and not show_prompt:
            action = PROMPT_PLACEHOLDER
        elif from_prompt:
            action = f"[正文] {action}"
        # 有摘要就优先显示摘要：它比原始动作更接近「这张卡在做什么」
        summary = agent.summary_text
        if agent.summary_status != "not_generated":
            mark = _SUMMARY_MARK.get(agent.summary_status, "?")
            action = f"[{mark}] {summary}"
        rows.append(
            [
                _paint(label, _OBSERVATION_STYLE.get(observation, "0"), color),
                ellipsize_lines(agent.card_label, 26),
                ellipsize_lines(action, 38),
                agent.progress,
                agent.workload,
                _stamp(agent.last_active),
            ]
        )
    lines.extend(render_table(columns, rows, indent="    "))
    if project.hidden_agents:
        lines.append(
            f"    … 另有 {project.hidden_agents} 张更早的卡被行数上限折叠（--limit 0 展开全部）"
        )
    return lines


def render_json(result: ScanResult) -> str:
    now = result.generated_at
    config = result.config
    payload = {
        "generated_at": now.isoformat(),
        "source_instances": list(result.source_instances),
        "runtime_status_supported": False,
        "dsh_home": str(config.dsh_home),
        "config_path": str(config.source_path) if config.source_path else None,
        "active_days": config.active_days,
        "active_hours": config.active_hours,
        "stats": {
            "workspaces": len(result.registry.workspaces),
            "projects": len(result.projects),
            "agents_total": result.total_agents,
            "agents_shown": result.visible_agents,
            "agents_hidden": result.total_agents - result.visible_agents,
            "agents_hidden_by_limit": result.hidden_by_limit,
            "unregistered": len(result.unregistered),
            "ignored": len(result.ignored),
            "archived": sum(1 for a in result.all_agents if a.archived),
        },
        "data_source_versions": list(result.source_versions),
        "cache_files_skipped": result.cache_files_skipped,
        "projects": [
            {
                "key": project.key,
                "id": project.id,
                "title": project.title,
                "paths": project.paths,
                "last_active": project.last_active.isoformat() if project.last_active else None,
                "open_todos": project.open_todo_total,
                "hidden_agents": project.hidden_agents,
                "agents": [_agent_json(a, result) for a in project.agents],
            }
            for project in result.projects
        ],
        "unregistered": [_agent_json(a, result) for a in result.unregistered],
        "suggestions": [
            {
                "workspace_title": s.workspace_title,
                "workspace_path": s.workspace_path,
                "candidate_project": s.candidate_project,
                "reason": s.reason,
            }
            for s in result.suggestions
        ],
        "warnings": result.warnings,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _agent_json(agent, result: ScanResult) -> dict:
    now = result.generated_at
    action, from_prompt = agent.recent_action()
    return {
        "identity_key": agent.identity_key,
        "source_instance": agent.source_instance,
        "session_id": agent.session_id,
        "runtime_status": agent.runtime_status,
        "observation": agent.observation_at(
            now, active_hours=result.config.active_hours
        ).value,
        "observation_label": OBSERVATION_LABEL.get(
            agent.observation_at(now, active_hours=result.config.active_hours), "?"
        ),
        "card_label": agent.card_label,
        "summary": (agent.human_summary or agent.resolved_summary) or None,
        "summary_status": agent.summary_status,
        "raw_title": agent.title,
        "recent_action": action or None,
        "recent_action_from_prompt": from_prompt,
        "todo_counts": {"done": agent.todo_counts[0], "total": agent.todo_counts[1]},
        "todos": [{"content": t.content, "status": t.status} for t in agent.todos],
        "goal": (
            {"id": agent.goal.id, "phase": agent.goal.phase, "objective": agent.goal.objective}
            if agent.goal
            else None
        ),
        "turns": agent.turns,
        "steps": agent.steps,
        "cwd": agent.cwd,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
        "last_active": agent.last_active.isoformat() if agent.last_active else None,
        "archived": agent.archived,
        "pinned": agent.pinned,
        "source": agent.source,
        "warnings": agent.warnings,
    }
