"""Memory 模型（backend-design §5.4）：候选 / 正式内容严格分离。

文件（共享契约，见 task-18）：
  work-memory/memory-candidates.org                     AI/系统提出的候选（CANDIDATE）
  work-memory/memory/{facts,decisions,gotchas}.org      人确认后的正式内容（VERIFIED）

硬约束（§5.4 + task-21）：
1. candidate 与 verified **不混存**：候选只在 memory-candidates.org，正式内容只在
   memory/*.org；AI 生成默认 CANDIDATE，不得直接进 VERIFIED。
2. 只有 actor=human 的 verify 才能把候选提升为 VERIFIED（见 require_human_actor）。
3. 冲突不得静默覆盖：要么 :PM_SUPERSEDES: 指向被取代条目并把旧的标 DEPRECATED，
   要么拒绝并说明冲突（见 detect_conflicts / follow_supersessions）。
4. 每条都能追溯 sources；没有来源的候选标 :PM_UNSOURCED: t（可见，不阻止）。
5. DEPRECATED 保留历史，不删除。

本模块提供：解析 / 序列化（无损往返）+ 纯逻辑（候选构造、冲突检测、上下文包组装）
+ 只读查询 + 写入入口（add_candidate / verify / deprecate）+ CLI 注册。

**写入一律复用 pm.entities 的 CAS / 原子写 / 审计 / 幂等**，这里不另造一套。

verify 跨两个文件（memory-candidates.org 与 memory/<type>.org），**不是原子事务，而是
补偿式顺序**：① 先写 memory/<type>.org 的 VERIFIED 副本（同 :ID:）→ ② 再原子改候选
文件（CAS + 状态 + 审计；状态的唯一真相在候选文件）→ ③ 需要 supersede 时最后把旧条目
标 DEPRECATED。中途失败会报出「已写什么、未写什么」，重跑靠同 ID 幂等对账收敛，绝不
对外声称「两文件原子」。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from pm import entities, ids
from pm.config import load as load_config
from pm.layout import Layout
from pm.org import clean_value, property_drawer, render_text

KIND = "memory"

STATUS_CANDIDATE = "CANDIDATE"
STATUS_VERIFIED = "VERIFIED"
STATUS_DEPRECATED = "DEPRECATED"
STATUSES = (STATUS_CANDIDATE, STATUS_VERIFIED, STATUS_DEPRECATED)

TYPE_FACT = "fact"
TYPE_DECISION = "decision"
TYPE_GOTCHA = "gotcha"
TYPES = (TYPE_FACT, TYPE_DECISION, TYPE_GOTCHA)

TYPE_SECTIONS = {
    TYPE_FACT: "Facts",
    TYPE_DECISION: "Decisions",
    TYPE_GOTCHA: "Gotchas",
}

SCOPE_GLOBAL = "global"

#: 记忆分层（内部记录/13 §2）：L1 条目一目一条、L2 一场景一文件、L3 一份常驻准则。
#: 候选区用 :PM_LAYER: 标明它最终属于哪一层；缺省按 L1（现有候选取值）。
#:
#: ★ 状态（2026-10-18，方案 A）：**预留能力** —— 界面不暴露、日常不启用，但**代码与口径保留**。
#:   L1 是默认层且**不写属性**（Org 逐字节不变，见下 to_properties）。别因为"界面上看不到"就当废码删除；
#:   也别顺手把 layer 接到 UI/注入里（那是行为变更）。边界与启用触发条件见 内部记录/13 顶部「当前状态」块。
LAYER_L1 = "L1"
LAYER_L2 = "L2"
LAYER_L3 = "L3"
LAYERS = (LAYER_L1, LAYER_L2, LAYER_L3)

CANDIDATES_RELATIVE = "memory-candidates.org"
CANDIDATES_TITLE = "Memory Candidates"
CANDIDATES_SECTION = "Memory Candidates"
CANDIDATES_NOTE = "# AI/系统提出的候选（CANDIDATE）；人确认后正文才进入 memory/<type>.org。"
MEMORY_DIRNAME = "memory"

HUMAN_ACTOR = "human"

#: 冲突用专用退出码（2 留给输入错误），与 inbox_ops 保持一致。
EXIT_INPUT = 2
EXIT_CONFLICT = 3

_HEADLINE = re.compile(r"^(?P<stars>\*+)(?:\s+(?P<title>.*))?$")
_SOURCE_SPLIT = re.compile(r"[,\s]+")


class MemoryError(Exception):
    """一次 memory 操作的明确失败；code 是机器可读的错误码。"""

    def __init__(self, code: str, message: str, *, exit_code: int = EXIT_INPUT, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.extra = dict(extra or {})


# ---------------------------------------------------------------- 路径
# 真源是 layout.py（§5.4）：Layout.memory_candidates / memory_dir / memory_type_file。

#: memory 域用单数类型名，layout 用复数文件名（facts/decisions/gotchas）。
TYPE_PLURALS = {
    TYPE_FACT: "facts",
    TYPE_DECISION: "decisions",
    TYPE_GOTCHA: "gotchas",
}


def candidates_path(library_root) -> Path:
    return Layout(Path(library_root)).memory_candidates


def memory_dir(library_root) -> Path:
    return Layout(Path(library_root)).memory_dir


def type_path(library_root, type: str) -> Path:
    return Layout(Path(library_root)).memory_type_file(TYPE_PLURALS[validate_type(type)])


# ---------------------------------------------------------------- 校验

def validate_type(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in TYPES:
        raise MemoryError("INVALID_TYPE", f"memory type 必须是 {', '.join(TYPES)} 之一，得到: {value!r}")
    return normalized


def validate_scope(value: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise MemoryError("INVALID_SCOPE", "scope 不能为空（项目 id 或 global）")
    if re.search(r"\s", normalized) or ":" in normalized:
        raise MemoryError("INVALID_SCOPE", f"scope 不能含空白或冒号: {value!r}")
    return normalized


def validate_sources(sources) -> tuple[str, ...]:
    """归一化来源引用：空格/逗号分隔的字符串或序列；单条内不得含空白或逗号。"""
    if sources is None:
        return ()
    if isinstance(sources, str):
        items: Sequence[str] = [item for item in _SOURCE_SPLIT.split(sources.strip()) if item]
    else:
        items = list(sources)
    result: list[str] = []
    for item in items:
        ref = str(item).strip()
        if not ref:
            continue
        if re.search(r"\s", ref) or "," in ref:
            raise MemoryError("INVALID_SOURCE", f"来源引用不能含空白或逗号: {item!r}")
        if ref not in result:
            result.append(ref)
    return tuple(result)


def clean_text(text: str) -> str:
    """创建时的文本归一化：统一换行、去掉每行行尾空白与首尾空行（保证往返无损）。"""
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _text_key(text: str) -> str:
    return " ".join(str(text).split()).casefold()


def require_human_actor(actor: str) -> str:
    """§5.4 硬约束：只有 actor=human 能 verify。AI/系统一律拒绝。"""
    normalized = (actor or "").strip()
    if normalized.casefold() != HUMAN_ACTOR:
        raise MemoryError(
            "AI_CANNOT_VERIFY",
            "只有 actor=human 的确认动作能把候选提升为 VERIFIED；AI/系统只能写 CANDIDATE（设计 §5.4）",
        )
    return HUMAN_ACTOR


# ---------------------------------------------------------------- 条目

@dataclass(frozen=True)
class MemoryEntry:
    """一条 memory 记录（候选与正式内容共用同一形状，以 status 区分）。"""

    id: str | None
    status: str = STATUS_CANDIDATE
    scope: str = SCOPE_GLOBAL
    type: str = TYPE_FACT
    #: 记忆分层（L1/L2/L3，内部记录/13 §2）。只解析**不求值**：不在这里做默认口径过滤。
    layer: str = LAYER_L1
    text: str = ""
    sources: tuple[str, ...] = ()
    revision: int = 1
    topic: str = ""
    task_id: str | None = None
    created_at: str | None = None
    created_by: str = ""
    verified_at: str | None = None
    verified_by: str | None = None
    deprecated_at: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    #: 展示用 1-based 行号；身份只看 :ID:（§9），不参与相等比较。
    line: int = field(default=0, compare=False)
    #: 没有 :ID: 的旧条目：可见但不参与按 ID 的操作。
    legacy: bool = field(default=False, compare=False)

    @property
    def entity_id(self) -> str:
        return self.id or ""

    @property
    def unsourced(self) -> bool:
        return not self.sources

    @property
    def title(self) -> str:
        return self.text.split("\n", 1)[0]

    @property
    def body_lines(self) -> list[str]:
        return self.text.split("\n")[1:]

    def to_properties(self) -> dict[str, str]:
        props: dict[str, str] = {
            "ID": self.id or "",
            "PM_KIND": KIND,
            "PM_STATUS": self.status,
            "PM_SCOPE": self.scope,
            "PM_TYPE": self.type,
            "PM_SOURCES": " ".join(self.sources),
        }
        # L1 是默认层：不写属性（保持既有 Org 逐字节不变）；L2/L3 必须显式标层。
        if self.layer and self.layer != LAYER_L1:
            props["PM_LAYER"] = self.layer
        if self.unsourced:
            props["PM_UNSOURCED"] = "t"
        if self.topic:
            props["PM_TOPIC"] = self.topic
        if self.task_id:
            props["PM_TASK_ID"] = self.task_id
        if self.created_at:
            props["PM_CREATED_AT"] = self.created_at
        if self.created_by:
            props["PM_CREATED_BY"] = self.created_by
        if self.verified_at:
            props["PM_VERIFIED_AT"] = self.verified_at
        if self.verified_by:
            props["PM_VERIFIED_BY"] = self.verified_by
        if self.deprecated_at:
            props["PM_DEPRECATED_AT"] = self.deprecated_at
        if self.supersedes:
            props["PM_SUPERSEDES"] = self.supersedes
        if self.superseded_by:
            props["PM_SUPERSEDED_BY"] = self.superseded_by
        props["PM_REVISION"] = str(self.revision)
        return props

    def to_dict(self, *, client: bool = True) -> dict:
        payload = {
            "id": self.id,
            "status": self.status,
            "scope": self.scope,
            "type": self.type,
            "text": self.text,
            "sources": list(self.sources),
            "unsourced": self.unsourced,
            "topic": self.topic,
            "taskId": self.task_id,
            "revision": self.revision,
            "createdAt": self.created_at,
            "createdBy": self.created_by,
            "verifiedAt": self.verified_at,
            "verifiedBy": self.verified_by,
            "deprecatedAt": self.deprecated_at,
            "supersedes": self.supersedes,
            "supersededBy": self.superseded_by,
            "legacy": self.legacy,
        }
        if not client:
            payload["line"] = self.line
            payload["layer"] = self.layer
        return payload


def new_memory_id(now_ms: int | None = None) -> str:
    """§5.4 的 memory 记录 ID：memory-<ULID>（与 inbox 共用同一 ULID 生成器）。"""
    return "memory-" + ids.new_ulid(now_ms)


def _validate_layer(value: str) -> str:
    layer = str(value or LAYER_L1).strip().upper() or LAYER_L1
    if layer not in LAYERS:
        raise MemoryError("BAD_LAYER", "layer 只能是 " + "/".join(LAYERS) + "，收到 " + repr(value))
    return layer


def build_candidate(
    text: str,
    *,
    scope: str,
    type: str,
    sources=(),
    created_by: str = "ai",
    task_id: str | None = None,
    topic: str = "",
    supersedes: str | None = None,
    now: datetime | None = None,
    entry_id: str | None = None,
    layer: str = LAYER_L1,
) -> MemoryEntry:
    """构造一条 CANDIDATE（纯函数，不落盘；CLI 的 add_candidate 走它）。"""
    body = clean_text(text)
    if not body:
        raise MemoryError("TEXT_REQUIRED", "memory 正文不能为空")
    at = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    return MemoryEntry(
        id=entry_id or new_memory_id(),
        status=STATUS_CANDIDATE,
        scope=validate_scope(scope),
        type=validate_type(type),
        text=body,
        sources=validate_sources(sources),
        revision=1,
        topic=clean_value(topic) if topic else "",
        task_id=(task_id or "").strip() or None,
        created_at=at,
        created_by=(created_by or "ai").strip() or "ai",
        supersedes=(supersedes or "").strip() or None,
        layer=_validate_layer(layer),
    )


# ---------------------------------------------------------------- 解析

def _property_line(raw: str) -> tuple[str, str] | None:
    stripped = raw.strip()
    if stripped in (":PROPERTIES:", ":END:", ":LOGBOOK:"):
        return None
    if not stripped.startswith(":") or ":" not in stripped[1:]:
        return None
    name, _, value = stripped[1:].partition(":")
    name = name.strip().upper()
    return (name, value.strip()) if name else None


def _int_prop(props: dict, key: str, default: int) -> int:
    raw = str(props.get(key, "") or "").strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_sources(raw: str) -> tuple[str, ...]:
    if not raw or not raw.strip():
        return ()
    return tuple(dict.fromkeys(part for part in _SOURCE_SPLIT.split(raw.strip()) if part))


def _read_drawers(lines: list[str], index: int, end: int) -> tuple[dict[str, str], int]:
    """读标题紧贴的属性抽屉（显式 :PROPERTIES: 或裸属性块），返回 (属性, 正文起始)。"""
    props: dict[str, str] = {}
    cursor = index
    if cursor < end and lines[cursor].strip() == ":PROPERTIES:":
        cursor += 1
        while cursor < end and lines[cursor].strip() != ":END:":
            parsed = _property_line(lines[cursor])
            if parsed is not None:
                props[parsed[0]] = parsed[1]
            cursor += 1
        if cursor < end:
            cursor += 1
    elif cursor < end and _property_line(lines[cursor]) is not None:
        while cursor < end:
            parsed = _property_line(lines[cursor])
            if parsed is None:
                break
            props[parsed[0]] = parsed[1]
            cursor += 1
        if cursor < end and lines[cursor].strip() == ":END:":
            cursor += 1
    return props, cursor


def _skip_logbook(lines: list[str], cursor: int, end: int) -> int:
    """审计抽屉整段跳过，绝不能混进正文（否则文本不再无损）。"""
    while cursor < end:
        if lines[cursor].strip() != ":LOGBOOK:":
            break
        cursor += 1
        while cursor < end and lines[cursor].strip() != ":END:":
            cursor += 1
        if cursor < end:
            cursor += 1
    return cursor


def _read_body(lines: list[str], cursor: int, end: int) -> tuple[list[str], int]:
    """正文：3 空格缩进的行（空行保持空串），遇到第 0 列 headline 或分隔空行结束。"""
    body: list[str] = []
    while cursor < end:
        line = lines[cursor]
        if not line.strip():
            probe = cursor + 1
            while probe < end and not lines[probe].strip():
                probe += 1
            if probe >= end or not lines[probe].startswith("   "):
                break
            body.append("")
            cursor += 1
            continue
        if not line.startswith("   "):
            break
        body.append(line[3:])
        cursor += 1
    return body, cursor


def _entry_from_props(props: dict, text_value: str, *, line: int = 0) -> MemoryEntry:
    entry_id = (props.get("ID") or "").strip() or None
    status = (props.get("PM_STATUS") or STATUS_CANDIDATE).strip() or STATUS_CANDIDATE
    scope = (props.get("PM_SCOPE") or SCOPE_GLOBAL).strip() or SCOPE_GLOBAL
    entry_type = (props.get("PM_TYPE") or TYPE_FACT).strip().lower() or TYPE_FACT
    # 缺省 L1；未知取值**原样保留**（不静默当 L1 —— 索引侧按 layer 白名单过滤，宁可漏不可错索引）
    layer = (props.get("PM_LAYER") or LAYER_L1).strip().upper() or LAYER_L1
    return MemoryEntry(
        id=entry_id,
        status=status,
        scope=scope,
        type=entry_type,
        layer=layer,
        text=text_value,
        sources=_parse_sources(props.get("PM_SOURCES", "")),
        revision=_int_prop(props, "PM_REVISION", 1),
        topic=(props.get("PM_TOPIC") or "").strip(),
        task_id=(props.get("PM_TASK_ID") or "").strip() or None,
        created_at=(props.get("PM_CREATED_AT") or "").strip() or None,
        created_by=(props.get("PM_CREATED_BY") or "").strip(),
        verified_at=(props.get("PM_VERIFIED_AT") or "").strip() or None,
        verified_by=(props.get("PM_VERIFIED_BY") or "").strip() or None,
        deprecated_at=(props.get("PM_DEPRECATED_AT") or "").strip() or None,
        supersedes=(props.get("PM_SUPERSEDES") or "").strip() or None,
        superseded_by=(props.get("PM_SUPERSEDED_BY") or "").strip() or None,
        line=line,
        legacy=entry_id is None,
    )


def parse_entries_text(text: str) -> list[MemoryEntry]:
    """把一份 memory org 文本解析成结构化条目（按文件顺序）。

    只认第 0 列的二级标题（** …）为条目；LOGBOOK 不进正文；无 :ID: 的条目
    标记 legacy=True（设计 §9：身份只看 :ID:，绝不按行号建立关联）。
    """
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if normalized.startswith("\ufeff"):
        normalized = normalized[1:]
    lines = normalized.split("\n")
    total = len(lines)
    entries: list[MemoryEntry] = []
    index = 0
    while index < total:
        match = _HEADLINE.match(lines[index])
        if match is None or len(match.group("stars")) != 2:
            index += 1
            continue
        title = match.group("title") or ""
        props, cursor = _read_drawers(lines, index + 1, total)
        cursor = _skip_logbook(lines, cursor, total)
        body, end = _read_body(lines, cursor, total)
        text_value = title + (("\n" + "\n".join(body)) if body else "")
        entries.append(_entry_from_props(props, text_value, line=index + 1))
        index = end if end > index + 1 else index + 1
    return entries


def _read_text(path: Path) -> str:
    path = Path(path)
    if not path.is_file():
        return ""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MemoryError("UNREADABLE", f"读不了 {path}: {exc}")
    return raw.decode("utf-8", "replace")


def parse_candidates(library_root) -> list[MemoryEntry]:
    """解析 memory-candidates.org（文件不存在 → 空列表，不抛错）。"""
    return parse_entries_text(_read_text(candidates_path(library_root)))


def parse_memory(library_root, *, type: str | None = None) -> list[MemoryEntry]:
    """解析 memory/{facts,decisions,gotchas}.org；type 给定时只看那一个文件。"""
    wanted = (validate_type(type),) if type else TYPES
    entries: list[MemoryEntry] = []
    for entry_type in wanted:
        entries.extend(parse_entries_text(_read_text(type_path(library_root, entry_type))))
    return entries


def list_candidates(library_root) -> dict:
    """CLI/MCP 用的 JSON 信封。"""
    entries = parse_candidates(library_root)
    return {
        "path": CANDIDATES_RELATIVE,
        "count": len(entries),
        "unsourcedCount": sum(1 for entry in entries if entry.unsourced),
        "entries": [entry.to_dict(client=False) for entry in entries],
    }


def list_memory(library_root, *, type: str | None = None) -> dict:
    entries = parse_memory(library_root, type=type)
    return {
        "path": MEMORY_DIRNAME,
        "count": len(entries),
        "entries": [entry.to_dict(client=False) for entry in entries],
    }


# ---------------------------------------------------------------- 序列化

def render_entry_lines(entry: MemoryEntry, *, level: int = 2) -> list[str]:
    """渲染一个条目：标题（正文首行原样）+ 属性抽屉 + 3 空格缩进正文。"""
    lines = [f"{'*' * level} {entry.title}"]
    lines.extend(property_drawer(entry.to_properties(), indent="   "))
    for body_line in entry.body_lines:
        lines.append(("   " + body_line) if body_line else "")
    return lines


def render_file_text(entries: Iterable[MemoryEntry], *, title: str, section: str, note: str | None = None) -> str:
    lines = [f"#+TITLE: {title}"]
    if note:
        lines.append(note)
    lines.append("")
    lines.append(f"* {section}")
    for entry in entries:
        lines.append("")
        lines.extend(render_entry_lines(entry))
    lines.append("")
    return render_text(lines)


def render_candidates_text(entries: Iterable[MemoryEntry]) -> str:
    return render_file_text(
        entries, title=CANDIDATES_TITLE, section=CANDIDATES_SECTION, note=CANDIDATES_NOTE
    )


def render_memory_text(type: str, entries: Iterable[MemoryEntry]) -> str:
    entry_type = validate_type(type)
    return render_file_text(
        entries, title=TYPE_SECTIONS[entry_type], section=TYPE_SECTIONS[entry_type]
    )


# ---------------------------------------------------------------- 冲突检测

@dataclass(frozen=True)
class Conflict:
    """与既有条目的冲突（不静默覆盖：要么 supersede，要么拒绝）。"""

    entry_id: str
    reason: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {"entryId": self.entry_id, "reason": self.reason, "detail": self.detail}


def _entry_id(entry) -> str:
    if isinstance(entry, MemoryEntry):
        return entry.id or ""
    return str(entry or "")


def detect_conflicts(prospective: MemoryEntry, existing: Iterable[MemoryEntry], *, explicit_ids=()) -> list[Conflict]:
    """同 scope+type 下判断候选是否与既有条目矛盾（显式规则，不用模糊语义）。

    规则：
      same-topic        同 scope+type 且 :PM_TOPIC: 相同但正文不同
      duplicate-text    同 scope+type 且归一化正文完全相同
      explicit          调用方显式声明的冲突 id
    DEPRECATED 条目只是历史，不参与冲突；自己（同 id）也不算。
    """
    if not isinstance(prospective, MemoryEntry):
        raise MemoryError("INVALID_ENTRY", "prospective 必须是 MemoryEntry")
    explicit = {str(item).strip() for item in (explicit_ids or ()) if str(item).strip()}
    seen: dict[str, Conflict] = {}
    for entry in existing:
        entry_id = _entry_id(entry)
        if entry_id and entry_id == prospective.id:
            continue
        if entry_id in explicit and entry_id not in seen:
            seen[entry_id] = Conflict(entry_id, "explicit", "调用方显式声明与既有条目冲突")
            continue
        if not isinstance(entry, MemoryEntry):
            continue
        if entry.status == STATUS_DEPRECATED:
            continue
        if entry.scope != prospective.scope or entry.type != prospective.type:
            continue
        if entry_id in seen:
            continue
        if prospective.topic and _text_key(entry.topic) == _text_key(prospective.topic):
            if _text_key(entry.text) != _text_key(prospective.text):
                seen[entry_id] = Conflict(entry_id, "same-topic", f"同 scope+type+topic 的既有条目内容不同: {entry.topic}")
            continue
        if _text_key(entry.text) == _text_key(prospective.text):
            seen[entry_id] = Conflict(entry_id, "duplicate-text", "同 scope+type 下已有相同内容")
    return list(seen.values())


def follow_supersessions(entries: Iterable[MemoryEntry], start_id: str) -> list[str]:
    """沿 :PM_SUPERSEDED_BY: 向后走，返回被取代链（不含起点）。用于校验链完整。"""
    by_id = {entry.id: entry for entry in entries if entry.id}
    chain: list[str] = []
    seen = {start_id}
    current = by_id.get(start_id)
    while current is not None and current.superseded_by:
        nxt = current.superseded_by
        if nxt in seen:
            break
        seen.add(nxt)
        chain.append(nxt)
        current = by_id.get(nxt)
    return chain


# ---------------------------------------------------------------- 上下文包

def context_pack(
    library_root,
    scope: str,
    *,
    task_id: str | None = None,
    include_global: bool = True,
    allow_cross_scope: bool = False,
    now: datetime | None = None,
) -> dict:
    """组装给 AI 用的上下文包（§P4-后端：按项目/任务）。

    只含 VERIFIED（candidates 一律不进）；DEPRECATED 只作为历史排除但计数可见。
    scope 命中：本 scope + global；task_id 给定时额外按 :PM_TASK_ID: 过滤。
    """
    wanted_scope = validate_scope(scope)
    wanted_task = (task_id or "").strip() or None
    verified_entries = parse_memory(library_root)
    candidates = parse_candidates(library_root)

    kept: list[MemoryEntry] = []
    excluded = {"candidate": 0, "deprecated": 0, "otherScope": 0, "otherTask": 0, "otherStatus": 0}
    for entry in verified_entries:
        if entry.status == STATUS_DEPRECATED:
            excluded["deprecated"] += 1
            continue
        if entry.status != STATUS_VERIFIED:
            excluded["otherStatus"] += 1
            continue
        in_scope = entry.scope == wanted_scope
        if not in_scope and include_global and wanted_scope != SCOPE_GLOBAL and entry.scope == SCOPE_GLOBAL:
            in_scope = True
        if not in_scope and allow_cross_scope and wanted_task and entry.task_id == wanted_task:
            in_scope = True
        if not in_scope:
            excluded["otherScope"] += 1
            continue
        if wanted_task and entry.task_id and entry.task_id != wanted_task:
            excluded["otherTask"] += 1
            continue
        kept.append(entry)

    excluded["candidate"] = sum(1 for entry in candidates if entry.status == STATUS_CANDIDATE)
    kept.sort(key=lambda item: (TYPES.index(item.type) if item.type in TYPES else len(TYPES), item.verified_at or item.created_at or "", item.id or ""))
    at = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    counts = {entry_type: sum(1 for entry in kept if entry.type == entry_type) for entry_type in TYPES}
    counts["total"] = len(kept)
    return {
        "scope": wanted_scope,
        "taskId": wanted_task,
        "generatedAt": at,
        "onlyVerified": True,
        "includeGlobal": bool(include_global),
        "allowCrossScope": bool(allow_cross_scope),
        "counts": counts,
        "excluded": excluded,
        "sources": sorted({ref for entry in kept for ref in entry.sources}),
        "entries": [entry.to_dict() for entry in kept],
    }


# ---------------------------------------------------------------- 写入（复用 pm.entities）
#
# verify 跨两个文件（memory-candidates.org + memory/<type>.org），**不是原子事务**，
# 而是补偿式顺序：
#   ① 先写 memory/<type>.org 的 VERIFIED 副本（同 :ID:，便于追溯）
#   ② 再原子改候选文件（CAS + :PM_STATUS: VERIFIED + LOGBOOK 审计）；状态的唯一真相在候选文件
#   ③ 需要 supersede 时最后把旧条目标 DEPRECATED（两侧链）
# 任一中间步骤失败都要如实报出「已写什么、未写什么」；重跑靠幂等对账收敛。


def _norm_key(key: str | None) -> str:
    return "".join(str(key).split()) if key else ""


def _entity_region(path, entity) -> str:
    lines = entities.read_text(Path(path)).split("\n")
    return "\n".join(lines[entity.start:entity.end])


#: 审计行里的状态迁移：- State "<to>" from "<from>" [...]
_STATE_RE = re.compile(r'State "([^"]*)" from "([^"]*)"')

#: 带 key= 的审计行分别属于哪个操作（一个 key 只能对应一次逻辑写入）。
_OP_CREATE = "create"
_OP_VERIFY = "verify"
_OP_DEPRECATE = "deprecate"
_OP_DISCARD = "discard"


def _key_operations(region: str, key: str) -> set[str]:
    """该实体里，带 key= 的审计行分属哪些操作：create / verify / deprecate / other。

    用于挡住「拿着别的操作的 key 来写」——统一幂等只看 key，会把这种情况误判成重放，
    于是命令退 0 却什么都没做（假的成功），或先写了副本再停住（半写）。
    """
    pattern = re.compile(r"(?<!\S)key=" + re.escape(key) + r"(?=\s|$)")
    operations: set[str] = set()
    for line in region.splitlines():
        if not pattern.search(line):
            continue
        match = _STATE_RE.search(line)
        if match is None:
            operations.add("other")
            continue
        to_state, from_state = match.group(1), match.group(2)
        if from_state == "(created)":
            operations.add(_OP_CREATE)
        elif to_state == STATUS_VERIFIED and from_state == STATUS_CANDIDATE:
            operations.add(_OP_VERIFY)
        elif to_state == STATUS_DEPRECATED:
            operations.add(_OP_DEPRECATE)
        else:
            operations.add("other")
    return operations


def _foreign_key_operations(path, entity_id: str, key: str, own: str) -> set[str]:
    """key 是否已经属于**别的**操作（不是 own）——是则不能拿它做 own。"""
    try:
        entity = entities.load_entity(Path(path), entity_id)
    except entities.EntityError:
        return set()
    return _key_operations(_entity_region(path, entity), key) - {own}


def _replay_in_file(path, key: str):
    """这个 key 是否已经在这个文件里由 apply_change 落地过（读侧对账）。

    只看 :LOGBOOK: 里的 key=，且**排除创建审计行**（from "(created)"）——
    创建 key 属于 create_entity，不能被 verify 误判成「verify 已重放」。
    """
    p = Path(path)
    if not key or not p.is_file():
        return None
    lines = entities.read_text(p).split("\n")
    pattern = re.compile(r"(?<!\S)key=" + re.escape(key) + r"(?=\s|$)")
    for entity in entities.iter_entities(p):
        region = "\n".join(lines[entity.start:entity.end])
        hits = [
            line
            for line in region.splitlines()
            if pattern.search(line) and 'from "(created)"' not in line
        ]
        if not hits:
            continue
        audit_id, observed = entities.audit_from_region("\n".join(hits))
        if audit_id is None:
            audit_id, observed = entities.audit_from_region(region)
        return entities.OpResult(
            path=p,
            entity_id=entity.entity_id,
            status=entity.status,
            revision=entity.revision,
            previous_status=entity.status,
            previous_revision=entity.revision,
            changed=False,
            idempotent=True,
            observed_at=observed,
            audit_event_id=audit_id,
            extra={
                "type": entity.props.get("PM_TYPE", ""),
                "scope": entity.props.get("PM_SCOPE", ""),
                "idempotentReplay": True,
            },
        )
    return None


def _find_entity(path, entity_id: str):
    p = Path(path)
    if not entity_id or not p.is_file():
        return None
    try:
        return entities.load_entity(p, entity_id)
    except entities.EntityError:
        return None


def _entry_from_entity(entity) -> MemoryEntry:
    """从 entities.Entity 还原一条 MemoryEntry（解析器没识别出的少数写法兜底）。"""
    match = _HEADLINE.match(entity.headline or "")
    title = (match.group("title") or "") if match else ""
    body = list(entity.body)
    while body and not body[-1].strip():
        body.pop()
    text_value = title + (("\n" + "\n".join(body)) if body else "")
    return replace(
        _entry_from_props(entity.props, text_value, line=entity.line),
        status=entity.status,
        revision=entity.revision,
    )


def _locate_entry(root: Path, memory_id: str):
    """按 :ID: 在 memory/*.org（正式）与 memory-candidates.org 里找条目；正式优先。"""
    for entry_type in TYPES:
        path = type_path(root, entry_type)
        for entry in parse_memory(root, type=entry_type):
            if entry.id == memory_id:
                return entry, path
    for entry in parse_candidates(root):
        if entry.id == memory_id:
            return entry, candidates_path(root)
    return None


def _relative(root: Path, path) -> str:
    try:
        return str(Path(path).relative_to(Path(root)))
    except ValueError:
        return str(path)


def _not_found(root: Path, memory_id: str) -> entities.EntityError:
    for path in [candidates_path(root)] + [type_path(root, t) for t in TYPES]:
        if not Path(path).is_file():
            continue
        try:
            entities.load_entity(Path(path), memory_id)
        except entities.EntityError as exc:
            if exc.code == "LEGACY_UNTRACKED":
                return exc
    return entities.EntityError(
        "NOT_FOUND",
        f"找不到 :ID: 为 {memory_id} 的 memory 条目（memory-candidates.org 与 memory/*.org 都查过）",
    )


def _verified_properties(entry: MemoryEntry, at_iso: str, *, revision: int | None = None) -> dict[str, str]:
    """正式副本的属性。revision 给了就写 :PM_REVISION:（与候选的 verify 后 revision 对齐）。"""
    props = {"PM_SCOPE": entry.scope, "PM_TYPE": entry.type, "PM_SOURCES": " ".join(entry.sources)}
    if entry.unsourced:
        props["PM_UNSOURCED"] = "t"
    if entry.topic:
        props["PM_TOPIC"] = entry.topic
    if entry.task_id:
        props["PM_TASK_ID"] = entry.task_id
    if entry.created_at:
        props["PM_CREATED_AT"] = entry.created_at
    if entry.created_by:
        props["PM_CREATED_BY"] = entry.created_by
    props["PM_VERIFIED_AT"] = at_iso
    props["PM_VERIFIED_BY"] = HUMAN_ACTOR
    if entry.supersedes:
        props["PM_SUPERSEDES"] = entry.supersedes
    if revision is not None:
        # 与候选 verify 后的 revision 对齐（create_entity 尊重该值，一次写成）。
        props["PM_REVISION"] = str(revision)
    return props


def add_candidate(
    library_root,
    *,
    text: str,
    scope: str,
    type: str,
    sources=(),
    created_by: str = "ai",
    task_id: str | None = None,
    topic: str = "",
    supersedes: str | None = None,
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
    entry_id: str | None = None,
    layer: str = LAYER_L1,
) -> entities.OpResult:
    """追加一条 CANDIDATE 到 memory-candidates.org（AI/系统默认入口，不进 VERIFIED）。"""
    entry = build_candidate(
        text, scope=scope, type=type, sources=sources, created_by=created_by,
        task_id=task_id, topic=topic, supersedes=supersedes, now=now, entry_id=entry_id,
        layer=layer,
    )
    root = Path(library_root)
    path = candidates_path(root)
    at = now or datetime.now().astimezone()
    key = _norm_key(idempotency_key)
    extra = {
        "memoryId": entry.id,
        "type": entry.type,
        "scope": entry.scope,
        "unsourced": entry.unsourced,
        "pathRelative": CANDIDATES_RELATIVE,
        "candidate": True,
    }
    props = {
        name: value
        for name, value in entry.to_properties().items()
        if name not in ("ID", "PM_KIND", "PM_STATUS", "PM_REVISION")
    }
    # 幂等走 entities.create_entity 的统一机制（key 写进创建审计行；同一 key + 同一 entity_id 才重放）。
    # 语义：**一个 key = 一次逻辑新增** —— 同 key 重试（即使 --text 不同）也返回首次结果，
    # 不产生第二条候选。适配原因：重试时新生成的 ULID 必然与首次不同，若不先取回首次 ID，
    # create_entity 会判成「换目标复用 key」而抛 IDEMPOTENCY_KEY_REUSED；
    # 故先用只读 find_idempotent_block 找回首次 ID，再交给 create_entity 走它自己的重放分支。
    entity_id = entry.id
    if key:
        holder = entities.find_idempotent_block(path, key)
        if holder is not None and holder["props"].get("ID"):
            entity_id = holder["props"]["ID"]
    # dry_run 只预演不落盘。
    created = entities.create_entity(
        path, entity_id=entity_id, kind=KIND, status=STATUS_CANDIDATE, headline=entry.title,
        section=CANDIDATES_SECTION, properties=props, body_lines=entry.body_lines,
        actor=entry.created_by, now=at, dry_run=dry_run, idempotency_key=idempotency_key,
    )
    extra["line"] = created.line
    if not created.created:
        # 同一 key 重放：不重复创建，返回首次的 line/auditEventId/observedAt。
        current = _find_entity(path, created.entity_id)
        status = current.status if current is not None else STATUS_CANDIDATE
        revision = current.revision if current is not None else 1
        extra["idempotentReplay"] = True
        return entities.OpResult(
            path=created.path, entity_id=created.entity_id, status=status, revision=revision,
            previous_status=status, previous_revision=revision, changed=False,
            idempotent=True, dry_run=dry_run, observed_at=created.observed_at,
            audit_event_id=created.audit_event_id, extra=extra,
        )
    return entities.OpResult(
        path=created.path, entity_id=created.entity_id, status=STATUS_CANDIDATE, revision=1,
        previous_status="(created)", previous_revision=0, changed=True, dry_run=dry_run,
        observed_at=at.isoformat(timespec="seconds"), audit_event_id=created.audit_event_id,
        extra=extra,
    )


def verify(
    library_root,
    memory_id: str,
    *,
    expected_revision: int,
    actor: str = HUMAN_ACTOR,
    reason: str = "",
    sources=None,
    supersedes: str | None = None,
    explicit_conflicts=(),
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> entities.OpResult:
    """人工确认候选：写 VERIFIED 副本 + 把候选标 VERIFIED（§5.4）。

    只有 actor=human；AI/系统调用一律 AI_CANNOT_VERIFY。跨文件补偿式顺序见模块写法说明。
    """
    require_human_actor(actor)
    root = Path(library_root)
    cpath = candidates_path(root)
    at = now or datetime.now().astimezone()
    at_iso = at.isoformat(timespec="seconds")
    key = _norm_key(idempotency_key)

    candidate_entity = entities.load_entity(cpath, memory_id)
    if candidate_entity.kind and candidate_entity.kind != KIND:
        raise MemoryError("NOT_MEMORY", f"{memory_id} 的 :PM_KIND: 是 {candidate_entity.kind}，不是 {KIND}")
    if key:
        # 一个 key 只对应一次逻辑写入：别人（create / deprecate）的 key 不能拿来 verify，
        # 否则统一机制会把它当重放 —— ① 已写 VERIFIED 副本、② 却不改状态，停在半写且重跑不收敛。
        foreign = _foreign_key_operations(cpath, memory_id, key, _OP_VERIFY)
        if foreign:
            raise entities.EntityError(
                "IDEMPOTENCY_KEY_REUSED",
                f"idempotency key {key} 属于 {'/'.join(sorted(foreign))} 操作，不能拿来 verify {memory_id}；请换一个 key",
            )
        # 只看 apply_change 写进 LOGBOOK、且属于 verify 的 key=（见 _replay_in_file）。
        replay = _replay_in_file(cpath, key)
        if replay is not None:
            if replay.entity_id and replay.entity_id != memory_id:
                raise entities.EntityError(
                    "IDEMPOTENCY_KEY_REUSED",
                    f"idempotency key {key} 已经用在 {replay.entity_id} 上，不能换目标重复使用",
                )
            return replay
    parsed = [entry for entry in parse_candidates(root) if entry.id == memory_id]
    candidate = parsed[0] if parsed else _entry_from_entity(candidate_entity)
    ctype = validate_type(candidate.type)
    scope = validate_scope(candidate.scope)
    vpath = type_path(root, ctype)
    existing_verified = _find_entity(vpath, memory_id)
    extra = {
        "memoryId": memory_id,
        "type": ctype,
        "scope": scope,
        "verifiedPath": _relative(root, vpath),
        "candidatePath": CANDIDATES_RELATIVE,
        "verifiedCopyWritten": False,
        #: 跨文件补偿式事务：不是两文件原子，失败时靠同 ID 幂等对账收敛。
        "compensating": True,
    }

    if candidate.status == STATUS_VERIFIED:
        if existing_verified is None:
            raise MemoryError(
                "INCONSISTENT_STATE",
                f"候选 {memory_id} 已是 VERIFIED，但 {extra['verifiedPath']} 里找不到同 ID 正文；"
                "状态与内容不一致，拒绝静默补写，请人工核对后再验证",
            )
        if existing_verified.status == STATUS_DEPRECATED:
            raise MemoryError(
                "ALREADY_DEPRECATED", f"{memory_id} 的正式条目已 DEPRECATED，不能再次 verify（历史保留）")
        audit_id, observed = entities.audit_from_region(_entity_region(cpath, candidate_entity))
        extra.update({"verifiedLine": existing_verified.line, "idempotentReplay": True})
        return entities.OpResult(
            path=cpath, entity_id=memory_id, status=STATUS_VERIFIED,
            revision=candidate_entity.revision, previous_status=STATUS_VERIFIED,
            previous_revision=candidate_entity.revision, changed=False, idempotent=True,
            observed_at=observed, audit_event_id=audit_id, extra=extra,
        )
    if candidate.status == STATUS_DEPRECATED:
        raise MemoryError("CANNOT_VERIFY_DEPRECATED", f"{memory_id} 已 DEPRECATED，不能提升为 VERIFIED")
    if candidate.status != STATUS_CANDIDATE:
        raise MemoryError("INVALID_STATUS", f"候选 {memory_id} 的状态是 {candidate.status}，只有 CANDIDATE 能 verify")

    # CAS 预检：冲突时**一个字节都不写**（apply_change 仍是最终权威）。
    if candidate.revision != expected_revision:
        raise entities.EntityError(
            "REVISION_CONFLICT",
            f"revision 冲突：现在写会覆盖别人的修改（文件里 {candidate.revision}，你看到的是 {expected_revision}）",
            exit_code=entities.EXIT_CONFLICT,
            extra={
                "currentRevision": candidate.revision,
                "expectedRevision": expected_revision,
                "diffHint": "文件已被其他编辑器/命令修改，请重新读取（pm memory candidates）后按新 revision 再提交",
            },
        )

    normalized_sources = validate_sources(sources) if sources is not None else None
    prospective = MemoryEntry(
        id=memory_id,
        status=STATUS_VERIFIED,
        scope=scope,
        type=ctype,
        text=clean_text(candidate.text),
        sources=normalized_sources if normalized_sources is not None else candidate.sources,
        revision=candidate.revision,
        topic=candidate.topic,
        task_id=candidate.task_id,
        created_at=candidate.created_at,
        created_by=candidate.created_by,
        supersedes=(supersedes or "").strip() or candidate.supersedes,
    )
    if not prospective.text:
        raise MemoryError("TEXT_REQUIRED", f"候选 {memory_id} 正文为空，不能 verify")

    supersede_target = None
    supersede_path = None
    if supersedes:
        located = _locate_entry(root, supersedes)
        if located is None:
            raise MemoryError("SUPERSEDE_TARGET_NOT_FOUND", f"要取代的 {supersedes} 在候选与正式记忆里都找不到")
        supersede_target, supersede_path = located
        if supersede_target.id == memory_id:
            raise MemoryError("SUPERSEDE_SELF", "不能 supersede 自己")
        if supersede_target.scope != scope or supersede_target.type != ctype:
            raise MemoryError(
                "SUPERSEDE_SCOPE_MISMATCH",
                f"{supersedes} 的 scope/type 是 {supersede_target.scope}/{supersede_target.type}，"
                f"与本次 {scope}/{ctype} 不同",
            )
        if supersede_target.status == STATUS_DEPRECATED:
            raise MemoryError("SUPERSEDE_TARGET_DEPRECATED", f"{supersedes} 已经 DEPRECATED，无需再次取代")

    conflicts = detect_conflicts(prospective, parse_memory(root, type=ctype), explicit_ids=explicit_conflicts)
    unresolved = [item for item in conflicts if not (supersedes and item.entry_id == supersedes)]
    if unresolved:
        raise MemoryError(
            "MEMORY_CONFLICT",
            "与既有正式记忆冲突，拒绝静默覆盖："
            + "; ".join(f"{item.entry_id}({item.reason})" for item in unresolved)
            + "；用 --supersedes 指向被取代条目（会把旧的标 DEPRECATED），或先人工解决冲突",
            extra={"conflicts": [item.to_dict() for item in unresolved]},
        )

    # ① 写 VERIFIED 副本（同 ID）。这里**不改候选状态**：状态的唯一真相在候选文件，由 ② 更新。
    #
    # revision 同步：② 成功后候选的 revision 是 expected_revision + 1；正式副本用**同一个 revision**
    # （create_entity 尊重 properties 里的 PM_REVISION，一次写成），这样 verify 返回的 revision
    # 能直接用于正式条目的下一次 CAS —— 否则 verify → deprecate 必冲突。
    target_revision = expected_revision + 1
    verified_written = False
    verified_line = existing_verified.line if existing_verified is not None else 0
    verified_revision = existing_verified.revision if existing_verified is not None else target_revision
    if existing_verified is None:
        created = entities.create_entity(
            vpath, entity_id=memory_id, kind=KIND, status=STATUS_VERIFIED,
            headline=prospective.title, section=TYPE_SECTIONS[ctype],
            properties=_verified_properties(prospective, at_iso, revision=target_revision),
            body_lines=prospective.body_lines, actor=HUMAN_ACTOR, now=at, dry_run=dry_run,
        )
        verified_line = created.line
        verified_revision = created.revision
        verified_written = not dry_run
    extra["verifiedCopyWritten"] = verified_written
    extra["verifiedCopyPlanned"] = existing_verified is None
    extra["verifiedLine"] = verified_line
    extra["verifiedRevision"] = verified_revision
    if verified_revision != target_revision:
        # 例如人工把候选 :PM_REVISION: 改过 >1，或正式副本是旧版流程留下的：如实标注，不假装同步。
        extra["revisionOutOfSync"] = {
            "verifiedRevision": verified_revision,
            "candidateRevisionAfterVerify": target_revision,
        }

    # ② 原子改候选：CAS + 状态 + 审计 + 幂等。
    set_props = {"PM_VERIFIED_AT": at_iso, "PM_VERIFIED_BY": HUMAN_ACTOR}
    clear_props: tuple[str, ...] = ()
    if normalized_sources is not None:
        set_props["PM_SOURCES"] = " ".join(normalized_sources)
        if normalized_sources:
            clear_props = ("PM_UNSOURCED",)
        else:
            set_props["PM_UNSOURCED"] = "t"
    if supersedes:
        set_props["PM_SUPERSEDES"] = supersedes
    try:
        result = entities.apply_change(
            cpath, memory_id, expected_revision=expected_revision, status=STATUS_VERIFIED,
            set_properties=set_props, clear_properties=clear_props, actor=HUMAN_ACTOR,
            reason=reason, idempotency_key=idempotency_key, dry_run=dry_run, now=at,
            audit_extra={"type": ctype, "scope": scope},
        )
    except entities.EntityError as exc:
        if exc.code == "REVISION_CONFLICT":
            exc.extra.update({
                "partial": True,
                "verifiedCopyWritten": verified_written,
                "verifiedPath": extra["verifiedPath"],
                "notWritten": ["候选 :PM_STATUS: → VERIFIED", "候选 LOGBOOK 审计行"],
                "hint": "已写入的 VERIFIED 副本保留（同 ID 可追溯）；修好 revision 后重跑 verify 会幂等收敛。",
            })
        raise

    # ③ supersede：最后把旧条目标 DEPRECATED，并写双向链。
    if supersedes and supersede_target is not None and supersede_path is not None:
        extra.update({
            "supersedes": supersedes,
            "supersededPath": _relative(root, supersede_path),
            "supersededRevision": supersede_target.revision,
        })
        try:
            entities.apply_change(
                supersede_path, supersedes, expected_revision=supersede_target.revision,
                status=STATUS_DEPRECATED,
                set_properties={"PM_SUPERSEDED_BY": memory_id, "PM_DEPRECATED_AT": at_iso},
                actor=actor, reason=reason or f"superseded by {memory_id}",
                dry_run=dry_run, now=at, audit_extra={"supersededBy": memory_id},
            )
        except entities.EntityError as exc:
            if exc.code == "REVISION_CONFLICT":
                exc.extra.update({
                    "partial": True,
                    "verifiedCopyWritten": verified_written,
                    "verifiedPath": extra["verifiedPath"],
                    "candidateStatus": STATUS_VERIFIED,
                    "notWritten": [f"{supersedes} :PM_STATUS: → DEPRECATED（:PM_SUPERSEDED_BY: 链未闭合）"],
                    "hint": f"新条目已写入且候选已 VERIFIED；{supersedes} 未标 DEPRECATED。"
                            "修好 revision 后重跑或手工 deprecate。",
                })
            raise

    result.extra.update(extra)
    return result


def deprecate(
    library_root,
    memory_id: str,
    *,
    expected_revision: int,
    reason: str,
    superseded_by: str | None = None,
    actor: str = HUMAN_ACTOR,
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> entities.OpResult:
    """把一条记忆标 DEPRECATED（保留历史，不删除；必须给 reason）。"""
    if not str(reason or "").strip():
        raise MemoryError("REASON_REQUIRED", "deprecate 必须给 --reason：审计要留下为什么废弃（§5.4 保留历史）")
    root = Path(library_root)
    at = now or datetime.now().astimezone()
    at_iso = at.isoformat(timespec="seconds")
    located = _locate_entry(root, memory_id)
    if located is None:
        raise _not_found(root, memory_id)
    entry, path = located
    # 一个 key 只对应一次逻辑写入：create / verify 的 key 不能拿来 deprecate，
    # 否则 apply_change 会把它当重放 → changed=False 却退 0（假的成功，§7 约束 7 的精神）。
    key = _norm_key(idempotency_key)
    if key:
        foreign = _foreign_key_operations(path, memory_id, key, _OP_DEPRECATE)
        if foreign:
            raise entities.EntityError(
                "IDEMPOTENCY_KEY_REUSED",
                f"idempotency key {key} 属于 {'/'.join(sorted(foreign))} 操作，不能拿来 deprecate {memory_id}；请换一个 key",
            )
    if superseded_by:
        successor = _locate_entry(root, superseded_by)
        if successor is None:
            raise MemoryError("SUPERSEDED_BY_NOT_FOUND", f"--superseded-by {superseded_by} 在候选与正式记忆里都找不到")
        if successor[0].id == memory_id:
            raise MemoryError("SUPERSEDED_BY_SELF", "不能把自己标成自己的取代者")
        if successor[0].status == STATUS_DEPRECATED:
            raise MemoryError("SUPERSEDED_BY_DEPRECATED", f"--superseded-by {superseded_by} 自己已 DEPRECATED，链会断")
    props = {"PM_DEPRECATED_AT": at_iso}
    if superseded_by:
        props["PM_SUPERSEDED_BY"] = superseded_by
    result = entities.apply_change(
        path, memory_id, expected_revision=expected_revision, status=STATUS_DEPRECATED,
        set_properties=props, actor=actor, reason=reason, idempotency_key=idempotency_key,
        dry_run=dry_run, now=at,
        audit_extra={"supersededBy": superseded_by} if superseded_by else None,
    )
    result.extra.update({
        "memoryId": memory_id,
        "type": entry.type,
        "scope": entry.scope,
        "supersededBy": superseded_by,
        "pathRelative": _relative(root, path),
    })
    return result


def discard(
    library_root,
    memory_id: str,
    *,
    expected_revision: int,
    reason: str,
    actor: str = HUMAN_ACTOR,
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> entities.OpResult:
    """丢弃一个**候选**：状态复用 DEPRECATED（不引入新状态、历史 append-only），必须给 reason。

    - **只允许从 CANDIDATE 丢**；已确认（VERIFIED）的条目请用 deprecate（保留取代链）→ 这里明确拒绝 `NOT_A_CANDIDATE`；
    - 已是 DEPRECATED → **幂等**：changed:false、不新增审计（不带 set_properties，走 apply_change 的零变更分支）；
    - 与其它写命令同一套：CAS（不匹配 → exit 3、零写入）、一条审计（`op=discard` + reason）、幂等键、--dry-run 零写入。
    """
    if not str(reason or "").strip():
        raise MemoryError("REASON_REQUIRED", "discard 必须给 --reason：审计要留下为什么丢弃这个候选（历史保留）")
    root = Path(library_root)
    at = now or datetime.now().astimezone()
    at_iso = at.isoformat(timespec="seconds")
    located = _locate_entry(root, memory_id)
    if located is None:
        raise _not_found(root, memory_id)
    entry, path = located
    if entry.status not in (STATUS_CANDIDATE, STATUS_DEPRECATED):
        raise MemoryError(
            "NOT_A_CANDIDATE",
            f"{memory_id} 现在是 {entry.status}，不是候选；已确认的记忆请用 pm memory deprecate（保留取代链）",
        )
    key = _norm_key(idempotency_key)
    if key:
        foreign = _foreign_key_operations(path, memory_id, key, _OP_DISCARD)
        if foreign:
            raise entities.EntityError(
                "IDEMPOTENCY_KEY_REUSED",
                f"idempotency key {key} 属于 {'/'.join(sorted(foreign))} 操作，不能拿来 discard {memory_id}；请换一个 key",
            )
    # 已是 DEPRECATED：不给 set_properties → 期望状态 == 当前状态 → apply_change 判零变更（不写、不审计、revision 不变）
    props = None if entry.status == STATUS_DEPRECATED else {"PM_DEPRECATED_AT": at_iso}
    result = entities.apply_change(
        path, memory_id, expected_revision=expected_revision, status=STATUS_DEPRECATED,
        set_properties=props, actor=actor, reason=reason, idempotency_key=idempotency_key,
        dry_run=dry_run, now=at, audit_extra={"op": _OP_DISCARD},
    )
    result.extra.update({
        "memoryId": memory_id,
        "type": entry.type,
        "scope": entry.scope,
        "discarded": entry.status == STATUS_CANDIDATE,
        "wasStatus": entry.status,
        "pathRelative": _relative(root, path),
    })
    return result


# ---------------------------------------------------------------- CLI（cli.py 自动挂载 register_cli）
#
# 与 inbox 命令同风格：读命令 --json；写命令 --expected-revision/--actor/--reason/
# --idempotency-key/--dry-run/--json/--yes，退出码 2=输入拒绝、3=CAS 冲突、0=成功。


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", metavar="PATH", default=argparse.SUPPRESS, help="指定 pm.toml")


def _add_write_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--actor", default=HUMAN_ACTOR, choices=["human", "ai", "system"],
                        help="谁发起的，写入审计（默认 human）")
    parser.add_argument("--reason", default="", metavar="R", help="变更原因，写入审计")
    parser.add_argument("--idempotency-key", dest="idempotency_key", default=None, metavar="KEY",
                        help="同一 key 重复提交不会产生第二次变更")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="只预演，一字节不落盘")
    parser.add_argument("--yes", action="store_true",
                        help="确认要写「默认配置指向的库」；未显式 --config 且非 --dry-run 时必需")
    parser.add_argument("--json", action="store_true", help="stdout 只输出纯 JSON")


# ---------------------------------------------------------------- L2 场景文件（内部记录/13 §2 / §7-B）

L2_DIRNAME = "l2"
L2_SECTION = "Scenes"

_SCENE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def l2_dir(library_root) -> Path:
    """L2 场景目录：memory/l2/<scope>/<scene>.org（一块一文件，路径即 id）。"""
    return Path(library_root) / MEMORY_DIRNAME / L2_DIRNAME


def _validate_token(value: str, *, what: str) -> str:
    text = str(value or "").strip()
    if not _SCENE_TOKEN.fullmatch(text):
        raise MemoryError("BAD_NAME", f"{what} 只能是字母/数字/._-（且以字母或数字开头）：{value!r}")
    return text


def scene_id(scope: str, scene: str) -> str:
    return "memory-l2-" + scope + "-" + scene


def scene_path(library_root, scope: str, scene: str) -> Path:
    return l2_dir(library_root) / _validate_token(scope, what="scope") / (_validate_token(scene, what="scene") + ".org")


def parse_source_pins(sources) -> list[tuple[str, int | None]]:
    """把 :PM_SOURCES: 的 token 解析成 (id, revision|None)。

    写法 `memory-xxx@3` = 「归纳时读到的那条 L1 的 revision」——stale 判定的锚点（内部记录/13 §3.2）。
    没有 `@rev` 的 token 返回 (id, None)：**不能证明新鲜，也不能假设过期**，单独归入「无锚点」。
    """
    pins: list[tuple[str, int | None]] = []
    for raw in sources or ():
        token = str(raw).strip()
        if not token:
            continue
        if "@" in token:
            head, _, tail = token.rpartition("@")
            try:
                pins.append((head.strip(), int(tail)))
            except ValueError:
                pins.append((token, None))
        else:
            pins.append((token, None))
    return pins


def parse_source_refs(sources) -> list[tuple[str, int | None, str | None]]:
    """把 :PM_SOURCES: 解析成 (ref, revision|None, hash|None)。

    - `memory-xxx@3`            → ("memory-xxx", 3, None)        L1 用 revision 锚点；
    - `memory/l2/a/b.org@ab12`  → ("memory/l2/a/b.org", None, "ab12")  L3 用**文件内容 hash** 锚点；
    - 无 `@`                    → (ref, None, None)              ⇒ 无法判定新鲜（归「无锚点」）。
    """
    out: list[tuple[str, int | None, str | None]] = []
    for raw in sources or ():
        token = str(raw).strip()
        if not token:
            continue
        if "@" in token:
            head, _, tail = token.rpartition("@")
            head = head.strip()
            if tail.isdigit():
                out.append((head, int(tail), None))
            elif tail:
                out.append((head, None, tail.strip()))
            else:
                out.append((token, None, None))
        else:
            out.append((token, None, None))
    return out


def read_scenes(library_root, *, scope: str | None = None) -> list[MemoryEntry]:
    """读 memory/l2/<scope>/<scene>.org（路径即 id）。layer 一律按 L2 认（目录即层级）。"""
    root = l2_dir(library_root)
    if not root.is_dir():
        return []
    wanted = _validate_token(scope, what="scope") if scope else None
    scenes: list[MemoryEntry] = []
    for path in sorted(root.glob("*/*.org")):
        if wanted and path.parent.name != wanted:
            continue
        entries = parse_entries_text(_read_text(path))
        if not entries:
            continue
        entry = entries[0]
        row_scope = entry.scope if entry.scope != SCOPE_GLOBAL else path.parent.name
        scenes.append(replace(entry, layer=LAYER_L2, scope=row_scope))
    return scenes


def write_scene(library_root, *, scope: str, scene: str, title: str, body: str = "",
                sources=(), type: str = TYPE_FACT, status: str = STATUS_CANDIDATE, actor: str = "ai", reason: str = "",
                expected_revision: int | None = None, dry_run: bool = False, now: datetime | None = None,
                idempotency_key: str | None = None) -> entities.OpResult:
    """新建/更新一个 L2 场景（CAS + 原子写 + 审计，全部复用 pm.entities，不另造一套）。

    新建：写一个 `** <title>` 块（:ID: = memory-l2-<scope>-<scene>、:PM_LAYER: L2、:PM_SOURCES: 版本锚点）。
    更新：必须给 expected_revision（CAS；不匹配 → REVISION_CONFLICT，一字节不写）。
    """
    root = Path(library_root)
    path = scene_path(root, scope, scene)
    entry_id = scene_id(scope, scene)
    at = now or datetime.now().astimezone()
    source_text = " ".join(str(item) for item in (sources or ()))
    # 写 :PM_TYPE: 是必须的：不写的话解析回默认类型，会让「同目标内容的幂等比较」永远不等（实测踩过）。
    props = {"PM_LAYER": LAYER_L2, "PM_SCOPE": scope, "PM_TYPE": validate_type(type),
             "PM_SOURCES": source_text}
    raw_lines = [line for line in str(body or "").split("\n")] if body else []
    # memory 域正文一律 3 空格缩进（与 create_entity(indent_body=True) 的产物一致）：
    # 新建与更新用**同一份** indented，否则更新后解析器读不到正文（实测踩过）。
    body_lines = [("   " + line) if line.strip() else "" for line in raw_lines]
    existing: MemoryEntry | None = None
    if path.is_file():
        parsed = parse_entries_text(_read_text(path))
        if parsed:
            existing = parsed[0]
    if existing is None:
        created = entities.create_entity(
            path, entity_id=entry_id, kind=KIND, status=status, headline=title,
            section=L2_SECTION, properties=props, body_lines=body_lines, indent_body=False,
            actor=actor, now=at, dry_run=dry_run, idempotency_key=idempotency_key,
        )
        return entities.OpResult(
            path=created.path, entity_id=created.entity_id, status=status, revision=created.revision,
            previous_status="(created)", previous_revision=0, changed=True, dry_run=dry_run,
            observed_at=at.isoformat(timespec="seconds"), audit_event_id=created.audit_event_id,
            extra={"scene": scene, "scope": scope, "sources": list(sources or ())},
        )
    if expected_revision is None:
        raise MemoryError("REVISION_REQUIRED", "更新既有 L2 场景必须给 --expected-revision（CAS）")
    result = entities.apply_change(
        path, existing.id or entry_id, expected_revision=expected_revision, status=status,
        set_properties=props, replace_body=body_lines, headline=title, actor=actor,
        reason=reason, dry_run=dry_run, now=at, idempotency_key=idempotency_key,
    )
    result.extra.update({"scene": scene, "scope": scope, "sources": list(sources or ())})
    return result


def command_stale(args) -> int:
    """`pm memory stale`：纯计算 —— 引用的 L1 revision 变了 / 没了 ⇒ 该 L2/L3 过期。只读，不改任何文件。"""
    json_mode = _wants_json(args)
    from pm import index as index_mod  # 延迟 import：index 依赖 memory（避免循环）

    try:
        root = _read_library(args)
    except MemoryError as exc:
        return _fail(json_mode, exc)
    try:
        report = index_mod.stale_check(root)
    except index_mod.IndexError_ as exc:
        return _fail(json_mode, MemoryError(exc.code, exc.message, exit_code=exc.exit_code))
    if json_mode:
        print(json.dumps({"ok": True, "data": report}, ensure_ascii=False, indent=2))
        return 0
    print("库: " + report["library"] + " | 检查 " + str(report["checked"]) + " 条 L2/L3（新鲜 " + str(report["fresh"]) + "）")
    for item in report["stale"]:
        print("  [过期] " + item["source"] + "  ← " + "; ".join(item["problems"]))
    for item in report["unpinned"]:
        print("  [无锚点] " + item["source"] + "  ← " + item["reason"])
    if not report["stale"] and not report["unpinned"]:
        print("  （没有过期项）")
    return 0


def command_scene_list(args) -> int:
    json_mode = _wants_json(args)
    try:
        root = _read_library(args)
    except MemoryError as exc:
        return _fail(json_mode, exc)
    scenes = read_scenes(root, scope=getattr(args, "scope", None))
    payload = {"path": str(l2_dir(root)), "count": len(scenes),
               "scenes": [entry.to_dict(client=False) for entry in scenes]}
    if json_mode:
        print(json.dumps({"ok": True, "data": payload}, ensure_ascii=False, indent=2))
        return 0
    print("L2 场景: " + str(payload["count"]) + " 个（" + str(l2_dir(root)) + "）")
    for entry in scenes:
        first = entry.text.split("\n")[0] if entry.text else ""
        print("  " + (entry.id or "(no-id)") + "  rev " + str(entry.revision) + "  " + first[:60])
    return 0


def command_scene_show(args) -> int:
    json_mode = _wants_json(args)
    try:
        root = _read_library(args)
    except MemoryError as exc:
        return _fail(json_mode, exc)
    path = scene_path(root, args.scope, args.scene)
    if not path.is_file():
        return _fail(json_mode, MemoryError("NOT_FOUND", "没有这个 L2 场景: " + str(path)))
    text = _read_text(path)
    if json_mode:
        print(json.dumps({"ok": True, "data": {"path": str(path), "text": text}}, ensure_ascii=False, indent=2))
        return 0
    print(text.rstrip())
    return 0


def command_scene_set(args) -> int:
    json_mode = _wants_json(args)
    from pm.cli import resolve_write_target

    layout, gate_error = resolve_write_target(args, json_mode)
    if layout is None:
        return _fail(json_mode, MemoryError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    try:
        result = write_scene(
            layout.root, scope=args.scope, scene=args.scene, title=args.title, body=args.body or "",
            sources=args.sources or (), status=args.status, actor=args.actor, reason=args.reason or "",
            expected_revision=getattr(args, "expected_revision", None), dry_run=args.dry_run,
            idempotency_key=args.idempotency_key,
        )
    except (MemoryError, entities.EntityError) as exc:
        return _fail(json_mode, exc)
    return _emit_write(result, layout, json_mode=json_mode, dry_run=args.dry_run, verb="已写 L2 场景")

def register_cli(subparsers) -> None:
    """把自己的子命令挂到 pm 的 subparsers 上（cli.py 的 _register_domain_commands 调它）。"""
    memory = subparsers.add_parser(
        "memory",
        help="记忆：候选 → 人工确认 → 上下文包（设计 §5.4）；三类 fact/decision/gotcha",
        description="记忆：候选 →（人确认）→ 正式 →（可选）废弃。"
                    " 分层 L1/L2/L3 是**预留能力**（界面不暴露、日常不启用）："
                    "scene/extract/condense/distill/stale 保留可用，边界见 内部记录/13 顶部「当前状态」。",
    )
    sub = memory.add_subparsers(dest="memory_command")

    candidates = sub.add_parser("candidates", help="列出记忆候选（AI/系统提出，未确认）")
    candidates.add_argument("--status", metavar="S", help="只看某个状态，如 CANDIDATE / VERIFIED")
    candidates.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(candidates)
    candidates.set_defaults(handler=command_candidates)

    listing = sub.add_parser("list", help="列出正式记忆（memory/*.org，含 DEPRECATED 历史）")
    listing.add_argument("--type", choices=list(TYPES), help="只看某类记忆")
    listing.add_argument("--scope", metavar="SCOPE", help="只看某个 scope")
    # 正式区只有 VERIFIED / DEPRECATED（候选在 memory-candidates.org，用 `pm memory candidates` 看）。
    # 用 type=str.upper + choices ⇒ 小写也认、非法值由 argparse **明确报错**（exit 2，不静默忽略）。
    listing.add_argument("--status", type=str.upper, choices=[STATUS_VERIFIED, STATUS_DEPRECATED],
                         metavar="{VERIFIED,DEPRECATED}", help="只看某个状态（默认全部）")
    listing.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(listing)
    listing.set_defaults(handler=command_list)

    context = sub.add_parser("context", help="组装给 AI 的上下文包（只含 VERIFIED）")
    context.add_argument("--scope", required=True, metavar="SCOPE", help="项目 id 或 global")
    context.add_argument("--task", metavar="TASK_ID", help="按任务过滤 :PM_TASK_ID:")
    context.add_argument("--no-global", dest="include_global", action="store_false", help="不包含 global 记忆")
    context.add_argument("--allow-cross-scope", dest="allow_cross_scope", action="store_true",
                         help="允许跨项目读取该任务记忆（需显式授权）")
    context.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(context)
    context.set_defaults(handler=command_context, include_global=True)

    add = sub.add_parser("add", help="新增一条记忆候选（AI/系统；默认 CANDIDATE）")
    add.add_argument("--text", required=True, metavar="TEXT", help="记忆正文（可含换行）")
    add.add_argument("--scope", required=True, metavar="SCOPE", help="项目 id 或 global")
    add.add_argument("--type", required=True, choices=list(TYPES), help="fact / decision / gotcha")
    add.add_argument("--sources", action="append", default=[], metavar="REF",
                     help="来源引用，可重复；缺省则标 :PM_UNSOURCED: t")
    add.add_argument("--topic", default="", metavar="T",
                     help="主题键：同 scope+type 且 topic 相同视为同一话题，用于冲突检测")
    add.add_argument("--task-id", dest="task_id", default=None, metavar="ID", help="关联任务 :ID:")
    add.add_argument("--created-by", dest="created_by", default="ai", metavar="WHO", help="提出者（默认 ai）")
    add.add_argument("--supersedes", default=None, metavar="MEMORY_ID", help="将取代的既有 memory :ID:")
    _add_write_options(add)
    _add_common_options(add)
    add.set_defaults(handler=command_add)

    verify_parser = sub.add_parser("verify", help="人工确认候选 → 写入 memory/<type>.org（只有 actor=human）")
    verify_parser.add_argument("memory_id", metavar="MEMORY_ID", help="候选 :ID:")
    verify_parser.add_argument("--expected-revision", dest="expected_revision", type=int, required=True,
                               metavar="N", help="你看到的 :PM_REVISION:；不匹配 → 退出码 3，一字节不写（CAS）")
    verify_parser.add_argument("--sources", action="append", default=None, metavar="REF",
                               help="确认时修正来源，可重复")
    verify_parser.add_argument("--supersedes", default=None, metavar="MEMORY_ID",
                               help="取代既有条目（旧的标 DEPRECATED，两侧写链）")
    verify_parser.add_argument("--conflict-with", dest="conflict_with", action="append", default=[],
                               metavar="MEMORY_ID", help="显式声明与某条既存记忆冲突（需同时 --supersedes 才通过）")
    _add_write_options(verify_parser)
    _add_common_options(verify_parser)
    verify_parser.set_defaults(handler=command_verify)

    deprecate_parser = sub.add_parser("deprecate", help="废弃一条记忆（保留历史，必须给 --reason）")
    deprecate_parser.add_argument("memory_id", metavar="MEMORY_ID", help="记忆 :ID:")
    deprecate_parser.add_argument("--expected-revision", dest="expected_revision", type=int, required=True,
                                  metavar="N", help="你看到的 :PM_REVISION:")
    deprecate_parser.add_argument("--superseded-by", dest="superseded_by", default=None, metavar="MEMORY_ID",
                                  help="取代它的新条目 :ID:")
    _add_write_options(deprecate_parser)
    _add_common_options(deprecate_parser)
    deprecate_parser.set_defaults(handler=command_deprecate)

    discard_parser = sub.add_parser(
        "discard", help="丢弃一个候选（只允许 CANDIDATE；状态复用 DEPRECATED，必须给 --reason）"
    )
    discard_parser.add_argument("memory_id", metavar="MEMORY_ID", help="候选 :ID:")
    discard_parser.add_argument("--expected-revision", dest="expected_revision", type=int, required=True,
                                metavar="N", help="你看到的 :PM_REVISION:；不匹配 → 退出码 3，一字节不写（CAS）")
    _add_write_options(discard_parser)
    _add_common_options(discard_parser)
    discard_parser.set_defaults(handler=command_discard)

    stale_parser = sub.add_parser("stale", help="纯计算：引用的 L1 revision 变了/没了 ⇒ 指出受影响的 L2/L3（只读）")
    stale_parser.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(stale_parser)
    stale_parser.set_defaults(handler=command_stale)

    scene = sub.add_parser("scene", help="L2 场景文件（memory/l2/<scope>/<scene>.org，一块一文件）")
    scene_sub = scene.add_subparsers(dest="scene_command")
    scene_set = scene_sub.add_parser("set", help="新建/更新一个 L2 场景（CAS + 原子写 + 审计）")
    scene_set.add_argument("--scope", required=True, metavar="SCOPE", help="项目 key 或 global")
    scene_set.add_argument("--scene", required=True, metavar="NAME", help="场景名（= 文件名，路径即 id）")
    scene_set.add_argument("--title", required=True, metavar="T", help="场景标题")
    scene_set.add_argument("--body", default="", metavar="TEXT", help="摘要正文（L2 只索引标题+摘要）")
    scene_set.add_argument("--sources", action="append", default=[], metavar="REF",
                           help="来源锚点，可重复；L1 用 id@revision（如 memory-abc@3）")
    scene_set.add_argument("--status", choices=list(STATUSES), default=STATUS_CANDIDATE, help="默认 CANDIDATE")
    scene_set.add_argument("--expected-revision", dest="expected_revision", type=int, default=None,
                           metavar="N", help="更新既有场景时的 CAS 版本（新建不用给）")
    _add_write_options(scene_set)
    _add_common_options(scene_set)
    scene_set.set_defaults(handler=command_scene_set)

    scene_show = scene_sub.add_parser("show", help="打印一个 L2 场景文件的原文")
    scene_show.add_argument("--scope", required=True, metavar="SCOPE")
    scene_show.add_argument("--scene", required=True, metavar="NAME")
    scene_show.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(scene_show)
    scene_show.set_defaults(handler=command_scene_show)

    scene_list = scene_sub.add_parser("list", help="列出 L2 场景（按 scope 可选过滤）")
    scene_list.add_argument("--scope", metavar="SCOPE", help="只看某个 scope")
    scene_list.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(scene_list)
    scene_list.set_defaults(handler=command_scene_list)

    # ---- M3 第二切片：三条生成命令（人触发 → 只产候选；默认零出网）----
    from pm import generate as generate_mod

    def _add_generate_options(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--llm", default="", metavar="CMD",
                            help="LLM 命令：prompt 走 stdin、候选 JSON 走 stdout（默认取 [memory.generate].llm；都没有则拒绝生成）")
        parser.add_argument("--skeleton", action="store_true", help="不调 LLM：只产「待归纳清单」候选（不编造内容）")
        parser.add_argument("--stale-only", dest="stale_only", action="store_true",
                            help="只处理 stale/缺失的目标；新鲜的目标跳过（不产重复）")
        parser.add_argument("--allow-network", dest="allow_network", action="store_true",
                            help="显式允许 LLM 命令出网（默认零出网；报告里会标注）")

    extract_parser = sub.add_parser("extract", help="从会话材料提炼 L1 候选（人触发 → 只产候选）")
    extract_parser.add_argument("--session", required=True, metavar="ID", help="会话 id")
    extract_parser.add_argument("--scope", default="global", metavar="SCOPE", help="候选归属 scope（默认 global）")
    extract_parser.add_argument("--instance", default="", metavar="ID", help="限定数据根 id")
    _add_generate_options(extract_parser)
    _add_write_options(extract_parser)
    _add_common_options(extract_parser)
    extract_parser.set_defaults(handler=generate_mod.command_extract, actor="ai")

    condense_parser = sub.add_parser("condense", help="把该 scope 的 VERIFIED L1 归纳成一个 L2 候选")
    condense_parser.add_argument("--scope", required=True, metavar="SCOPE", help="项目 key 或 global")
    condense_parser.add_argument("--topic", default="", metavar="T", help="目标主题（= 目标键；默认 default）")
    _add_generate_options(condense_parser)
    _add_write_options(condense_parser)
    _add_common_options(condense_parser)
    condense_parser.set_defaults(handler=generate_mod.command_condense, actor="ai")

    distill_parser = sub.add_parser("distill", help="把 L2 集合蒸馏成一个 L3 候选")
    distill_parser.add_argument("--scope", default="global", metavar="SCOPE", help="项目 key 或 global（默认 global = 全部 L2）")
    distill_parser.add_argument("--topic", default="", metavar="T", help="目标主题（默认 = scope）")
    _add_generate_options(distill_parser)
    _add_write_options(distill_parser)
    _add_common_options(distill_parser)
    distill_parser.set_defaults(handler=generate_mod.command_distill, actor="ai")


def _wants_json(args) -> bool:
    return bool(getattr(args, "json", False))


def _fail(json_mode: bool, error) -> int:
    payload = {"ok": False, "error": {"code": error.code, "message": error.message}}
    payload.update(error.extra or {})
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
    print(f"pm: [{error.code}] {error.message}", file=sys.stderr)
    return int(error.exit_code)


def _read_library(args) -> Path:
    config, _warnings = load_config(getattr(args, "config", None))
    if config.library is None:
        raise MemoryError("NO_LIBRARY", "未配置 work-memory 库（pm.toml 缺 library）")
    return Path(config.library)


def _emit_write(result, layout, *, json_mode: bool, dry_run: bool, verb: str) -> int:
    if json_mode:
        payload = {
            "ok": True,
            "entityId": result.entity_id,
            "memoryId": result.entity_id,
            "source": result.source,
            "observedAt": result.observed_at,
            "auditEventId": result.audit_event_id,
            "status": result.status,
            "revision": result.revision,
            "previousStatus": result.previous_status,
            "previousRevision": result.previous_revision,
            "changed": result.changed,
            "path": _relative(layout.root, result.path),
        }
        payload.update(result.extra or {})
        if result.idempotent:
            payload["idempotent"] = True
        if dry_run:
            payload["dry_run"] = True
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    prefix = "[dry-run] " if dry_run else ""
    audit = f"  audit {result.audit_event_id}" if result.audit_event_id else ""
    if result.idempotent:
        print(prefix + f"该 idempotency-key 已处理过，未再次变更：{result.entity_id} 仍是 {result.status} rev {result.revision}{audit}")
        return 0
    if not result.changed:
        print(prefix + f"无需变更：{result.entity_id} 已是 {result.status} rev {result.revision}{audit}")
        return 0
    print(prefix + f"{verb} {result.entity_id}  {result.previous_status} → {result.status}"
                   f"  rev {result.previous_revision} → {result.revision}{audit}")
    return 0


def command_candidates(args) -> int:
    json_mode = _wants_json(args)
    try:
        root = _read_library(args)
        payload = list_candidates(root)
        wanted = (getattr(args, "status", None) or "").strip().upper()
        if wanted:
            payload["entries"] = [row for row in payload["entries"] if row["status"].upper() == wanted]
            payload["count"] = len(payload["entries"])
    except (MemoryError, entities.EntityError) as exc:
        return _fail(json_mode, exc)
    if json_mode:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
        return 0
    if not payload["entries"]:
        print("memory 没有符合条件的候选。")
        return 0
    print(f"记忆候选 {payload['count']} 条（{payload['path']}，库 {root}）")
    for row in payload["entries"]:
        identity = row["id"] or "(无 :ID:)"
        head = row["text"].splitlines()[0] if row["text"] else ""
        mark = "  ⚠ 无来源" if row["unsourced"] else ""
        print(f"  [{row['status']}] {identity}  {row['type']}/{row['scope']}  rev {row['revision']}"
              f"  第 {row['line']} 行  {head[:36]}{mark}")
    return 0


def command_list(args) -> int:
    json_mode = _wants_json(args)
    try:
        root = _read_library(args)
        entries = parse_memory(root, type=getattr(args, "type", None))
        scope = (getattr(args, "scope", None) or "").strip()
        if scope:
            entries = [entry for entry in entries if entry.scope == scope]
        wanted = (getattr(args, "status", None) or "").strip().upper()
        if wanted:
            entries = [entry for entry in entries if entry.status.upper() == wanted]
        payload = {"path": MEMORY_DIRNAME, "count": len(entries),
                   "entries": [entry.to_dict(client=False) for entry in entries]}
        if wanted:
            payload["status"] = wanted   # 只在过滤时才加这个键 ⇒ 不带参数时 JSON 与今天逐字节一致
    except (MemoryError, entities.EntityError) as exc:
        return _fail(json_mode, exc)
    if json_mode:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
        return 0
    if not payload["entries"]:
        print("memory 没有符合条件的正式记忆。")
        return 0
    print(f"正式记忆 {payload['count']} 条（{payload['path']}/，库 {root}）")
    for row in payload["entries"]:
        head = row["text"].splitlines()[0] if row["text"] else ""
        print(f"  [{row['status']}] {row['id']}  {row['type']}/{row['scope']}  rev {row['revision']}"
              f"  第 {row['line']} 行  {head[:36]}")
    return 0


def command_context(args) -> int:
    json_mode = _wants_json(args)
    try:
        root = _read_library(args)
        payload = context_pack(
            root, args.scope, task_id=getattr(args, "task", None),
            include_global=bool(getattr(args, "include_global", True)),
            allow_cross_scope=bool(getattr(args, "allow_cross_scope", False)),
        )
    except (MemoryError, entities.EntityError) as exc:
        return _fail(json_mode, exc)
    if json_mode:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
        return 0
    counts = payload["counts"]
    print(f"上下文包 scope={payload['scope']} task={payload['taskId'] or '-'}"
          f"  verified {counts['total']} 条（fact {counts['fact']} / decision {counts['decision']}"
          f" / gotcha {counts['gotcha']}）；已排除 {payload['excluded']}")
    for row in payload["entries"]:
        head = row["text"].splitlines()[0] if row["text"] else ""
        print(f"  [{row['type']}/{row['scope']}] {row['id']}  {head[:48]}")
    return 0


def command_add(args) -> int:
    json_mode = _wants_json(args)
    from pm.cli import resolve_write_target

    layout, gate_error = resolve_write_target(args, json_mode)
    if layout is None:
        return _fail(json_mode, MemoryError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    try:
        result = add_candidate(
            layout.root, text=args.text, scope=args.scope, type=args.type,
            sources=args.sources or (), created_by=args.created_by, task_id=args.task_id,
            topic=args.topic, supersedes=args.supersedes,
            idempotency_key=args.idempotency_key, dry_run=args.dry_run,
        )
    except (MemoryError, entities.EntityError) as exc:
        return _fail(json_mode, exc)
    return _emit_write(result, layout, json_mode=json_mode, dry_run=args.dry_run, verb="已新增候选")


def command_verify(args) -> int:
    json_mode = _wants_json(args)
    from pm.cli import resolve_write_target

    layout, gate_error = resolve_write_target(args, json_mode)
    if layout is None:
        return _fail(json_mode, MemoryError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    try:
        result = verify(
            layout.root, args.memory_id, expected_revision=args.expected_revision,
            actor=args.actor, reason=args.reason or "", sources=args.sources,
            supersedes=args.supersedes, explicit_conflicts=args.conflict_with or (),
            idempotency_key=args.idempotency_key, dry_run=args.dry_run,
        )
    except (MemoryError, entities.EntityError) as exc:
        return _fail(json_mode, exc)
    return _emit_write(result, layout, json_mode=json_mode, dry_run=args.dry_run, verb="已确认")


def command_deprecate(args) -> int:
    json_mode = _wants_json(args)
    from pm.cli import resolve_write_target

    layout, gate_error = resolve_write_target(args, json_mode)
    if layout is None:
        return _fail(json_mode, MemoryError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    try:
        result = deprecate(
            layout.root, args.memory_id, expected_revision=args.expected_revision,
            reason=args.reason or "", superseded_by=args.superseded_by, actor=args.actor,
            idempotency_key=args.idempotency_key, dry_run=args.dry_run,
        )
    except (MemoryError, entities.EntityError) as exc:
        return _fail(json_mode, exc)
    return _emit_write(result, layout, json_mode=json_mode, dry_run=args.dry_run, verb="已废弃")


def command_discard(args) -> int:
    json_mode = _wants_json(args)
    from pm.cli import resolve_write_target

    layout, gate_error = resolve_write_target(args, json_mode)
    if layout is None:
        return _fail(json_mode, MemoryError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    try:
        result = discard(
            layout.root, args.memory_id, expected_revision=args.expected_revision,
            reason=args.reason or "", actor=args.actor,
            idempotency_key=args.idempotency_key, dry_run=args.dry_run,
        )
    except (MemoryError, entities.EntityError) as exc:
        return _fail(json_mode, exc)
    return _emit_write(result, layout, json_mode=json_mode, dry_run=args.dry_run, verb="已丢弃")

