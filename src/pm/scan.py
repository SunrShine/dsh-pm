"""扫描：把 DSH 的工作区 + 会话投影组装成项目视图。

这一层是**纯函数**：输入（注册表、会话、配置、now），输出 ScanResult。
不读文件、不写文件，便于用 fixture 做单元测试。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from pm.config import Config, normalize_path
from pm.model import OBSERVATION_ORDER, Agent, CacheObservation, Project
from pm.sources import dsh_projcache, dsh_workspace
from pm.sources.dsh_projcache import CacheLoad
from pm.sources.dsh_workspace import Workspace, WorkspaceRegistry


def slugify(value: str) -> str:
    """把标题/路径转成稳定的 ascii key（非 ascii 字符折叠为 -）。"""
    out: list[str] = []
    for ch in value.strip().lower():
        if ch.isascii() and ch.isalnum():
            out.append(ch)
        elif ch in "-_":
            out.append(ch)
        else:
            out.append("-")
    text = "".join(out)
    while "--" in text:
        text = text.replace("--", "-")
    return text.strip("-") or "unnamed"


@dataclass
class Suggestion:
    """「这个工作区看起来属于某个已合并项目」的提示，等人确认后写进 pm.toml。"""

    workspace_title: str
    workspace_path: str
    candidate_project: str
    reason: str


@dataclass
class ScanResult:
    generated_at: datetime
    config: Config
    projects: list[Project] = field(default_factory=list)
    unregistered: list[Agent] = field(default_factory=list)
    ignored: list[Agent] = field(default_factory=list)
    all_agents: list[Agent] = field(default_factory=list)
    registry: WorkspaceRegistry = field(default_factory=WorkspaceRegistry)
    hidden_agents: int = 0
    hidden_projects: int = 0
    hidden_by_limit: int = 0
    include_all: bool = False
    limit: int = 0
    source_instances: tuple[str, ...] = ()
    source_versions: tuple[int, ...] = ()
    cache_files_skipped: int = 0
    suggestions: list[Suggestion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def visible_agents(self) -> int:
        return sum(len(p.agents) for p in self.projects)

    @property
    def total_agents(self) -> int:
        return len(self.all_agents)


def group_agents(
    agents: Iterable[Agent],
    registry: WorkspaceRegistry,
    config: Config,
) -> tuple[dict[str, Project], list[Agent], list[Agent]]:
    """按「项目 key」归组 agent；返回 (项目表, 未登记, 已忽略)。"""
    merge_index = config.merge_index()
    alias_index = config.alias_index()
    workspace_by_path = {normalize_path(ws.path): ws for ws in registry.workspaces}
    excluded = {normalize_path(p) for p in config.exclude_paths}

    projects: dict[str, Project] = {}
    unregistered: list[Agent] = []
    ignored: list[Agent] = []

    for agent in agents:
        cwd = normalize_path(agent.cwd)
        if cwd in excluded:
            ignored.append(agent)
            continue
        key = ""
        title = ""
        rule = merge_index.get(cwd)
        if rule is not None:
            key, title = rule.key, rule.title
        elif cwd in alias_index:
            key = alias_index[cwd]
            title = key
        else:
            workspace = workspace_by_path.get(cwd)
            if workspace is None:
                unregistered.append(agent)
                continue
            key = slugify(workspace.title)
            title = workspace.title

        project = projects.get(key)
        if project is None:
            project = Project(key=key, title=title)
            projects[key] = project
        if cwd and cwd not in project.paths:
            project.paths.append(cwd)
        agent.workspace_title = workspace_by_path.get(cwd, Workspace("", cwd, title)).title
        project.agents.append(agent)

    for project in projects.values():
        project.paths.sort()
    return projects, unregistered, ignored


#: 目录名里过于通用、不能作为「同一项目」证据的词。
_STOP_TOKENS = frozenset(
    {"projects", "project", "tools", "tool", "dev", "src", "test", "tests", "repo", "git", "demo"}
)


def name_tokens(value: str) -> set[str]:
    """把目录名切成可比较的词元：demo → {pe, tree, 01}。"""
    parts = re.split(r"[^0-9a-zA-Z]+", value.lower())
    return {p for p in parts if len(p) >= 2 and p not in _STOP_TOKENS}


def suggest_merges(registry: WorkspaceRegistry, config: Config) -> list[Suggestion]:
    """启发式提示：与已合并项目路径**同父目录且目录名有共同词元**的工作区。

    只用「同父目录」会产生误报（$HOME/projects 下所有目录都互为兄弟），
    所以再加上词元交集检查：demo01 与 demo01 无交集 → 不提示。
    """
    merge_index = config.merge_index()
    merged_paths = set(merge_index)
    suggestions: list[Suggestion] = []
    for workspace in registry.workspaces:
        path = normalize_path(workspace.path)
        if path in merged_paths:
            continue
        tokens = name_tokens(Path(path).name)
        if not tokens:
            continue
        parent = str(Path(path).parent)
        for merged_path, rule in merge_index.items():
            if str(Path(merged_path).parent) != parent:
                continue
            shared = tokens & name_tokens(Path(merged_path).name)
            if not shared:
                continue
            suggestions.append(
                Suggestion(
                    workspace_title=workspace.title,
                    workspace_path=path,
                    candidate_project=rule.key,
                    reason=f"与 {merged_path} 同目录且共享词元 {sorted(shared)}",
                )
            )
            break
    return suggestions


def scan(
    *,
    config: Config,
    registry: WorkspaceRegistry,
    cache: CacheLoad,
    now: datetime,
    include_all: bool = False,
    only_project: str | None = None,
    limit: int = 8,
    source_instances: tuple[str, ...] = (),
) -> ScanResult:
    """组装最终视图（纯函数）。

    limit 是「噪声预算」的执行手段：每个项目默认最多显示 limit 行，
    多出来的在项目标题下折算成一行提示，而不是把终端刷满。
    """
    result = ScanResult(
        generated_at=now,
        config=config,
        registry=registry,
        include_all=include_all,
        limit=limit,
        source_instances=source_instances,
        source_versions=cache.versions,
        cache_files_skipped=cache.skipped_files,
    )
    result.warnings.extend(registry.warnings)
    result.warnings.extend(cache.warnings)

    pin_ids = {dsh_projcache.canonical_session_id(p) for p in config.pins}
    for agent in cache.agents:
        if dsh_projcache.canonical_session_id(agent.session_id) in pin_ids:
            agent.pinned = True

    result.all_agents = sorted(
        cache.agents,
        key=lambda a: (a.last_active is not None, a.last_active),
        reverse=True,
    )

    projects, unregistered, ignored = group_agents(cache.agents, registry, config)
    result.unregistered = unregistered
    result.ignored = ignored

    visible: list[Project] = []
    hidden_agents = 0
    hidden_projects = 0
    hidden_by_limit = 0
    for project in projects.values():
        if only_project and project.key != only_project:
            continue
        kept = [
            agent
            for agent in project.agents
            if include_all
            or agent.matches_noise_filter(
                now, active_days=config.active_days, active_hours=config.active_hours
            )
        ]
        hidden = len(project.agents) - len(kept)
        hidden_agents += hidden
        if not kept and not include_all:
            hidden_projects += 1
            continue
        kept.sort(key=_agent_sort_key(now, config))
        if limit > 0 and len(kept) > limit:
            project.hidden_agents = len(kept) - limit
            hidden_by_limit += project.hidden_agents
            kept = kept[:limit]
        project.agents = kept
        visible.append(project)

    if only_project:
        result.hidden_agents = 0
        result.hidden_projects = 0
    else:
        result.hidden_agents = hidden_agents
        result.hidden_projects = hidden_projects
    result.hidden_by_limit = hidden_by_limit

    visible.sort(key=_project_sort_key(now, config))
    result.projects = visible
    result.suggestions = suggest_merges(registry, config)
    return result


_OBSERVATION_RANK = {value: rank for rank, value in enumerate(OBSERVATION_ORDER)}


def _agent_sort_key(now: datetime, config: Config):
    def key(agent: Agent):
        observation = agent.observation_at(now, active_hours=config.active_hours)
        stamp = agent.last_active.timestamp() if agent.last_active else 0.0
        return (_OBSERVATION_RANK.get(observation, 9), -stamp)

    return key


def _project_sort_key(now: datetime, config: Config):
    def key(project: Project):
        stamp = project.last_active.timestamp() if project.last_active else 0.0
        return (-stamp, project.key)

    return key
