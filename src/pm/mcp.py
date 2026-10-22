"""pm 的 MCP server（stdio）。

DSH 侧通过 packages/mcp/mcp-client 连接，工具会注册成 mcp__<serverName>__<name>。
协议要点（读 SDK 2.0.0 源码实测，不是猜的）：
- 传输是**换行分隔的 JSON-RPC 2.0**：serializeMessage = JSON.stringify(msg) + "\n"，
  读侧按 "\n" 切分，没有 Content-Length 头。
- 协议版本 2026-07-28（SDK 2.0.0 主流），同时接受 2025-11-25 / 2024-11-05。
- **stdout 只能出现协议消息**，任何日志必须走 stderr。这里用把 sys.stdout 换成
  sys.stderr 的办法兜底，防止将来有人加了一句 print 就把协议流写坏。

工具设计原则：
- 读工具直接给结构化文本，不写文件。
- 写工具只有三种：写 AI 摘要、向人工文件**追加**条目、重新生成 generated/。
  它们都不改写已有内容（见 pm.humanwrite 与 pm.summaries）。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from pm import __version__, entities, sessions
from pm.config import Config, ConfigPathError, load as load_config
from pm.humanwrite import append_entry, entry_block, plan_entry, stamp
from pm.ids import new_inbox_id
from pm.instances import load_all
from pm.layout import Layout
from pm.library_view import attach_library_summaries
from pm.model import OBSERVATION_LABEL
from pm.render import plan as plan_mod
from pm.render.plan import resolve_summaries
from pm.scan import ScanResult, scan as run_scan
from pm.summaries import load_ai, load_human, upsert_ai_summary

#: capture 写入的 inbox 记录初始 revision（设计 §5.1 的 PM_REVISION: 1）。
CAPTURE_REVISION = 1
#: capture 产生的 inbox 记录初始状态（§5.1）。
CAPTURE_STATUS = "CAPTURED"

SERVER_NAME = "pm"
LATEST_PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_PROTOCOL_VERSIONS = ("2026-07-28", "2025-11-25", "2024-11-05")

INSTRUCTIONS = (
    "pm 是 work-memory（org 记忆库）的查询与写入接口。"
    "运行状态一律 unknown —— 读到的只是快照，快照里没有「此刻是否还在跑」的信号，所以不猜。"
    "DONE 只由人写，AI 说完成最多到 REVIEW。"
    "写摘要一律走 set_summary，它不会覆盖人工摘要。"
)


class ToolError(Exception):
    """工具执行失败，返回 isError 内容而不是断连。"""


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[["Service", dict[str, Any]], str]


# ---------------------------------------------------------------- 服务层


class Service:
    """MCP 工具共用的加载/写入逻辑。"""

    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = config_path
        self._config: Config | None = None

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config, _warnings = load_config(self.config_path)
        return self._config

    @property
    def library(self) -> Path:
        library = self.config.library
        if library is None or not Path(library).is_dir():
            raise ToolError(
                "配置里没有可用的 library（work-memory 库根）。"
                "请在 pm.toml 里设置 library = \"...\"。"
            )
        return Path(library)

    def layout(self) -> Layout:
        return Layout(self.library)

    def scan(
        self, *, include_all: bool = True, limit: int = 0, project: str | None = None
    ) -> ScanResult:
        now = datetime.now().astimezone()
        sources = load_all(self.config.effective_instances)
        result = run_scan(
            config=self.config,
            registry=sources.registry,
            cache=sources.cache,
            now=now,
            include_all=include_all,
            only_project=project,
            limit=limit,
            source_instances=sources.instance_ids,
        )
        attach_library_summaries(self.config, result)
        return result

    def project(self, key: str) -> Any:
        for item in self.scan(include_all=True, limit=0, project=key).projects:
            return item
        raise ToolError("找不到项目: " + key)

    def agent(self, session_id: str) -> Any:
        wanted = session_id if session_id.startswith("session-") else "session-" + session_id
        for project in self.scan(include_all=True, limit=0).projects:
            for agent in project.agents:
                if agent.session_id == wanted:
                    return agent, project
        raise ToolError("找不到工作卡: " + wanted)


# ---------------------------------------------------------------- 工具


def _fmt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


def tool_projects(svc: Service, args: dict[str, Any]) -> str:
    result = svc.scan()
    lines = ["key\t标题\t卡数\t缺摘要\t工作区\t最近记录"]
    for project in result.projects:
        missing = sum(1 for a in project.agents if a.summary_status == "not_generated")
        lines.append(
            "\t".join(
                [
                    project.key,
                    project.title,
                    str(len(project.agents)),
                    str(missing),
                    str(len(project.paths)),
                    _fmt(project.last_active),
                ]
            )
        )
    lines.append("")
    lines.append("数据根: " + ", ".join(result.source_instances))
    lines.append("运行状态一律 unknown：读到的只是快照，快照里没有「此刻是否还在跑」的信号。")
    return "\n".join(lines)


def tool_cards(svc: Service, args: dict[str, Any]) -> str:
    key = str(args.get("project") or "")
    if not key:
        raise ToolError("缺少参数 project")
    only_missing = bool(args.get("missing_summary"))
    limit = int(args.get("limit") or 30)
    project = svc.project(key)
    # 保持扫描顺序（先看观察值优先级、再按最近记录降序）——
    # 「现在什么情况」要的是最需要注意的在前，不是步数最多的在前。
    rows = [
        a
        for a in project.agents
        if not only_missing or a.summary_status == "not_generated"
    ]
    shown = rows[:limit] if limit > 0 else rows
    lines = [
        "项目 %s（%s）共 %d 张卡，本页 %d 张" % (project.title, project.key, len(project.agents), len(shown)),
        "session_id\t观察\t轮/步\t摘要来源\t摘要\t工作目录",
    ]
    for agent in shown:
        observation = agent.observation_at(datetime.now().astimezone())
        label = OBSERVATION_LABEL.get(observation, observation.value)
        lines.append(
            "\t".join(
                [
                    agent.session_id,
                    label,
                    "T%d/S%d" % (agent.turns, agent.steps),
                    agent.summary_status,
                    agent.summary_text if agent.summary_status != "not_generated" else "",
                    agent.cwd,
                ]
            )
        )
    if len(rows) > len(shown):
        lines.append("（还有 %d 张未显示，用更大的 limit）" % (len(rows) - len(shown)))
    return "\n".join(lines)


def tool_card(svc: Service, args: dict[str, Any]) -> str:
    session_id = str(args.get("session_id") or "")
    if not session_id:
        raise ToolError("缺少参数 session_id")
    agent, project = svc.agent(session_id)
    now = datetime.now().astimezone()
    observation = agent.observation_at(now)
    lines = [
        "工作卡 " + agent.session_id,
        "  身份键    " + agent.identity_key,
        "  项目      %s（%s）" % (project.title, project.key),
        "  工作目录  " + (agent.cwd or "-"),
        "  运行状态  unknown（未接入运行时接口）",
        "  缓存观察  %s · 记录于 %s" % (OBSERVATION_LABEL.get(observation, "?"), _fmt(agent.last_active)),
        "  轮/步     T%d/S%d" % (agent.turns, agent.steps),
        "  摘要      [%s] %s" % (agent.summary_status, agent.summary_text),
    ]
    if agent.goal:
        lines.append("  缓存 goal %s：%s" % (agent.goal.phase, agent.goal.objective))
    if agent.todos:
        lines.append("  缓存待办  %d/%d" % (agent.todo_counts[0], agent.todo_counts[1]))
        for todo in agent.todos[:20]:
            lines.append("            [%s] %s" % (todo.status, todo.content))
    return "\n".join(lines)


def tool_summary_queue(svc: Service, args: dict[str, Any]) -> str:
    project = args.get("project")
    result = svc.scan(project=str(project) if project else None)
    pending = [
        (p.key, a)
        for p in result.projects
        for a in p.agents
        if a.summary_status == "not_generated"
    ]
    if not pending:
        return "没有缺摘要的工作卡。"
    pending.sort(key=lambda pair: pair[1].steps, reverse=True)
    lines = ["缺摘要 %d 张（按步数降序）" % len(pending), "project\tsession_id\t轮/步\t工作目录"]
    for key, agent in pending:
        lines.append("%s\t%s\tT%d/S%d\t%s" % (key, agent.session_id, agent.turns, agent.steps, agent.cwd))
    lines.append("")
    lines.append("补摘要：用 session_log 取材料 → set_summary 写回。")
    lines.append("批量时反复调用本工具，写完的卡会自动从列表消失。")
    return "\n".join(lines)


def tool_session_log(svc: Service, args: dict[str, Any]) -> str:
    session_id = str(args.get("session_id") or "")
    if not session_id:
        raise ToolError("缺少参数 session_id")
    wanted = session_id if session_id.startswith("session-") else "session-" + session_id
    for instance in svc.config.effective_instances:
        log_path = sessions.find_log(instance, wanted)
        if log_path is None:
            continue
        try:
            text, _frames, _failed = sessions.decode(log_path)
        except sessions.LogError as exc:
            raise ToolError(str(exc)) from exc
        digest = sessions.build_digest(
            sessions.iter_events(text),
            session_id=wanted,
            instance=instance.id,
            path=str(log_path),
        )
        return sessions.render_digest(
            digest,
            prompts=int(args.get("prompts") or 12),
            prompt_chars=int(args.get("prompt_chars") or 160),
            deliverables=int(args.get("deliverables") or 15),
            show_prompts=bool(args.get("show_prompts", True)),
        )
    raise ToolError("找不到会话日志: " + wanted)


def tool_set_summary(svc: Service, args: dict[str, Any]) -> str:
    session_id = str(args.get("session_id") or "")
    text = str(args.get("text") or "").strip()
    if not session_id or not text:
        raise ToolError("需要 session_id 与 text")
    if len(text) > 200:
        raise ToolError("摘要过长（%d 字）；一句话结论即可，上限 200 字。" % len(text))
    agent, _project = svc.agent(session_id)
    library = svc.layout().root
    human = load_human(library)
    if agent.identity_key in human:
        return "已有人工摘要，按规则不覆盖：" + human[agent.identity_key].text
    upsert_ai_summary(
        library,
        identity_key=agent.identity_key,
        text=text,
        model=str(args.get("model") or ""),
    )
    return "已写入 " + agent.identity_key + "\n" + text


@dataclass(frozen=True)
class CaptureResult:
    """一次 capture 的结果（设计 §5：entityId / revision / source / observedAt / auditEventId）。"""

    path: Path
    found_section: bool
    line: int  # 追加块首行的 1-based 行号
    inbox_id: str
    revision: int
    audit_event_id: str = ""
    observed_at: str | None = None
    source: str = entities.SOURCE_ORG

    @property
    def entity_id(self) -> str:
        return self.inbox_id


@dataclass(frozen=True)
class CapturePlan:
    """一次 capture 的**预演**：文件/行号/块内容/将用的 ID 与审计事件（不落盘）。"""

    path: Path
    found_section: bool
    line: int  # 追加块首行的 1-based 行号
    block: str
    inbox_id: str
    revision: int
    audit_event_id: str = ""
    observed_at: str | None = None
    source: str = entities.SOURCE_ORG

    @property
    def entity_id(self) -> str:
        return self.inbox_id


def _capture_actor(actor: str | None, source: str) -> str:
    """审计行的 actor：CLI 敲的是人，MCP 是 AI；显式传入优先。"""
    if actor:
        return actor
    return "ai" if str(source).lower() == "mcp" else "human"


def _capture_parts(
    text: str,
    *,
    title: str | None,
    source: str,
    model: str,
    project_hint: str | None,
    captured: datetime,
) -> tuple[str, dict[str, str], list[str]]:
    """capture 的 headline / 属性 / 正文行（§5.1 + §11：原文只保存一份）。"""
    text_lines = text.split("\n")
    if title:
        headline_text = title
        body_lines = text_lines  # 显式标题：原文整段进正文
    else:
        headline_text = text_lines[0]
        body_lines = text_lines[1:]
    headline = "INBOX" + ((" " + headline_text) if headline_text else "")
    properties: dict[str, str] = {
        "PM_SOURCE": source,
        "PM_ADDED_BY": model or source,
        "PM_CAPTURED_AT": captured.isoformat(timespec="seconds"),
    }
    if project_hint:
        properties["PM_PROJECT_HINT"] = project_hint
    if title:
        properties["PM_TITLE"] = title
    return headline, properties, body_lines


def capture_block(
    text: str,
    *,
    title: str | None = None,
    source: str = "cli",
    model: str = "cli",
    project_hint: str | None = None,
    inbox_id: str | None = None,
    now: datetime | None = None,
    actor: str | None = None,
) -> str:
    """capture 的 org 块（写入与预演共用）。

    委托 entities.build_entity_block，所以与 create_entity 真写出来的块**同形**
    （含 :LOGBOOK: 里的创建审计）。设计 §5.1 的字段、§11 的「原文只存一份」都由它保证。
    """
    captured = now or datetime.now().astimezone()
    inbox_id = inbox_id or new_inbox_id(int(captured.timestamp() * 1000))
    headline, properties, body_lines = _capture_parts(
        text, title=title, source=source, model=model,
        project_hint=project_hint, captured=captured,
    )
    block, _audit_id = entities.build_entity_block(
        entity_id=inbox_id, kind="inbox", status=CAPTURE_STATUS, headline=headline,
        properties=properties, body_lines=body_lines, indent_body=True,
        actor=_capture_actor(actor, source), at=captured,
    )
    return block


def _new_capture_id(now: datetime | None) -> str:
    stamp_ms = int((now or datetime.now().astimezone()).timestamp() * 1000)
    return new_inbox_id(stamp_ms)


def capture_text(
    library_root: Path,
    text: str,
    *,
    title: str | None = None,
    source: str = "cli",
    model: str = "cli",
    project_hint: str | None = None,
    now: datetime | None = None,
    actor: str | None = None,
    idempotency_key: str | None = None,
) -> CaptureResult:
    """向库根的 inbox.org **追加**一条快速笔记（绝不改写已有内容）。

    MCP 工具 pm_capture 与 CLI 子命令 pm capture 共用这**同一条**实现；
    写入本身走 entities.create_entity（CAS/审计/幂等同一套），这里只表达 capture 的形态。
    """
    captured = now or datetime.now().astimezone()
    inbox_id = _new_capture_id(captured)
    path = Layout(library_root).inbox
    headline, properties, body_lines = _capture_parts(
        text, title=title, source=source, model=model,
        project_hint=project_hint, captured=captured,
    )
    created = entities.create_entity(
        path,
        entity_id=inbox_id,
        kind="inbox",
        status=CAPTURE_STATUS,
        headline=headline,
        section="Inbox",
        properties=properties,
        body_lines=body_lines,
        indent_body=True,
        actor=_capture_actor(actor, source),
        now=captured,
        idempotency_key=idempotency_key,
    )
    return CaptureResult(
        path=path,
        found_section=created.found_section,
        line=created.line,
        inbox_id=created.entity_id,
        revision=created.revision,
        audit_event_id=created.audit_event_id,
        observed_at=created.observed_at or captured.isoformat(timespec="seconds"),
    )

def plan_capture(
    library_root: Path,
    text: str,
    *,
    title: str | None = None,
    source: str = "cli",
    model: str = "cli",
    project_hint: str | None = None,
    now: datetime | None = None,
    actor: str | None = None,
) -> CapturePlan:
    """预演一次 capture：算出文件/行号/块内容/将用的 ID 与审计事件，**绝不写任何字节**。

    与 capture_text 共用 _capture_parts + entities.build_entity_block，
    所以 dry-run 显示的块/行号/ID 就是真写时会落下的那一份。
    """
    captured = now or datetime.now().astimezone()
    inbox_id = _new_capture_id(captured)
    path = Layout(library_root).inbox
    headline, properties, body_lines = _capture_parts(
        text, title=title, source=source, model=model,
        project_hint=project_hint, captured=captured,
    )
    block, audit_id = entities.build_entity_block(
        entity_id=inbox_id, kind="inbox", status=CAPTURE_STATUS, headline=headline,
        properties=properties, body_lines=body_lines, indent_body=True,
        actor=_capture_actor(actor, source), at=captured,
    )
    found, line = plan_entry(path, headline="Inbox", block=block)
    return CapturePlan(
        path=path, found_section=found, line=line, block=block,
        inbox_id=inbox_id, revision=CAPTURE_REVISION,
        audit_event_id=audit_id, observed_at=captured.isoformat(timespec="seconds"),
    )


def tool_capture(svc: Service, args: dict[str, Any]) -> str:
    text = str(args.get("text") or "").strip()
    if not text:
        raise ToolError("缺少参数 text")
    title = str(args.get("title") or "").strip() or None
    result = capture_text(
        svc.layout().root,
        text,
        title=title,
        source="mcp",
        model=str(args.get("model") or "mcp"),
    )
    note = "" if result.found_section else "（没找到 * Inbox 小节，已追加到文件末尾）"
    return (
        "已追加到 "
        + str(result.path)
        + note
        + "（"
        + result.inbox_id
        + "，rev "
        + str(result.revision)
        + "，audit "
        + result.audit_event_id
        + "）"
    )


def tool_pm_recall(svc: Service, args: dict[str, Any]) -> str:
    """只读：按 `pm recall` 的口径检索记忆（默认 L1/L2 + VERIFIED），返回可核对的 path:line。

    参数与 CLI 对齐（以 `pm recall --help` 为准）：query 必填；scope/type/limit 可选；
    include_candidate/include_deprecated 放宽口径。**不写任何人类文件**（索引是派生物，落 `.local/`）。
    """
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("需要 query（非空字符串；可为中文短语）")

    # 延迟 import：这是 P0 的模块，坏模块不该拖垮 MCP 启动
    from pm import index as index_module

    def _optional_text(name: str):
        value = args.get(name)
        text = str(value).strip() if value is not None else ""
        return text or None

    try:
        limit = int(args["limit"]) if args.get("limit") is not None else index_module.DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise ToolError("limit 必须是整数")
    if limit <= 0:
        limit = index_module.DEFAULT_LIMIT
    try:
        payload = index_module.recall(
            svc.library, query,
            scope=_optional_text("scope"), type=_optional_text("type"), limit=limit,
            include_candidate=bool(args.get("include_candidate")),
            include_deprecated=bool(args.get("include_deprecated")),
            any_mode=bool(args.get("any")),
        )
    except Exception as exc:  # IndexError_（QUERY_REQUIRED/INDEX_MISSING…）：明确报错，绝不静默空结果
        code = str(getattr(exc, "code", "RECALL_FAILED"))
        message = str(getattr(exc, "message", exc))
        raise ToolError("[" + code + "] " + message)
    hits = payload.get("hits") or []
    lines = [
        "命中 %d 条（%s%s，库 %s）" % (
            payload.get("count", len(hits)), payload.get("mode") or "?",
            "，降级" if payload.get("degraded") else "", svc.library,
        )
    ]
    if payload.get("note"):
        lines.append("注意：" + str(payload["note"]))
    for hit in hits:
        lines.append("%s:%s\t%s\t%s\t%s" % (
            hit.get("path"), hit.get("line"), hit.get("type"), hit.get("status"),
            str(hit.get("snippet") or hit.get("title") or "").replace("\n", " ")[:120],
        ))
    if not hits:
        lines.append("（0 命中；本次索引：" + ("新建" if payload.get("indexBuiltNow") else "未新建") + "）")
    return "\n".join(lines)


def tool_task_add(svc: Service, args: dict[str, Any]) -> str:
    key = str(args.get("project") or "")
    title = str(args.get("title") or "").strip()
    if not key or not title:
        raise ToolError("需要 project 与 title")
    project = svc.project(key)

    # D1：MCP 是 **AI 路径**，必须复用 tasks.py 的状态集/状态机，不能 str().upper() 就交出去。
    # 延迟 import：避免模块级循环依赖，也保证坏模块不会拖垮 MCP 启动。
    from pm import tasks as tasks_module

    try:
        todo = tasks_module.normalize_status(args.get("todo") or tasks_module.STATUS_TODO)
        tasks_module.validate_transition(tasks_module.STATUS_INBOX, todo, actor="ai")
    except Exception as exc:
        code = str(getattr(exc, "code", "INVALID_STATUS"))
        message = str(getattr(exc, "message", exc))
        raise ToolError("[" + code + "] " + message)
    if tasks_module.is_terminal(todo):
        raise ToolError(
            "AI 不能直接创建终态任务（" + todo + "）：DONE 只能由人写，CANCELLED 走人的取消命令；"
            "AI 提交请用 TODO / NEXT（或先建再走 REVIEW）。"
        )

    body = str(args.get("body") or "").strip()

    # **与 CLI `pm task create` 同一套属性铸造**（含 `:ID:`/`:PM_KIND:`/`:PM_STATUS:`/`:PM_PROJECT_ID:`）：
    # 以前这里自己拼 entry_block + append_entry，产出没有 :ID: 的条目 ⇒ CLI 无法寻址（transition/evidence 全做不到）。
    # 现在统一走 tasks.build_task + tasks.create_task（同为 AI 路径的写入口，也带创建审计）。
    try:
        task = tasks_module.build_task(
            title,
            project_id=tasks_module.project_key(key),   # 与 CLI create 一致：:PM_PROJECT_ID: 用裸 key（真库惯例）
            status=todo,
            ai=bool(args.get("ai")),
            assignee=str(args.get("assignee") or "unassigned"),
            goal=body or "（待补充：目标 / 边界 / 验收）",
            criteria=[str(item) for item in (args.get("criteria") or [])],
            extra_properties={
                "PM_SOURCE": "ai",
                "PM_ADDED_AT": stamp(),
                "PM_ADDED_BY": str(args.get("model") or "mcp"),
            },
        )
        line, audit_id, _preview = tasks_module.create_task(
            svc.layout().tasks_file(project.id), task, actor="ai"
        )
    except Exception as exc:  # 明确报错，绝不静默产出不可寻址条目
        code = str(getattr(exc, "code", "TASK_ADD_FAILED"))
        message = str(getattr(exc, "message", exc))
        raise ToolError("[" + code + "] " + message)
    return (
        "已创建任务 " + str(task["id"]) + "（" + todo + "）→ "
        + str(svc.layout().tasks_file(project.id)) + ":" + str(line)
        + "  audit=" + audit_id
    )


def tool_proposal_draft(svc: Service, args: dict[str, Any]) -> str:
    """生成一条 AI 计划提案（§5.3）。**只创建提案，绝不创建正式任务**。

    直接调 pm.proposals.create_proposal（模块函数），不经 CLI/shell；
    源 inbox 状态、变更 op / 验收标准等校验全部复用 proposals 模块，这里不另写一套。
    """
    from pm import proposals as proposals_module  # 延迟 import，避免循环依赖

    source = str(args.get("sourceInboxId") or "").strip()
    if not source:
        raise ToolError("需要 sourceInboxId（源 inbox 记录的 :ID:）")
    changes = args.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ToolError("需要 changes（至少一条 {op, title, criteria[]}）")
    risks = args.get("risks") if isinstance(args.get("risks"), list) else []
    actions = args.get("actions") if isinstance(args.get("actions"), list) else []
    layout = svc.layout()
    try:
        result = proposals_module.create_proposal(
            layout.root,
            source_inbox_id=source,
            changes=changes,
            risks=[str(item) for item in risks],
            actions=[str(item) for item in actions],
            title=(str(args.get("title") or "").strip() or None),
            project=(str(args.get("project") or "").strip() or None),
            created_by="ai",
            actor="ai",
            allow_duplicate=bool(args.get("allowDuplicate", False)),
        )
    except Exception as exc:
        code = str(getattr(exc, "code", "PROPOSAL_ERROR"))
        message = str(getattr(exc, "message", exc))
        raise ToolError("[" + code + "] " + message)
    try:
        relative = str(Path(result.path).relative_to(layout.root))
    except ValueError:  # pragma: no cover - 提案文件永远在库根下
        relative = str(result.path)
    return json.dumps(
        {
            "ok": True,
            "entityId": result.entity_id,
            "revision": result.revision,
            "source": result.source,
            "observedAt": result.observed_at,
            "auditEventId": result.audit_event_id,
            "status": result.status,
            "path": relative,
            # create 现在会顺带把源 inbox 标成 TASK_PROPOSED（两文件补偿式写）：
            # 这里如实给出第二步的结果与 written/notWritten，不让调用方以为只写了提案。
            "inbox": {
                "id": result.source_inbox_id,
                "status": result.inbox_status,
                "revision": result.inbox_revision,
            },
            "written": list((result.extra or {}).get("written") or []),
            "notWritten": list((result.extra or {}).get("notWritten") or []),
            "partial": bool(result.partial),
        },
        ensure_ascii=False,
    )


def tool_render(svc: Service, args: dict[str, Any]) -> str:
    layout = svc.layout()
    project = args.get("project")
    result = svc.scan(
        include_all=bool(args.get("include_all", True)),
        limit=0,
        project=str(project) if project else None,
    )
    resolved = resolve_summaries(result, load_human(layout.root), load_ai(layout.root))
    ops = plan_mod.build_plan(layout, result, resolved, now=result.generated_at)
    write = bool(args.get("write"))
    items = plan_mod.apply(ops, layout, write=write)
    counts: dict[str, int] = {}
    for item in items:
        counts[item.action] = counts.get(item.action, 0) + 1
    lines = ["模式 " + ("落盘" if write else "干跑"), "库 " + str(layout.root)]
    for action, number in sorted(counts.items()):
        lines.append("  %-10s %d" % (action, number))
    if not write and any(item.writes for item in items):
        lines.append("要真正落盘，加 write=true。")
    return "\n".join(lines)


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "projects",
        "列出 work-memory 里的项目：key、标题、卡数、缺摘要数、工作区数、最近记录时间。",
        {"type": "object", "properties": {}, "additionalProperties": False},
        tool_projects,
    ),
    ToolSpec(
        "cards",
        "列出某个项目的工作卡。missing_summary=true 只看缺摘要的；limit 控制条数（默认 30，0=不限）。",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "项目 key，见 projects"},
                "missing_summary": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
            "required": ["project"],
            "additionalProperties": False,
        },
        tool_cards,
    ),
    ToolSpec(
        "card",
        "看单张工作卡的详情：观察值、轮/步、摘要、缓存 goal 与 todos。",
        {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
            "additionalProperties": False,
        },
        tool_card,
    ),
    ToolSpec(
        "summary_queue",
        "列出缺摘要的工作卡。可带 project 限定；不传则全库。",
        {
            "type": "object",
            "properties": {"project": {"type": "string"}},
            "additionalProperties": False,
        },
        tool_summary_queue,
    ),
    ToolSpec(
        "session_log",
        "读某个会话的日志并提炼进展材料：用户请求、AI 待办快照、交付物（带路径）、最后输出。"
        "只在投影缓存里没有 goal/todos 时才需要——那些卡只能靠日志写摘要。",
        {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "prompts": {"type": "integer", "description": "显示几条用户请求（默认 12）"},
                "prompt_chars": {"type": "integer", "description": "每条截断字数（默认 160）"},
                "deliverables": {"type": "integer", "description": "显示几个交付物（默认 15）"},
                "show_prompts": {"type": "boolean"},
            },
            "required": ["session_id"],
            "additionalProperties": False,
        },
        tool_session_log,
    ),
    ToolSpec(
        "set_summary",
        "写入一条 AI 摘要（一句话，≤200 字）。已有人工摘要时拒绝覆盖并说明。",
        {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "text": {"type": "string"},
                "model": {"type": "string"},
            },
            "required": ["session_id", "text"],
            "additionalProperties": False,
        },
        tool_set_summary,
    ),
    ToolSpec(
        "capture",
        "把一句话追加进 inbox.org（人工文件，只追加不改写已有内容）。",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "title": {"type": "string"},
                "model": {"type": "string"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        tool_capture,
    ),
    ToolSpec(
        "pm_recall",
        "只读检索 work-memory 的记忆（默认 L1/L2 + status=VERIFIED；见 内部记录/11 §5-P1）："
        "返回命中片段与它可核对的 path:line。参数与 pm recall 对齐（query 必填；scope/type/limit 可选；"
        "include_candidate/include_deprecated 放宽口径；any 改为任一命中）。不写任何人类文件——索引是派生物，只落 .local/。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询词（可为中文短语）"},
                "scope": {"type": "string", "description": "只看某个 scope（项目 key 或 global）"},
                "type": {"type": "string", "description": "只看某类：fact / decision / gotcha"},
                "limit": {"type": "integer", "description": "最多返回几条（默认 10）"},
                "include_candidate": {"type": "boolean", "description": "把 CANDIDATE 也纳入（默认只 VERIFIED）"},
                "include_deprecated": {"type": "boolean", "description": "把 DEPRECATED 也纳入（默认排除）"},
                "any": {"type": "boolean", "description": "词间改为任一命中（默认 AND；多词 AND 零命中时会自动放宽并标 match=any）"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        tool_pm_recall,
    ),
    ToolSpec(
        "task_add",
        "往项目的 tasks.org 追加一个任务（只追加，AI 路径）。ai=true 表示这是要交给 AI 做的任务。"
        "状态受 §5.2 状态机约束：DONE 只能由人写、CANCELLED 由人的取消命令写，"
        "本工具只接受从 INBOX 出发的合法初始状态（TODO / NEXT）；非法状态会明确报错，不会静默降级。",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "title": {"type": "string"},
                "todo": {"type": "string", "description": "TODO / NEXT / DOING / BLOCKED（默认 TODO）"},
                "body": {"type": "string"},
                "criteria": {"type": "array", "items": {"type": "string"},
                             "description": "验收标准（可多条；建任务时就带稳定 ID，便于后续 evidence add）"},
                "ai": {"type": "boolean"},
                "assignee": {"type": "string"},
                "model": {"type": "string"},
            },
            "required": ["project", "title"],
            "additionalProperties": False,
        },
        tool_task_add,
    ),
    ToolSpec(
        "proposal_draft",
        "生成一条 AI 计划提案，写入 proposals.org（设计 §5.3）。"
        "**只创建提案，绝不创建正式任务** —— 未批准的内容不能进 tasks.org；"
        "批准/拒绝由人在 pm proposal approve / reject 完成。"
        "sourceInboxId 必须是已存在的 inbox :ID:；源 inbox 状态与变更 op / 验收标准的合法性"
        "全部复用 proposals 模块的校验；出错会给出与 CLI 一致的错误码。",
        {
            "type": "object",
            "properties": {
                "sourceInboxId": {"type": "string", "description": "源 inbox 记录的 :ID:"},
                "project": {
                    "type": "string",
                    "description": "人已确认的项目 key；不传则不写 :PM_PROJECT:（源记录的 hint 不会静默采用）",
                },
                "title": {"type": "string"},
                "changes": {
                    "type": "array",
                    "description": "至少一条变更：{op, title, criteria[]}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "description": "如 新增 / 修改 / 删除"},
                            "title": {"type": "string"},
                            "text": {"type": "string"},
                            "taskId": {"type": "string"},
                            "criteria": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["op"],
                        "additionalProperties": False,
                    },
                },
                "risks": {"type": "array", "items": {"type": "string"}},
                "actions": {"type": "array", "items": {"type": "string"}},
                "allowDuplicate": {
                    "type": "boolean",
                    "description": "同一条 inbox 已有 PENDING 提案时仍再建一条（默认拒绝 PROPOSAL_EXISTS_FOR_INBOX）",
                },
            },
            "required": ["sourceInboxId", "changes"],
            "additionalProperties": False,
        },
        tool_proposal_draft,
    ),
    ToolSpec(
        "render",
        "把 DSH 状态重新生成进库里的 generated/。默认干跑，write=true 才落盘。",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "include_all": {"type": "boolean"},
                "write": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        tool_render,
    ),
)


# ---------------------------------------------------------------- 协议


def _result(message_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": payload}


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _text(payload: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": payload}]}


def handle(message: dict[str, Any], service: Service) -> dict[str, Any] | None:
    """处理一条 JSON-RPC 消息。返回 None 表示这是通知，不需要回应。"""
    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}

    if message_id is None:
        return None  # 通知（例如 notifications/initialized）

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
        return _result(
            message_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _result(message_id, {})
    if method == "tools/list":
        return _result(
            message_id,
            {
                "tools": [
                    {"name": tool.name, "description": tool.description, "inputSchema": tool.input_schema}
                    for tool in TOOLS
                ]
            },
        )
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        spec = next((t for t in TOOLS if t.name == name), None)
        if spec is None:
            return _result(message_id, _text("未知工具: " + name))
        try:
            return _result(message_id, _text(spec.handler(service, arguments)))
        except ToolError as exc:
            return _result(message_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
        except Exception as exc:  # noqa: BLE001 - 任何异常都不该打断协议
            return _result(
                message_id,
                {"content": [{"type": "text", "text": "工具内部错误: %s: %s" % (type(exc).__name__, exc)}],
                 "isError": True},
            )
    if method in ("resources/list", "prompts/list"):
        key = "resources" if method.startswith("resources") else "prompts"
        return _result(message_id, {key: []})
    return _error(message_id, -32601, "Method not found: " + str(method))


def serve(config_path: str | None = None, stdin: Any = None, stdout: Any = None) -> int:
    """stdio 主循环。stdout 只写协议消息。"""
    import io

    real_stdout = stdout or sys.stdout
    source = stdin or sys.stdin
    service = Service(config_path)

    # **先加载配置再服务**（task-197）：显式 --config / PM_CONFIG / DSH_UI_PM_CONFIG 指向的
    # pm.toml 不存在或解析失败时直接失败退出，绝不"静默拿默认库（源码检出里 = 真库）对外服务"。
    try:
        service.config
    except ConfigPathError as exc:
        print(f"pm mcp: [{exc.code}] {exc}", file=sys.stderr)
        return exc.exit_code

    # 兜底：把任何意外的 print 重定向到 stderr，避免写坏协议流
    sys.stdout = sys.stderr
    try:
        for raw in source:
            line = raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            response = handle(message, service)
            if response is None:
                continue
            real_stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            real_stdout.flush()
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    finally:
        sys.stdout = real_stdout
    return 0
