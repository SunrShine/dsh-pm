"""生成 org 文本。

**纯度要求**：所有生成内容必须是「数据 + 人工覆盖」的纯函数，
不得包含 render 时刻的墙钟时间。否则同一份数据渲染两次会产生 diff，
幂等性断言就会失效。因此这里只写绝对时间戳，不写「3 天前」这类相对表述。
"""

from __future__ import annotations

import re
from datetime import datetime

from pm import __version__
from pm.model import OBSERVATION_LABEL, RUNTIME_UNKNOWN, Agent
from pm.org import file_header, headline, render_text
from pm.scan import ScanResult
from pm.summaries import SummaryEntry
from pm.width import display_width, pad

GENERATED_TAGS = ("pm", "generated")


#: [[target][描述]] 或 [[target]]；org 渲染时只显示描述，对齐也按它算。
_LINK_RE = re.compile(r"\[\[([^\]\[]+)\](?:\[([^\]]*)\])?\]")
#: org 把整列都是数字的列右对齐。
_NUMBER_RE = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?$")


def cell_display_width(text: str) -> int:
    """单元格在 org 里的**渲染宽度**。

    Emacs 的 org-table-align 就是这么算的：[[file:..][打开]] 只按「打开」计宽。
    我们若按原始文本计宽，Emacs 一 align 就会推翻 —— 两边必须用同一把尺子。
    """

    def shrink(match: re.Match[str]) -> str:
        desc = match.group(2)
        return desc if desc is not None else match.group(1)

    return display_width(_LINK_RE.sub(shrink, text))


def org_table(headers: list[str], rows: list[list[str]], *, indent: str = "  ") -> list[str]:
    """生成与 Emacs org-table-align 结果一致的 org 表格。

    两条规则缺一不可：
    1. 列宽按 cell_display_width（链接只算描述），与 org 一致；
    2. 补齐也用同一把尺子，否则链接列会多补出一堆空格。
    """
    def cell(value: str) -> str:
        # org 表格里的裸竖线会破坏列结构
        return " ".join(str(value).replace("|", "/").split())

    header_cells = [cell(h) for h in headers]
    body_cells = [[cell(c) for c in row] for row in rows]
    widths = [cell_display_width(h) for h in header_cells]
    for row in body_cells:
        for index, value in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], cell_display_width(value))

    # org 会把「全是数字」的列右对齐；不跟它一致就永远对不齐。
    numeric: list[bool] = []
    for index in range(len(widths)):
        values = [row[index] for row in body_cells if index < len(row) and row[index]]
        numeric.append(bool(values) and all(_NUMBER_RE.match(v) for v in values))

    def pad_cell(raw: str, width: int, right: bool) -> str:
        gap = max(0, width - cell_display_width(raw))
        return (" " * gap + raw) if right else (raw + " " * gap)

    def line(cells: list[str]) -> str:
        padded = [
            pad_cell(cells[i] if i < len(cells) else "", widths[i], numeric[i])
            for i in range(len(widths))
        ]
        return indent + "| " + " | ".join(padded) + " |"

    out = [line(header_cells), indent + "|" + "+".join("-" * (w + 2) for w in widths) + "|"]
    out.extend(line(row) for row in body_cells)
    return out


# 每个页面各自的导航 —— 不含指向自己的自链接。
NAV_CARDS: dict[str, str] = {
    "../index.org": "← 看板",
    "summary-queue.org": "缺摘要",
    "projects.org": "项目索引",
    "../inbox.org": "Inbox",
}

NAV_QUEUE: dict[str, str] = {
    "../index.org": "← 看板",
    "agents.org": "工作卡总表",
    "projects.org": "项目索引",
    "../inbox.org": "Inbox",
}

NAV_PROJECTS: dict[str, str] = {
    "../index.org": "← 看板",
    "agents.org": "工作卡总表",
    "../inbox.org": "Inbox",
}

NAV_IN_PROJECT_PAGE: dict[str, str] = {
    "../../index.org": "← 看板",
    "../agents.org": "工作卡总表",
    "../../inbox.org": "Inbox",
}


def nav_line(links: dict[str, str]) -> list[str]:
    """统一的返回导航。放在文件顶部，长文件底部再放一次。"""
    if not links:
        return []
    joined = "   ·   ".join(f"[[file:{path}][{label}]]" for path, label in links.items())
    return ["  " + joined, ""]


def _stamp(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M %z") if value else ""


def _bullets(items: list[str], empty: str) -> list[str]:
    return [f"   - {item}" for item in items] if items else [f"   {empty}"]


def _summary_provenance(entry: SummaryEntry | None) -> str:
    if entry is None:
        return "not_generated"
    if entry.source == "human":
        return "human（人工撰写，机器永不覆盖）"
    parts = [p for p in (entry.generated_by, entry.generated_at) if p]
    return "ai" + (f"（{' / '.join(parts)}）" if parts else "")


def session_card_text(
    agent: Agent,
    *,
    project: str,
    project_key: str = "",
    summary: SummaryEntry | None,
    now: datetime,
    active_hours: int = 24,
) -> str:
    observation = agent.observation_at(now, active_hours=active_hours)
    label = OBSERVATION_LABEL.get(observation, observation.value)
    action, from_prompt = agent.recent_action()

    properties = {
        "ID": f"card-{agent.source_instance}-{agent.session_id}",
        "PM_KIND": "card",
        "PM_SOURCE_INSTANCE": agent.source_instance,
        "PM_SESSION": agent.session_id,
        "PM_IDENTITY": agent.identity_key,
        "PM_PROJECT": project,
        "PM_CWD": agent.cwd or "",
        "PM_RUNTIME_STATUS": RUNTIME_UNKNOWN,
        "PM_OBSERVATION": observation.value,
        "PM_OBSERVED_AT": _stamp(agent.last_active),
        "PM_TURNS": str(agent.turns),
        "PM_STEPS": str(agent.steps),
        "PM_SUMMARY_SOURCE": summary.source if summary else "not_generated",
        "PM_CACHE_FILE": agent.raw_path,
    }

    lines = file_header(
        f"工作卡 {agent.session_id}",
        tags=("pm", "card"),
        extra=[f"#+PM_GENERATOR: pm {__version__}"],
    )
    # 卡片在 generated/sessions/<instance>/ 下，回库根要退三层
    nav = {
        "../../../index.org": "← 看板",
        "../../agents.org": "工作卡总表",
    }
    if project_key:
        nav["../../projects/" + project_key + ".org"] = "← 项目页"
    nav["../../../inbox.org"] = "Inbox"
    lines.extend(nav_line(nav))

    summary_body = [
        f"   来源：{_summary_provenance(summary)}",
        f"   {summary.text if summary else '[待生成摘要]'}",
    ]

    lines.extend(
        headline(
            1,
            f"工作卡：{agent.card_label}",
            tags=("pm", "card"),
            properties=properties,
            body=[
                "",
                "** 状态",
                f"   运行状态：{RUNTIME_UNKNOWN}"
                "（未接入 DSH 运行时接口；读到的只是快照，快照里没有「此刻是否还在跑」的信号，所以不猜）",
                f"   缓存观察：{label}   ·   记录于 {_stamp(agent.last_active) or '未知'}",
                f"   轮/步：T{agent.turns}/S{agent.steps}   ·   缓存待办：{agent.progress}",
                "",
                "** 一句话摘要",
                *summary_body,
                "",
                "** 最近记录的动作",
                f"   {action if action and not from_prompt else ('[来自对话正文，已按策略隐去]' if from_prompt else '[无结构化动作记录]')}",
                "",
                "** 缓存目标（goal）",
                *(
                    [
                        f"   - 阶段：{agent.goal.phase}",
                        f"   - 目标：{agent.goal.objective}",
                        "   注意：phase=complete 只表示目标被标记结束，不代表已通过验收。",
                    ]
                    if agent.goal
                    else ["   （缓存中没有 goal）"]
                ),
                "",
                "** 缓存任务（todos）",
                *_bullets(
                    [f"[{t.status}] {t.content}" for t in agent.todos],
                    "（缓存中没有 todo）",
                ),
                "",
                "** 来源",
                f"   - 数据实例：{agent.source_instance}",
                f"   - 会话：{agent.session_id}",
                f"   - 工作目录：{agent.cwd or '(未记录)'}",
                f"   - 项目：{project}",
                f"   - 缓存文件：{agent.raw_path}",
            ],
        )
    )
    return render_text(lines)


def summary_queue_text(result: ScanResult, *, pending: list[Agent]) -> str:
    pending = sorted(pending, key=lambda a: (a.last_active is None, a.last_active))
    lines = file_header("待生成摘要的工作卡", tags=GENERATED_TAGS)
    lines.extend(nav_line(NAV_QUEUE))
    lines.append(f"共 {len(pending)} 张卡缺少人工/AI 摘要。")
    lines.append("")
    lines.append("生成方式：在 DSH 会话里让 agent 读取本文件，逐条生成摘要后写回 overrides.org（人工复核）。")
    lines.append("")
    for agent in pending:
        lines.extend(
            headline(
                1,
                f"{agent.session_id}",
                tags=("pm", "todo"),
                properties={
                    "PM_IDENTITY": agent.identity_key,
                    "PM_PROJECT": agent.workspace_title or "",
                    "PM_CWD": agent.cwd or "",
                    "PM_STEPS": str(agent.steps),
                    # 路径相对本文件所在目录（generated/），这样 org 里能直接跳转
                    "PM_CARD": f"sessions/{agent.source_instance}/{agent.session_id}.org",
                },
            )
        )
    return render_text(lines)


def _workspace_lines(project) -> list[str]:
    """org 文件里没有终端宽度限制，所以每个工作区单独一行全部列出。

    终端视图用 Project.path_label 显示「首个 (+N)」是宽度妥协，
    这里不该继承那个妥协 —— 合并项目的成员路径正是人最需要一眼看清的。
    """
    if not project.paths:
        return ["   - 工作区：（无）"]
    if len(project.paths) == 1:
        return [f"   - 工作区：{project.paths[0]}"]
    lines = [f"   - 工作区（{len(project.paths)} 个）："]
    lines.extend(f"     - {path}" for path in project.paths)
    return lines


def projects_index_text(result: ScanResult, *, counts: dict[str, tuple[int, int]]) -> str:
    lines = file_header("项目索引", tags=GENERATED_TAGS)
    lines.extend(nav_line(NAV_PROJECTS))
    lines.append("运行状态列恒为 unknown：读到的只是快照，快照里没有「此刻是否还在跑」的信号，所以不猜。")
    lines.append("")
    for project in result.projects:
        total, pending = counts.get(project.key, (0, 0))
        lines.extend(
            headline(
                1,
                project.title,
                tags=("pm", "project"),
                properties={
                    "ID": project.id,
                    "PM_KIND": "project",
                    "PM_KEY": project.key,
                    "PM_PATHS": "|".join(project.paths),
                    "PM_RUNTIME_STATUS": RUNTIME_UNKNOWN,
                    "PM_LAST_RECORDED": _stamp(project.last_active),
                },
                body=[
                    "",
                    *_workspace_lines(project),
                    f"   - 工作卡：{len(project.agents)} 张"
                    + (f"（另有 {project.hidden_agents} 张被行数上限折叠）" if project.hidden_agents else ""),
                    f"   - 缓存待办：{project.open_todo_total}/{project.open_todo_total + project.done_todo_total}",
                    f"   - 缺摘要：{pending}/{total}",
                ],
            )
        )
    return render_text(lines)


def index_text(
    result: ScanResult,
    *,
    resolved: dict[str, SummaryEntry | None],
    human_links: dict[str, str],
    now: datetime,
    active_hours: int = 24,
) -> str:
    """库根看板：**只放总览**，每个项目的卡片表在 generated/projects/<key>.org。

    之前把十个项目、上百张卡塞进这一个文件，人直接读根本读不动。
    现在的分工：index.org = 导航 + 项目总表；项目页 = 该项目的全部卡。

    human_links 是「已存在的人工文件」的 根相对路径 -> 标签；
    只链接真实存在的文件，否则会在 Emacs 里留下死链。
    """
    lines = file_header("work-memory 看板", tags=GENERATED_TAGS)
    lines.append("")
    lines.append("* 从这里开始")
    for path, label in human_links.items():
        if "/" in path:
            continue  # 项目人工文件挂在各自项目页上
        lines.append(f"  - [[file:{path}][{label}]]")
    lines.append(f"  - [[file:generated/agents.org][工作卡总表（{len(resolved)} 张）]]")
    lines.append("  - [[file:generated/summary-queue.org][缺摘要清单]]")
    lines.append("  - [[file:generated/projects.org][项目索引（机器可读）]]")
    lines.append("")
    lines.append("  运行状态一律 unknown —— 读到的只是快照，快照里没有「此刻是否还在跑」的信号，所以不猜。")
    lines.append("")
    lines.append("* 项目总览")
    rows = []
    for project in result.projects:
        pending = sum(1 for a in project.agents if resolved.get(a.identity_key) is None)
        total_todos = project.open_todo_total + project.done_todo_total
        page = f"generated/projects/{project.key}.org"
        rows.append(
            [
                project.title,
                str(len(project.agents)),
                str(pending),
                str(len(project.paths)),
                f"{project.open_todo_total}/{total_todos}",
                _stamp(project.last_active) or "-",
                f"[[file:{page}][打开]]",
            ]
        )
    lines.extend(
        org_table(
            ["项目", "工作卡", "缺摘要", "工作区", "缓存待办", "最近记录", "详情"], rows
        )
    )
    lines.append("")
    lines.append("  每个项目的完整卡片表见 generated/projects/<key>.org。")
    return render_text(lines)


def project_page_text(
    project,
    *,
    resolved: dict[str, SummaryEntry | None],
    human_links: dict[str, str],
    now: datetime,
    active_hours: int = 24,
    limit: int = 0,
    card_prefix: str = "../sessions",
    root_prefix: str = "../../",
) -> str:
    """单个项目的页面：全部工作卡 + 该项目的人工区链接。

    链接前缀是相对**本文件所在目录**（generated/projects/）算的 —— 写错就是死链，
    有 LinkIntegrityTest 全库盯着。
    """
    lines = file_header(project.title + " — 工作卡", tags=GENERATED_TAGS)
    lines.extend(nav_line(NAV_IN_PROJECT_PAGE))
    shown = project.agents[:limit] if limit > 0 else project.agents
    pending = sum(1 for a in project.agents if resolved.get(a.identity_key) is None)
    body = [
        "",
        *_workspace_lines(project),
        f"   - 工作卡：{len(project.agents)} 张"
        + (f"（另有 {project.hidden_agents} 张被行数上限折叠，见工作卡总表）" if project.hidden_agents else ""),
        f"   - 缓存待办：{project.open_todo_total}/{project.open_todo_total + project.done_todo_total}"
        f"   ·   缺摘要：{pending}/{len(project.agents)}",
        f"   - 最近记录：{_stamp(project.last_active) or '-'}",
    ]
    for path, label in human_links.items():
        if path.startswith(f"projects/{project.id}/"):
            body.append(f"   - 人工区：[[file:{root_prefix}{path}][{label}]]")
    body.append("")
    rows = []
    for agent in shown:
        observation = agent.observation_at(now, active_hours=active_hours)
        label = OBSERVATION_LABEL.get(observation, observation.value)
        entry = resolved.get(agent.identity_key)
        text = entry.text if entry else "[待生成摘要]"
        source = entry.source if entry else "not_generated"
        card = f"{card_prefix}/{agent.source_instance}/{agent.session_id}.org"
        mark = {"human": "人", "ai": "AI"}.get(source, "—")
        rows.append(
            [
                label,
                f"[[file:{card}][{agent.session_id[:19]}]]",
                f"{mark} {text}",
                agent.progress,
                _stamp(agent.last_active) or "-",
            ]
        )
    if len(project.agents) > len(shown):
        rows.append(["…", f"另有 {len(project.agents) - len(shown)} 张未显示", "", "", ""])
    body.extend(org_table(["观察", "工作卡", "摘要", "进度", "记录于"], rows, indent="   "))
    body.append("")
    body.append("  返回：[[file:../../index.org][← 看板]]   ·   [[file:../agents.org][全库工作卡总表]]")
    lines.extend(
        headline(
            1,
            project.title,
            tags=("pm", "project"),
            properties={
                "ID": project.id,
                "PM_KEY": project.key,
                "PM_RUNTIME_STATUS": RUNTIME_UNKNOWN,
                "PM_PATHS": "|".join(project.paths),
            },
            body=body,
        )
    )
    return render_text(lines)


def agents_index_text(
    result: ScanResult,
    *,
    by_key: dict[str, Agent],
    sources: dict[str, str],
    now: datetime,
    active_hours: int = 24,
) -> str:
    lines = file_header("工作卡总表", tags=GENERATED_TAGS)
    lines.extend(nav_line(NAV_CARDS))
    rows = []
    for agent in sorted(by_key.values(), key=lambda a: (a.last_active is None, a.last_active), reverse=True):
        observation = agent.observation_at(now, active_hours=active_hours)
        label = OBSERVATION_LABEL.get(observation, observation.value)
        # 链接相对本文件所在目录（generated/），否则 Emacs 里点开是死链
        card = f"sessions/{agent.source_instance}/{agent.session_id}.org"
        summary = "[[file:%s][%s]]" % (card, agent.session_id[:13])
        rows.append(
            [
                label,
                summary,
                agent.workspace_title or "-",
                agent.progress,
                f"T{agent.turns}/S{agent.steps}",
                _stamp(agent.last_active) or "-",
                sources.get(agent.identity_key, "not_generated"),
            ]
        )
    lines.extend(
        org_table(["观察", "工作卡", "项目", "缓存待办", "轮/步", "记录于", "摘要来源"], rows)
    )
    return render_text(lines)
