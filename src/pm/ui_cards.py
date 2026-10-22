"""pm ui-cards：把扫描结果投影成给 DSH 插件消费的稳定 JSON。

契约字段（task-1 冻结；改字段必须同步 ui-pm 插件）：

    schemaVersion     协议版本，当前 "ui-cards-v1"（设计 §9；新增字段是增量的）
    capabilities      本实现支持的能力列表，当前 ["cards","inbox","subagents"]
    generated_at      扫描时间（ISO8601）
    library           work-memory 库绝对路径，未配置为 null
    inbox             快速笔记（库根 inbox.org）：{path, count, entries[{text,line,id,status}]}；
                      entries[].id 是 :ID:（无则 null），status = PM_STATUS 或 LEGACY_UNTRACKED；
                      条目还带 capturedAt/source/projectHint 与补充计数
                      annotationCount/revisionCount/lastAnnotationText
                      （旧条目这三个计数是 null —— 「不知道」与「0」要能区分）；
                      以及 pinned（bool，缺 :PM_PIN: = false）：置顶只有是/否，
                      不存在「不知道」，所以它**不是** null 而是 false；
                      **刻意不带补充块全文**（那是 pm inbox list 的投影，避免侧边栏膨胀）；
                      无库/无文件/解析失败为 null。只读，不修改任何人工文件
    instances         本次读取的数据实例 id 列表
    runtime_status    恒为 "unknown"（读到的只是快照，快照里没有「此刻是否还在跑」的信号，不推断）
    projects[]        每个项目一行聚合：key/title/paths/cards/missing_summary/
                      open_todos/total_todos/last_recorded/attention/stale_busy
                      attention = 该项目 needs_attention 为真的卡数（与卡片级同一谓词）
                      stale_busy = 该项目 observation 为 STALE_BUSY 的卡数
                      paths = 保留卡片的 cwd 集合；last_recorded = 保留卡片的最大 recorded_at
                      —— 项目级字段必须与同一次输出的 cards 数组自洽（含默认排除子 agent）
    cards[]           每张工作卡一行，按 (needs_attention 降序, recorded_at 降序) 全局排序
                      needs_attention = observation 为 STALE_BUSY 或还有未完成 todo
                      is_subagent = 主 agent 派发的子 agent（默认被排除，见 --include-subagents）
                      —— 判定以投影事实为准：session_mode == "continuable"（task-170）
                      session_mode = record.rows.subagent.val.identity.mode 原样（"continuable"|"one-shot"|null）
                      session_label = …identity.label 原样（队友/子 agent 的名字；缺 → null）
                      session_title = rows.title.val 原样（不清洗；注入型文本也照给）
                      session_name = 清洗后的人可读名字：label → 非注入型 title → null（拿不到就是 null，不猜）

诚实性约束（与 model.py 一致）：
- 只输出**缓存观察值** observation，不输出"正在运行"。
- 摘要缺失时 summary 为 null、summary_source 为 "not_generated"，
  不拿 DSH 自动标题冒充摘要。

聚合口径：
1. 先按视图过滤（默认排除子 agent，--include-subagents 保留全部）；
2. 项目行基于过滤后的**全部**工作卡 —— 不受 --limit 影响，--limit 只截断 cards 数组；
3. 因此默认视图 == 默认卡片集合的最大值/计数，--include-subagents 视图 == 全部卡片。
"""

from __future__ import annotations

from pathlib import Path

from pm.layout import Layout
from pm.model import OBSERVATION_LABEL, RUNTIME_UNKNOWN, CacheObservation
from pm.scan import ScanResult

#: ui-cards 协议版本（设计 §9）：新增字段是增量的，不破坏既有键。
UI_CARDS_SCHEMA_VERSION = "ui-cards-v1"
#: 统一 envelope 的协议版本（设计 §6）。
API_SCHEMA_VERSION = "pm-api-v2"
#: 本实现对外声明支持的能力。
CAPABILITIES = ("cards", "inbox", "subagents")


def _session_name(agent) -> str | None:
    """会话的**人可读名字**：identity.label → 非注入型 title → None（拿不到就如实 null，不猜）。

    队友会话的 title 是 `<system-reminder> You are teammate "pm-f…` 这类**注入文本**，不能当名字；
    这里对以 `<` 开头的 title 一律返回 None（原文仍在 `session_title` 里，前端可自行决定怎么显示）。
    """
    label = (getattr(agent, "session_label", None) or "").strip()
    if label:
        return label
    title = (getattr(agent, "title", "") or "").strip()
    if not title or title.startswith("<"):
        return None
    return title


def needs_attention(agent, observation: CacheObservation) -> bool:
    """这张卡是否需要人看一眼。

    STALE_BUSY = 缓存留有未完成步骤且已陈旧（会话可能中断）；
    或还有未完成的 todo。
    """
    return observation is CacheObservation.STALE_BUSY or bool(agent.open_todos)


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _recorded_key(value) -> float:
    """降序排序键：None（从未记录）永远排在最后。"""
    return value.timestamp() if value is not None else float("-inf")


def _card_file(library: Path | None, source_instance: str, session_id: str) -> str | None:
    """卡片 org 文件相对库根的路径（文件名规则以 Layout 为唯一真源）。"""
    if library is None:
        return None
    layout = Layout(Path(library))
    try:
        return str(layout.session_card(source_instance, session_id).relative_to(layout.root))
    except ValueError:  # pragma: no cover - 只在异常输入（含 ..）时发生
        return None


def _card(
    library: Path | None,
    project_key: str,
    agent,
    observation: CacheObservation,
    attention: bool,
) -> dict:
    summary = agent.human_summary.strip() or agent.resolved_summary.strip()
    return {
        "session_id": agent.session_id,
        "instance": agent.source_instance,
        "project": project_key,
        "observation": observation.value,
        "observation_label": OBSERVATION_LABEL.get(observation, observation.value),
        "summary": summary or None,
        "summary_source": agent.summary_status,
        "turns": agent.turns,
        "steps": agent.steps,
        "recorded_at": _iso(agent.last_active),
        "cwd": agent.cwd,
        "open_todos": len(agent.open_todos),
        "total_todos": len(agent.todos),
        "needs_attention": attention,
        "is_subagent": bool(agent.is_subagent),
        # 投影事实（不是推导）：mode/label 原样给出，缺失为 null；session_name 是清洗后的人可读名字
        "session_mode": agent.session_mode,
        "session_label": agent.session_label,
        "session_title": agent.title or None,
        "session_name": _session_name(agent),
        "card_file": _card_file(library, agent.source_instance, agent.session_id),
    }


def build_cards_payload(
    result: ScanResult,
    *,
    only_project: str | None = None,
    limit: int = 0,
    library: Path | None = None,
    inbox: dict | None = None,
    include_subagents: bool = False,
) -> dict:
    """组装 ui-cards 载荷（纯函数）。

    only_project 只保留指定项目 key；limit > 0 时每个项目最多输出 limit 张卡。
    同项目内先按 (needs_attention, recorded_at 降序) 取前 limit 张，
    再对全部入选卡做全局排序。

    inbox 由调用方读好传入（读文件在 pm.inbox.read_inbox），
    本函数保持纯函数，便于用 fixture 测试。
    """
    now = result.generated_at
    active_hours = result.config.active_hours
    if library is None:
        library = result.config.library

    project_rows: list[dict] = []
    # (card, needs_attention, recorded_key, session_id)
    collected: list[tuple[dict, bool, float, str]] = []

    for project in result.projects:
        if only_project and project.key != only_project:
            continue
        entries: list[tuple] = []
        for agent in project.agents:
            # 子 agent 是内部委派，默认不出现在面板上；聚合计数也只在保留集合上算，
            # 否则会出现「项目说 88 张、卡片只列 60 张」的自相矛盾。
            if agent.is_subagent and not include_subagents:
                continue
            observation = agent.observation_at(now, active_hours=active_hours)
            entries.append((agent, observation, needs_attention(agent, observation)))

        # 项目聚合基于保留集合（含被 --limit 截断的，--limit 只截数组）。
        # 每个字段都必须与同一次输出的 cards 数组自洽：
        # - attention 与卡片级 needs_attention 用**同一条谓词**，否则会出现
        #   「项目说 3 张要关注、卡片列出 8 张」；
        # - last_recorded / paths 曾经取自 project.last_active / project.paths（未过滤），
        #   于是默认视图出现「最大卡片时间是 19:17，项目却说 20:06」（20:06 来自子 agent）。
        attention = sum(1 for _a, _obs, flag in entries if flag)
        stale_busy = sum(1 for _a, obs, _n in entries if obs is CacheObservation.STALE_BUSY)
        missing = sum(1 for a, _obs, _n in entries if a.summary_status == "not_generated")
        recorded = [a.last_active for a, _o, _n in entries if a.last_active is not None]
        project_rows.append(
            {
                "key": project.key,
                "title": project.title,
                "paths": sorted({a.cwd for a, _o, _n in entries if a.cwd}),
                "cards": len(entries),
                "missing_summary": missing,
                "open_todos": sum(len(a.open_todos) for a, _o, _n in entries),
                "total_todos": sum(len(a.todos) for a, _o, _n in entries),
                "last_recorded": _iso(max(recorded)) if recorded else None,
                "attention": attention,
                "stale_busy": stale_busy,
            }
        )

        entries.sort(
            key=lambda item: (
                0 if item[2] else 1,
                -_recorded_key(item[0].last_active),
                item[0].session_id,
            )
        )
        shown = entries if limit <= 0 else entries[:limit]
        for agent, observation, attention_flag in shown:
            collected.append(
                (
                    _card(library, project.key, agent, observation, attention_flag),
                    attention_flag,
                    _recorded_key(agent.last_active),
                    f"{agent.source_instance}/{agent.session_id}",
                )
            )

    # 契约排序：needs_attention 优先，其次 recorded_at 降序（全局）；
    # 最后用身份键兜底，保证同一份数据每次输出顺序一致（便于插件 diff）。
    collected.sort(key=lambda item: (0 if item[1] else 1, -item[2], item[3]))
    card_rows = [item[0] for item in collected]

    project_rows.sort(
        key=lambda row: (
            0 if row["attention"] > 0 else 1,
            -(_parse_stamp(row["last_recorded"]) or float("-inf")),
            row["key"],
        )
    )
    return {
        "schemaVersion": UI_CARDS_SCHEMA_VERSION,
        "capabilities": list(CAPABILITIES),
        "generated_at": now.isoformat(),
        "library": str(library) if library is not None else None,
        "inbox": inbox,
        "instances": list(result.source_instances),
        "runtime_status": RUNTIME_UNKNOWN,
        "projects": project_rows,
        "cards": card_rows,
    }


def build_envelope(payload: dict, *, warnings: list[str] | None = None) -> dict:
    """把 ui-cards 载荷包成设计 §6 的统一 envelope（pm-api-v2）。

    只为新入口（pm api --envelope）服务；ui-cards 的既有形状一字不动，
    两者数据同源，所以不会出现两个视图互相矛盾。
    """
    return {
        "ok": True,
        "schemaVersion": API_SCHEMA_VERSION,
        "generatedAt": payload["generated_at"],
        "source": {
            "org": payload["library"],
            "dshInstances": list(payload["instances"]),
        },
        "data": {
            "schemaVersion": payload["schemaVersion"],
            "capabilities": list(payload["capabilities"]),
            "runtime_status": payload["runtime_status"],
            "projects": payload["projects"],
            "cards": payload["cards"],
            "inbox": payload["inbox"],
        },
        "warnings": list(warnings or []),
    }


def _parse_stamp(value: str | None) -> float | None:
    """把 last_recorded 的 ISO8601 字符串还原成时间戳；None/坏值返回 None。"""
    if not value:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value).timestamp()
    except ValueError:  # pragma: no cover - 只可能来自手改过的载荷
        return None
