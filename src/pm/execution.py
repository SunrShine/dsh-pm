"""执行准备向导的 CLI 侧：workspace / project context / execution-config / handoff。

契约：内部记录（未随仓库发布） §0 §1（Lead 冻结）。

**红线（§0）**：绝不实现假 dispatch。dispatchStatus 只有两个值：
  NOT_READY      还没有工作区 / 会话关联
  HANDOFF_READY  执行配置已保存，可以复制 handoff 文本交给 DSH
运行状态依旧恒 unknown —— 本模块不引入任何「运行中」语义。

落盘：tasks.org 任务块属性（绝不改任务状态），全部走 entities.apply_change
（CAS + 原子写 + 审计 + 幂等键）；冲突 exit 3、输入错误 exit 2。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from pm import entities
from pm.config import load as load_config, normalize_path
from pm.instances import load_all
from pm.layout import Layout
from pm.library_view import attach_library_summaries
from pm.scan import scan as run_scan
from pm.sources import dsh_workspace

#: §0：dispatchStatus 只允许这两个值。
DISPATCH_NOT_READY = "NOT_READY"
DISPATCH_HANDOFF_READY = "HANDOFF_READY"
DISPATCH_STATUSES = (DISPATCH_NOT_READY, DISPATCH_HANDOFF_READY)

#: §1：执行配置在任务块属性里的键（绝不改状态）。
PROP_PROJECT = "PM_EXEC_PROJECT"
PROP_WORKSPACE = "PM_EXEC_WORKSPACE"
PROP_INSTANCE = "PM_EXEC_INSTANCE"
PROP_SESSION = "PM_EXEC_SESSION"
PROP_MEMORY = "PM_EXEC_MEMORY"
PROP_NOTE = "PM_EXEC_NOTE"
PROP_SET_AT = "PM_EXEC_SET_AT"
PROP_SET_BY = "PM_EXEC_SET_BY"

_MEMORY_SEP = "|"

EXIT_CONFLICT = entities.EXIT_CONFLICT
EXIT_INPUT = entities.EXIT_INPUT


class ExecutionError(entities.EntityError):
    """执行配置命令的语义错误（复用 entities 的错误形状）。"""


# ---------------------------------------------------------------- 读取辅助


def _load(args: argparse.Namespace):
    """加载配置 + 数据源 + 扫描结果（含人工/AI 摘要）。"""
    config, _warnings = load_config(getattr(args, "config", None))
    dsh_home = getattr(args, "dsh_home", None)
    if dsh_home:
        config = replace(config, dsh_home=Path(dsh_home).expanduser(), instances=())
    sources = load_all(config.effective_instances)
    now = datetime.now().astimezone()
    result = run_scan(
        config=config,
        registry=sources.registry,
        cache=sources.cache,
        now=now,
        include_all=True,
        limit=0,
        source_instances=sources.instance_ids,
    )
    attach_library_summaries(config, result)
    return config, sources, result


def _library_root(config) -> Path:
    if config.library is None:
        raise ExecutionError("NO_LIBRARY", "未配置 work-memory 库（pm.toml 缺 library）")
    root = Path(config.library)
    if not root.is_dir():
        raise ExecutionError("LIBRARY_MISSING", f"work-memory 库目录不存在: {root}")
    return root


def _workspace_meta(config) -> tuple[dict, dict]:
    """扫描各实例的 workspace.json：path → title / path → instance id。"""
    titles: dict[str, str] = {}
    instances: dict[str, str] = {}
    for instance in config.effective_instances:
        if not instance.exists:
            continue
        registry = dsh_workspace.load(instance.path)
        for workspace in registry.workspaces:
            key = normalize_path(workspace.path)
            if not key:
                continue
            titles.setdefault(key, workspace.title)
            instances.setdefault(key, instance.id)
    return titles, instances


# ---------------------------------------------------------------- 读命令


def list_workspaces(config, sources, project_key: str) -> dict:
    """某个项目下的工作区清单（含每目录会话数）。"""
    project_key = str(project_key or "").strip()
    if not project_key:
        raise ExecutionError("INVALID_PROJECT", "需要项目 key")
    now = datetime.now().astimezone()
    result = run_scan(
        config=config,
        registry=sources.registry,
        cache=sources.cache,
        now=now,
        include_all=True,
        limit=0,
        source_instances=sources.instance_ids,
    )
    project = next((item for item in result.projects if item.key == project_key), None)
    known = sorted({item.key for item in result.projects} | {rule.key for rule in config.merges})
    if project is None:
        raise ExecutionError(
            "UNKNOWN_PROJECT",
            f"未知项目 key: {project_key}；可用: " + ", ".join(known),
        )
    rule_paths = {
        normalize_path(path)
        for rule in config.merges
        if rule.key == project_key
        for path in rule.paths
    }
    observed = {normalize_path(path) for path in project.paths if path}
    paths = sorted(rule_paths | observed)
    titles, instance_by_path = _workspace_meta(config)
    counts = Counter(normalize_path(agent.cwd) for agent in sources.cache.agents)
    agent_instance: dict[str, str] = {}
    for agent in sources.cache.agents:
        agent_instance.setdefault(normalize_path(agent.cwd), agent.source_instance)
    workspaces = [
        {
            "path": path,
            "title": titles.get(path) or Path(path).name,
            "instance": instance_by_path.get(path) or agent_instance.get(path),
            "sessionCount": counts.get(path, 0),
        }
        for path in paths
    ]
    return {"project": project_key, "workspaces": workspaces}


def _memory_rows(entries) -> list[dict]:
    return [
        {
            "id": entry.get("id"),
            "type": entry.get("type"),
            "scope": entry.get("scope"),
            "text": entry.get("text"),
            "status": entry.get("status"),
        }
        for entry in entries
    ]


def project_context(library_root: Path, project_key: str, *, include_global: bool = True) -> dict:
    """项目的上下文记忆：**只含 VERIFIED**（candidate / deprecated 一律不出现）。"""
    from pm import memory as memory_module  # 延迟 import：复用他们的解析与校验

    key = str(project_key or "").strip()
    if not key:
        raise ExecutionError("INVALID_PROJECT", "需要项目 key")
    pack = memory_module.context_pack(Path(library_root), key, include_global=include_global)
    return {"project": key, "memories": _memory_rows(pack["entries"])}


def workspace_context(
    config, sources, result, library_root: Path, path: str, *, include_global: bool = True
) -> dict:
    """某个工作区目录：所属项目 + 该项目记忆 + 该目录下的会话（观察值，不是运行状态）。"""
    target = normalize_path(path)
    if not target:
        raise ExecutionError("INVALID_WORKSPACE", "需要工作区路径")
    project_key = None
    for project in result.projects:
        if target in {normalize_path(item) for item in project.paths}:
            project_key = project.key
            break
    memories = (
        project_context(library_root, project_key, include_global=include_global)["memories"]
        if project_key
        else []
    )
    now = result.generated_at
    sessions = []
    for agent in result.all_agents:
        if normalize_path(agent.cwd) != target:
            continue
        observation = agent.observation_at(now, active_hours=config.active_hours)
        summary = agent.human_summary.strip() or agent.resolved_summary.strip()
        sessions.append(
            {
                "id": agent.session_id,
                "instance": agent.source_instance,
                "observation": observation.value,
                "summary": summary or None,
            }
        )
    sessions.sort(key=lambda row: (row["id"] or "", row["instance"] or ""))
    return {
        "path": target,
        "project": project_key,
        "memories": memories,
        "sessions": sessions,
    }


# ---------------------------------------------------------------- 任务定位


def _tasks_module():
    try:
        from pm import tasks as tasks_module
    except Exception as exc:  # pragma: no cover - 依赖缺失时给出明确错误
        raise ExecutionError("TASKS_UNAVAILABLE", f"pm.tasks 不可用: {exc}")
    return tasks_module


def find_task_file(layout: Layout, task_id: str) -> tuple[Path, dict]:
    """按 :ID: 在 projects/*/tasks.org 里找任务（身份只看 ID，不看行号）。"""
    tasks_module = _tasks_module()
    wanted = str(task_id or "").strip()
    if not wanted:
        raise ExecutionError("INVALID_TASK_ID", "需要任务 :ID:")
    for path in sorted(Path(layout.projects_dir).glob("*/tasks.org")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        task = tasks_module.find_task(tasks_module.parse_tasks(text), wanted)
        if task is not None:
            return path, task
    raise ExecutionError("TASK_NOT_FOUND", f"找不到 :ID: 为 {wanted} 的任务")


def _project_of(path: Path, task: dict) -> str | None:
    key = task.get("project_id")
    if key:
        return str(key)
    name = Path(path).parent.name
    if name.startswith("proj-"):
        return name[len("proj-") :]
    return None


def _dispatch_status(workspace: str | None, session: str | None) -> str:
    """§0 红线：只可能返回 NOT_READY / HANDOFF_READY。"""
    status = DISPATCH_HANDOFF_READY if (workspace and session) else DISPATCH_NOT_READY
    if status not in DISPATCH_STATUSES:  # pragma: no cover - 防御性
        raise ExecutionError("INVALID_DISPATCH_STATUS", f"不允许的 dispatchStatus: {status}")
    return status


def _exec_config(path: Path, task: dict) -> dict:
    props = task.get("properties") or {}
    workspace = props.get(PROP_WORKSPACE) or None
    session = props.get(PROP_SESSION) or None
    refs = [item for item in str(props.get(PROP_MEMORY) or "").split(_MEMORY_SEP) if item]
    dispatch = _dispatch_status(workspace, session)
    return {
        "taskId": task.get("id"),
        "revision": int(task.get("revision") or 1),
        "project": props.get(PROP_PROJECT) or _project_of(path, task),
        "workspace": workspace,
        "instance": props.get(PROP_INSTANCE) or None,
        "memoryRefs": refs,
        "session": session,
        "note": props.get(PROP_NOTE) or None,
        "setAt": props.get(PROP_SET_AT) or None,
        "setBy": props.get(PROP_SET_BY) or None,
        "dispatchStatus": dispatch,
    }


def read_execution_config(layout: Layout, task_id: str) -> dict:
    path, task = find_task_file(layout, task_id)
    return _exec_config(path, task)


def _merge_planned(current: dict, set_props: dict, clears: tuple, *, revision: int) -> dict:
    """dry-run / 真写都返回「变更之后」的配置（真写与文件一致，dry-run 是计划值）。"""
    planned = dict(current)
    mapping = {
        PROP_PROJECT: "project",
        PROP_WORKSPACE: "workspace",
        PROP_INSTANCE: "instance",
        PROP_SESSION: "session",
        PROP_NOTE: "note",
        PROP_SET_AT: "setAt",
        PROP_SET_BY: "setBy",
    }
    for key, field in mapping.items():
        if key in set_props:
            planned[field] = set_props[key] or None
        if key in clears:
            planned[field] = None
    if PROP_MEMORY in set_props:
        planned["memoryRefs"] = [x for x in str(set_props[PROP_MEMORY]).split(_MEMORY_SEP) if x]
    elif PROP_MEMORY in clears:
        planned["memoryRefs"] = []
    planned["dispatchStatus"] = _dispatch_status(planned.get("workspace"), planned.get("session"))
    planned["revision"] = revision
    return planned


def _validate_memory_refs(library_root: Path, refs: list[str]) -> list[str]:
    """memoryRefs 只接受 VERIFIED 的 memory :ID:（candidate / deprecated / 不存在都拒绝）。"""
    from pm import memory as memory_module

    cleaned = [str(ref).strip() for ref in refs if str(ref).strip()]
    if not cleaned:
        return []
    verified = {
        entry.id
        for entry in memory_module.parse_memory(Path(library_root))
        if entry.status == memory_module.STATUS_VERIFIED
    }
    invalid = [ref for ref in cleaned if ref not in verified]
    if invalid:
        raise ExecutionError(
            "INVALID_MEMORY_REF",
            "memoryRefs 只接受 VERIFIED 的记忆；以下不是 VERIFIED（candidate / deprecated / 不存在）："
            + ", ".join(invalid),
        )
    return cleaned


def _now(now: datetime | None) -> datetime:
    return now or datetime.now().astimezone()


def _write_result(result, config: dict, *, extra: dict | None = None) -> dict:
    payload = {
        "ok": True,
        "entityId": result.entity_id,
        "revision": result.revision,
        "source": result.source,
        "observedAt": result.observed_at,
        "auditEventId": result.audit_event_id,
        **config,
    }
    if result.idempotent:
        payload["idempotent"] = True
    if result.dry_run:
        payload["dry_run"] = True
    payload.update(extra or {})
    return payload


# ---------------------------------------------------------------- 写命令


def set_execution_config(
    layout: Layout,
    task_id: str,
    *,
    workspace: str,
    instance: str | None = None,
    project: str | None = None,
    memory_refs: list[str] | None = None,
    session: str | None = None,
    note: str = "",
    reason: str = "",
    actor: str = "ai",
    expected_revision: int,
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
    config=None,
) -> dict:
    """整体写入执行配置（**替换**语义：未给的可选字段会被清空），绝不改任务状态。

    `reason` 可选：给了就逐字进审计（HTTP 路由会转发它）；没给用一条默认说明。
    """
    workspace_path = normalize_path(str(workspace or "").strip())
    if not workspace_path:
        raise ExecutionError("INVALID_WORKSPACE", "execution-config set 需要 --workspace PATH")
    path, task = find_task_file(layout, task_id)
    library_root = Path(layout.root)
    refs = _validate_memory_refs(library_root, list(memory_refs or []))

    resolved_project = str(project or "").strip() or _project_of(path, task)
    resolved_instance = str(instance or "").strip() or None
    if resolved_instance is None:
        _, instance_by_path = _workspace_meta(config or load_config(None)[0])
        resolved_instance = instance_by_path.get(workspace_path)
    at = _now(now)
    actor_value = (str(actor or "ai").strip() or "ai")

    set_props = {
        PROP_PROJECT: resolved_project or "",
        PROP_WORKSPACE: workspace_path,
        PROP_SET_AT: at.isoformat(timespec="seconds"),
        PROP_SET_BY: actor_value,
    }
    clears: list[str] = []
    for name, value in ((PROP_INSTANCE, resolved_instance), (PROP_SESSION, session), (PROP_MEMORY, refs), (PROP_NOTE, note)):
        if value:
            set_props[name] = _MEMORY_SEP.join(value) if name == PROP_MEMORY else str(value)
        else:
            clears.append(name)

    result = entities.apply_change(
        path,
        task_id,
        expected_revision=expected_revision,
        set_properties=set_props,
        clear_properties=tuple(clears),
        actor=actor_value,
        reason=str(reason or "").strip() or f"execution-config set（workspace={workspace_path}）",
        idempotency_key=idempotency_key,
        dry_run=dry_run,
        now=at,
    )
    planned = _merge_planned(_exec_config(path, task), set_props, tuple(clears), revision=result.revision)
    return _write_result(result, planned)


def link_session(
    layout: Layout,
    task_id: str,
    *,
    session: str,
    instance: str | None = None,
    actor: str = "human",
    reason: str = "",
    expected_revision: int,
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
    config=None,
) -> dict:
    """只关联会话（不动工作区 / 记忆 / 说明）。"""
    session_id = str(session or "").strip()
    if not session_id:
        raise ExecutionError("INVALID_SESSION", "link-session 需要 --session SESSION_ID")
    path, task = find_task_file(layout, task_id)
    resolved_instance = str(instance or "").strip() or None
    if resolved_instance is None:
        sources = load_all((config or load_config(None)[0]).effective_instances)
        for agent in sources.cache.agents:
            if agent.session_id == session_id:
                resolved_instance = agent.source_instance
                break
    at = _now(now)
    set_props = {PROP_SESSION: session_id}
    if resolved_instance:
        set_props[PROP_INSTANCE] = resolved_instance
    result = entities.apply_change(
        path,
        task_id,
        expected_revision=expected_revision,
        set_properties=set_props,
        clear_properties=(),
        actor=actor,
        reason=reason or f"link-session（{session_id}）",
        idempotency_key=idempotency_key,
        dry_run=dry_run,
        now=at,
    )
    planned = _merge_planned(_exec_config(path, task), set_props, (), revision=result.revision)
    return _write_result(result, planned)


def unlink_session(
    layout: Layout,
    task_id: str,
    *,
    reason: str,
    actor: str = "human",
    expected_revision: int,
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
    config=None,
) -> dict:
    """解除会话关联；**必须给 reason**（审计要留下为什么）。"""
    if not str(reason or "").strip():
        raise ExecutionError("REASON_REQUIRED", "unlink-session 必须给 --reason（审计要留下为什么）")
    path, task = find_task_file(layout, task_id)
    at = _now(now)
    result = entities.apply_change(
        path,
        task_id,
        expected_revision=expected_revision,
        clear_properties=(PROP_SESSION,),
        actor=actor,
        reason=reason,
        idempotency_key=idempotency_key,
        dry_run=dry_run,
        now=at,
    )
    planned = _merge_planned(_exec_config(path, task), {}, (PROP_SESSION,), revision=result.revision)
    return _write_result(result, planned)


# ---------------------------------------------------------------- handoff（只读）


def handoff(layout: Layout, task_id: str, *, now: datetime | None = None) -> dict:
    """确定性渲染的 handoff：同一 revision 必然同样输出；不含对话正文。"""
    path, task = find_task_file(layout, task_id)
    config = _exec_config(path, task)
    text = render_handoff(task, config)
    return {**config, "title": task.get("title") or "", "handoff": text}


def render_handoff(task: dict, config: dict) -> str:
    """handoff 文本：只描述执行准备，绝不声称已派发 / 已启动。"""
    dispatch = config.get("dispatchStatus") or DISPATCH_NOT_READY
    if dispatch not in DISPATCH_STATUSES:  # pragma: no cover - 防御性
        dispatch = DISPATCH_NOT_READY
    lines = [
        "# 执行 handoff（由 pm 生成）",
        "",
        "任务：" + str(config.get("taskId") or ""),
    ]
    title = str(task.get("title") or "").strip()
    if title:
        lines.append("标题：" + title)
    lines.extend(
        [
            "项目：" + str(config.get("project") or "（未设置）"),
            "revision：" + str(config.get("revision") or 1),
            "工作区：" + str(config.get("workspace") or "（未设置）"),
            "实例：" + str(config.get("instance") or "（未设置）"),
            "会话：" + str(config.get("session") or "（未设置）"),
        ]
    )
    refs = config.get("memoryRefs") or []
    lines.append("上下文记忆：")
    if refs:
        lines.extend("  - " + str(ref) for ref in refs)
    else:
        lines.append("  （无）")
    lines.append("附加说明：" + str(config.get("note") or "（无）"))
    lines.extend(
        [
            "dispatchStatus：" + dispatch,
            "",
            "说明：pm 不派发、不启动任何执行；运行状态仍为 unknown。",
            "请把这段文本复制到目标 DSH 会话，由人确认后再执行。",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI


def _fail(json_mode: bool, error: "entities.EntityError") -> int:
    payload = {"ok": False, "error": {"code": error.code, "message": error.message}}
    payload.update(error.extra)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
    print(f"pm: [{error.code}] {error.message}", file=sys.stderr)
    return error.exit_code


def _read_layout(args) -> Layout:
    config, _warnings = load_config(getattr(args, "config", None))
    return Layout(_library_root(config))


def _write_layout(args, json_mode: bool) -> Layout:
    from pm.cli import resolve_write_target  # 延迟 import，避免循环

    layout, error = resolve_write_target(args, json_mode)
    if layout is None:
        raise ExecutionError(error[0], error[1], exit_code=error[2])
    return layout


def command_workspace_list(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        config, sources, _result = _load(args)
        payload = list_workspaces(config, sources, args.project)
    except entities.EntityError as exc:
        return _fail(json_mode, exc)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"项目 {payload['project']} 的工作区 {len(payload['workspaces'])} 个")
    for row in payload["workspaces"]:
        print(f"  {row['path']}  [{row['title']}]  instance={row['instance'] or '-'}  会话 {row['sessionCount']}")
    return 0


def command_project_context(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        layout = _read_layout(args)
        payload = project_context(
            layout.root, args.project, include_global=not getattr(args, "no_global", False)
        )
    except entities.EntityError as exc:
        return _fail(json_mode, exc)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"项目 {payload['project']} 的上下文记忆 {len(payload['memories'])} 条（只含 VERIFIED）")
    for row in payload["memories"]:
        print(f"  [{row['type']}/{row['scope']}] {row['id']}  {str(row['text']).splitlines()[0][:60]}")
    return 0


def command_workspace_context(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        config, sources, result = _load(args)
        payload = workspace_context(
            config, sources, result, _library_root(config), args.path,
            include_global=not getattr(args, "no_global", False),
        )
    except entities.EntityError as exc:
        return _fail(json_mode, exc)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"工作区 {payload['path']}（项目 {payload['project'] or '未登记'}）")
    print(f"  记忆 {len(payload['memories'])} 条（只含 VERIFIED），会话 {len(payload['sessions'])} 个")
    for row in payload["sessions"]:
        print(f"  {row['id']}  [{row['observation']}]  {row['instance']}  {row['summary'] or '（无摘要）'}")
    return 0


def command_exec_config_get(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        layout = _read_layout(args)
        payload = read_execution_config(layout, args.task_id)
    except entities.EntityError as exc:
        return _fail(json_mode, exc)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(payload["handoff"] if "handoff" in payload else _human_config(payload))
    return 0


def _human_config(payload: dict) -> str:
    lines = [
        f"任务 {payload['taskId']}（revision {payload['revision']}，dispatchStatus {payload['dispatchStatus']}）",
        f"  项目     {payload['project'] or '（未设置）'}",
        f"  工作区   {payload['workspace'] or '（未设置）'}",
        f"  实例     {payload['instance'] or '（未设置）'}",
        f"  会话     {payload['session'] or '（未设置）'}",
        f"  记忆     {', '.join(payload['memoryRefs']) or '（无）'}",
        f"  说明     {payload['note'] or '（无）'}",
        f"  设置于   {payload['setAt'] or '（未设置）'} / {payload['setBy'] or '（未设置）'}",
    ]
    return "\n".join(lines)


def command_exec_config_set(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        config, _warnings = load_config(getattr(args, "config", None))
        layout = _write_layout(args, json_mode)
        payload = set_execution_config(
            layout,
            args.task_id,
            config=config,
            workspace=args.workspace,
            instance=args.instance,
            project=args.project,
            memory_refs=args.memory,
            session=args.session,
            note=args.note or "",
            reason=getattr(args, "reason", "") or "",
            actor=args.actor,
            expected_revision=args.expected_revision,
            idempotency_key=args.idempotency_key,
            dry_run=args.dry_run,
        )
    except entities.EntityError as exc:
        return _fail(json_mode, exc)
    return _emit_write(json_mode, payload)


def command_link_session(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        config, _warnings = load_config(getattr(args, "config", None))
        layout = _write_layout(args, json_mode)
        payload = link_session(
            layout,
            args.task_id,
            config=config,
            session=args.session,
            instance=args.instance,
            actor=args.actor,
            reason=args.reason or "",
            expected_revision=args.expected_revision,
            idempotency_key=args.idempotency_key,
            dry_run=getattr(args, "dry_run", False),
        )
    except entities.EntityError as exc:
        return _fail(json_mode, exc)
    return _emit_write(json_mode, payload)


def command_unlink_session(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        layout = _write_layout(args, json_mode)
        payload = unlink_session(
            layout,
            args.task_id,
            reason=args.reason,
            actor=args.actor,
            expected_revision=args.expected_revision,
            idempotency_key=args.idempotency_key,
            dry_run=getattr(args, "dry_run", False),
        )
    except entities.EntityError as exc:
        return _fail(json_mode, exc)
    return _emit_write(json_mode, payload)


def _emit_write(json_mode: bool, payload: dict) -> int:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(_human_config(payload))
    return 0


def command_handoff(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        layout = _read_layout(args)
        payload = handoff(layout, args.task_id)
    except entities.EntityError as exc:
        return _fail(json_mode, exc)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload["handoff"])
    return 0


# ---------------------------------------------------------------- 注册


def _common(parser) -> None:
    from pm.cli import _add_common_options

    _add_common_options(parser, as_defaults=True)


def _write_flags(parser, *, actor_default: str = "ai") -> None:
    parser.add_argument("--actor", default=actor_default, choices=["human", "ai", "system"],
                        help="谁写的（写入审计；默认 " + actor_default + "）")
    parser.add_argument("--expected-revision", dest="expected_revision", type=int, required=True,
                        metavar="N", help="你看到的 :PM_REVISION:；不匹配 → exit 3，不写")
    parser.add_argument("--idempotency-key", dest="idempotency_key", default=None, metavar="KEY",
                        help="同一 key 重复提交不会产生第二次变更")
    parser.add_argument("--yes", action="store_true",
                        help="确认写默认配置指向的库；未显式 --config 且非 --dry-run 时必需")
    parser.add_argument("--json", action="store_true", help="stdout 只输出纯 JSON")


def register_cli(subparsers) -> None:
    """把 workspace / project / task 执行配置命令挂上去（由 pm.cli 调用）。"""
    import argparse as _argparse

    # ---- pm workspace list / context ----
    workspace = subparsers.add_parser("workspace", help="工作区（DSH workspace）：列表与上下文")
    workspace_sub = workspace.add_subparsers(dest="workspace_command")
    listing = workspace_sub.add_parser("list", help="列出某个项目的工作区")
    listing.add_argument("--project", required=True, metavar="KEY")
    listing.add_argument("--json", action="store_true")
    _common(listing)
    listing.set_defaults(handler=command_workspace_list)
    context = workspace_sub.add_parser("context", help="某个工作区目录的上下文（记忆 + 会话）")
    context.add_argument("path", metavar="PATH")
    context.add_argument("--no-global", dest="no_global", action="store_true",
                         help="只要本项目 scope 的记忆，不要 global")
    context.add_argument("--json", action="store_true")
    _common(context)
    context.set_defaults(handler=command_workspace_context)

    # ---- pm project context ----
    project = subparsers.add_parser("project", help="项目上下文（只含 VERIFIED 记忆）")
    project_sub = project.add_subparsers(dest="project_command")
    pcontext = project_sub.add_parser("context", help="项目的上下文记忆（只含 VERIFIED）")
    pcontext.add_argument("project", metavar="KEY")
    pcontext.add_argument("--no-global", dest="no_global", action="store_true",
                          help="只要本项目 scope 的记忆，不要 global")
    pcontext.add_argument("--json", action="store_true")
    _common(pcontext)
    pcontext.set_defaults(handler=command_project_context)

    # ---- pm project list / create（task-43：统一列表 + 按骨架新建目录）----
    from pm import projects as projects_module

    projects_module.register_cli(project_sub)

    # ---- pm task execution-config / link-session / unlink-session / handoff ----
    task_parser = getattr(subparsers, "choices", {}).get("task")
    if task_parser is None:
        print("pm: 未找到 task 子命令（pm.tasks 未注册），执行配置命令未挂载", file=sys.stderr)
        return
    task_sub = next(
        (action for action in task_parser._actions if isinstance(action, _argparse._SubParsersAction)),
        None,
    )
    if task_sub is None:  # pragma: no cover - 正常注册必有
        print("pm: task 子命令没有 subparsers，执行配置命令未挂载", file=sys.stderr)
        return

    exec_config = task_sub.add_parser("execution-config", help="AI 执行配置（get / set，绝不改任务状态）")
    exec_sub = exec_config.add_subparsers(dest="execution_config_command")
    ec_get = exec_sub.add_parser("get", help="读取任务的执行配置")
    ec_get.add_argument("task_id", metavar="TASK_ID")
    ec_get.add_argument("--json", action="store_true")
    _common(ec_get)
    ec_get.set_defaults(handler=command_exec_config_get)
    ec_set = exec_sub.add_parser("set", help="整体写入执行配置（替换语义，不改状态）")
    ec_set.add_argument("task_id", metavar="TASK_ID")
    ec_set.add_argument("--workspace", required=True, metavar="PATH")
    ec_set.add_argument("--instance", default=None, metavar="ID")
    ec_set.add_argument("--project", default=None, metavar="KEY")
    ec_set.add_argument("--memory", action="append", default=[], metavar="MEM_ID",
                        help="上下文记忆 :ID:（可重复；只接受 VERIFIED）")
    ec_set.add_argument("--session", default=None, metavar="SESSION_ID")
    ec_set.add_argument("--note", default="", metavar="TEXT")
    ec_set.add_argument("--reason", default="", metavar="R",
                        help="为什么这么设置；写入审计（HTTP 路由会转发 reason）")
    ec_set.add_argument("--dry-run", dest="dry_run", action="store_true", help="只预演，不落盘")
    _write_flags(ec_set)
    _common(ec_set)
    ec_set.set_defaults(handler=command_exec_config_set)

    link = task_sub.add_parser("link-session", help="给任务关联一个 DSH 会话")
    link.add_argument("task_id", metavar="TASK_ID")
    link.add_argument("--session", required=True, metavar="SESSION_ID")
    link.add_argument("--instance", default=None, metavar="ID")
    link.add_argument("--reason", default="", metavar="R")
    link.add_argument("--dry-run", dest="dry_run", action="store_true")
    _write_flags(link, actor_default="human")
    _common(link)
    link.set_defaults(handler=command_link_session)

    unlink = task_sub.add_parser("unlink-session", help="解除会话关联（必须给 reason）")
    unlink.add_argument("task_id", metavar="TASK_ID")
    unlink.add_argument("--reason", required=False, default="", metavar="R",
                        help="为什么解除（必填；缺失会以 REASON_REQUIRED 拒绝）")
    unlink.add_argument("--dry-run", dest="dry_run", action="store_true")
    _write_flags(unlink, actor_default="human")
    _common(unlink)
    unlink.set_defaults(handler=command_unlink_session)

    handoff_parser = task_sub.add_parser("handoff", help="只读：输出可复制 handoff 文本 + 结构化字段")
    handoff_parser.add_argument("task_id", metavar="TASK_ID")
    handoff_parser.add_argument("--json", action="store_true")
    _common(handoff_parser)
    handoff_parser.set_defaults(handler=command_handoff)
