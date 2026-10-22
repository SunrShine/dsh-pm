"""跨数据根加载：把多个 DSH 实例的工作区与会话拼成一个视图。

每个实例独立加载（各自的注册表、各自的 archivedSessionIds），
再合并。**不能**先合并注册表再判断归档 —— archivedSessionIds 是实例内的 id，
跨实例混用会误判。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pm.config import Instance
from pm.sources import dsh_projcache, dsh_workspace
from pm.sources.dsh_projcache import CacheLoad
from pm.sources.dsh_workspace import Workspace, WorkspaceRegistry


@dataclass
class LoadedSources:
    instances: tuple[Instance, ...] = ()
    registry: WorkspaceRegistry = field(default_factory=WorkspaceRegistry)
    cache: CacheLoad = field(default_factory=CacheLoad)
    warnings: list[str] = field(default_factory=list)

    @property
    def instance_ids(self) -> tuple[str, ...]:
        return tuple(instance.id for instance in self.instances)


def load_all(instances: tuple[Instance, ...]) -> LoadedSources:
    """逐个实例只读加载，然后合并。坏实例只记 warning，不阻塞其它实例。"""
    result = LoadedSources(instances=instances)
    workspaces: list[Workspace] = []
    archived: set[str] = set()
    agents = []
    versions: set[int] = set()
    scanned = 0
    skipped = 0

    for instance in instances:
        if not instance.exists:
            result.warnings.append(f"[{instance.id}] 数据根不存在，跳过: {instance.path}")
            continue
        registry = dsh_workspace.load(instance.path)
        for warning in registry.warnings:
            result.warnings.append(f"[{instance.id}] {warning}")
        workspaces.extend(registry.workspaces)
        archived.update(registry.archived_session_ids)

        cache = dsh_projcache.load(
            instance.projcache_dir,
            archived_ids=registry.archived_session_ids,
            title_for_path=registry.title_for_path,
            source_instance=instance.id,
        )
        for warning in cache.warnings:
            result.warnings.append(f"[{instance.id}] {warning}")
        agents.extend(cache.agents)
        versions.update(cache.versions)
        scanned += cache.scanned_files
        skipped += cache.skipped_files

    result.registry = WorkspaceRegistry(
        workspaces=tuple(workspaces), archived_session_ids=frozenset(archived)
    )
    result.cache = CacheLoad(
        agents=agents,
        warnings=[],
        scanned_files=scanned,
        skipped_files=skipped,
        versions=tuple(sorted(versions)),
    )
    return result
