"""领域模型：Project / Agent / Todo / Goal。

严格区分两类事实（对齐 上游设计 方案 §3、§8）：

1. **缓存观察（observation）**：DSH 投影缓存里记录了什么。有证据、有采样时间，
   但它证明不了「进程此刻在跑」——读到的只是快照，快照里没有「此刻是否还在跑」的信号。
2. **运行状态（runtime_status）**：进程当前状态。**只有受支持的运行时接口才能提供**。
   在接入之前一律返回 "unknown"，绝不从缓存推断「正在运行」。

因此本模块不再有 RUNNING/DONE 这类会误导人的状态：
- 缓存里有未完成 step → BUSY，但只作为**观察**展示，并附新鲜度。
- goal.phase = complete → CLOSED，不是 DONE。按方案 §4.2，AI 说完成只到 REVIEW，
  DONE 必须由人验收后才成立。

时间戳一律使用带时区的 datetime。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

#: DSH todo 投影里出现过的状态词表（实测：completed / in_progress / pending）。
OPEN_TODO_STATUSES = frozenset({"pending", "in_progress", "todo", "doing"})
CLOSED_TODO_STATUSES = frozenset({"completed", "complete", "cancelled", "canceled", "done"})

#: goal.phase 中视为「已结束」的值。注意：结束 ≠ 验收通过。
CLOSED_GOAL_PHASES = frozenset({"complete", "completed", "cancelled", "canceled", "done", "failed"})

#: 未接入运行时接口时，运行状态的唯一诚实取值。
RUNTIME_UNKNOWN = "unknown"

#: 工作卡摘要的来源标记。
SUMMARY_HUMAN = "human"                 # 人工撰写或修订
SUMMARY_NOT_GENERATED = "not_generated" # 尚未生成；DSH 的自动标题不算摘要


class CacheObservation(str, Enum):
    """**缓存观察值** —— 不是运行状态。

    命名刻意避开 RUNNING/DONE：这两个词会让人以为我们知道进程状态和验收结果。
    """

    BUSY = "BUSY"              # 缓存留有未完成 step，且最近仍有记录
    STALE_BUSY = "STALE_BUSY"  # 缓存留有未完成 step，但记录早已陈旧（可能中断）
    RECENT = "RECENT"          # 无未完成 step，最近仍有记录
    IDLE = "IDLE"              # 无未完成 step，且记录陈旧
    CLOSED = "CLOSED"          # goal 被标记结束且无未完成 todo —— 仍不等于验收通过
    ARCHIVED = "ARCHIVED"      # 用户已归档
    EMPTY = "EMPTY"            # 0 轮且无标题的空会话


#: 表格排序优先级（越靠前越需要人关注）。
OBSERVATION_ORDER: tuple[CacheObservation, ...] = (
    CacheObservation.STALE_BUSY,
    CacheObservation.BUSY,
    CacheObservation.RECENT,
    CacheObservation.IDLE,
    CacheObservation.CLOSED,
    CacheObservation.ARCHIVED,
    CacheObservation.EMPTY,
)

#: 默认视图完全不展示的观察值。
DEFAULT_HIDDEN_OBSERVATIONS: frozenset[CacheObservation] = frozenset(
    {CacheObservation.EMPTY, CacheObservation.ARCHIVED}
)

#: 观察值的中文标签，供界面使用。
OBSERVATION_LABEL: dict[CacheObservation, str] = {
    CacheObservation.BUSY: "忙碌",
    CacheObservation.STALE_BUSY: "陈旧·忙碌",
    CacheObservation.RECENT: "近有记录",
    CacheObservation.IDLE: "沉寂",
    CacheObservation.CLOSED: "已结束",
    CacheObservation.ARCHIVED: "已归档",
    CacheObservation.EMPTY: "空会话",
}


@dataclass(frozen=True)
class Todo:
    """DSH 会话内的 AI 自规划任务（来自 projcache 的 todos 投影）。"""

    content: str
    status: str

    @property
    def is_open(self) -> bool:
        return self.status not in CLOSED_TODO_STATUSES


@dataclass(frozen=True)
class Goal:
    """DSH 会话的 goal 投影。phase=complete 只说明目标被标记结束。"""

    id: str
    objective: str
    phase: str
    revision: int = 0
    rounds_started: int = 0

    @property
    def is_closed(self) -> bool:
        return self.phase in CLOSED_GOAL_PHASES

    @property
    def is_active(self) -> bool:
        return bool(self.phase) and not self.is_closed


@dataclass
class Agent:
    """一个 DSH 会话 = 一张 AI 工作卡。

    身份键是 (source_instance, session_id)：不同数据实例下同名 session id
    不能相互覆盖（方案 §3）。
    """

    session_id: str
    source_instance: str = "dsh-default"
    cwd: str = ""
    workspace_title: str = ""
    title: str = ""
    first_prompt: str = ""
    last_prompt: str = ""
    created_at: datetime | None = None
    last_active: datetime | None = None
    turns: int = 0
    steps: int = 0
    open_step: object | None = None
    pending_calls: int = 0
    todos: list[Todo] = field(default_factory=list)
    goal: Goal | None = None
    archived: bool = False
    pinned: bool = False
    #: 是否是主 agent 派发的**子 agent**（默认排除出面板；判定见 pm.subagents）。
    #: 子 agent 按设计不挂工作区，workspace.json 里找不到它们是正常的。
    #: **推导以投影事实为准**：`session_mode == "continuable"`（见下），缺失才回退日志探针。
    is_subagent: bool = False
    #: 投影事实 `record.rows.subagent.val.identity.mode`：`continuable`（被 spawn 的 subagent/队友）/
    #: `one-shot`（普通会话）/ `None`（投影里没有这个字段）。**不压成布尔**，保留原始取值。
    session_mode: str | None = None
    #: 投影事实 `…identity.label`：队友/子 agent 的人类可读名字；拿不到就是 `None`（不猜）。
    session_label: str | None = None
    #: 人工撰写/修订的一句话摘要（从 overrides.org 读回）。空 = 没有人工摘要。
    human_summary: str = ""
    #: 从库里解析出来的摘要（人工 > AI），以及它的来源标记。
    resolved_summary: str = ""
    resolved_summary_source: str = ""
    source: str = "projcache"
    warnings: list[str] = field(default_factory=list)
    raw_path: str = ""

    # ---- 身份 -----------------------------------------------------

    @property
    def identity_key(self) -> str:
        return f"{self.source_instance}/{self.session_id}"

    # ---- 事实与推断的边界 -----------------------------------------

    @property
    def runtime_status(self) -> str:
        """运行状态。读到的只是快照，快照里没有「此刻是否还在跑」的信号，故恒为 unknown。

        接入 DSH 受支持的运行时接口后，由 runtime adapter 覆盖此值；
        在那之前任何 RUNNING 字样都是编造。
        """
        return RUNTIME_UNKNOWN

    @property
    def cache_says_busy(self) -> bool:
        """缓存里是否留有未完成的步骤（**观察**，非运行状态）。"""
        return self.open_step is not None or self.pending_calls > 0

    # ---- 摘要 -----------------------------------------------------

    @property
    def summary_status(self) -> str:
        if self.resolved_summary_source:
            return self.resolved_summary_source
        return SUMMARY_HUMAN if self.human_summary.strip() else SUMMARY_NOT_GENERATED

    @property
    def card_label(self) -> str:
        """工作卡的**标识**，不是摘要。

        DSH 的自动标题常常是「You are working in the」这类无用串，
        所以它只能当标签用于辨认，不能冒充「一句话摘要」。
        """
        if self.human_summary.strip():
            return self.human_summary.strip()
        if self.title.strip():
            return self.title.strip()
        return self.session_id[:19]

    @property
    def summary_text(self) -> str:
        """展示用摘要；未生成时给出明确占位，而不是拿标题凑数。"""
        if self.human_summary.strip():
            return self.human_summary.strip()
        if self.resolved_summary.strip():
            return self.resolved_summary.strip()
        return "[待生成摘要]"

    # ---- 任务与进度 -----------------------------------------------

    @property
    def open_todos(self) -> list[Todo]:
        return [t for t in self.todos if t.is_open]

    @property
    def todo_counts(self) -> tuple[int, int]:
        """(已完成, 总数)。这是**缓存里的 todo 计数**，不是项目验收进度。"""
        done = sum(1 for t in self.todos if not t.is_open)
        return done, len(self.todos)

    @property
    def progress(self) -> str:
        done, total = self.todo_counts
        return f"{done}/{total}" if total else "-"

    @property
    def workload(self) -> str:
        return f"T{self.turns}/S{self.steps}"

    def recent_action(self) -> tuple[str, bool]:
        """最近记录的动作，返回 (文本, 是否来自对话正文)。

        只有 todo / goal 是结构化事实；退回到 prompt 时把第二项标 True，
        由界面决定是否展示（默认不展示，以免输出原始对话正文）。
        """
        for todo in self.todos:
            if todo.status == "in_progress":
                return todo.content, False
        for todo in self.todos:
            if todo.is_open:
                return todo.content, False
        if self.goal is not None and self.goal.objective:
            return self.goal.objective, False
        for source in (self.last_prompt, self.first_prompt):
            for line in source.splitlines():
                if line.strip():
                    return line.strip(), True
        return "", False

    # ---- 观察与新鲜度 ---------------------------------------------

    def observation_at(self, now: datetime, *, active_hours: int = 24) -> CacheObservation:
        if self.archived:
            return CacheObservation.ARCHIVED
        fresh = self.last_active is not None and (now - self.last_active) <= timedelta(hours=active_hours)
        if self.cache_says_busy:
            return CacheObservation.BUSY if fresh else CacheObservation.STALE_BUSY
        if self.turns == 0 and not self.title.strip():
            return CacheObservation.EMPTY
        if fresh:
            return CacheObservation.RECENT
        if self.goal is not None and self.goal.is_closed and not self.open_todos:
            return CacheObservation.CLOSED
        return CacheObservation.IDLE

    def observation_age(self, now: datetime) -> timedelta | None:
        return None if self.last_active is None else now - self.last_active

    def is_stale(self, now: datetime, *, active_hours: int = 24) -> bool:
        age = self.observation_age(now)
        return age is None or age > timedelta(hours=active_hours)

    def is_recent(self, now: datetime, days: int) -> bool:
        if self.last_active is None:
            return False
        return now - self.last_active <= timedelta(days=days)

    def matches_noise_filter(self, now: datetime, *, active_days: int, active_hours: int = 24) -> bool:
        """噪声预算：默认视图只保留仍然需要人看一眼的工作卡。"""
        if self.observation_at(now, active_hours=active_hours) in DEFAULT_HIDDEN_OBSERVATIONS:
            return False
        if self.pinned:
            return True
        if self.is_recent(now, active_days):
            return True
        if self.open_todos:
            return True
        if self.goal is not None and self.goal.is_active:
            return True
        return False


@dataclass
class Project:
    """一个项目：由一个或多个 DSH 工作区构成。

    project_id 一旦写入 org 的 :ID: 就是**权威身份**；路径只是可变关联，
    因此不用目录 basename 当主键（方案 §3）。
    """

    key: str
    title: str
    id: str = ""
    paths: list[str] = field(default_factory=list)
    agents: list[Agent] = field(default_factory=list)
    #: 因超出每项目行数上限而未展示的工作卡数
    hidden_agents: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"proj-{self.key}"

    @property
    def last_active(self) -> datetime | None:
        stamps = [a.last_active for a in self.agents if a.last_active is not None]
        return max(stamps) if stamps else None

    @property
    def open_todo_total(self) -> int:
        return sum(len(a.open_todos) for a in self.agents)

    @property
    def done_todo_total(self) -> int:
        return sum(a.todo_counts[0] for a in self.agents)

    @property
    def path_label(self) -> str:
        if not self.paths:
            return ""
        head = self.paths[0]
        extra = len(self.paths) - 1
        return head if extra <= 0 else f"{head} (+{extra})"
