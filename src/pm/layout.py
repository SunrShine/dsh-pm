"""work-memory 目录布局。

严格区分两类文件（对齐 alpha 方案 §10）：

  人工文件（机器只读或仅在缺失时创建）
    inbox.org
    overrides.org                     人工摘要 / pin 覆盖
    projects/<project-id>/project.org 目标、范围、验收
    projects/<project-id>/tasks.org   任务与状态
    projects/<project-id>/memory.org  该项目的事实与决策
    journal/YYYY-MM-DD.org            日记

  生成文件（机器整体所有，每次重写）
    generated/agents.org
    generated/projects.org
    generated/summary-queue.org
    generated/sessions/<instance>/<session-id>.org
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

HUMAN_FILES = ("README.org", "inbox.org", "overrides.org")
GENERATED_DIR = "generated"
LOCAL_DIR = ".local"

#: 设计 §5.4 的正式记忆类型（人确认后的三类）。
MEMORY_TYPES = ("facts", "decisions", "gotchas")

#: 库根下归机器整体所有的文件（其余根文件都归人）。
#: index.org 是看板，放根目录是为了好找，但它由 render 整体重写。
MACHINE_ROOT_FILES = ("index.org",)


@dataclass(frozen=True)
class Layout:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).expanduser())

    # ---- 人工文件 ----
    @property
    def readme(self) -> Path:
        return self.root / "README.org"

    @property
    def inbox(self) -> Path:
        return self.root / "inbox.org"

    @property
    def overrides(self) -> Path:
        return self.root / "overrides.org"

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    @property
    def journal_dir(self) -> Path:
        return self.root / "journal"

    @property
    def proposals_dir(self) -> Path:
        """目录 proposals/（历史布局，保留）。**§5.3 的提案用独立单文件**，见 proposals_file。"""
        return self.root / "proposals"

    @property
    def proposals_file(self) -> Path:
        """设计 §5.3 的提案真源：库根下**独立单文件** proposals.org。

        与 proposals_dir 的区别：那个是目录（历史布局，可能仍在别处使用），
        这个才是 §5.3 指定的 proposal 实体文件。
        """
        return self.root / "proposals.org"

    @property
    def memory_candidates(self) -> Path:
        """设计 §5.4：AI/系统提出的记忆候选（未确认），独立单文件。"""
        return self.root / "memory-candidates.org"

    @property
    def memory_dir(self) -> Path:
        """设计 §5.4：人确认后的正式记忆目录 memory/。"""
        return self.root / "memory"

    def memory_type_file(self, memory_type: str) -> Path:
        """memory/<facts|decisions|gotchas>.org（§5.4）。

        与 memory_file(project_id) 的区别：那个是**项目目录下**的 memory.org
        （projects/<id>/memory.org），这个是库根 memory/ 下按类型分的正式记忆文件。
        """
        name = str(memory_type).strip().lower()
        if name not in MEMORY_TYPES:
            raise ValueError(
                "未知记忆类型: " + str(memory_type) + "；可用: " + ", ".join(MEMORY_TYPES)
            )
        return self.memory_dir / f"{name}.org"

    @property
    def local_dir(self) -> Path:
        return self.root / LOCAL_DIR

    def project_dir(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def project_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.org"

    def tasks_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "tasks.org"

    def memory_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "memory.org"

    def journal_file(self, day: date) -> Path:
        return self.journal_dir / f"{day.isoformat()}.org"

    # ---- 生成文件 ----
    @property
    def index(self) -> Path:
        """库根看板：一个入口点进所有卡。"""
        return self.root / "index.org"

    @property
    def generated_dir(self) -> Path:
        return self.root / GENERATED_DIR

    @property
    def agents_index(self) -> Path:
        return self.generated_dir / "agents.org"

    @property
    def projects_index(self) -> Path:
        return self.generated_dir / "projects.org"

    @property
    def summary_queue(self) -> Path:
        return self.generated_dir / "summary-queue.org"

    @property
    def project_pages_dir(self) -> Path:
        return self.generated_dir / "projects"

    def project_page(self, key: str) -> Path:
        """每个项目一个页面文件 —— 避免所有项目挤在 index.org 里。"""
        return self.project_pages_dir / f"{key}.org"

    def instance_dir(self, source_instance: str) -> Path:
        return self.generated_dir / "sessions" / source_instance

    def session_card(self, source_instance: str, session_id: str) -> Path:
        return self.instance_dir(source_instance) / f"{session_id}.org"

    # ---- 目录集合 ----
    def directories(self) -> list[Path]:
        return [
            self.root,
            self.projects_dir,
            self.journal_dir,
            self.proposals_dir,
            self.generated_dir,
            self.local_dir,
        ]

    def is_generated(self, path: Path) -> bool:
        try:
            return self.generated_dir.resolve() in Path(path).resolve().parents
        except OSError:
            return False

    def is_machine_owned(self, path: Path) -> bool:
        """机器整体拥有的文件：generated/** 以及库根的 index.org。

        这些文件每次 render 都会被整体重写，手工修改会丢失。
        """
        candidate = Path(path)
        try:
            if candidate.parent.resolve() == self.root.resolve() and candidate.name in MACHINE_ROOT_FILES:
                return True
        except OSError:
            pass
        return self.is_generated(candidate)
