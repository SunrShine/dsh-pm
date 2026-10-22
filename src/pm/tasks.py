"""Task 模型（backend-design §5.2）：tasks.org 的解析 / 序列化 / 状态机 / 分组 / CLI。

纯逻辑（不碰磁盘）
  parse_tasks(text)            解析 tasks.org 文本 → task 记录列表
  render_task_block(task)      一个任务块（标题做 org 转义，不裸拼用户输入）
  render_tasks_file(tasks)     整份文件
  validate_transition(...)     §5.2 状态机（DONE 只能由人写）
  group_tasks(tasks)           项目页看板列 待办/执行中/受阻/待验收/已结束（5 列；状态不合并）

写入路径（CAS / 原子写 / 审计 / 幂等）一律委托 pm.entities，本模块不重写一套：
  create_task(...)             新任务（走 entities.create_entity）
  transition_task(...)         状态迁移（走 entities.apply_change，含 headline 关键字改写）
  set_criterion(...)           勾选/取消验收标准（走 entities.apply_change）
  plan_team_import(...)        Agent Team 任务板快照 → 导入计划（纯规划；默认 dry-run）

CLI：本模块暴露 register_cli(subparsers)，由 pm.cli 的域注册钩子自动挂上；
     handler 命名 command_xxx(args) -> int，JSON 走 stdout、其余走 stderr，退出码
     0=成功 / 2=输入或语义拒绝 / 3=CAS 冲突（与 inbox 一致）。

身份纪律（§9）：只用 :ID: 定位，绝不按行号建立关联（行号仅展示）。
格式纪律（§7.2）：标题经 escape_headline 折叠空白与换行，绝不把用户输入直接拼成 headline。

状态机（§5.2）：TODO → NEXT → DOING → REVIEW → DONE，NEXT/DOING ⇄ WAITING/BLOCKED，
任意未完成 → CANCELLED；DONE 只能由 actor=human 写，AI/系统提交最高只能到 REVIEW。
**严格线性**：不允许跳级（TODO → DOING 判非法，必须经 NEXT）—— 这是按 §5.2 的箭头定的；
要放开跳级只改 ALLOWED_TRANSITIONS 这一张表。
真实数据调和：项目 scaffold 的 #+TODO: 声明了 INBOX，本模块把它并入状态集
（INBOX → TODO/NEXT/CANCELLED，分组时与 TODO 同属「收件箱」），否则真实文件里的 INBOX 任务无法处理。

共用 entities 的坑（下一个做行级替换的人注意）：
  entities.Entity.body_start 是**正文末尾的插入点**（append_body 往里追加用），不是正文起点；
  要做行级替换必须先按 :PROPERTIES:/:LOGBOOK: 的位置重算正文起点（见 _body_begin）。
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
import secrets
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from pm import entities, humanwrite, ids, org
from pm.layout import Layout

#: 任务挂在哪个一级小节下（scaffold 生成的是 * 任务）。
TASKS_SECTION = "任务"

#: 状态集合。INBOX 来自项目文件 #+TODO: INBOX(i) … 的声明（scaffold），
#: 与 TODO 同属收件箱族；其余按 §5.2。
STATUS_INBOX = "INBOX"
STATUS_TODO = "TODO"
STATUS_NEXT = "NEXT"
STATUS_DOING = "DOING"
STATUS_WAITING = "WAITING"
STATUS_BLOCKED = "BLOCKED"
STATUS_REVIEW = "REVIEW"
STATUS_DONE = "DONE"
STATUS_CANCELLED = "CANCELLED"

ALL_STATUSES = (
    STATUS_INBOX, STATUS_TODO, STATUS_NEXT, STATUS_DOING,
    STATUS_WAITING, STATUS_BLOCKED, STATUS_REVIEW, STATUS_DONE, STATUS_CANCELLED,
)

DEFAULT_STATUS = STATUS_TODO

#: 终态：不允许再迁出（§5.2 硬约束）。
TERMINAL_STATUSES = frozenset({STATUS_DONE, STATUS_CANCELLED})

#: §5.2 状态机。REVIEW → DONE 是唯一进 DONE 的边；DONE/CANCELLED 无出边。
#: 严格线性，不允许跳级；要放开跳级（如 TODO → DOING）只需要改这一张表。
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_INBOX: frozenset({STATUS_TODO, STATUS_NEXT, STATUS_CANCELLED}),
    STATUS_TODO: frozenset({STATUS_NEXT, STATUS_CANCELLED}),
    STATUS_NEXT: frozenset({STATUS_DOING, STATUS_WAITING, STATUS_BLOCKED, STATUS_CANCELLED}),
    STATUS_DOING: frozenset({STATUS_REVIEW, STATUS_WAITING, STATUS_BLOCKED, STATUS_CANCELLED}),
    STATUS_WAITING: frozenset({STATUS_NEXT, STATUS_DOING, STATUS_BLOCKED, STATUS_CANCELLED}),
    STATUS_BLOCKED: frozenset({STATUS_NEXT, STATUS_DOING, STATUS_WAITING, STATUS_CANCELLED}),
    STATUS_REVIEW: frozenset({
        STATUS_DONE, STATUS_DOING, STATUS_WAITING, STATUS_BLOCKED, STATUS_CANCELLED,
    }),
    STATUS_DONE: frozenset(),
    STATUS_CANCELLED: frozenset(),
}

#: 任务看板列（Lead 2026-10-12 裁定：看板列 8→5，**状态本身不合并**）。
#: org 关键字 / 状态机 / 审计 / 历史一个字不动；每个 task dict 继续带真实 status，
#: 前端靠它渲染子状态 chip（收件箱 / 待办 / 下一步 / 执行中 / 等待 / 阻塞 / 待验收 / 已完成 / 已取消）。
#: 顺序按工作流：待办 → 执行中 → 受阻 → 待验收 → 已结束。
TASK_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("todo", "待办", (STATUS_INBOX, STATUS_TODO, STATUS_NEXT)),
    ("doing", "执行中", (STATUS_DOING,)),
    ("blocked", "受阻", (STATUS_WAITING, STATUS_BLOCKED)),
    ("review", "待验收", (STATUS_REVIEW,)),
    ("closed", "已结束", (STATUS_DONE, STATUS_CANCELLED)),
)

#: status → 看板列 key（一个 status 只属于一列；合并列在这里展开）。
TASK_STATUS_TO_GROUP = {
    status: key for key, _label, statuses in TASK_GROUPS for status in statuses
}
#: 兼容 task-19 时的旧名（与 TASK_STATUS_TO_GROUP 等价）。
GROUP_BY_STATUS = TASK_STATUS_TO_GROUP

#: :ID: 前缀。
TASK_ID_PREFIX = "task-"


class TaskOpError(entities.EntityError):
    """一次 task 操作的明确失败。

    继承 entities.EntityError，所以 CLI 只需要 except EntityError 就能同时接住
    本模块的语义拒绝与 entities 的 CAS 冲突。
    """


# ---------------------------------------------------------------- org 原语

_AT_COL0 = re.compile(r"^(?P<stars>\*+)(?:\s+(?P<title>.*))?$")
_KEYWORD_TOKEN = re.compile(r"^(?P<keyword>[A-Z][A-Z0-9_]*)(?:\s+(?P<rest>.*))?$")
_SECTION = re.compile(r"^(?P<label>非目标|目标)\s*[：:]\s*(?P<value>.*)$")
_CRITERIA_HEADLINE = re.compile(r"^验收标准\s*:?\s*$")
_CRITERION = re.compile(r"^(?P<indent>[ \t]*)[-+]\s+\[(?P<mark>[ xX])\](?:\s+(?P<text>.*))?$")

#: 验收标准项的稳定 ID：c- 加 4 位小写 hex（形如 c-1a2b，见 内部记录/14 §1）。
#: 注意：文档正文写「4 字节 hex」，但示例与 E2 的 CLI 都是 c-1a2b（4 位）——按示例实现，已在回报里请裁定。
_CRITERION_ID_TOKEN = re.compile(r"^\[(?P<id>c-[0-9a-f]{4})\]\s*")
CRITERION_ID_PREFIX = "c-"


def new_criterion_id(existing=None) -> str:
    """生成一个验收标准项 ID（4 位 hex）；与 existing 里已有的不重复。"""
    used = {str(item) for item in (existing or ()) if item}
    for _ in range(64):
        candidate = CRITERION_ID_PREFIX + secrets.token_hex(2)
        if candidate not in used:
            return candidate
    return CRITERION_ID_PREFIX + secrets.token_hex(4)  # pragma: no cover - 极端兜底
_HEADLINE_LIKE = re.compile(r"^\*+(\s|$)")

#: 已知属性（render 时按契约顺序输出，其余按原顺序追加）。
_KNOWN_PROPERTIES = (
    "ID", "PM_KIND", "PM_STATUS", "PM_PROJECT_ID", "PM_SOURCE_INBOX_ID",
    "PM_REVISION", "PM_AI", "PM_ASSIGNEE",
)


def escape_headline(value) -> str:
    """把一个用户输入折成合法 headline 文本（§7 约束 2）。

    - 折叠换行 / 制表符 / 连续空白：注入换行加 ** TODO x 不会造出第二条 headline；
    - 首尾去空白；空输入返回空串（调用方决定是否报 EMPTY_TITLE）。
    """
    return " ".join(str(value if value is not None else "").split()).strip()


def _collapse(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def _property_line(raw: str) -> tuple[str, str] | None:
    stripped = raw.strip()
    if stripped in (":PROPERTIES:", ":END:", ":LOGBOOK:"):
        return None
    if not stripped.startswith(":") or ":" not in stripped[1:]:
        return None
    name, _, value = stripped[1:].partition(":")
    name = name.strip().upper()
    return (name, value.strip()) if name else None


def _read_drawers(lines: list[str], start: int, end: int):
    """读 headline 后紧贴的 :PROPERTIES: / :LOGBOOK:（缩进容错，兼容 inbox 风格）。

    返回 (props, PROPERTIES 的 [start,end) 或 None, LOGBOOK 的 [start,end) 或 None, 正文起点)。
    LOGBOOK 整段跳过，绝不混进正文。
    """
    props: dict[str, str] = {}
    drawer: tuple[int, int] | None = None
    logbook: tuple[int, int] | None = None
    cursor = start + 1
    while cursor < end:
        stripped = lines[cursor].strip()
        if stripped == ":PROPERTIES:":
            begin = cursor
            cursor += 1
            while cursor < end and lines[cursor].strip() != ":END:":
                parsed = _property_line(lines[cursor])
                if parsed is not None:
                    props[parsed[0]] = parsed[1]
                cursor += 1
            if cursor < end:
                cursor += 1
            drawer = (begin, cursor)
            continue
        if stripped == ":LOGBOOK:":
            begin = cursor
            cursor += 1
            while cursor < end and lines[cursor].strip() != ":END:":
                cursor += 1
            if cursor < end:
                cursor += 1
            logbook = (begin, cursor)
            continue
        if drawer is None and _property_line(lines[cursor]) is not None:
            # 裸属性块（手写/旧数据，没有 :PROPERTIES: 标记）
            begin = cursor
            while cursor < end:
                parsed = _property_line(lines[cursor])
                if parsed is None:
                    break
                props[parsed[0]] = parsed[1]
                cursor += 1
            if cursor < end and lines[cursor].strip() == ":END:":
                cursor += 1
            drawer = (begin, cursor)
            continue
        break
    return props, drawer, logbook, cursor


def _headlines(lines: list[str]) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for index, raw in enumerate(lines):
        match = _AT_COL0.match(raw)
        if match is not None:
            found.append((index, len(match.group("stars")), match.group("title") or ""))
    return found


def _normalize_body(body: list[str]) -> list[str]:
    """兼容两种正文缩进风格。

    - 规范风格（render 输出）：小节标记 / 验收标准 headline 在第 0 列，续行 3 空格；
    - entities.create_entity 风格：全部非空正文行统一 +3 空格（inbox v2 惯例）。
    若所有非空行都以 3 空格开头，则整体去掉这层缩进，还原成规范风格。
    """
    nonblank = [line for line in body if line.strip()]
    if nonblank and all(line.startswith("   ") for line in nonblank):
        return [line[3:] if line.startswith("   ") else line for line in body]
    return body


def _parse_body(lines: list[str]) -> tuple[str, str, list[str]]:
    """解析正文里的小节（目标 / 非目标）与未知行。

    规范：目标：<首行>，续行 3 空格缩进（空行写空串，靠“下一个非空行是否缩进”判定归属）。
    """
    goal = ""
    non_goal = ""
    extra: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _SECTION.match(line)
        if match is not None:
            key = "goal" if match.group("label") == "目标" else "non_goal"
            value = match.group("value").strip()
            index += 1
            continuation: list[str] = []
            while index < len(lines):
                candidate = lines[index]
                if _SECTION.match(candidate) is not None or _AT_COL0.match(candidate):
                    break
                if candidate.startswith("   "):
                    continuation.append(candidate[3:])
                    index += 1
                    continue
                if not candidate.strip():
                    probe = index + 1
                    while probe < len(lines) and not lines[probe].strip():
                        probe += 1
                    if probe < len(lines) and lines[probe].startswith("   "):
                        continuation.append("")
                        index += 1
                        continue
                    break
                break
            if continuation:
                value = value + "\n" + "\n".join(continuation)
            if key == "goal":
                goal = value
            else:
                non_goal = value
            continue
        if line.strip():
            extra.append(line)
        index += 1
    return goal, non_goal, extra


#: 证据节名与枚举（内部记录/14 §2）。
EVIDENCE_HEADLINE = "证据（验收）"
EVIDENCE_KINDS = ("test", "build", "manual", "artifact", "review", "other")
EVIDENCE_RESULTS = ("pass", "fail", "info")
EVIDENCE_ACTORS = ("human", "ai", "system")
#: 证据 id 的寻址字段（顺序固定；改这里等于换 id 方案，必须同步测试与文档）。
EVIDENCE_ID_FIELDS = ("criterionId", "kind", "result", "ref", "at", "actor", "note")


def _evidence_field(parts: list[str], index: int) -> str | None:
    if index >= len(parts):
        return None
    value = parts[index].strip()
    return value or None


def parse_task_evidence(lines: list[str], *, base: int = 0) -> list[dict]:
    """只解析**该任务自己的** *** 证据（验收） 节 → 证据条目列表。

    每行 raw.split("|", 6)：前 6 段是结构（criterionId/kind/result/ref/at/actor），
    余下整段是 note（其中的 | 原样保留）。**缺字段一律 null，不猜**。
    节外的行（哪怕长得一样）不收；line 是 1-based 文件行号。
    """
    span = _section_span(lines, EVIDENCE_HEADLINE)
    if span is None:
        return []
    out: list[dict] = []
    for index in range(span[0] + 1, span[1]):
        raw_line = lines[index]
        text = _bullet_text(raw_line)
        if text is None:
            continue
        parts = text.split("|", 6)
        note = parts[6].strip() if len(parts) > 6 else ""
        out.append({
            "criterionId": _evidence_field(parts, 0),
            "kind": _evidence_field(parts, 1),
            "result": _evidence_field(parts, 2),
            "ref": _evidence_field(parts, 3),
            "at": _evidence_field(parts, 4),
            "actor": _evidence_field(parts, 5),
            "note": note or None,
            "raw": raw_line,
            "line": base + index + 1,
        })
    # 给每条证据一个**可核对 id**（task-01M4ZPRF…：rm 要按 id 删、list 要按 id 认）。
    # 内容寻址：由七个结构化字段算 sha256 前 4 位 —— **不改磁盘行格式**（老证据也有 id），
    # 行内容不变则 id 稳定；完全相同的行用出现序号区分（e-xxxx-2、e-xxxx-3…）。
    seen: dict[str, int] = {}
    for entry in out:
        digest = "e-" + hashlib.sha256(
            "|".join(str(entry.get(field) or "") for field in EVIDENCE_ID_FIELDS).encode("utf-8")
        ).hexdigest()[:4]
        seen[digest] = seen.get(digest, 0) + 1
        entry["id"] = digest if seen[digest] == 1 else digest + "-" + str(seen[digest])
    return out


def render_evidence_line(entry: dict) -> str:
    """规范证据行：- <crit> | <kind> | <result> | <ref> | <at> | <actor> | <note…>。

    note 必须是最后一段（其中的 | 原样保留）；结构字段不允许 |（ref 在写入口先被拒绝）。
    """
    parts = [
        _structural(entry.get("criterionId")),
        _structural(entry.get("kind")),
        _structural(entry.get("result")),
        _structural(entry.get("ref")),
        _structural(entry.get("at")),
        _structural(entry.get("actor")),
    ]
    line = "- " + " | ".join(parts)
    note = str(entry.get("note") or "").strip()
    if note:
        line += " | " + note
    return line


def _parse_criteria(lines: list[str], *, base: int = 0) -> tuple[list[dict], list[str]]:
    """解析验收标准行；同时认「有 ID」「无 ID（旧数据）」两种形态。

    lines 是 criteria 节内容行（含嵌套项）；base 是 lines[0] 在文件里的 0-based 行号。
    返回 [{id, text, done, indent, line}]，旧数据无 ID 时 id = null（绝不现编一个）。
    """
    criteria: list[dict] = []
    extra: list[str] = []
    for offset, line in enumerate(lines):
        match = _CRITERION.match(line)
        if match is not None:
            rest = match.group("text") or ""
            token = _CRITERION_ID_TOKEN.match(rest)
            criterion_id = None
            if token is not None:
                criterion_id = token.group("id")
                rest = rest[token.end():]
            criteria.append(
                {
                    "id": criterion_id,
                    "text": rest.rstrip(),
                    "done": match.group("mark").lower() == "x",
                    "indent": len(match.group("indent").expandtabs(4)),
                    "line": base + offset + 1,
                }
            )
            continue
        if line.strip():
            extra.append(line)
    return criteria, extra


#: 单条任务最多返回多少条 LOGBOOK 历史；超出只给最近 HISTORY_LIMIT 条并置 historyTruncated。
HISTORY_LIMIT = 100

#: LOGBOOK 里的审计行（缩进容错：真实行是 "   - State ..."，不要用行首锚死）。
_HISTORY_LINE = re.compile(r"^\s*-\s*State\s")
#: - State "<to>" from "<from>" ...
_STATE_PAIR = re.compile(r'^\s*-\s*State\s+"(?P<to>[^"]*)"\s+from\s+"(?P<from>[^"]*)"')
#: 原始 org 时间戳：[2026-10-12 Mon 12:16]
_ORG_STAMP = re.compile(r"\[(?P<value>[^\]]+)\]")
#: reason= 可能含空格：取到下一个 key=value token 之前（未知键也认）
_REASON_TOKEN = re.compile(r"(?<!\S)reason=(?P<value>.*?)(?=\s+[A-Za-z_][A-Za-z0-9_]*=|$)")


def _audit_token(line: str, name: str) -> str | None:
    match = re.search(r"(?<!\S)" + re.escape(name) + r"=(\S+)", line)
    return match.group(1) if match else None


def parse_history_line(line: str) -> dict:
    """解析一条 LOGBOOK 审计行 → 事件对象。

    缺失字段一律 null（绝不猜）：旧条目可能没有 actor / at / audit / rev / reason。
    raw 原样保留（含未知键，如 op=dag-set），不报错。
    """
    pair = _STATE_PAIR.match(line)
    stamp = _ORG_STAMP.search(line)
    reason_match = _REASON_TOKEN.search(line)
    revision_value = _audit_token(line, "rev")
    revision = None
    if revision_value is not None:
        try:
            revision = int(revision_value)
        except ValueError:
            revision = None
    reason = reason_match.group("value").strip() if reason_match else ""
    return {
        "at": _audit_token(line, "at"),
        "orgAt": stamp.group("value") if stamp else None,
        "actor": _audit_token(line, "actor"),
        "from": pair.group("from") if pair else None,
        "to": pair.group("to") if pair else None,
        "revision": revision,
        "reason": reason or None,
        "auditEventId": _audit_token(line, "audit"),
        "raw": line,
    }


def parse_task_history(lines: list[str], span, *, limit: int = HISTORY_LIMIT) -> tuple[list[dict], int, bool]:
    """解析任务自己的 :LOGBOOK:（span = [start,end)，含 :LOGBOOK:/:END: 两行）。

    只认该区间内形如 - State 的行（缩进容错），按文件顺序 = 发生顺序（旧→新）。
    没有 LOGBOOK（span=None）或没有条目 → ([], 0, False)，不是 null。
    返回 (返回给调用方的事件, **事件总数**, 是否截断)：
    - 事件总数**不受 limit 影响**（前端「共 N 条」读的是它，不能被截断后的条数糊弄）；
    - 超过 limit 条只留**最近** limit 条；总数 > 返回数时 truncated=True（如实标注，不静默丢）。
    """
    if span is None:
        return ([], 0, False)
    entries: list[dict] = []
    for index in range(span[0] + 1, span[1]):
        if index >= len(lines):
            continue
        line = lines[index]
        if line.strip() == ":END:":
            continue
        if _HISTORY_LINE.match(line) is None:
            continue
        entries.append(parse_history_line(line))
    total = len(entries)
    if total > limit:
        return (entries[-limit:], total, True)
    return (entries, total, False)


def status_of_headline(headline: str) -> str | None:
    """从 ** KEYWORD title 取出 org TODO 关键字；没有则 None。"""
    match = _AT_COL0.match(str(headline or ""))
    if match is None:
        return None
    token = _KEYWORD_TOKEN.match(match.group("title") or "")
    if token is None:
        return None
    keyword = token.group("keyword")
    return keyword if keyword in ALL_STATUSES else None


def headline_keyword_rest(headline: str) -> tuple[int, str | None, str]:
    """拆 headline：返回 (层级, 关键字或 None, 剩余标题文本)。"""
    match = _AT_COL0.match(str(headline or ""))
    if match is None:
        return (2, None, _collapse(headline))
    level = len(match.group("stars"))
    content = match.group("title") or ""
    token = _KEYWORD_TOKEN.match(content)
    if token is not None and token.group("keyword") in ALL_STATUSES:
        return (level, token.group("keyword"), (token.group("rest") or "").strip())
    return (level, None, content.strip())


def replace_headline_keyword(headline: str, status: str) -> str:
    """把 headline 的 TODO 关键字换成 status，保留层级与标题（其余逐字保留）。"""
    level, _keyword, rest = headline_keyword_rest(headline)
    line = "*" * level + " " + status
    if rest:
        line += " " + rest
    return line.rstrip()


# ---------------------------------------------------------------- 解析

def resolve_status(task: dict) -> str:
    """取任务的域内状态：status > keyword > pm_status > TODO。"""
    for key in ("status", "keyword", "pm_status"):
        value = task.get(key)
        if value:
            return str(value).strip().upper()
    return DEFAULT_STATUS


def _revision_of(props: dict) -> int:
    return entities.revision_of(props)


def _parse_task(lines: list[str], start: int, end: int, level: int) -> dict:
    match = _AT_COL0.match(lines[start])
    content = (match.group("title") or "").strip()
    keyword = None
    title = content
    token = _KEYWORD_TOKEN.match(content)
    if token is not None and token.group("keyword") in ALL_STATUSES:
        keyword = token.group("keyword")
        title = (token.group("rest") or "").strip()

    props, drawer, logbook, cursor = _read_drawers(lines, start, end)
    body = _normalize_body(lines[cursor:end])

    criteria_index = None
    for offset, line in enumerate(body):
        head = _AT_COL0.match(line)
        if head is None or len(head.group("stars")) < 3:
            continue
        if _CRITERIA_HEADLINE.match((head.group("title") or "").strip()):
            criteria_index = offset
            break

    evidence_index = None
    for offset, line in enumerate(body):
        head = _AT_COL0.match(line)
        if head is None or len(head.group("stars")) < 3:
            continue
        if (head.group("title") or "").strip() == EVIDENCE_HEADLINE:
            evidence_index = offset
            break

    team_tasks = parse_team_children(body, base=cursor)
    dag_edges = parse_dag_edges(body, base=cursor)
    evidence = parse_task_evidence(body, base=cursor)
    history, history_total, history_truncated = parse_task_history(lines, logbook)

    pre = body if criteria_index is None else body[:criteria_index]
    post_end = len(body)
    if evidence_index is not None and (criteria_index is None or evidence_index > criteria_index):
        post_end = evidence_index
    post = [] if criteria_index is None else body[criteria_index + 1 : post_end]
    goal, non_goal, body_extra = _parse_body(pre)
    criteria, criteria_extra = _parse_criteria(
        post, base=(cursor + criteria_index + 1) if criteria_index is not None else cursor
    )

    ai_raw = str(props.get("PM_AI", "") or "").strip().lower()
    pm_status = props.get("PM_STATUS") or None
    status = keyword or pm_status or DEFAULT_STATUS
    extra_properties = {
        key: value for key, value in props.items() if key not in _KNOWN_PROPERTIES
    }
    return {
        "id": props.get("ID") or None,
        "keyword": keyword,
        "status": status,
        "pm_status": pm_status,
        "status_mismatch": bool(pm_status and keyword and pm_status.upper() != keyword.upper()),
        "title": title,
        "project_id": props.get("PM_PROJECT_ID") or None,
        "source_inbox_id": props.get("PM_SOURCE_INBOX_ID") or None,
        "revision": _revision_of(props),
        "ai": ai_raw in ("t", "true", "yes", "y", "1"),
        "assignee": props.get("PM_ASSIGNEE") or None,
        "goal": goal,
        "non_goal": non_goal,
        "criteria": criteria,
        "has_criteria": criteria_index is not None,
        "evidence": evidence,
        "body_extra": body_extra,
        "criteria_extra": criteria_extra,
        "extra_properties": extra_properties,
        "properties": dict(props),
        "line": start + 1,
        "level": level,
        "start": start,
        "end": end,
        "drawer": drawer,
        "logbook": logbook,
        "body_start": cursor,
        "team_tasks": team_tasks,
        "dag_edges": dag_edges,
        "history": history,
        "history_count": history_total,
        "history_truncated": history_truncated,
        "raw_headline": lines[start],
    }


def parse_tasks(text: str, *, level: int = 2) -> list[dict]:
    """解析 tasks.org 文本 → task 记录列表（按文件顺序）。

    每个记录：
      id, keyword, status, title, project_id, source_inbox_id, revision, ai, assignee,
      goal, non_goal, criteria:[{text, done, indent}]
    外加：pm_status / status_mismatch / has_criteria / body_extra / criteria_extra /
    extra_properties / properties / line / level / start / end / drawer / logbook /
    body_start / raw_headline（行号只作展示，身份只看 :ID:）。
    """
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    heads = _headlines(lines)
    tasks: list[dict] = []
    for position, (index, headline_level, title_part) in enumerate(heads):
        if headline_level != level:
            continue
        if _CRITERIA_HEADLINE.match(title_part.strip()):
            continue
        end = len(lines)
        for next_index, next_level, _next_title in heads[position + 1 :]:
            if next_level <= headline_level:
                end = next_index
                break
        tasks.append(_parse_task(lines, index, end, headline_level))
    return tasks


def read_tasks(path: Path, *, level: int = 2) -> list[dict]:
    """读 tasks.org；文件不存在 → []（列表页不该因为还没建文件而报错）。"""
    path = Path(path)
    if not path.is_file():
        return []
    return parse_tasks(entities.read_text(path), level=level)


def find_task(tasks: list[dict], task_id: str) -> dict | None:
    for task in tasks:
        if task.get("id") == task_id:
            return task
    return None


# ---------------------------------------------------------------- 序列化

def _normalize_criterion(criterion) -> dict:
    if isinstance(criterion, str):
        return {"id": None, "text": criterion, "done": False, "indent": 0}
    text = criterion.get("text", "")
    return {
        "id": criterion.get("id") or None,
        "text": str(text if text is not None else ""),
        "done": bool(criterion.get("done")),
        "indent": max(0, int(criterion.get("indent") or 0)),
    }


def render_criterion(criterion) -> str:
    item = _normalize_criterion(criterion)
    mark = "x" if item["done"] else " "
    line = " " * item["indent"] + "- [" + mark + "]"
    if item["id"]:
        line += " [" + item["id"] + "]"
    if item["text"]:
        line += " " + item["text"]
    return line


def _section_lines(label: str, value) -> list[str]:
    text = "" if value is None else str(value).rstrip("\n")
    if text == "":
        return []
    parts = text.split("\n")
    lines = [label + "：" + parts[0]]
    for extra in parts[1:]:
        lines.append(("   " + extra) if extra else "")
    return lines


def _escape_body_line(raw: str) -> str:
    """正文里以 * 开头的未知行，写回时缩进，免得被 org 当成 headline。"""
    return ("   " + raw) if _HEADLINE_LIKE.match(raw) else raw


def render_task_body(task: dict) -> list[str]:
    """任务块的正文行（标题/抽屉之外的部分）。"""
    lines: list[str] = []
    lines.extend(_section_lines("目标", task.get("goal")))
    lines.extend(_section_lines("非目标", task.get("non_goal")))
    for raw in task.get("body_extra") or []:
        lines.append(_escape_body_line(str(raw)))
    has_criteria = task.get("has_criteria")
    if has_criteria is None:
        has_criteria = bool(task.get("criteria")) or bool(task.get("criteria_extra"))
    if has_criteria:
        if lines:
            lines.append("")
        lines.append("*** 验收标准")
        for criterion in task.get("criteria") or []:
            lines.append(render_criterion(criterion))
        for raw in task.get("criteria_extra") or []:
            lines.append(str(raw))
    evidence = task.get("evidence") or []
    if evidence:
        if lines:
            lines.append("")
        lines.append("*** " + EVIDENCE_HEADLINE)
        for entry in evidence:
            lines.append(entry.get("raw") or render_evidence_line(entry))
    return lines


def _property_pairs(task: dict) -> dict[str, str]:
    pairs: dict[str, str] = {}
    task_id = task.get("id")
    if task_id:
        pairs["ID"] = str(task_id)
    pairs["PM_KIND"] = "task"
    pm_status = task.get("pm_status")
    if pm_status:
        pairs["PM_STATUS"] = str(pm_status).strip().upper()
    if task.get("project_id"):
        pairs["PM_PROJECT_ID"] = str(task["project_id"])
    if task.get("source_inbox_id"):
        pairs["PM_SOURCE_INBOX_ID"] = str(task["source_inbox_id"])
    pairs["PM_REVISION"] = str(int(task.get("revision") or 1))
    pairs["PM_AI"] = "t" if task.get("ai") else "nil"
    if task.get("assignee") is not None:
        pairs["PM_ASSIGNEE"] = str(task["assignee"])
    for key, value in (task.get("extra_properties") or {}).items():
        if key not in pairs:
            pairs[key] = str(value)
    return pairs


def render_task_block(task: dict, *, level: int = 2) -> list[str]:
    """一个任务块（headline + :PROPERTIES: + 正文 + *** 验收标准）。"""
    from pm.org import property_drawer

    status = resolve_status(task)
    title = escape_headline(task.get("title"))
    stars = "*" * level
    headline_text = stars + " " + status + ((" " + title) if title else "")
    lines = [headline_text]
    lines.extend(property_drawer(_property_pairs(task)))
    lines.extend(render_task_body(task))
    return lines


def render_tasks_file(tasks: list[dict], *, title: str | None = None) -> str:
    lines: list[str] = []
    if title:
        lines.extend(["#+TITLE: " + title, ""])
    for position, task in enumerate(tasks):
        if position:
            lines.append("")
        lines.extend(render_task_block(task))
    return "\n".join(lines) + ("\n" if lines else "")


def new_task_id(now_ms: int | None = None) -> str:
    return TASK_ID_PREFIX + ids.new_ulid(now_ms)


def build_task(
    title: str,
    *,
    project_id: str | None = None,
    task_id: str | None = None,
    status: str = DEFAULT_STATUS,
    revision: int = 1,
    ai: bool = False,
    assignee: str | None = "unassigned",
    source_inbox_id: str | None = None,
    goal: str = "",
    non_goal: str = "",
    criteria=None,
    has_criteria: bool = True,
    extra_properties: dict | None = None,
    pm_status: str | None = None,
) -> dict:
    """构造一个 parse_tasks 兼容的任务记录（纯函数，不落盘）。"""
    clean_title = escape_headline(title)
    if not clean_title:
        raise TaskOpError("EMPTY_TITLE", "任务标题不能为空（折叠空白后是空串）")
    normalized_status = normalize_status(status)
    items = [_normalize_criterion(item) for item in (criteria or [])]
    used_ids = {item["id"] for item in items if item["id"]}
    for item in items:
        if not item["id"]:  # 新任务在创建时就带上稳定 ID，不必等迁移
            item["id"] = new_criterion_id(used_ids)
            used_ids.add(item["id"])
    return {
        "id": task_id or new_task_id(),
        "keyword": normalized_status,
        "status": normalized_status,
        "pm_status": normalized_status if pm_status is None else pm_status,
        "status_mismatch": False,
        "title": clean_title,
        "project_id": project_id,
        "source_inbox_id": source_inbox_id,
        "revision": int(revision),
        "ai": bool(ai),
        "assignee": assignee,
        "goal": "" if goal is None else str(goal).rstrip("\n"),
        "non_goal": "" if non_goal is None else str(non_goal).rstrip("\n"),
        "criteria": items,
        "has_criteria": bool(has_criteria) or bool(items),
        "body_extra": [],
        "criteria_extra": [],
        "extra_properties": dict(extra_properties or {}),
        "properties": {},
        "line": None,
        "level": 2,
        "start": None,
        "end": None,
        "drawer": None,
        "logbook": None,
        "body_start": None,
        "raw_headline": "",
        "team_tasks": [],
        "dag_edges": [],
        "evidence": [],
        "history": [],
        "history_count": 0,
        "history_truncated": False,
    }


def _last_evidence(task: dict) -> dict | None:
    """列表用的"最近一条证据"：按 at 取最新（同 at 取文件里靠后的那条）；没有证据 → None。"""
    entries = task.get("evidence") or []
    if not entries:
        return None
    last = entries[-1]
    for entry in entries:
        if str(entry.get("at") or "") > str(last.get("at") or ""):
            last = entry
    return {
        "id": last.get("id"),
        "criterionId": last.get("criterionId"),
        "kind": last.get("kind"),
        "result": last.get("result"),
        "ref": last.get("ref"),
        "at": last.get("at"),
    }


def task_summary(task: dict) -> dict:
    """给列表/页面的紧凑形状（不含正文明细）。"""
    criteria = task.get("criteria") or []
    history = task.get("history") or []
    history_total = task.get("history_count")
    if history_total is None:
        history_total = len(history)
    return {
        "id": task.get("id"),
        "title": task.get("title") or "",
        "keyword": task.get("keyword"),
        "status": resolve_status(task),
        "revision": int(task.get("revision") or 1),
        "ai": bool(task.get("ai")),
        "assignee": task.get("assignee"),
        "projectId": task.get("project_id"),
        "sourceInboxId": task.get("source_inbox_id"),
        "line": task.get("line"),
        "criteriaDone": sum(1 for item in criteria if item.get("done")),
        "criteriaTotal": len(criteria),
        "teamTaskCount": len(task.get("team_tasks") or []),
        "dagEdgeCount": len(task.get("dag_edges") or []),
        "evidenceCount": len(task.get("evidence") or []),
        # 列表里"一眼看出最近一条证据是什么"（task-01M4ZPRF…）：只给一条紧凑形状，不塞整个数组
        "lastEvidence": _last_evidence(task),
        "historyCount": int(history_total),
        "historyShown": len(history),
    }


def group_tasks(tasks: list[dict]) -> list[dict]:
    """按项目页看板列分组；固定返回 5 列（待办/执行中/受阻/待验收/已结束）。

    列只决定**展示**，不合并状态：每个 task dict 继续带真实 status，前端用 status 渲染子状态 chip。
    每列额外给 statuses（组成该列的原始状态）与 status（仅单状态列有值，合并列为 None）；
    未知状态不硬塞进任何列，追加到「未分类」（不静默丢弃）。
    """
    buckets: dict[str, list[dict]] = {key: [] for key, _label, _statuses in TASK_GROUPS}
    unknown: list[dict] = []
    for task in tasks:
        key = TASK_STATUS_TO_GROUP.get(resolve_status(task))
        if key is None:
            unknown.append(task)
        else:
            buckets[key].append(task)
    groups = [
        {
            "key": key,
            "label": label,
            "statuses": list(statuses),
            "status": statuses[0] if len(statuses) == 1 else None,
            "count": len(buckets[key]),
            "tasks": buckets[key],
        }
        for key, label, statuses in TASK_GROUPS
    ]
    if unknown:
        groups.append(
            {"key": "unknown", "label": "未分类", "statuses": [], "status": None,
             "count": len(unknown), "tasks": unknown}
        )
    return groups


# ---------------------------------------------------------------- 状态机

def normalize_status(value) -> str:
    status = str(value or "").strip().upper().replace("-", "_")
    if status not in ALL_STATUSES:
        raise TaskOpError(
            "INVALID_STATUS",
            "未知任务状态: " + repr(value) + "；可选 " + ", ".join(ALL_STATUSES),
        )
    return status


def is_terminal(status) -> bool:
    return normalize_status(status) in TERMINAL_STATUSES


def can_transition(current, target, *, actor: str = "human") -> bool:
    try:
        validate_transition(current, target, actor=actor)
    except TaskOpError:
        return False
    return True


def validate_transition(current, target, *, actor: str = "human") -> str:
    """§5.2 状态机校验；非法时抛 TaskOpError（码 2，不落盘）。

    硬约束：DONE 只能由人写；AI 提交只能到 REVIEW。
    """
    source = normalize_status(current)
    destination = normalize_status(target)
    normalized_actor = (str(actor or "human").strip().lower()) or "human"
    if destination == STATUS_DONE and normalized_actor != "human":
        raise TaskOpError(
            "DONE_REQUIRES_HUMAN",
            "DONE 只能由 actor=human 写入（收到 actor=" + normalized_actor + "）；AI/系统提交请用 REVIEW。",
            extra={"status": source, "targetStatus": destination, "actor": normalized_actor},
        )
    if source == destination:
        return destination
    if source in TERMINAL_STATUSES:
        raise TaskOpError(
            "TERMINAL_STATE",
            source + " 是终态，不能再迁移到 " + destination,
            extra={"status": source, "targetStatus": destination},
        )
    if destination not in ALLOWED_TRANSITIONS[source]:
        allowed = ", ".join(sorted(ALLOWED_TRANSITIONS[source])) or "（无）"
        raise TaskOpError(
            "INVALID_TRANSITION",
            "非法状态迁移：" + source + " → " + destination + "；" + source + " 允许的去向：" + allowed,
            extra={"status": source, "targetStatus": destination,
                   "allowed": sorted(ALLOWED_TRANSITIONS[source])},
        )
    return destination


# ---------------------------------------------------------------- 路径

def project_dir_id(project: str) -> str:
    """项目目录 ID：demo / proj-demo 都接受，落到 proj-demo。"""
    text = str(project or "").strip()
    if not text:
        raise TaskOpError("INVALID_PROJECT", "项目 key 不能为空")
    return text if text.startswith("proj-") else "proj-" + text


def project_key(project: str) -> str:
    """PM_PROJECT_ID 用项目 key（§5.2 示例 demo），不带 proj- 前缀。"""
    text = str(project or "").strip()
    return text[len("proj-"):] if text.startswith("proj-") else text


def tasks_path(layout: Layout, project: str) -> Path:
    return layout.tasks_file(project_dir_id(project))


# ---------------------------------------------------------------- entities 能力探测

def _apply_change_params():
    return inspect.signature(entities.apply_change).parameters


def _create_params():
    return inspect.signature(entities.create_entity).parameters


def has_replace_lines() -> bool:
    """pm-api 是否已给 apply_change 加 replace_lines（改 headline / 勾选验收标准要用）。"""
    return "replace_lines" in _apply_change_params()


def has_indent_body() -> bool:
    return "indent_body" in _create_params()


def _require_replace_lines() -> None:
    if not has_replace_lines():
        raise TaskOpError(
            "ENTITIES_CAPABILITY_MISSING",
            "pm.entities.apply_change 还不支持 replace_lines（task-19 已向 Lead 申请）；写入路径待 pm-api 补齐后可用。",
        )


# ---------------------------------------------------------------- 写入（委托 entities）
#
# 注意：entities.Entity.body_start 是「正文末尾插入点」，不是正文起点；
# 凡是要按行做替换（勾选验收标准）都必须先用 _body_begin() 重算起点，否则会错行/越界。

_CONFLICT_HINT = "文件已被其他编辑器/命令修改，请重新读取（pm task list）后按新 revision 再提交"


def _conflict(current: int, expected: int) -> TaskOpError:
    return TaskOpError(
        "REVISION_CONFLICT",
        "revision 冲突：现在写会覆盖别人的修改（文件里 " + str(current) + "，你看到的是 " + str(expected) + "）",
        exit_code=entities.EXIT_CONFLICT,
        extra={"currentRevision": current, "expectedRevision": expected, "diffHint": _CONFLICT_HINT},
    )


def _entity_status(entity: entities.Entity, *, default: str = DEFAULT_STATUS) -> str:
    keyword = status_of_headline(entity.headline)
    if keyword:
        return keyword
    value = str(entity.props.get("PM_STATUS", "") or "").strip().upper()
    return value or default


def _noop_result(path: Path, entity: entities.Entity, task_id: str, status: str) -> entities.OpResult:
    lines = entities.read_text(path).split("\n")
    region = "\n".join(lines[entity.start : entity.end])
    audit_id, observed = entities.audit_from_region(region)
    return entities.OpResult(
        path=path,
        entity_id=task_id,
        status=status,
        revision=entity.revision,
        previous_status=status,
        previous_revision=entity.revision,
        changed=False,
        observed_at=observed,
        audit_event_id=audit_id,
    )


def _norm_key(key) -> str:
    return "".join(str(key).split()) if key else ""


def _key_holder_elsewhere(text: str, task_id: str, key: str) -> str | None:
    """key 是否被别的实体用过（entities 的 IDEMPOTENCY_KEY_REUSED 同口径）。"""
    if not key:
        return None
    pattern = re.compile(r"(?<!\S)key=" + re.escape(key) + r"(?=\s|$)")
    lines = text.split("\n")
    for block in entities.iter_entity_blocks(text):
        region = "\n".join(lines[block["start"] : block["end"]])
        if pattern.search(region):
            holder = block["props"].get("ID", "")
            if holder != task_id:
                return holder
    return None


def _idempotent_result(
    path: Path, entity: entities.Entity, task_id: str, idempotency_key
) -> entities.OpResult | None:
    """同一个 idempotency-key 已在这个实体上落过盘 → 返回首次结果（不重复写）。

    entities.apply_change 自己也会做这件事；这里提前查是为了让「先做状态机/CAS 前置校验」
    的路径也能保持与 inbox 一致的幂等语义（重放不报 409、不落盘）。
    key 用在别的实体上 → 与 inbox 一致地拒绝（IDEMPOTENCY_KEY_REUSED）。
    """
    key = _norm_key(idempotency_key)
    if not key:
        return None
    text = entities.read_text(path)
    lines = text.split("\n")
    region = "\n".join(lines[entity.start : entity.end])
    audit_id, observed = entities.audit_from_region(region, key)
    if not audit_id:
        holder = _key_holder_elsewhere(text, task_id, key)
        if holder is not None:
            raise entities.EntityError(
                "IDEMPOTENCY_KEY_REUSED",
                "idempotency key " + key + " 已经用在 " + holder + " 上，不能换目标重复使用",
            )
        return None
    status = str(entity.props.get("PM_STATUS", "") or "").strip().upper() or _entity_status(entity)
    return entities.OpResult(
        path=path,
        entity_id=task_id,
        status=status,
        revision=entity.revision,
        previous_status=_entity_status(entity),
        previous_revision=entity.revision,
        changed=False,
        idempotent=True,
        observed_at=observed,
        audit_event_id=audit_id,
    )


def transition_task(
    path: Path,
    task_id: str,
    *,
    to_status: str,
    expected_revision: int,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> entities.OpResult:
    """状态迁移：改 headline 的 TODO 关键字 + PM_STATUS + revision + 审计（同一次原子写）。"""
    _require_replace_lines()
    path = Path(path)
    target = normalize_status(to_status)
    entity = entities.load_entity(path, task_id, default_status=DEFAULT_STATUS)
    current = _entity_status(entity)
    validate_transition(current, target, actor=actor)
    if entity.revision != expected_revision:
        replay = _idempotent_result(path, entity, task_id, idempotency_key)
        if replay is not None:
            return replay
        raise _conflict(entity.revision, expected_revision)
    if current == target and status_of_headline(entity.headline) == target:
        replay = _idempotent_result(path, entity, task_id, idempotency_key)
        if replay is not None:
            return replay
        return _noop_result(path, entity, task_id, current)

    new_headline = replace_headline_keyword(entity.headline, target)
    raw_lines = entities.read_text(path).split("\n")
    new_body, added_criteria_ids = _ensure_criteria_ids(_raw_body_lines(raw_lines, entity))
    extra_kwargs = {}
    if added_criteria_ids:
        # 迁移顺带在下一次写任务时完成：同一次 CAS，审计标 op=criteria-ids-init
        extra_kwargs["replace_body"] = new_body
        extra_kwargs["audit_extra"] = {"op": "criteria-ids-init",
                                       "ids": str(len(added_criteria_ids)), "with": "transition"}

    def _validate(ent: entities.Entity, target_status: str) -> None:
        validate_transition(_entity_status(ent), target_status, actor=actor)

    return entities.apply_change(
        path,
        task_id,
        expected_revision=expected_revision,
        status=target,
        replace_lines={0: new_headline},
        actor=actor,
        reason=reason,
        idempotency_key=idempotency_key,
        dry_run=dry_run,
        now=now,
        **extra_kwargs,
        validate=_validate,
        default_status=DEFAULT_STATUS,
    )


def _body_begin(lines: list[str], entity: entities.Entity) -> int:
    """实体正文第一条的绝对行下标。

    注意 entities 的 Entity.body_start 是**正文末尾的插入点**（append_body 用），
    不是正文起点；这里按抽屉/LOGBOOK 的已知位置重新算出起点。
    """
    if entity.drawer is None:
        raise TaskOpError(
            "LEGACY_UNTRACKED",
            entity.entity_id + " 没有 :PROPERTIES: 抽屉，无法按身份处理；请先补 :ID: / 状态字段。",
        )
    cursor = entity.drawer[1]
    if cursor < len(lines) and lines[cursor].strip() == ":LOGBOOK:":
        cursor += 1
        while cursor < len(lines) and lines[cursor].strip() != ":END:":
            cursor += 1
        if cursor < len(lines):
            cursor += 1
    return cursor


def _raw_body_lines(lines: list[str], entity) -> list[str]:
    """实体正文的**原始行**（保留行首缩进；不含抽屉/LOGBOOK 与尾部空行）。

    entities 的 entity.body 会按 inbox 旧惯例把「3 空格缩进」去掉；而迁移 / 勾选对外承诺
    「只加 ID token / 只改复选框字符，其余一字不改」——行首缩进也是内容，所以写路径必须用原始行。
    """
    begin = _body_begin(lines, entity)
    end = min(int(getattr(entity, "end", len(lines))), len(lines))
    raw = list(lines[begin:end])
    while raw and not raw[-1].strip():
        raw.pop()
    return raw


def _criteria_section_missing_note(lines: list[str]) -> str:
    """认不到 *** 验收标准 节时给人的可操作原因（迁移不许静默）。

    Org 里标题必须顶格（第 0 列）才算标题；缩进的标题只是普通正文 —— 那是真实库里另一类形态，
    这里如实告诉用户「看到缩进的标题了」，别只说一句「没得改」。
    """
    for line in lines:
        if re.match(r"^[ \t]+\*{3,}\s*验收标准\s*:?\s*$", line):
            return "未找到 *** 验收标准 节：节标题必须顶格（第 0 列），当前标题带了缩进"
    return "该任务没有 *** 验收标准 节（没有验收标准可迁移）"


#: 验收标准节的子标题名（level>=3）。
CRITERIA_HEADLINE_NAME = "验收标准"


def _criteria_section_bullets(lines: list[str]) -> list[int]:
    """验收标准节里所有 - [ ] 行的下标（含嵌套项，按文件顺序）。"""
    span = _section_span(lines, CRITERIA_HEADLINE_NAME)
    if span is None:
        return []
    return [index for index in range(span[0] + 1, span[1]) if _CRITERION.match(lines[index])]


def _criterion_ids(lines: list[str]) -> list[str]:
    ids: list[str] = []
    for index in _criteria_section_bullets(lines):
        match = _CRITERION.match(lines[index])
        token = _CRITERION_ID_TOKEN.match(match.group("text") or "")
        if token is not None:
            ids.append(token.group("id"))
    return ids


def _ensure_criteria_ids(lines: list[str]) -> tuple[list[str], list[str]]:
    """给验收标准节里缺 ID 的行补 ID：**只插入 [c-xxxx]，文本与勾选态逐字节不动**。

    返回 (新的行列表, 新补的 id 列表)；没有可补的就原样返回（幂等）。
    """
    result = list(lines)
    existing = set(_criterion_ids(result))
    added: list[str] = []
    for index in _criteria_section_bullets(result):
        line = result[index]
        match = _CRITERION.match(line)
        if _CRITERION_ID_TOKEN.match(match.group("text") or ""):
            continue
        new_id = new_criterion_id(existing)
        existing.add(new_id)
        added.append(new_id)
        insert_at = match.end("mark") + 1  # 紧接着 checkbox 的 ] 之后插入
        result[index] = line[:insert_at] + " [" + new_id + "]" + line[insert_at:]
    return result, added


def _criterion_entries(lines: list[str]) -> list[dict]:
    """验收标准节的条目（含 id/文本/勾选态/行下标），供选择器定位。"""
    entries: list[dict] = []
    for position, index in enumerate(_criteria_section_bullets(lines)):
        match = _CRITERION.match(lines[index])
        rest = match.group("text") or ""
        token = _CRITERION_ID_TOKEN.match(rest)
        entries.append({
            "positions": position,
            "index": index,
            "id": token.group("id") if token else None,
            "text": (rest[token.end():] if token else rest).rstrip(),
            "done": match.group("mark").lower() == "x",
        })
    return entries


def _resolve_criterion(lines: list[str], *, criterion_id=None, index=None, text=None) -> dict:
    """按 id / 序号 / 文本定位一条验收标准；三选一由调用方保证。

    找不到一律 CRITERION_NOT_FOUND，extra 里带现有 ids（前端/CLI 能直接用）。
    """
    entries = _criterion_entries(lines)
    if not entries:
        raise TaskOpError("CRITERIA_MISSING", "该任务没有验收标准（*** 验收标准 + - [ ] 列表项）")
    ids = [entry["id"] for entry in entries if entry["id"]]
    if criterion_id is not None:
        wanted = str(criterion_id).strip()
        for entry in entries:
            if entry["id"] == wanted:
                return entry
        raise TaskOpError(
            "CRITERION_NOT_FOUND",
            "找不到 id 为 " + wanted + " 的验收标准",
            extra={"criterionId": wanted, "ids": ids, "criterionCount": len(entries)},
        )
    if index is not None:
        if not isinstance(index, int) or index < 0 or index >= len(entries):
            raise TaskOpError(
                "CRITERION_NOT_FOUND",
                "验收标准序号越界：" + str(index) + "（当前 " + str(len(entries)) + " 条，从 0 开始）",
                extra={"index": index, "ids": ids, "criterionCount": len(entries)},
            )
        return entries[index]
    wanted_text = " ".join(str(text or "").split())
    matches = [entry for entry in entries if entry["text"] == wanted_text]
    if not matches:
        raise TaskOpError(
            "CRITERION_NOT_FOUND",
            "找不到文本为 " + repr(wanted_text) + " 的验收标准",
            extra={"text": wanted_text, "ids": ids, "criterionCount": len(entries)},
        )
    if len(matches) > 1:
        raise TaskOpError(
            "AMBIGUOUS_CRITERION",
            "文本 " + repr(wanted_text) + " 匹配到多条验收标准，请改用 --criterion-id",
            extra={"text": wanted_text, "ids": [entry["id"] for entry in matches]},
        )
    return matches[0]


def _tag_criterion(result: entities.OpResult, entry) -> entities.OpResult:
    """把定位到的标准项 id 带进返回 extra（供 CLI/JSON 直接展示）。"""
    result.extra = dict(result.extra or {})
    if entry and entry.get("id"):
        result.extra["criterionId"] = entry["id"]
    return result


def init_criterion_ids(
    path: Path,
    task_id: str,
    *,
    expected_revision: int,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> entities.OpResult:
    """给缺稳定 ID 的验收标准项补 ID（只加 ID，文本/勾选态一字不改）。

    一次 CAS + 一条审计 op=criteria-ids-init；幂等（没得补 → changed:false）；
    终态任务拒绝（TASK_TERMINAL）。返回的 extra 里带 criteriaIdsAdded。
    """
    path = Path(path)
    entity = entities.load_entity(path, task_id, default_status=DEFAULT_STATUS)
    if entity.revision != expected_revision:
        replay = _idempotent_result(path, entity, task_id, idempotency_key)
        if replay is not None:
            return _tag_added(replay, [])
        raise _conflict(entity.revision, expected_revision)
    status = _entity_status(entity)
    if status in TERMINAL_STATUSES:
        raise TaskOpError(
            "TASK_TERMINAL",
            "任务 " + task_id + " 已是终态 " + status + "，拒绝迁移验收标准 ID",
            extra={"taskId": task_id, "status": status},
        )
    raw_lines = entities.read_text(path).split("\n")
    body = _raw_body_lines(raw_lines, entity)
    new_body, added = _ensure_criteria_ids(body)
    if not added:
        replay = _idempotent_result(path, entity, task_id, idempotency_key)
        if replay is not None:
            return _tag_added(replay, [])
        result = _tag_added(_noop_result(path, entity, task_id, status), [])
        if _section_span(body, CRITERIA_HEADLINE_NAME) is None:
            # 不许静默：没有可迁移的节时也要给一句可操作原因
            result.extra["note"] = _criteria_section_missing_note(body)
        return result
    return _tag_added(entities.apply_change(
        path,
        task_id,
        expected_revision=expected_revision,
        replace_body=new_body,
        actor=actor,
        reason=reason or "补齐验收标准项稳定 ID",
        idempotency_key=idempotency_key,
        dry_run=dry_run,
        now=now,
        audit_extra={"op": "criteria-ids-init", "ids": str(len(added))},
        default_status=DEFAULT_STATUS,
    ), added)


def _tag_added(result: entities.OpResult, added) -> entities.OpResult:
    result.extra = dict(result.extra or {})
    result.extra["criteriaIdsAdded"] = list(added)
    return result


def _criteria_with_added(lines: list[str], base: int, added) -> list[dict]:
    """dry-run / no-op 时按计划把新 ID 填进只读形状（added 与缺 ID 的行同序）。"""
    entries = _criterion_entries(lines)
    pool = iter(added or [])
    for entry in entries:
        if not entry["id"]:
            entry["id"] = next(pool, None)
    return [{"id": entry["id"], "text": entry["text"], "done": entry["done"],
             "line": base + entry["index"] + 1} for entry in entries]


def _validate_evidence_field(name: str, value, allowed) -> str:
    text = " ".join(str(value or "").split())
    if text not in allowed:
        raise TaskOpError(
            "INVALID_EVIDENCE_FIELD",
            name + " 必须是 " + " / ".join(allowed) + "（收到 " + repr(value) + "）",
            extra={"field": name, "value": value, "allowed": list(allowed)},
        )
    return text


def _append_evidence_line(body: list[str], line: str) -> list[str]:
    """把一条证据行写进正文：有节 → 追加到节末尾；没有 → 在验收标准之后新建节。"""
    result = list(body)
    span = _section_span(result, EVIDENCE_HEADLINE)
    if span is not None:
        insert_at = span[1]
        while insert_at > span[0] + 1 and not result[insert_at - 1].strip():
            insert_at -= 1
        result.insert(insert_at, line)
        return result
    criteria_span = _section_span(result, CRITERIA_HEADLINE_NAME)
    if criteria_span is not None:
        insert_at = criteria_span[1]
        while insert_at > criteria_span[0] + 1 and not result[insert_at - 1].strip():
            insert_at -= 1
        result[insert_at:insert_at] = ["", "*** " + EVIDENCE_HEADLINE, line]
        return result
    while result and not result[-1].strip():
        result.pop()
    if result:
        result.append("")
    result.extend(["*** " + EVIDENCE_HEADLINE, line])
    return result


def _evidence_duplicate(entries, *, criterion_id, kind, result, ref, actor, note):
    for entry in entries:
        if (entry.get("criterionId") == criterion_id and entry.get("kind") == kind
                and entry.get("result") == result and entry.get("ref") == ref
                and entry.get("actor") == actor and (entry.get("note") or "") == (note or "")):
            return entry
    return None


def _tag_evidence(result: entities.OpResult, entry, count: int) -> entities.OpResult:
    result.extra = dict(result.extra or {})
    result.extra["evidence"] = entry
    result.extra["evidenceCount"] = count
    return result


def list_evidence(path: Path, task_id: str) -> list[dict]:
    """只读该任务自己的 *** 证据（验收） 节（节外行不收）。"""
    path = Path(path)
    entity = entities.load_entity(path, task_id, default_status=DEFAULT_STATUS)
    lines = entities.read_text(path).split("\n")
    return parse_task_evidence(_raw_body_lines(lines, entity), base=_body_begin(lines, entity))


def add_evidence(
    path: Path,
    task_id: str,
    *,
    criterion_id: str,
    kind: str,
    result: str,
    ref: str,
    note: str = "",
    actor: str = "human",
    expected_revision: int,
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> entities.OpResult:
    """给某条验收标准追加一条证据（append-only）。

    校验：criterion-id 必须存在（否则 CRITERION_NOT_FOUND，extra 带 ids）；kind/result/actor 枚举；
    ref 不得含 |（塞不下写 --note）。写入走一次 CAS + 一条审计 op=evidence-add criterion=… kind=… result=…；
    六字段（criterionId/kind/result/ref/actor/note，不含自动生成的 at）全同的重复提交 → changed:false。
    """
    path = Path(path)
    entity = entities.load_entity(path, task_id, default_status=DEFAULT_STATUS)
    if entity.revision != expected_revision:
        replay = _idempotent_result(path, entity, task_id, idempotency_key)
        if replay is not None:
            return _tag_evidence(replay, None, len(list_evidence(path, task_id)))
        raise _conflict(entity.revision, expected_revision)
    status = _entity_status(entity)
    if status in TERMINAL_STATUSES:
        raise TaskOpError(
            "TASK_TERMINAL",
            "任务 " + task_id + " 已是终态 " + status + "，拒绝新增证据",
            extra={"taskId": task_id, "status": status},
        )
    kind = _validate_evidence_field("kind", kind, EVIDENCE_KINDS)
    result = _validate_evidence_field("result", result, EVIDENCE_RESULTS)
    actor = _validate_evidence_field("actor", actor, EVIDENCE_ACTORS)
    ref_text = str(ref or "").strip()
    if "|" in ref_text:
        raise TaskOpError(
            "INVALID_EVIDENCE_REF",
            "ref 里不能含 |（结构分隔符）；塞不下的内容请写进 --note",
            extra={"ref": ref, "hint": "把带 | 的部分放到 --note，ref 只留 commit / 路径 / URL / 命令"},
        )
    if not ref_text:
        raise TaskOpError("INVALID_EVIDENCE_REF", "ref 不能为空（commit / 路径 / URL / 命令文本）")

    raw_lines = entities.read_text(path).split("\n")
    new_body, added_ids = _ensure_criteria_ids(_raw_body_lines(raw_lines, entity))
    criteria_ids = [entry["id"] for entry in _criterion_entries(new_body) if entry["id"]]
    if criterion_id not in criteria_ids:
        hint = "先 pm task criteria init-ids 给标准项补稳定 ID" if not criteria_ids else \
               "用 pm task show --json 的 criteria[].id 里现有的值"
        raise TaskOpError(
            "CRITERION_NOT_FOUND",
            "找不到 id 为 " + str(criterion_id) + " 的验收标准",
            extra={"criterionId": criterion_id, "ids": criteria_ids, "hint": hint},
        )
    note_text = str(note or "").strip()
    entries = parse_task_evidence(new_body, base=0)
    at = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    duplicate = _evidence_duplicate(entries, criterion_id=criterion_id, kind=kind, result=result,
                                    ref=ref_text, actor=actor, note=note_text)
    if duplicate is not None:
        replay = _idempotent_result(path, entity, task_id, idempotency_key)
        if replay is not None:
            return _tag_evidence(replay, duplicate, len(entries))
        return _tag_evidence(_noop_result(path, entity, task_id, status), duplicate, len(entries))

    entry = {
        "criterionId": criterion_id, "kind": kind, "result": result, "ref": ref_text,
        "at": at, "actor": actor, "note": note_text or None,
    }
    line = render_evidence_line(entry)
    body2 = _append_evidence_line(new_body, line)
    entry_with_meta = dict(entry)
    entry_with_meta["raw"] = line
    entry_with_meta["line"] = None
    audit_extra = (
        {"op": "criteria-ids-init", "ids": str(len(added_ids)), "with": "evidence-add"}
        if added_ids else
        {"op": "evidence-add", "criterion": criterion_id, "kind": kind, "result": result}
    )
    result_op = entities.apply_change(
        path,
        task_id,
        expected_revision=expected_revision,
        replace_body=body2,
        actor=actor,
        reason=reason or ("新增验收证据 ref=" + ref_text[:12]),
        idempotency_key=idempotency_key,
        dry_run=dry_run,
        now=now,
        audit_extra=audit_extra,
        default_status=DEFAULT_STATUS,
    )
    if not dry_run:
        refreshed = list_evidence(path, task_id)
        for item in refreshed:
            if (item.get("criterionId") == criterion_id and item.get("kind") == kind
                    and item.get("result") == result and item.get("ref") == ref_text
                    and item.get("actor") == actor and (item.get("note") or "") == note_text):
                entry_with_meta = item
                break
        return _tag_evidence(result_op, entry_with_meta, len(refreshed))
    return _tag_evidence(result_op, entry_with_meta, len(entries) + 1)


def remove_evidence(
    path: Path,
    task_id: str,
    evidence_id: str,
    *,
    expected_revision: int,
    reason: str = "",
    actor: str = "human",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> entities.OpResult:
    """按证据 id 从任务上**移除一条证据**（其余证据与正文其它部分逐字保留）。

    - id 由内容寻址（见 `EVIDENCE_ID_FIELDS`），`pm task evidence list/show` 都给出它；
    - 找不到 → `EVIDENCE_NOT_FOUND`（exit 2，extra 带现有 ids），**不静默成功**；
    - 走同一套写路径：CAS（`expected_revision` 不匹配 → REVISION_CONFLICT exit 3、零写入）+ 一条审计
      （`op=evidence-rm criterion=… evidence=…`）；
    - 终态任务（DONE/CANCELLED）拒绝（`TASK_TERMINAL`），与 add 一致：已封存的人类记录不在这里改。
    """
    path = Path(path)
    target_id = str(evidence_id or "").strip()
    if not target_id:
        raise TaskOpError("EVIDENCE_ID_REQUIRED", "需要证据 id（先 pm task evidence list 看 id）")
    entity = entities.load_entity(path, task_id, default_status=DEFAULT_STATUS)
    if entity.revision != expected_revision:
        replay = _idempotent_result(path, entity, task_id, idempotency_key)
        if replay is not None:
            return _tag_evidence(replay, None, len(list_evidence(path, task_id)))
        raise _conflict(entity.revision, expected_revision)
    status = _entity_status(entity)
    if status in TERMINAL_STATUSES:
        raise TaskOpError(
            "TASK_TERMINAL",
            "任务 " + task_id + " 已是终态 " + status + "，拒绝移除证据",
            extra={"taskId": task_id, "status": status},
        )
    raw_lines = entities.read_text(path).split("\n")
    body = _raw_body_lines(raw_lines, entity)
    entries = parse_task_evidence(body, base=0)
    target = next((item for item in entries if item.get("id") == target_id), None)
    if target is None:
        raise TaskOpError(
            "EVIDENCE_NOT_FOUND",
            "任务 " + task_id + " 上没有 id 为 " + target_id + " 的证据",
            extra={"taskId": task_id, "evidenceId": target_id,
                   "ids": [item.get("id") for item in entries]},
        )
    body2 = [line for offset, line in enumerate(body) if offset != target["line"] - 1]
    result_op = entities.apply_change(
        path,
        task_id,
        expected_revision=expected_revision,
        replace_body=body2,
        actor=actor,
        reason=reason or ("移除验收证据 " + target_id + "（ref=" + str(target.get("ref") or "")[:12] + "）"),
        idempotency_key=idempotency_key,
        dry_run=dry_run,
        now=now,
        audit_extra={"op": "evidence-rm", "criterion": target.get("criterionId") or "",
                     "evidence": target_id},
        default_status=DEFAULT_STATUS,
    )
    remaining = list_evidence(path, task_id) if not dry_run else [
        item for item in entries if item.get("id") != target_id
    ]
    return _tag_evidence(result_op, target, len(remaining))


def set_criterion(
    path: Path,
    task_id: str,
    *,
    index: int | None = None,
    criterion_id: str | None = None,
    text: str | None = None,
    done: bool = True,
    expected_revision: int,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> entities.OpResult:
    """勾选/取消一条验收标准（走 CAS + 审计；不改状态机）。

    选择器三选一（调用方保证）：criterion_id（稳定 ID，推荐）/ index（0-based，deprecated）/
    text（精确文本，deprecated）。顺带把缺 ID 的标准项补上 —— 同一次 CAS；
    这次写入的审计会带 op=criteria-ids-init（并在 extra 记 n）。
    """
    path = Path(path)
    entity = entities.load_entity(path, task_id, default_status=DEFAULT_STATUS)
    if entity.revision != expected_revision:
        replay = _idempotent_result(path, entity, task_id, idempotency_key)
        if replay is not None:
            return replay
        raise _conflict(entity.revision, expected_revision)

    raw_lines = entities.read_text(path).split("\n")
    new_body, added_ids = _ensure_criteria_ids(_raw_body_lines(raw_lines, entity))
    entry = _resolve_criterion(new_body, criterion_id=criterion_id, index=index, text=text)
    line = new_body[entry["index"]]
    match = _CRITERION.match(line)
    already = (match.group("mark").lower() == "x") == bool(done)
    if already and not added_ids:
        replay = _idempotent_result(path, entity, task_id, idempotency_key)
        if replay is not None:
            return _tag_criterion(replay, entry)
        return _tag_criterion(_noop_result(path, entity, task_id, _entity_status(entity)), entry)

    mark = "x" if done else " "
    new_body[entry["index"]] = line[:match.start("mark")] + mark + line[match.end("mark"):]
    audit_extra = ({"op": "criteria-ids-init", "ids": str(len(added_ids)), "with": "check"}
                   if added_ids else None)
    return _tag_criterion(entities.apply_change(
        path,
        task_id,
        expected_revision=expected_revision,
        replace_body=new_body,
        actor=actor,
        reason=reason or ("勾选验收标准" if done else "取消勾选验收标准"),
        idempotency_key=idempotency_key,
        dry_run=dry_run,
        now=now,
        audit_extra=audit_extra,
        default_status=DEFAULT_STATUS,
    ), entry)


def _create_props(task: dict) -> dict[str, str]:
    props = {
        "PM_PROJECT_ID": task.get("project_id"),
        "PM_SOURCE_INBOX_ID": task.get("source_inbox_id"),
        "PM_AI": "t" if task.get("ai") else "nil",
        "PM_ASSIGNEE": task.get("assignee"),
    }
    if task.get("extra_properties"):
        props.update({k: v for k, v in task["extra_properties"].items()})
    return {key: value for key, value in props.items() if value not in (None, "")}


def _create_entity_on(path: Path, task: dict, *, actor: str, now: datetime | None):
    status = resolve_status(task)
    title = escape_headline(task.get("title"))
    kwargs = {
        "entity_id": task["id"],
        "kind": "task",
        "status": status,
        "headline": status + ((" " + title) if title else ""),
        "section": TASKS_SECTION,
        "properties": _create_props(task),
        "body_lines": render_task_body(task),
        "actor": actor,
        "now": now,
    }
    if has_indent_body():
        kwargs["indent_body"] = False
    return entities.create_entity(path, **kwargs)


def _headline_sequence(lines: list[str], *, level: int = 2) -> list[str]:
    """第 level 层、col-0 的 headline 行序列（内容 + 顺序）。"""
    out: list[str] = []
    for line in lines:
        match = _AT_COL0.match(line)
        if match is not None and len(match.group("stars")) == level:
            out.append(line)
    return out


def _swallowed_headline_lines(text: str, *, headline: str | None = None, level: int = 2) -> list[int]:
    """哪些 **col-0 的 level 层 headline 行**没有被实体扫描识别为块起点（1-based 行号）。

    这些行就是被"没闭合的抽屉"吞掉的块 —— 它们还在文件里，但实体寻址看不见。
    """
    lines = text.split("\n")
    if headline:
        from pm.humanwrite import find_section

        span = find_section(lines, headline)
        start, end = span if span is not None else (0, len(lines))
    else:
        start, end = 0, len(lines)
    raw = [
        index
        for index in range(start, min(end, len(lines)))
        if (match := _AT_COL0.match(lines[index])) is not None
        and len(match.group("stars")) == level
    ]
    parsed = {block["start"] for block in entities.iter_entity_blocks(text, headline=headline, level=level)}
    return [index + 1 for index in raw if index not in parsed]


def _assert_structure_intact(before: list[str], after_text: str, *, headline: str | None, level: int = 2) -> None:
    """写入前结构守卫：补 ID 只能**插入属性/审计行**，绝不能吞掉后面的块。

    两件事：① headline 序列（内容+顺序）一字不变；② 每一行 col-0 headline 都必须仍被识别为块起点。
    漏一个 `:END:` 就会让抽屉吃到后面块的 `:END:`：那些 `:ID:` 还在文件里，实体解析却看不到
    （表现为"`pm task show` 正常、写路径 NOT_FOUND"）。守卫把这种损坏挡在写盘之前。
    """
    after_lines = after_text.split("\n")
    if _headline_sequence(before, level=level) != _headline_sequence(after_lines, level=level):
        raise entities.EntityError(
            "DRAWER_BREAKS_HEADLINES",
            "补 :ID: 会改变 headline 序列（抽屉没闭合？）——拒绝写盘，文件未改动",
            extra={"level": level, "before": len(_headline_sequence(before, level=level)),
                   "after": len(_headline_sequence(after_lines, level=level))},
        )
    swallowed = _swallowed_headline_lines(after_text, headline=headline, level=level)
    if swallowed:
        raise entities.EntityError(
            "DRAWER_BREAKS_HEADLINES",
            "补 :ID: 后有 headline 没被识别为块（抽屉没闭合，把后面的块吞了）——拒绝写盘，文件未改动；"
            "可疑行号：" + ", ".join(str(item) for item in swallowed[:5]),
            extra={"level": level, "swallowedLines": swallowed},
        )


def init_task_ids(
    path: Path,
    *,
    project_id: str | None = None,
    actor: str = "human",
    reason: str = "",
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    """给**缺 `:ID:` 的任务块**补上铸造属性 + 一条审计（task-01M51Y84… 的修复路径）。

    - 只处理 `* 任务` 小节里第 2 层、且抽屉里没有 `:ID:` 的块；补 `:ID:`/`:PM_KIND: task`/`:PM_STATUS:`（+ 需要时 `:PM_PROJECT_ID:`）；
    - 每个块在它自己的 `:LOGBOOK:` 里留一条 `op=task-id-stamp` 审计行；整文件一次原子写；
    - **幂等**：没有待补的块 → `changed:false`；`--dry-run` 零写入。
    """
    path = Path(path)
    text = entities.read_text(path)
    lines = text.split("\n")
    blocks = entities.iter_entity_blocks(text, headline=TASKS_SECTION, level=2)
    targets = [block for block in blocks if not str(block["props"].get("ID") or "").strip()]
    if not targets:
        return {"changed": False, "count": 0, "stamped": [], "path": str(path)}
    at = now or datetime.now().astimezone()
    new_lines = list(lines)
    stamped: list[dict] = []
    for block in sorted(targets, key=lambda item: item["start"], reverse=True):
        task_id = new_task_id()
        status = status_of_headline(block["headline"]) or DEFAULT_STATUS
        props = {"ID": task_id, "PM_KIND": "task", "PM_STATUS": status}
        if project_id and not str(block["props"].get("PM_PROJECT_ID") or "").strip():
            props["PM_PROJECT_ID"] = project_id
        revision = int(block["props"].get("PM_REVISION") or 1)
        audit_id = entities.new_audit_id(at)
        # entities.audit_line 自带 3 空格缩进（与 LOGBOOK 抽屉一致），这里不要再加
        log = entities.audit_line(
            at=at, entity_id=task_id, audit_id=audit_id, actor=actor,
            from_status="(stamped)", to_status=status, revision=revision, reason=reason,
            extra={"op": "task-id-stamp"},
        )
        block_lines = new_lines[block["start"]:block["end"]]
        # 找抽屉 :END:；没有抽屉就在 headline 之后造一个
        drawer_end = None
        for offset, line in enumerate(block_lines):
            if offset and line.strip() == ":END:":
                drawer_end = offset
                break
        if drawer_end is None:
            insert_at = block["start"] + 1
            new_lines[insert_at:insert_at] = (
                ["   :PROPERTIES:"] + ["   :" + name + ": " + value for name, value in props.items()]
                + ["   :END:", "   :LOGBOOK:", log]
            )
        else:
            absolute_end = block["start"] + drawer_end
            new_lines[absolute_end:absolute_end] = [
                "   :" + name + ": " + value for name, value in props.items()
            ]
            # 抽屉之后：已有 :LOGBOOK: 就插到它的 :END: 之前；否则紧跟抽屉新起一个
            absolute_end += len(props)
            tail = new_lines[absolute_end + 1:block["end"] + (len(props) - 1)]
            logbook_end = None
            for offset, line in enumerate(tail):
                if line.strip() == ":LOGBOOK:":
                    for inner in range(offset + 1, len(tail)):
                        if tail[inner].strip() == ":END:":
                            logbook_end = absolute_end + 1 + inner
                            break
                    break
            if logbook_end is not None:
                new_lines.insert(logbook_end, log)
            else:
                # **必须带闭合 :END:** —— 漏了它，抽屉会一直吃到下一个块的 :END:，
                # 把后面的块吞进抽屉里 ⇒ 那些 :ID: 明明在文件里却寻址不到（task-01M52D77… 的 422 就是这个）。
                new_lines[absolute_end + 1:absolute_end + 1] = ["   :LOGBOOK:", log, "   :END:"]
        stamped.append({"id": task_id, "title": headline_keyword_rest(block["headline"])[2], "line": block["line"]})
    newline = "\r\n" if "\r\n" in text else "\n"
    _assert_structure_intact(lines, newline.join(new_lines), headline=TASKS_SECTION, level=2)
    if not dry_run:
        org.write_atomic(path, newline.join(new_lines), newline=newline)
    return {
        "changed": True,
        "count": len(stamped),
        "stamped": sorted(stamped, key=lambda item: item["line"]),
        "path": str(path),
    }


def command_task_init_ids(args) -> int:
    """pm task init-ids：给缺 :ID: 的任务块补铸造属性（幂等；dry-run 零写入）。"""
    json_mode = bool(getattr(args, "json", False))
    layout, gate_error = _write_layout(args, json_mode)
    if layout is None:
        return _emit_error(json_mode, TaskOpError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    path = tasks_path(layout, args.project)
    try:
        outcome = init_task_ids(
            path, project_id=project_key(args.project), actor=args.actor,
            reason=str(getattr(args, "reason", "") or ""), dry_run=bool(args.dry_run),
        )
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)
    payload = {
        "ok": True,
        "project": project_key(args.project),
        "path": _relative(path, layout),
        "changed": outcome["changed"],
        "count": outcome["count"],
        "stamped": outcome["stamped"],
    }
    if getattr(args, "dry_run", False):
        payload["dry_run"] = True
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    prefix = "[dry-run] " if getattr(args, "dry_run", False) else ""
    if not outcome["changed"]:
        print(prefix + "没有需要补 :ID: 的任务块（" + payload["path"] + "）")
        return 0
    print(prefix + "已补 :ID: " + str(outcome["count"]) + " 个任务块（" + payload["path"] + "）：")
    for item in payload["stamped"]:
        print("  " + item["id"] + "  " + str(item["title"])[:50] + "  (line " + str(item["line"]) + ")")
    return 0


def create_task(
    path: Path,
    task: dict,
    *,
    actor: str = "human",
    dry_run: bool = False,
    now: datetime | None = None,
) -> tuple[int, str, list[str] | None]:
    """把 build_task 造出的记录写入 tasks.org；返回 (1-based 行号, auditEventId, 预览块)。

    dry-run 用临时副本真跑一遍 create_entity 再丢弃，保证「预演 == 真写」，
    真实库一个字节都不碰。
    """
    path = Path(path)
    # **负例有牙**（task-01M51Y84…）：写入路径产出的块必须带 :ID:/:PM_KIND:/:PM_STATUS: ——
    # 缺了就明确报错，绝不静默写出"CLI 寻址不到"的条目。
    pairs = _property_pairs(task)
    missing = [name for name in ("ID", "PM_KIND", "PM_STATUS") if not str(pairs.get(name) or "").strip()]
    if missing:
        raise entities.EntityError(
            "TASK_STAMP_INCOMPLETE",
            "任务块缺少必填属性 " + "/".join(missing) + "（:{0}:）——拒绝写入；"
            "请走 build_task/create_task 这套铸造路径，别自己拼属性".format(":".join(missing)),
            exit_code=entities.EXIT_INPUT,
        )
    if not dry_run:
        line, audit_id = _create_entity_on(path, task, actor=actor, now=now)
        return line, audit_id, None

    with tempfile.TemporaryDirectory() as tmp:
        preview_path = Path(tmp) / path.name
        if path.is_file():
            shutil.copyfile(path, preview_path)
        line, audit_id = _create_entity_on(preview_path, task, actor=actor, now=now)
        preview_lines = entities.read_text(preview_path).split("\n")
        return line, audit_id, _block_at(preview_lines, line - 1)


def _block_at(lines: list[str], start: int) -> list[str]:
    """取从 start 起的实体块（下一个同级/更高级 headline 前）。"""
    match = _AT_COL0.match(lines[start]) if 0 <= start < len(lines) else None
    level = len(match.group("stars")) if match is not None else 2
    end = len(lines)
    for index in range(start + 1, len(lines)):
        head = _AT_COL0.match(lines[index])
        if head is not None and len(head.group("stars")) <= level:
            end = index
            break
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


# ---------------------------------------------------------------- Agent Team 任务板导入

#: 幂等锚点：board task id 写在这个属性上。
TEAM_TASK_PROPERTY = "PM_TEAM_TASK_ID"

#: board 状态 → org 任务状态。**completed 落 REVIEW，绝不写 DONE**（DONE 只能由人写）。
TEAM_STATUS_MAP = {
    "pending": STATUS_TODO,
    "in_progress": STATUS_DOING,
    "completed": STATUS_REVIEW,
}

#: 未知 board 状态的落点（会单独报告，不静默）。
TEAM_UNKNOWN_STATUS = STATUS_TODO

#: 判断「org 状态是否比 team 映射更靠后」；更靠后 → kept，什么都不动。
TEAM_PROGRESS_RANK = {
    STATUS_INBOX: 0, STATUS_TODO: 1, STATUS_NEXT: 2,
    STATUS_DOING: 3, STATUS_WAITING: 3, STATUS_BLOCKED: 3,
    STATUS_REVIEW: 4, STATUS_DONE: 5, STATUS_CANCELLED: 5,
}

#: 来源行前缀（刷新时按它在正文里定位那一行）。
TEAM_SOURCE_PREFIX = "来源：Agent Team "

#: --parent 模式的登记属性：逗号分隔的 board task id，按快照顺序。
TEAM_TASKS_PROPERTY = "PM_TEAM_TASKS"

#: 子任务记录的正文节名（每行 - <id> | <subject> | <status> | owner=…）。
TEAM_CHILDREN_HEADLINE = "子任务（会话规划）"

#: DAG 的正文节名（本期只读：解析 - <a> -> <b>）。
TEAM_DAG_HEADLINE = "任务 DAG"

_BULLET_LINE = re.compile(r"^[ \t]*[-+]\s+(?P<text>.*)$")
_DAG_EDGE = re.compile(r"^(?P<src>\S+)\s*->\s*(?P<dst>\S+)$")


def normalize_team_status(value) -> str:
    """board 状态归一化：pending / In Progress / in-progress 都折成 in_progress。"""
    text = str(value or "").strip().lower().replace("-", " ")
    return "_".join(text.split())


def _team_field(item: dict, *names):
    for name in names:
        value = item.get(name)
        if value is not None and str(value).strip():
            return value
    return ""


def _team_task_id(item: dict) -> str:
    return str(_team_field(item, "id", "taskId", "task_id", "teamTaskId")).strip()


def _team_join(value) -> str:
    if isinstance(value, (list, tuple)):
        return "、".join(str(part) for part in value if str(part).strip())
    return _collapse(value)


def team_source_line(item: dict, team_id: str, snapshot_status: str) -> str:
    """『来源：Agent Team task-<n> · owner=… · blockedBy=… · writeScopes=…』（缺字段容忍）。"""
    parts = ["来源：Agent Team " + team_id]
    owner = _collapse(_team_field(item, "ownerName", "owner", "assignee"))
    if owner:
        parts.append("owner=" + owner)
    blocked = _team_join(item.get("blockedBy") if item.get("blockedBy") is not None else item.get("blocked_by"))
    if blocked:
        parts.append("blockedBy=" + blocked)
    scopes = _team_join(item.get("writeScopes") if item.get("writeScopes") is not None else item.get("write_scopes"))
    if scopes:
        parts.append("writeScopes=" + scopes)
    return " · ".join(parts)


def _bullet_text(line: str) -> str | None:
    match = _BULLET_LINE.match(line)
    return (match.group("text") or "").strip() if match else None


def _section_span(lines: list[str], name: str) -> tuple[int, int] | None:
    """名为 name 的 level>=3 子标题的整段 [start,end)（含子标题行）；没有则 None。"""
    start = None
    level = 0
    for index, line in enumerate(lines):
        match = _AT_COL0.match(line)
        if start is None:
            if match is not None:
                here = len(match.group("stars"))
                if here >= 3 and (match.group("title") or "").strip() == name:
                    start = index
                    level = here
            continue
        if match is not None and len(match.group("stars")) <= level:
            return (start, index)
    if start is None:
        return None
    return (start, len(lines))


def _structural(value) -> str:
    """结构字段（id / status / owner）里不能出现 | 或换行。"""
    return _collapse(value).replace("|", "/")


def _parse_child_entry(text: str) -> dict | None:
    """解析一行子任务记录 → {id, status, owner, title}。

    规范格式（新）：- <id> | <status> | owner=<owner> | <subject…>
      subject 放最后，可含 |、owner=、空格；用 maxsplit=3 整段取回，保证往返逐字一致。
    兼容旧格式（真实库里已经写下的行）：
      - <id> | <subject> | <status> | owner=<owner>  → 最后两段是结构，中间 join 回 subject
      - <id> | <subject> | <status>                 → 最后一段是 status
    """
    raw = str(text or "").strip()
    bullet = _BULLET_LINE.match(raw)
    if bullet is not None:
        raw = (bullet.group("text") or "").strip()
    if "|" not in raw:
        return None
    head = raw.split("|", 3)
    if len(head) >= 3 and head[2].strip().lower().startswith("owner="):
        team_id = head[0].strip()
        if not team_id:
            return None
        return {
            "id": team_id,
            "status": head[1].strip(),
            "owner": head[2].strip()[len("owner="):].strip(),
            "title": head[3].strip() if len(head) > 3 else "",
        }
    parts = [part.strip() for part in raw.split("|")]
    team_id = parts[0] if parts else ""
    if not team_id:
        return None
    if len(parts) >= 4 and parts[-1].lower().startswith("owner="):
        return {
            "id": team_id,
            "status": parts[-2],
            "owner": parts[-1][len("owner="):].strip(),
            "title": " | ".join(parts[1:-2]),
        }
    if len(parts) >= 3:
        return {"id": team_id, "status": parts[-1], "owner": "", "title": " | ".join(parts[1:-1])}
    return {"id": team_id, "status": "", "owner": "", "title": parts[1] if len(parts) > 1 else ""}


def _render_child_line(entry: dict) -> str:
    """规范格式：- <id> | <status> | owner=<owner> | <subject…>（自由文本放最后）。"""
    line = ("- " + _structural(entry.get("id")) + " | " + _structural(entry.get("status"))
            + " | owner=" + _structural(entry.get("owner")))
    subject = escape_headline(entry.get("title"))
    if subject:
        line += " | " + subject
    return line



def parse_team_children(lines: list[str], *, base: int = 0) -> list[dict]:
    """解析 *** 子任务（会话规划） 节（按节内顺序）。

    lines 是实体正文行；base 是 lines[0] 在文件里的 0-based 行号。
    返回 [{id, title, status, owner, line}]，line 是 1-based 文件行号。
    """
    span = _section_span(lines, TEAM_CHILDREN_HEADLINE)
    if span is None:
        return []
    out: list[dict] = []
    for index in range(span[0] + 1, span[1]):
        text = _bullet_text(lines[index])
        if text is None:
            continue
        entry = _parse_child_entry(text)
        if entry is None:
            continue
        entry["line"] = base + index + 1
        out.append(entry)
    return out


def parse_dag_edges(lines: list[str], *, base: int = 0) -> list[list[str]]:
    """解析 *** 任务 DAG 节里的 - <a> -> <b> → [[from,to],...]（本期只读，不写）。"""
    span = _section_span(lines, TEAM_DAG_HEADLINE)
    if span is None:
        return []
    edges: list[list[str]] = []
    for index in range(span[0] + 1, span[1]):
        text = _bullet_text(lines[index])
        if text is None:
            continue
        match = _DAG_EDGE.match(text)
        if match:
            edges.append([match.group("src"), match.group("dst")])
    return edges


#: DAG 端点的**形状下限**：非成员被 --allow-unknown 放行时必须长这样（board id 如 task-48 合法）。
#: 注意：端点身份看的是「子任务 id 空间」（:PM_TEAM_TASKS:），不是 org 任务的 ULID 形状。
_BOARD_ID_RE = re.compile(r"^task-[A-Za-z0-9-]+$")


def _render_dag_line(edge) -> str:
    return "- " + edge[0] + " -> " + edge[1]


def parse_edge_spec(spec) -> tuple[str, str]:
    """把 --edge 的输入解析成 (from, to)；形式必须是 a -> b。"""
    text = str(spec or "").strip()
    bullet = _BULLET_LINE.match(text)
    if bullet is not None:
        text = (bullet.group("text") or "").strip()
    match = _DAG_EDGE.match(text)
    if match is None:
        raise TaskOpError("INVALID_EDGE", "边要写成 'a -> b'（收到 " + repr(spec) + "）")
    return (match.group("src"), match.group("dst"))


def task_child_ids(entity) -> list[str]:
    """任务的子任务 id：:PM_TEAM_TASKS: 属性 ∪ *** 子任务（会话规划） 节，按出现顺序去重。"""
    ids: list[str] = []
    prop = str((getattr(entity, "props", None) or {}).get(TEAM_TASKS_PROPERTY, "") or "")
    for part in prop.replace("，", ",").split(","):
        part = part.strip()
        if part and part not in ids:
            ids.append(part)
    for entry in parse_team_children(list(getattr(entity, "body", None) or []), base=0):
        if entry["id"] not in ids:
            ids.append(entry["id"])
    return ids


def plan_dag_set(entity, edges, *, replace: bool = False, allow_unknown: bool = False,
                 raw_body: list[str] | None = None) -> dict:
    """计算 *** 任务 DAG 节的写入计划（纯逻辑，不落盘）。

    默认**合并**（去重后按 (from, to) 排序）；--replace 整体替换；无 --edge + --replace 为清空。
    端点与子任务记录**同一个 id 空间**（:PM_TEAM_TASKS: / 子任务节里的 board id，如 task-48）：
    成员资格优先（是成员就直接接受，不要求 ULID 形状）；非成员只有 --allow-unknown 且形如
    task-[A-Za-z0-9-]+ 才放行；明显畸形的 token 才报 INVALID_EDGE_ENDPOINT。
    """
    provided = [parse_edge_spec(spec) for spec in edges]
    existing = [tuple(edge) for edge in parse_dag_edges(list(getattr(entity, "body", None) or []), base=0)]
    merged = list(provided) if replace else (existing + provided)
    merged = sorted(set(merged), key=lambda edge: (edge[0], edge[1]))

    child_ids = task_child_ids(entity)
    child_set = set(child_ids)
    malformed: list[str] = []
    unknown: list[str] = []
    for endpoint in dict.fromkeys(e for edge in merged for e in edge):
        if endpoint in child_set:
            # 成员资格优先：端点和子任务记录同一个 id 空间（board id task-<n> 天然合法），不要求 ULID 形状
            continue
        if _BOARD_ID_RE.match(endpoint) is None:
            malformed.append(endpoint)
        else:
            unknown.append(endpoint)
    if malformed:
        raise TaskOpError(
            "INVALID_EDGE_ENDPOINT",
            "DAG 端点形状不合法（既不是该任务的子任务，也不是 task-[A-Za-z0-9-]+）："
            + ", ".join(repr(item) for item in malformed),
            extra={"endpoints": malformed, "childIds": child_ids},
        )
    if unknown and not allow_unknown:
        raise TaskOpError(
            "EDGE_ENDPOINT_NOT_A_CHILD",
            "DAG 端点不在该任务的子任务里（:PM_TEAM_TASKS:）：" + ", ".join(unknown),
            extra={"unknownEndpoints": unknown, "childIds": child_ids,
                   "hint": "先 pm task import-team --parent 挂上这些子任务，或加 --allow-unknown 放行"},
        )

    current_body = list(getattr(entity, "body", None) or [])
    # 发现用 entity.body（缩进容错），落盘用原始行（保留行首缩进，只改该改的字节）
    raw = list(raw_body) if raw_body is not None else list(current_body)
    span = _section_span(current_body, TEAM_DAG_HEADLINE)
    if span is not None:
        new_body = raw[: span[0]] + raw[span[1]:]
    else:
        new_body = list(raw)
    while new_body and not new_body[-1].strip():
        new_body.pop()
    if merged:
        if new_body:
            new_body.append("")
        new_body.append("*** " + TEAM_DAG_HEADLINE)
        for edge in merged:
            new_body.append(_render_dag_line(edge))
    # 顺带补齐验收标准项 ID（只插入 [c-xxxx]，行数不变）
    new_body, added_criteria_ids = _ensure_criteria_ids(new_body)

    return {
        "existing": [list(edge) for edge in existing],
        "edges": [list(edge) for edge in merged],
        "unknownEndpoints": unknown,
        "childIds": child_ids,
        "body": new_body,
        "changed": new_body != raw,
        "hasSection": span is not None,
        "criteriaIdsAdded": added_criteria_ids,
    }


def build_team_task(
    item: dict, *, project_id: str, snapshot_status: str, team_id: str, entity_id: str | None = None
) -> dict:
    """board 条目 → 任务记录：title=subject，body=description+来源行，PM_AI: t，PM_TEAM_TASK_ID 锚点。"""
    subject = escape_headline(_team_field(item, "subject", "title"))
    description = str(_team_field(item, "description", "body") or "").rstrip("\n")
    owner = _collapse(_team_field(item, "ownerName", "owner", "assignee"))
    mapped = TEAM_STATUS_MAP.get(snapshot_status, TEAM_UNKNOWN_STATUS)
    task = build_task(
        subject,
        project_id=project_id,
        task_id=entity_id,
        status=mapped,
        ai=True,
        assignee=owner or "unassigned",
        goal=description,
        criteria=[],
        has_criteria=False,
        extra_properties={TEAM_TASK_PROPERTY: team_id},
    )
    task["body_extra"] = [team_source_line(item, team_id, snapshot_status)]
    return task


def _team_headline_with_title(entity: entities.Entity, title: str) -> str:
    """保留实体的层级与 TODO 关键字，只把标题换掉。"""
    level, keyword, _rest = headline_keyword_rest(entity.headline)
    line = "*" * level
    if keyword:
        line += " " + keyword
    if title:
        line += " " + title
    return line.rstrip()


def _team_source_at(lines: list[str], entity: entities.Entity, team_id: str) -> tuple[int, str] | None:
    """找实体正文里的来源行：返回 (绝对行号, 原缩进) 或 None。"""
    if entity.drawer is None:
        return None
    begin = _body_begin(lines, entity)
    for index in range(begin, min(entity.end, len(lines))):
        stripped = lines[index].strip()
        if stripped.startswith(TEAM_SOURCE_PREFIX) and team_id in stripped:
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip(" \t"))]
            return (index, indent)
    return None


def _snapshot_items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("tasks", "board", "items", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict) and isinstance(value.get("tasks"), list):
                return value["tasks"]
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("tasks"), list):
            return data["tasks"]
        if isinstance(data, list):
            return data
    return None


def load_team_snapshot(source: str) -> list:
    """读 board 快照：PATH 或 -（stdin）。只认 JSON，**不读任何 harness 会话存储**。"""
    text_source = str(source or "")
    if text_source == "-":
        if sys.stdin is None or getattr(sys.stdin, "isatty", lambda: False)():
            raise TaskOpError(
                "NO_STDIN",
                "要从 stdin 读快照请用管道（… | pm task import-team --from-json -），或改用 --from-json <文件>",
            )
        raw = sys.stdin.read()
    else:
        path = Path(text_source).expanduser()
        if not path.is_file():
            raise TaskOpError("SNAPSHOT_NOT_FOUND", "读不到 team board 快照: " + str(path))
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise TaskOpError("SNAPSHOT_UNREADABLE", "读不了 " + str(path) + ": " + str(exc))
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise TaskOpError("INVALID_SNAPSHOT", "快照不是合法 JSON: " + str(exc))
    items = _snapshot_items(payload)
    if items is None:
        raise TaskOpError(
            "INVALID_SNAPSHOT",
            "快照里找不到任务数组（支持 [...]、{tasks:[...]}、{data:{tasks:[...]}}）",
        )
    return items


def _snapshot_candidates(snapshot: list, statuses) -> tuple[list[dict], list[dict], list[dict]]:
    """过滤/归一化快照：返回 (items, skipped, unknown)。

    items 元素：{index, item, teamId, subject, snapshotStatus, mapped, unknown}。
    """
    items: list[dict] = []
    skipped: list[dict] = []
    unknown: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(snapshot):
        if not isinstance(item, dict):
            skipped.append({"index": index, "reason": "快照条目不是对象"})
            continue
        team_id = _team_task_id(item)
        if not team_id:
            skipped.append({"index": index, "reason": "缺少 board task id，无法做幂等锚点"})
            continue
        subject = escape_headline(_team_field(item, "subject", "title"))
        if not subject:
            skipped.append({"index": index, "teamId": team_id, "reason": "缺少 subject/title"})
            continue
        snapshot_status = normalize_team_status(_team_field(item, "status"))
        if statuses and snapshot_status not in statuses:
            skipped.append({
                "index": index, "teamId": team_id,
                "reason": "被 --status 过滤（" + (snapshot_status or "空") + "）",
            })
            continue
        if team_id in seen:
            skipped.append({"index": index, "teamId": team_id, "reason": "同一快照内重复的 board task id"})
            continue
        seen.add(team_id)
        mapped = TEAM_STATUS_MAP.get(snapshot_status, TEAM_UNKNOWN_STATUS)
        is_unknown = snapshot_status not in TEAM_STATUS_MAP
        if is_unknown:
            unknown.append({
                "teamId": team_id, "status": snapshot_status, "mappedTo": mapped,
                "hint": "未知 board 状态，按 TODO 落，需人工确认",
            })
        items.append({
            "index": index, "item": item, "teamId": team_id, "subject": subject,
            "snapshotStatus": snapshot_status, "mapped": mapped, "unknown": is_unknown,
        })
    return items, skipped, unknown


def _plan_team_children(path: Path, snapshot: list, *, parent_id, statuses, actor, now) -> dict:
    """--parent 模式：不建顶层任务，把团队任务作为子任务记录挂到父任务上。

    规范行：- <id> | <status> | owner=<owner> | <subject…>（自由文本放最后，subject 可含 |）。
    已被旧格式写坏的行：只要还在本次快照里，就按快照**就地改写**成规范格式；不在快照里的保留原行
    （不拿启发式猜出来的 subject 覆盖旧行，避免二次损坏）。
    与父任务**同一次 CAS + 一条审计**；父任务不存在 → NOT_FOUND + hint；终态 → PARENT_TERMINAL。
    """
    try:
        parent = entities.load_entity(path, parent_id, default_status=DEFAULT_STATUS)
    except entities.EntityError as exc:
        if exc.code == "NOT_FOUND":
            raise TaskOpError(
                "NOT_FOUND", exc.message,
                extra={"hint": "父任务 :ID: 不存在；先 pm task create --project <key> --title <t>，"
                               "或核对 --parent 的 task id"},
            ) from exc
        raise
    parent_status = _entity_status(parent)
    if parent_status in TERMINAL_STATUSES:
        raise TaskOpError(
            "PARENT_TERMINAL",
            "父任务 " + parent_id + " 已是终态 " + parent_status + "，拒绝挂载子任务（终态任务不再改）",
            extra={"parentId": parent_id, "parentStatus": parent_status},
        )

    lines = entities.read_text(path).split("\n")
    body_begin = _body_begin(lines, parent)
    current_body = list(parent.body)
    raw_body = _raw_body_lines(lines, parent)
    span = _section_span(current_body, TEAM_CHILDREN_HEADLINE)

    children: list[dict] = []
    positions: dict[str, int] = {}
    if span is not None:
        for index in range(span[0] + 1, span[1]):
            text = _bullet_text(current_body[index])
            if text is None:
                continue
            entry = _parse_child_entry(text)
            if entry is None or entry["id"] in positions:
                continue
            entry["raw"] = raw_body[index]
            positions[entry["id"]] = len(children)
            children.append(entry)

    items, skipped, unknown = _snapshot_candidates(snapshot, statuses)
    created: list[dict] = []
    updated: list[dict] = []
    unchanged: list[dict] = []
    for item in items:
        team_id = item["teamId"]
        desired = {
            "id": team_id,
            "title": item["subject"],
            "status": item["snapshotStatus"],
            "owner": _collapse(_team_field(item["item"], "ownerName", "owner", "assignee")),
        }
        row_base = {
            "teamId": team_id, "parentId": parent_id, "title": desired["title"],
            "status": desired["status"], "owner": desired["owner"],
        }
        if team_id in positions:
            current = children[positions[team_id]]
            field_changes = [key for key in ("title", "status", "owner") if current.get(key) != desired.get(key)]
            rendered = _render_child_line(desired)
            if field_changes or (current.get("raw") or "").strip() != rendered:
                # 字段变了，或只是旧格式/坏行要迁移成规范格式 —— 都就地改写（不新增行）
                current.update(desired)
                row = dict(row_base)
                row["changes"] = field_changes or ["format"]
                updated.append(row)
            else:
                unchanged.append(dict(row_base))
        else:
            positions[team_id] = len(children)
            children.append(desired)
            row = dict(row_base)
            row["unknownStatus"] = item["unknown"]
            created.append(row)

    item_ids = {item["teamId"] for item in items}
    kept = [
        {
            "teamId": entry["id"], "parentId": parent_id, "title": entry["title"],
            "status": entry["status"], "owner": entry["owner"],
            "reason": "正文节里已有但本次快照未包含，保持原行不动",
        }
        for entry in children if entry["id"] not in item_ids
    ]

    new_body = list(raw_body)
    if span is not None:
        new_body = new_body[: span[0]] + new_body[span[1]:]
    while new_body and not new_body[-1].strip():
        new_body.pop()

    drawer_extra = 0 if TEAM_TASKS_PROPERTY in parent.props else 1
    line_by_id: dict[str, int] = {}
    if children:
        if new_body:
            new_body.append("")
        new_body.append("*** " + TEAM_CHILDREN_HEADLINE)
        for entry in children:
            rendered = _render_child_line(entry)
            # 内容变了/新格式 → 写规范行；内容没变 → 原行（保留缩进）；新条目 → 规范行
            if entry["id"] in item_ids and (entry.get("raw") or "").strip() != rendered:
                new_body.append(rendered)
            elif entry.get("raw"):
                new_body.append(entry["raw"])
            else:  # pragma: no cover - 旧行读不到 raw 时兜底
                new_body.append(rendered)
            line_by_id[entry["id"]] = body_begin + drawer_extra + (len(new_body) - 1) + 1

    new_body, added_criteria_ids = _ensure_criteria_ids(new_body)

    desired_property = ",".join(entry["id"] for entry in children)
    old_property = str(parent.props.get(TEAM_TASKS_PROPERTY, "") or "").strip()
    changed = (new_body != raw_body) or (desired_property != old_property)

    for row in created + updated + unchanged + kept:
        row["line"] = line_by_id.get(row["teamId"])

    return {
        "mode": "parent",
        "path": path,
        "parentId": parent_id,
        "parentStatus": parent_status,
        "parentChanged": changed,
        "parentExpectedRevision": parent.revision,
        "parentProperty": desired_property,
        "parentBody": new_body,
        "criteriaIdsAdded": added_criteria_ids,
        "count": len(snapshot),
        "created": created,
        "updated": updated,
        "kept": kept,
        "skipped": skipped,
        "unchanged": unchanged,
        "unknownStatus": unknown,
        "simulatedText": None,
    }



def plan_team_import(
    path: Path,
    snapshot: list,
    *,
    project_id: str,
    parent_id: str | None = None,
    statuses=None,
    actor: str = "ai",
    now: datetime | None = None,
) -> dict:
    """把 board 快照映射成导入计划（纯规划，不落盘）。

    两种模式：
    - 平面（默认）：新任务写进项目 tasks.org，锚点 :PM_TEAM_TASK_ID:；
    - --parent：**不建顶层任务**，把团队任务作为子任务记录挂到父任务（:PM_TEAM_TASKS: + 正文节）。
    分类：created / updated / kept / unchanged / skipped / unknownStatus。
    幂等：同一份快照第二次跑，全部落进 unchanged/kept，零写入。
    """
    path = Path(path)
    if parent_id:
        return _plan_team_children(
            path, snapshot, parent_id=parent_id, statuses=statuses, actor=actor, now=now
        )

    existing: dict[str, dict] = {}
    for task in read_tasks(path):
        anchor = str((task.get("properties") or {}).get(TEAM_TASK_PROPERTY, "") or "").strip()
        if anchor and anchor not in existing:
            existing[anchor] = task

    raw_text = entities.read_text(path) if path.is_file() else "* " + TASKS_SECTION + "\n"
    current_lines = raw_text.split("\n")
    simulated = raw_text

    created: list[dict] = []
    updated: list[dict] = []
    kept: list[dict] = []
    unchanged: list[dict] = []
    items, skipped, unknown = _snapshot_candidates(snapshot, statuses)

    for item in items:
        team_id = item["teamId"]
        subject = item["subject"]
        snapshot_status = item["snapshotStatus"]
        mapped = item["mapped"]
        is_unknown = item["unknown"]

        org = existing.get(team_id)
        if org is not None:
            entity = entities.load_entity(path, org.get("id"), default_status=DEFAULT_STATUS)
            org_status = _entity_status(entity)
            desired_line = team_source_line(item["item"], team_id, snapshot_status)
            replace_lines: dict[int, str] = {}
            changes: list[str] = []
            if headline_keyword_rest(entity.headline)[2] != subject:
                replace_lines[0] = _team_headline_with_title(entity, subject)
                changes.append("title")
            source = _team_source_at(current_lines, entity, team_id)
            if source is not None:
                absolute, indent = source
                if current_lines[absolute].strip() != desired_line:
                    replace_lines[absolute - entity.start] = indent + desired_line
                    changes.append("source")
            if TEAM_PROGRESS_RANK.get(org_status, 0) > TEAM_PROGRESS_RANK.get(mapped, 0):
                kept.append({
                    "teamId": team_id, "entityId": org.get("id"), "status": org_status,
                    "snapshotStatus": snapshot_status, "mappedTo": mapped,
                    "reason": "org 状态比 team 映射更靠后，保持不动（只增不改状态）",
                })
            elif changes:
                updated.append({
                    "teamId": team_id, "entityId": org.get("id"), "status": org_status,
                    "snapshotStatus": snapshot_status, "changes": changes,
                    "expectedRevision": entity.revision, "replaceLines": replace_lines,
                })
            else:
                unchanged.append({
                    "teamId": team_id, "entityId": org.get("id"), "status": org_status,
                    "snapshotStatus": snapshot_status,
                })
            continue

        task = build_team_task(
            item["item"], project_id=project_id, snapshot_status=snapshot_status, team_id=team_id
        )
        block, audit_id = entities.build_entity_block(
            entity_id=task["id"], kind="task", status=mapped,
            headline=mapped + ((" " + task["title"]) if task["title"] else ""),
            properties=_create_props(task),
            body_lines=render_task_body(task), indent_body=False, actor=actor, at=now,
        )
        simulated, _found, number = humanwrite.append_under_tracked(
            simulated, headline=TASKS_SECTION, block=block
        )
        created.append({
            "teamId": team_id, "entityId": task["id"], "title": task["title"],
            "status": mapped, "snapshotStatus": snapshot_status, "unknownStatus": is_unknown,
            "line": number + 1, "auditEventId": audit_id, "task": task,
        })

    return {
        "mode": "flat",
        "path": path,
        "count": len(snapshot),
        "created": created,
        "updated": updated,
        "kept": kept,
        "skipped": skipped,
        "unchanged": unchanged,
        "unknownStatus": unknown,
        "simulatedText": simulated,
    }


def _team_created_row(entry: dict, *, line=None, audit_id=None, dry_run=True) -> dict:
    return {
        "teamId": entry["teamId"],
        "entityId": entry["entityId"],
        "title": entry["title"],
        "status": entry["status"],
        "snapshotStatus": entry["snapshotStatus"],
        "unknownStatus": bool(entry["unknownStatus"]),
        "line": entry["line"] if line is None else line,
        "auditEventId": entry["auditEventId"] if audit_id is None else audit_id,
        "dryRun": bool(dry_run),
    }


def _team_updated_row(entry: dict, *, audit_id=None, revision=None, dry_run=True) -> dict:
    row = {
        "teamId": entry["teamId"],
        "entityId": entry["entityId"],
        "status": entry["status"],
        "snapshotStatus": entry["snapshotStatus"],
        "changes": list(entry["changes"]),
        "expectedRevision": entry["expectedRevision"],
        "dryRun": bool(dry_run),
    }
    if audit_id is not None:
        row["auditEventId"] = audit_id
    if revision is not None:
        row["revision"] = revision
    return row


# ---------------------------------------------------------------- CLI

def _add_common(parser: argparse.ArgumentParser) -> None:
    """复用 cli 的公共参数（SUPPRESS 默认值，避免覆盖顶层 --config）。"""
    try:
        from pm import cli as cli_module

        cli_module._add_common_options(parser, as_defaults=True)
    except (ImportError, AttributeError):  # pragma: no cover - cli 一定在
        parser.add_argument("--config", metavar="PATH", default=argparse.SUPPRESS)


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="stdout 只输出纯 JSON")


def _add_write_flags(parser: argparse.ArgumentParser, *, need_revision: bool = True) -> None:
    if need_revision:
        parser.add_argument(
            "--expected-revision", dest="expected_revision", type=int, required=True,
            metavar="N", help="你看到的 :PM_REVISION:；不匹配 → 409，一字节不写（CAS）",
        )
    parser.add_argument("--actor", default="human", choices=["human", "ai", "system"],
                        help="谁发起的，写入审计（默认 human）")
    parser.add_argument("--reason", default="", metavar="R", help="变更原因，写入审计")
    parser.add_argument("--idempotency-key", dest="idempotency_key", default=None, metavar="KEY",
                        help="同一 key 重复提交不会产生第二次变更")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="只预演，一字节不落盘")
    parser.add_argument("--yes", action="store_true",
                        help="确认要写「默认配置指向的库」；未显式 --config 且非 --dry-run 时必需")
    _add_json(parser)


def register_cli(subparsers) -> None:
    """由 pm.cli 的域注册钩子调用；本模块自己建 parser、自己设 handler。"""
    task = subparsers.add_parser("task", help="任务（projects/<id>/tasks.org，§5.2）")
    task_sub = task.add_subparsers(dest="task_command")

    listing = task_sub.add_parser("list", help="列出项目任务（按状态分组；身份只看 :ID:）")
    listing.add_argument("--project", required=True, metavar="KEY", help="项目 key，如 demo")
    listing.add_argument("--status", metavar="S", help="只看某个状态（TODO / DOING / REVIEW …）")
    _add_json(listing)
    _add_common(listing)
    listing.set_defaults(handler=command_list)

    show = task_sub.add_parser("show", help="显示单个任务（含目标/非目标/验收标准）")
    show.add_argument("task_id", metavar="TASK_ID", help="任务 :ID:")
    show.add_argument("--project", required=True, metavar="KEY")
    _add_json(show)
    _add_common(show)
    show.set_defaults(handler=command_show)

    create = task_sub.add_parser("create", help="新建任务（走 entities.create_entity + 审计）")
    create.add_argument("--project", required=True, metavar="KEY")
    create.add_argument("--title", required=True, metavar="T", help="标题（做 org 转义）")
    create.add_argument("--goal", default="", metavar="TEXT", help="目标（可多行）")
    create.add_argument("--non-goal", dest="non_goal", default="", metavar="TEXT", help="非目标")
    create.add_argument("--criterion", action="append", default=[], metavar="TEXT",
                        help="验收标准（可重复）")
    create.add_argument("--from-inbox", dest="source_inbox_id", default=None, metavar="INBOX_ID",
                        help="来源 inbox ID（写入 PM_SOURCE_INBOX_ID，可回链）")
    create.add_argument("--ai", action="store_true", help="标记为 AI 创建（PM_AI: t）")
    create.add_argument("--assignee", default="unassigned", metavar="WHO")
    create.add_argument("--id", dest="task_id", default=None, metavar="TASK_ID",
                        help="指定 :ID:（默认生成 task-<ULID>）")
    _add_write_flags(create, need_revision=False)
    _add_common(create)
    create.set_defaults(handler=command_create)

    transition = task_sub.add_parser("transition", help="状态迁移（§5.2 状态机 + CAS + 审计）")
    transition.add_argument("task_id", metavar="TASK_ID")
    transition.add_argument("--project", required=True, metavar="KEY")
    transition.add_argument("--to", required=True, metavar="STATUS",
                            help="目标状态：" + " / ".join(ALL_STATUSES))
    _add_write_flags(transition)
    _add_common(transition)
    transition.set_defaults(handler=command_transition)

    check = task_sub.add_parser("check", help="勾选/取消验收标准（CAS + 审计）")
    check.add_argument("task_id", metavar="TASK_ID")
    check.add_argument("--project", required=True, metavar="KEY")
    check.add_argument("--criterion-id", dest="criterion_id", default=None, metavar="ID",
                       help="按稳定 ID 定位（推荐，如 c-1a2b）")
    check.add_argument("--index", type=int, default=None, metavar="N",
                       help="[deprecated] 按 0 开始的文件序号定位；请改用 --criterion-id")
    check.add_argument("--criterion", default=None, metavar="序号|文本",
                       help="[deprecated] 按序号或精确文本定位；请改用 --criterion-id")
    check.add_argument("--uncheck", action="store_true", help="取消勾选（默认勾选）")
    _add_write_flags(check)
    _add_common(check)
    check.set_defaults(handler=command_check)

    evidence = task_sub.add_parser("evidence", help="验收证据（正文节 *** 证据（验收），append-only）")
    evidence_sub = evidence.add_subparsers(dest="evidence_command")

    ev_add = evidence_sub.add_parser("add", help="给某条验收标准追加一条证据（CAS + 一条审计）")
    ev_add.add_argument("task_id", metavar="TASK_ID")
    ev_add.add_argument("--project", required=True, metavar="KEY")
    ev_add.add_argument("--criterion-id", dest="criterion_id", required=True, metavar="ID",
                        help="验收标准项稳定 ID（如 c-1a2b）")
    ev_add.add_argument("--kind", required=True, choices=list(EVIDENCE_KINDS),
                        help="证据类型：" + " / ".join(EVIDENCE_KINDS))
    ev_add.add_argument("--result", required=True, choices=list(EVIDENCE_RESULTS),
                        help="结论：" + " / ".join(EVIDENCE_RESULTS) + "（不知道就写 info，绝不猜 pass）")
    ev_add.add_argument("--ref", required=True, metavar="REF",
                        help="commit / 路径 / URL / 命令文本；不得含 |（塞不下写 --note）")
    ev_add.add_argument("--note", default="", metavar="TEXT", help="自由文本（最后一段，可含 |）")
    _add_write_flags(ev_add)
    _add_common(ev_add)
    ev_add.set_defaults(handler=command_evidence_add)

    ev_rm = evidence_sub.add_parser(
        "rm", help="按证据 id 移除一条证据（CAS + 一条审计；找不到 id 明确报错）"
    )
    ev_rm.add_argument("task_id", metavar="TASK_ID")
    ev_rm.add_argument("evidence_id", metavar="EVIDENCE_ID",
                       help="证据 id（见 pm task evidence list；内容寻址，如 e-1a2b）")
    ev_rm.add_argument("--project", required=True, metavar="KEY")
    _add_write_flags(ev_rm)
    _add_common(ev_rm)
    ev_rm.set_defaults(handler=command_evidence_rm)

    ev_list = evidence_sub.add_parser("list", help="列出任务的验收证据（只读）")
    ev_list.add_argument("task_id", metavar="TASK_ID")
    ev_list.add_argument("--project", required=True, metavar="KEY")
    _add_json(ev_list)
    _add_common(ev_list)
    ev_list.set_defaults(handler=command_evidence_list)

    init_ids = task_sub.add_parser(
        "init-ids", help="给缺 :ID: 的任务块补铸造属性（幂等；dry-run 零写入，带审计）"
    )
    init_ids.add_argument("--project", required=True, metavar="KEY")
    # 整文件操作、没有单一实体的 revision → 不要 CAS 参数（need_revision=False）
    _add_write_flags(init_ids, need_revision=False)
    _add_common(init_ids)
    init_ids.set_defaults(handler=command_task_init_ids)

    criteria = task_sub.add_parser("criteria", help="验收标准项（稳定 ID）")
    criteria_sub = criteria.add_subparsers(dest="criteria_command")
    init_ids = criteria_sub.add_parser(
        "init-ids", help="给缺稳定 ID 的验收标准项补 ID（只加 ID，幂等）"
    )
    init_ids.add_argument("task_id", metavar="TASK_ID")
    init_ids.add_argument("--project", required=True, metavar="KEY")
    _add_write_flags(init_ids)
    _add_common(init_ids)
    init_ids.set_defaults(handler=command_criteria_init_ids)

    dag = task_sub.add_parser("dag", help="任务的 DAG（正文节 *** 任务 DAG）")
    dag_sub = dag.add_subparsers(dest="dag_command")
    dag_set = dag_sub.add_parser(
        "set", help="设置/合并 DAG 边（--edge 'a -> b'，默认合并去重按 from,to 排序）"
    )
    dag_set.add_argument("task_id", metavar="TASK_ID", help="持有 DAG 的任务 :ID:")
    dag_set.add_argument("--project", required=True, metavar="KEY")
    dag_set.add_argument("--edge", action="append", default=[], metavar="A -> B",
                         help="一条有向边，可重复；端点默认必须是该任务的 :PM_TEAM_TASKS: 子任务")
    dag_set.add_argument("--replace", action="store_true",
                         help="用给出的边整体替换（不带 --edge 时=清空该节）")
    dag_set.add_argument("--allow-unknown", dest="allow_unknown", action="store_true",
                         help="放行不在子任务列表里的端点（默认拒绝）")
    _add_write_flags(dag_set)
    _add_common(dag_set)
    dag_set.set_defaults(handler=command_dag_set)

    importer = task_sub.add_parser(
        "import-team",
        help="把 Agent Team 任务板快照补进项目 tasks.org（默认 dry-run，--write 落盘）",
    )
    importer.add_argument("--project", required=True, metavar="KEY")
    importer.add_argument(
        "--parent", default=None, metavar="TASK_ID",
        help="挂到该项目任务的子任务记录上（不创建顶层任务；父任务已 DONE/CANCELLED 时拒绝）",
    )
    importer.add_argument(
        "--from-json", dest="from_json", required=True, metavar="PATH|-",
        help="board 快照 JSON：- 表示 stdin；支持 [...]、{tasks:[...]}、{data:{tasks:[...]}}",
    )
    importer.add_argument(
        "--status", action="append", default=[], metavar="S",
        help="只导入快照里这些状态的条目（可重复；pending / in_progress / completed）",
    )
    importer.add_argument(
        "--write", action="store_true",
        help="真正落盘；默认 dry-run（只预演，一字节不写）",
    )
    importer.add_argument(
        "--actor", default="ai", choices=["human", "ai", "system"],
        help="写入审计 actor（默认 ai：条目来自 Agent Team，标 PM_AI: t）",
    )
    importer.add_argument(
        "--yes", action="store_true",
        help="确认要写「默认配置指向的库」；未显式 --config 且带 --write 时必需",
    )
    _add_json(importer)
    _add_common(importer)
    importer.set_defaults(handler=command_import_team)


def _emit_error(json_mode: bool, error: entities.EntityError) -> int:
    payload = {"ok": False, "error": {"code": error.code, "message": error.message}}
    payload.update(error.extra)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
    print("pm: [" + error.code + "] " + error.message, file=sys.stderr)
    return error.exit_code


def _read_layout(args) -> tuple[Layout | None, entities.EntityError | None]:
    from pm.config import load as load_config

    config, _warnings = load_config(getattr(args, "config", None))
    if config.library is None:
        return None, TaskOpError("NO_LIBRARY", "未配置 work-memory 库（pm.toml 缺 library）")
    return Layout(Path(config.library)), None


def _write_layout(args, json_mode: bool) -> tuple[Layout | None, tuple | None]:
    from pm import cli as cli_module

    resolver = getattr(cli_module, "resolve_write_target", None) or getattr(
        cli_module, "_resolve_write_target"
    )
    return resolver(args, json_mode)


def _relative(path: Path, layout: Layout) -> str:
    try:
        return str(Path(path).relative_to(layout.root))
    except ValueError:
        return str(path)


def _open_tasks(layout: Layout, project: str) -> tuple[Path, list[dict]]:
    path = tasks_path(layout, project)
    return path, read_tasks(path)


def command_list(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    layout, error = _read_layout(args)
    if error is not None:
        return _emit_error(json_mode, error)
    path, tasks = _open_tasks(layout, args.project)
    wanted = (getattr(args, "status", None) or "").strip().upper() or None
    if wanted:
        tasks = [task for task in tasks if resolve_status(task) == wanted]
    groups = group_tasks(tasks)
    payload = {
        "ok": True,
        "project": project_key(args.project),
        "path": _relative(path, layout),
        "count": len(tasks),
        "groups": [
            {"key": group["key"], "label": group["label"], "count": group["count"],
             "tasks": [task_summary(task) for task in group["tasks"]]}
            for group in groups
        ],
    }
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not tasks:
        print(payload["project"] + " 没有符合条件的任务（" + payload["path"] + "）。")
        return 0
    print(payload["project"] + " 任务 " + str(payload["count"]) + " 条（" + payload["path"] + "）")
    for group in payload["groups"]:
        if not group["count"]:
            continue
        print("  [" + group["label"] + "] " + str(group["count"]))
        for row in group["tasks"]:
            criteria = ("  验收 " + str(row["criteriaDone"]) + "/" + str(row["criteriaTotal"])) if row["criteriaTotal"] else ""
            print("    " + row["status"].ljust(9) + " " + str(row["id"]) + "  rev " + str(row["revision"]) + "  " + row["title"][:40] + criteria)
    return 0


def _require_task(layout: Layout, project: str, task_id: str) -> tuple[Path, dict]:
    path, tasks = _open_tasks(layout, project)
    task = find_task(tasks, task_id)
    if task is None:
        legacy = [item for item in tasks if not item.get("id")]
        if legacy:
            raise entities.legacy_error(task_id, len(legacy))
        raise TaskOpError("NOT_FOUND", "找不到 :ID: 为 " + task_id + " 的任务（" + _relative(path, layout) + "）")
    return path, task


def _task_detail(task: dict) -> dict:
    payload = task_summary(task)
    payload.update(
        {
            "goal": task.get("goal") or "",
            "nonGoal": task.get("non_goal") or "",
            "criteria": task.get("criteria") or [],
            "pmStatus": task.get("pm_status"),
            "statusMismatch": bool(task.get("status_mismatch")),
            "properties": task.get("properties") or {},
            "teamTasks": task.get("team_tasks") or [],
            "dagEdges": task.get("dag_edges") or [],
            "evidence": task.get("evidence") or [],
            "evidenceCount": len(task.get("evidence") or []),
            "history": task.get("history") or [],
            "historyCount": int(task.get("history_count")
                                if task.get("history_count") is not None
                                else len(task.get("history") or [])),
            "historyShown": len(task.get("history") or []),
            "historyTruncated": bool(task.get("history_truncated")),
            "line": task.get("line"),
        }
    )
    return payload


def command_show(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    layout, error = _read_layout(args)
    if error is not None:
        return _emit_error(json_mode, error)
    try:
        path, task = _require_task(layout, args.project, args.task_id)
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)
    payload = {"ok": True, "path": _relative(path, layout), "task": _task_detail(task)}
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    detail = payload["task"]
    print(str(detail["id"]) + "  [" + detail["status"] + "]  rev " + str(detail["revision"]) + "  " + detail["title"])
    print("  项目 " + str(detail["projectId"]) + "  负责人 " + str(detail["assignee"]) + "  AI " + str(detail["ai"]))
    if detail["goal"]:
        print("  目标：" + detail["goal"])
    if detail["nonGoal"]:
        print("  非目标：" + detail["nonGoal"])
    if detail["criteria"]:
        print("  验收标准：")
        for index, item in enumerate(detail["criteria"]):
            print("    [" + ("x" if item["done"] else " ") + "] " + str(index) + ". " + item["text"])
    return 0


def _write_payload(result: entities.OpResult, layout: Layout, *, dry_run: bool, extra=None) -> dict:
    payload = {
        "ok": True,
        "entityId": result.entity_id,
        "taskId": result.entity_id,
        "source": result.source,
        "observedAt": result.observed_at,
        "auditEventId": result.audit_event_id,
        "status": result.status,
        "revision": result.revision,
        "previousStatus": result.previous_status,
        "previousRevision": result.previous_revision,
        "changed": result.changed,
        "path": _relative(result.path, layout),
    }
    if result.idempotent:
        payload["idempotent"] = True
    if dry_run:
        payload["dry_run"] = True
    payload.update(extra or {})
    payload.update(result.extra or {})
    return payload


def command_create(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    layout, gate_error = _write_layout(args, json_mode)
    if layout is None:
        return _emit_error(json_mode, TaskOpError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    try:
        task = build_task(
            args.title,
            project_id=project_key(args.project),
            task_id=args.task_id,
            ai=bool(args.ai),
            assignee=args.assignee,
            source_inbox_id=args.source_inbox_id,
            goal=args.goal,
            non_goal=args.non_goal,
            criteria=list(args.criterion or []),
        )
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)

    path = tasks_path(layout, args.project)
    now = datetime.now().astimezone()
    try:
        line, audit_id, preview = create_task(path, task, actor=args.actor, dry_run=args.dry_run, now=now)
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)

    payload = {
        "ok": True,
        "entityId": task["id"],
        "taskId": task["id"],
        "source": entities.SOURCE_ORG,
        "observedAt": now.isoformat(timespec="seconds"),
        "auditEventId": audit_id,
        "status": resolve_status(task),
        "revision": 1,
        "previousStatus": None,
        "previousRevision": None,
        "changed": True,
        "path": _relative(path, layout),
        "line": line,
        "dry_run": bool(args.dry_run),
    }
    if preview is not None:
        payload["block"] = "\n".join(preview)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    prefix = "[dry-run] " if args.dry_run else ""
    print(prefix + "已创建任务 " + task["id"] + "  " + resolve_status(task) + "  " + task["title"])
    print("  " + _relative(path, layout) + ":" + str(line) + "  audit " + audit_id)
    return 0


def command_transition(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    layout, gate_error = _write_layout(args, json_mode)
    if layout is None:
        return _emit_error(json_mode, TaskOpError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    path = tasks_path(layout, args.project)
    try:
        result = transition_task(
            path,
            args.task_id,
            to_status=args.to,
            expected_revision=args.expected_revision,
            actor=args.actor,
            reason=args.reason or "",
            idempotency_key=args.idempotency_key,
            dry_run=args.dry_run,
        )
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)
    if json_mode:
        print(json.dumps(_write_payload(result, layout, dry_run=args.dry_run), ensure_ascii=False))
        return 0
    prefix = "[dry-run] " if args.dry_run else ""
    if not result.changed:
        print(prefix + "无需变更：" + result.entity_id + " 已是 " + result.status + " rev " + str(result.revision))
        return 0
    print(prefix + "已迁移 " + result.entity_id + "  " + result.previous_status + " → " + result.status
          + "  rev " + str(result.previous_revision) + " → " + str(result.revision) + "  audit " + str(result.audit_event_id))
    return 0


def command_check(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    layout, gate_error = _write_layout(args, json_mode)
    if layout is None:
        return _emit_error(json_mode, TaskOpError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    path = tasks_path(layout, args.project)
    done = not bool(args.uncheck)
    selector_count = sum(1 for value in (getattr(args, "criterion_id", None),
                                         getattr(args, "index", None),
                                         getattr(args, "criterion", None)) if value is not None)
    if selector_count == 0:
        return _emit_error(json_mode, TaskOpError(
            "CRITERION_SELECTOR_REQUIRED",
            "请给一个定位参数：--criterion-id c-xxxx（推荐），或 deprecated 的 --index / --criterion",
        ))
    if selector_count > 1:
        return _emit_error(json_mode, TaskOpError(
            "CRITERION_SELECTOR_CONFLICT",
            "--criterion-id / --index / --criterion 只能给一个",
        ))
    select: dict = {}
    if getattr(args, "criterion_id", None) is not None:
        select["criterion_id"] = args.criterion_id
    elif getattr(args, "index", None) is not None:
        select["index"] = args.index
    else:
        raw_select = str(args.criterion).strip()
        if re.fullmatch(r"\d+", raw_select):
            select["index"] = int(raw_select)
        else:
            select["text"] = raw_select
    try:
        result = set_criterion(
            path,
            args.task_id,
            done=done,
            expected_revision=args.expected_revision,
            actor=args.actor,
            reason=args.reason or "",
            idempotency_key=args.idempotency_key,
            dry_run=args.dry_run,
            **select,
        )
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)
    extra = {"criteriaDone": done}
    if "index" in select:
        extra["criteriaIndex"] = select["index"]
    if json_mode:
        print(json.dumps(_write_payload(result, layout, dry_run=args.dry_run, extra=extra), ensure_ascii=False))
        return 0
    prefix = "[dry-run] " if args.dry_run else ""
    verb = "勾选" if done else "取消勾选"
    print(prefix + "已" + verb + "验收标准 [" + str(getattr(result, "extra", {}).get("criterionId") or "?")
          + "]：" + result.entity_id + "  rev " + str(result.previous_revision) + " → "
          + str(result.revision) + "  audit " + str(result.audit_event_id))
    return 0

def _team_child_row(entry: dict, *, dry_run: bool, changes=None, reason=None) -> dict:
    row = {
        "teamId": entry.get("teamId"),
        "parentId": entry.get("parentId"),
        "title": entry.get("title") or "",
        "status": entry.get("status") or "",
        "owner": entry.get("owner") or "",
        "line": entry.get("line"),
        "dryRun": bool(dry_run),
    }
    if changes:
        row["changes"] = list(changes)
    if reason:
        row["reason"] = reason
    if entry.get("unknownStatus"):
        row["unknownStatus"] = True
    return row


def _finish_team_flat_import(args, layout, path, plan, json_mode) -> int:
    rows_created: list[dict] = []
    rows_updated: list[dict] = []
    try:
        # 先刷新已有（用原始偏移的 CAS），再追加新任务：追加只在小节末尾，不会移动已有行
        for entry in plan["updated"]:
            if args.dry_run:
                rows_updated.append(_team_updated_row(entry, dry_run=True))
                continue
            result = entities.apply_change(
                path, entry["entityId"], expected_revision=entry["expectedRevision"],
                replace_lines=entry["replaceLines"], actor=args.actor,
                reason="按 Agent Team 快照刷新标题/来源行（状态不动）",
                default_status=DEFAULT_STATUS,
            )
            rows_updated.append(_team_updated_row(
                entry, audit_id=result.audit_event_id, revision=result.revision, dry_run=False,
            ))
        for entry in plan["created"]:
            if args.dry_run:
                rows_created.append(_team_created_row(entry, dry_run=True))
                continue
            line, audit_id, _preview = create_task(path, entry["task"], actor=args.actor)
            rows_created.append(_team_created_row(entry, line=line, audit_id=audit_id, dry_run=False))
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)

    payload = {
        "ok": True,
        "mode": "flat",
        "project": project_key(args.project),
        "path": _relative(path, layout),
        "dry_run": args.dry_run,
        "count": plan["count"],
        "totals": {
            "created": len(rows_created),
            "updated": len(rows_updated),
            "kept": len(plan["kept"]),
            "skipped": len(plan["skipped"]),
            "unchanged": len(plan["unchanged"]),
            "unknownStatus": len(plan["unknownStatus"]),
        },
        "created": rows_created,
        "updated": rows_updated,
        "kept": plan["kept"],
        "skipped": plan["skipped"],
        "unchanged": plan["unchanged"],
        "unknownStatus": plan["unknownStatus"],
    }
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    prefix = "[dry-run] " if args.dry_run else ""
    print(prefix + "team 快照 " + str(payload["count"]) + " 条 → " + payload["path"])
    print("  新建 " + str(len(rows_created)) + " / 刷新 " + str(len(rows_updated))
          + " / 已有保持 " + str(len(plan["kept"])) + " / 无变化 " + str(len(plan["unchanged"]))
          + " / 跳过 " + str(len(plan["skipped"])))
    for row in rows_created:
        print("  + " + row["status"] + "  " + row["entityId"] + "  " + row["title"]
              + "  ← team " + row["teamId"] + "  第 " + str(row["line"]) + " 行")
    for row in rows_updated:
        print("  ~ " + row["status"] + "  " + row["entityId"] + "  刷新 " + ",".join(row["changes"])
              + "  ← team " + row["teamId"])
    for row in plan["kept"]:
        print("  = 保持 " + str(row["entityId"]) + "  " + str(row["status"]) + "  ← team " + row["teamId"])
    for row in plan["unchanged"]:
        print("  . 无变化 " + str(row["entityId"]) + "  " + str(row["status"]) + "  ← team " + row["teamId"])
    for row in plan["unknownStatus"]:
        print("  ! 未知状态 " + repr(row["status"]) + " → " + row["mappedTo"] + "（team " + row["teamId"] + "）")
    for row in plan["skipped"]:
        print("  x 跳过：" + row["reason"])
    print("未落盘（默认 dry-run）；加 --write 才写。"
          if args.dry_run else "已落盘（--write）；同一快照再跑一次是 0 变更。")
    return 0


def _finish_team_parent_import(args, layout, path, plan, json_mode) -> int:
    parent_row = {
        "entityId": plan["parentId"],
        "status": plan["parentStatus"],
        "changed": bool(plan["parentChanged"]),
        "expectedRevision": plan["parentExpectedRevision"],
        "property": plan["parentProperty"],
    }
    try:
        if not args.dry_run and plan["parentChanged"]:
            result = entities.apply_change(
                path, plan["parentId"], expected_revision=plan["parentExpectedRevision"],
                set_properties={TEAM_TASKS_PROPERTY: plan["parentProperty"]},
                replace_body=plan["parentBody"], actor=args.actor,
                reason="挂载/更新 Agent Team 子任务（会话规划）",
                audit_extra=(
                    {"op": "criteria-ids-init", "ids": str(len(plan.get("criteriaIdsAdded") or [])),
                     "with": "import-team"}
                    if plan.get("criteriaIdsAdded") else None
                ),
                default_status=DEFAULT_STATUS,
            )
            parent_row.update({
                "action": "update",
                "previousRevision": result.previous_revision,
                "revision": result.revision,
                "auditEventId": result.audit_event_id,
            })
            # 写后按文件真值刷新子任务行号
            reloaded = entities.load_entity(path, plan["parentId"], default_status=DEFAULT_STATUS)
            reload_lines = entities.read_text(path).split("\n")
            actual = {
                entry["id"]: entry["line"]
                for entry in parse_team_children(reloaded.body, base=_body_begin(reload_lines, reloaded))
            }
            for row in plan["created"] + plan["updated"] + plan["unchanged"] + plan["kept"]:
                if row["teamId"] in actual:
                    row["line"] = actual[row["teamId"]]
        else:
            parent_row["action"] = "would-update" if plan["parentChanged"] else "unchanged"
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)

    rows_created = [_team_child_row(e, dry_run=args.dry_run) for e in plan["created"]]
    rows_updated = [_team_child_row(e, dry_run=args.dry_run, changes=e.get("changes")) for e in plan["updated"]]
    rows_unchanged = [_team_child_row(e, dry_run=args.dry_run) for e in plan["unchanged"]]
    rows_kept = [_team_child_row(e, dry_run=args.dry_run, reason=e.get("reason")) for e in plan["kept"]]
    payload = {
        "ok": True,
        "mode": "parent",
        "project": project_key(args.project),
        "path": _relative(path, layout),
        "dry_run": args.dry_run,
        "count": plan["count"],
        "parentId": plan["parentId"],
        "parent": parent_row,
        "totals": {
            "created": len(rows_created),
            "updated": len(rows_updated),
            "kept": len(rows_kept),
            "skipped": len(plan["skipped"]),
            "unchanged": len(rows_unchanged),
            "unknownStatus": len(plan["unknownStatus"]),
        },
        "created": rows_created,
        "updated": rows_updated,
        "kept": rows_kept,
        "skipped": plan["skipped"],
        "unchanged": rows_unchanged,
        "unknownStatus": plan["unknownStatus"],
    }
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    prefix = "[dry-run] " if args.dry_run else ""
    print(prefix + "team 快照 " + str(payload["count"]) + " 条 → 挂到 " + str(plan["parentId"])
          + "（" + payload["path"] + "）")
    print("  子任务：新建 " + str(len(rows_created)) + " / 原地更新 " + str(len(rows_updated))
          + " / 无变化 " + str(len(rows_unchanged)) + " / 保留 " + str(len(rows_kept)))
    if parent_row.get("action") == "update":
        print("  父任务 " + str(plan["parentId"]) + " 已写 rev " + str(parent_row.get("previousRevision"))
              + " → " + str(parent_row.get("revision")) + "  audit " + str(parent_row.get("auditEventId")))
    elif parent_row.get("action") == "would-update":
        print("  父任务 " + str(plan["parentId"]) + " 将有更新（dry-run 未写）")
    else:
        print("  父任务无需变更")
    for row in rows_created:
        print("  + " + row["status"] + "  " + row["teamId"] + "  " + row["title"])
    for row in rows_updated:
        print("  ~ " + row["teamId"] + "  更新 " + ",".join(row.get("changes") or [])
              + "  → " + row["status"])
    for row in plan["unknownStatus"]:
        print("  ! 未知状态 " + repr(row["status"]) + " → " + row["mappedTo"] + "（team " + row["teamId"] + "）")
    for row in plan["skipped"]:
        print("  x 跳过：" + row["reason"])
    print("未落盘（默认 dry-run）；加 --write 才写。"
          if args.dry_run else "已落盘（--write）；同一快照再跑一次是 0 变更。")
    return 0


def command_import_team(args) -> int:
    """pm task import-team：把 Agent Team 任务板快照补进项目 tasks.org。

    默认 dry-run（同 pm render 惯例），--write 才落盘；只读 JSON 快照，**不读 harness 会话存储**。
    平面模式：新任务标 :PM_AI: t 并写 :PM_TEAM_TASK_ID: 作幂等锚点；completed → REVIEW，绝不写 DONE。
    --parent 模式：不建顶层任务，改把团队任务作为子任务记录挂到父任务（:PM_TEAM_TASKS: + 正文节），
    与父任务同一次 CAS + 一条审计；父任务不存在 → NOT_FOUND，终态 → PARENT_TERMINAL。
    """
    json_mode = bool(getattr(args, "json", False))
    args.dry_run = not bool(getattr(args, "write", False))
    layout, gate_error = _write_layout(args, json_mode)
    if layout is None:
        return _emit_error(json_mode, TaskOpError(gate_error[0], gate_error[1], exit_code=gate_error[2]))

    project = project_key(args.project)
    project_dir = layout.project_dir(project_dir_id(args.project))
    if not project_dir.is_dir():
        return _emit_error(json_mode, TaskOpError(
            "NOT_FOUND",
            "项目不存在: " + project + "（" + str(project_dir) + "）",
            extra={"hint": "先创建项目：pm project create " + project
                           + " --config <pm.toml>（备选：pm init --root " + str(layout.root)
                           + " --project " + project + "）"},
        ))

    try:
        snapshot = load_team_snapshot(args.from_json)
        wanted = {normalize_team_status(value) for value in (args.status or []) if str(value).strip()}
        path = tasks_path(layout, args.project)
        plan = plan_team_import(
            path, snapshot, project_id=project, parent_id=getattr(args, "parent", None),
            statuses=wanted or None, actor=args.actor,
        )
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)

    if plan["mode"] == "parent":
        return _finish_team_parent_import(args, layout, path, plan, json_mode)
    return _finish_team_flat_import(args, layout, path, plan, json_mode)


def _emit_dag_result(args, layout, plan, result, json_mode) -> int:
    payload = {
        "ok": True,
        "entityId": result.entity_id,
        "taskId": result.entity_id,
        "source": result.source,
        "observedAt": result.observed_at,
        "auditEventId": result.audit_event_id,
        "status": result.status,
        "revision": result.revision,
        "previousStatus": result.previous_status,
        "previousRevision": result.previous_revision,
        "changed": result.changed,
        "path": _relative(result.path, layout),
        "dagEdges": plan["edges"],
        "replaced": bool(args.replace),
        "allowUnknown": bool(args.allow_unknown),
        "unknownEndpoints": plan["unknownEndpoints"],
        "childIds": plan["childIds"],
    }
    if result.idempotent:
        payload["idempotent"] = True
    if getattr(args, "dry_run", False):
        payload["dry_run"] = True
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    prefix = "[dry-run] " if getattr(args, "dry_run", False) else ""
    if not result.changed:
        print(prefix + "无需变更：" + result.entity_id + " 的 DAG 已是 "
              + str(len(plan["edges"])) + " 条边")
        return 0
    print(prefix + "已更新 " + result.entity_id + " 的 DAG：" + str(len(plan["edges"])) + " 条边"
          + ("（--replace）" if args.replace else "（合并）")
          + "  rev " + str(result.previous_revision) + " → " + str(result.revision)
          + "  audit " + str(result.audit_event_id))
    for edge in plan["edges"]:
        print("  - " + edge[0] + " -> " + edge[1])
    if plan["unknownEndpoints"]:
        print("  ! --allow-unknown 放行了未知端点：" + ", ".join(plan["unknownEndpoints"]))
    return 0


def command_dag_set(args) -> int:
    """pm task dag set：写/合并任务的 *** 任务 DAG 节（CAS + 一条审计 op=dag-set）。

    默认合并去重按 (from,to) 排序；--replace 整体替换（无 --edge = 清空该节）；
    端点默认必须是该任务 :PM_TEAM_TASKS: 里的子任务（--allow-unknown 放行）；终态任务拒绝。
    """
    json_mode = bool(getattr(args, "json", False))
    layout, gate_error = _write_layout(args, json_mode)
    if layout is None:
        return _emit_error(json_mode, TaskOpError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    path = tasks_path(layout, args.project)
    try:
        entity = entities.load_entity(path, args.task_id, default_status=DEFAULT_STATUS)
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)

    status = _entity_status(entity)
    # CAS 先于领域校验（与 inbox 一致）：拿着旧 revision 的调用方先拿到 3，而不是被端点规则挡住
    if entity.revision != args.expected_revision:
        replay = _idempotent_result(path, entity, args.task_id, args.idempotency_key)
        if replay is not None:
            return _emit_dag_result(args, layout, {
                "edges": [list(edge) for edge in parse_dag_edges(list(entity.body or []), base=0)],
                "unknownEndpoints": [], "childIds": task_child_ids(entity),
            }, replay, json_mode)
        return _emit_error(json_mode, _conflict(entity.revision, args.expected_revision))
    if status in TERMINAL_STATUSES:
        return _emit_error(json_mode, TaskOpError(
            "TASK_TERMINAL",
            "任务 " + args.task_id + " 已是终态 " + status + "，拒绝改 DAG",
            extra={"taskId": args.task_id, "status": status},
        ))
    try:
        plan = plan_dag_set(
            entity, list(getattr(args, "edge", None) or []),
            replace=bool(args.replace), allow_unknown=bool(args.allow_unknown),
            raw_body=_raw_body_lines(entities.read_text(path).split("\n"), entity),
        )
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)

    try:
        if not plan["changed"]:
            replay = _idempotent_result(path, entity, args.task_id, args.idempotency_key)
            result = replay if replay is not None else _noop_result(path, entity, args.task_id, status)
        else:
            result = entities.apply_change(
                path, args.task_id, expected_revision=args.expected_revision,
                replace_body=plan["body"], actor=args.actor,
                reason=args.reason or "更新任务 DAG",
                idempotency_key=args.idempotency_key, dry_run=bool(args.dry_run),
                audit_extra=(
                    {"op": "criteria-ids-init", "ids": str(len(plan.get("criteriaIdsAdded") or [])),
                     "with": "dag-set", "edges": str(len(plan["edges"]))}
                    if plan.get("criteriaIdsAdded")
                    else {"op": "dag-set", "edges": str(len(plan["edges"]))}
                ),
                default_status=DEFAULT_STATUS,
            )
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)
    return _emit_dag_result(args, layout, plan, result, json_mode)


def _criteria_read_model(lines: list[str], base: int) -> list[dict]:
    """验收标准的只读形状：{id, text, done, line}（line 是 1-based 文件行号）。"""
    out: list[dict] = []
    for entry in _criterion_entries(lines):
        out.append({
            "id": entry["id"],
            "text": entry["text"],
            "done": entry["done"],
            "line": base + entry["index"] + 1,
        })
    return out


def _emit_criteria_init(args, layout, path, entity, added, result, json_mode) -> int:
    dry_run = bool(getattr(args, "dry_run", False))
    if result.changed and not dry_run:
        current = entities.load_entity(path, args.task_id, default_status=DEFAULT_STATUS)
        raw_lines = entities.read_text(path).split("\n")
        criteria = _criteria_read_model(_raw_body_lines(raw_lines, current),
                                        _body_begin(raw_lines, current))
    else:
        raw_lines = entities.read_text(path).split("\n")
        criteria = _criteria_with_added(_raw_body_lines(raw_lines, entity),
                                        _body_begin(raw_lines, entity), added)
    payload = {
        "ok": True,
        "entityId": result.entity_id,
        "taskId": result.entity_id,
        "source": result.source,
        "observedAt": result.observed_at,
        "auditEventId": result.audit_event_id,
        "status": result.status,
        "revision": result.revision,
        "previousStatus": result.previous_status,
        "previousRevision": result.previous_revision,
        "changed": result.changed,
        "path": _relative(result.path, layout),
        "criteriaIdsAdded": list(added),
        "criteria": criteria,
    }
    note = (result.extra or {}).get("note")
    if note:
        payload["note"] = note
    if result.idempotent:
        payload["idempotent"] = True
    if dry_run:
        payload["dry_run"] = True
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    prefix = "[dry-run] " if dry_run else ""
    if not result.changed:
        print(prefix + "无需变更：" + (note or (result.entity_id + " 的验收标准项都已有稳定 ID")))
        return 0
    print(prefix + "已补 " + str(len(added)) + " 个稳定 ID：" + result.entity_id
          + "  rev " + str(result.previous_revision) + " → " + str(result.revision)
          + "  audit " + str(result.audit_event_id))
    for row in criteria:
        print("  - [" + str(row["id"]) + "] " + ("x" if row["done"] else " ") + " " + row["text"])
    return 0


def command_criteria_init_ids(args) -> int:
    """pm task criteria init-ids：给缺稳定 ID 的验收标准项补 ID（只加 ID，幂等）。"""
    json_mode = bool(getattr(args, "json", False))
    layout, gate_error = _write_layout(args, json_mode)
    if layout is None:
        return _emit_error(json_mode, TaskOpError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    path = tasks_path(layout, args.project)
    try:
        entity = entities.load_entity(path, args.task_id, default_status=DEFAULT_STATUS)
        result = init_criterion_ids(
            path, args.task_id, expected_revision=args.expected_revision,
            actor=args.actor, reason=args.reason or "",
            idempotency_key=args.idempotency_key, dry_run=bool(args.dry_run),
        )
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)
    added = list((result.extra or {}).get("criteriaIdsAdded") or [])
    return _emit_criteria_init(args, layout, path, entity, added, result, json_mode)


def command_evidence_add(args) -> int:
    """pm task evidence add：给某条验收标准追加一条证据（append-only，一次 CAS + 一条审计）。"""
    json_mode = bool(getattr(args, "json", False))
    layout, gate_error = _write_layout(args, json_mode)
    if layout is None:
        return _emit_error(json_mode, TaskOpError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    path = tasks_path(layout, args.project)
    try:
        result = add_evidence(
            path, args.task_id,
            criterion_id=args.criterion_id, kind=args.kind, result=args.result,
            ref=args.ref, note=args.note or "", actor=args.actor,
            expected_revision=args.expected_revision, reason=args.reason or "",
            idempotency_key=args.idempotency_key, dry_run=bool(args.dry_run),
        )
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)
    entry = (result.extra or {}).get("evidence")
    payload = {
        "ok": True,
        "entityId": result.entity_id,
        "taskId": result.entity_id,
        "source": result.source,
        "observedAt": result.observed_at,
        "auditEventId": result.audit_event_id,
        "status": result.status,
        "revision": result.revision,
        "previousStatus": result.previous_status,
        "previousRevision": result.previous_revision,
        "changed": result.changed,
        "path": _relative(result.path, layout),
        "evidence": entry,
        "evidenceCount": (result.extra or {}).get("evidenceCount"),
    }
    if result.idempotent:
        payload["idempotent"] = True
    if getattr(args, "dry_run", False):
        payload["dry_run"] = True
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    prefix = "[dry-run] " if getattr(args, "dry_run", False) else ""
    if not result.changed:
        print(prefix + "重复证据，未写入：" + result.entity_id + " 已有六字段相同的证据"
              + "（" + str((result.extra or {}).get("evidenceCount")) + " 条）")
        return 0
    print(prefix + "已加证据 " + str(args.kind) + " · " + str(args.result) + " · " + str(args.ref)
          + "  → 标准 [" + str(args.criterion_id) + "]  " + result.entity_id
          + "  rev " + str(result.previous_revision) + " → " + str(result.revision)
          + "  audit " + str(result.audit_event_id))
    return 0


def command_evidence_rm(args) -> int:
    """pm task evidence rm：按证据 id 移除一条证据（CAS + 审计；找不到 id 明确报错）。"""
    json_mode = bool(getattr(args, "json", False))
    layout, gate_error = _write_layout(args, json_mode)
    if layout is None:
        return _emit_error(json_mode, TaskOpError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    path = tasks_path(layout, args.project)
    try:
        result = remove_evidence(
            path, args.task_id, args.evidence_id,
            expected_revision=args.expected_revision, reason=args.reason or "",
            actor=args.actor, idempotency_key=args.idempotency_key, dry_run=bool(args.dry_run),
        )
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)
    removed = (result.extra or {}).get("evidence") or {}
    payload = {
        "ok": True,
        "entityId": result.entity_id,
        "taskId": result.entity_id,
        "source": result.source,
        "observedAt": result.observed_at,
        "auditEventId": result.audit_event_id,
        "status": result.status,
        "revision": result.revision,
        "previousStatus": result.previous_status,
        "previousRevision": result.previous_revision,
        "changed": result.changed,
        "path": _relative(result.path, layout),
        "evidenceId": args.evidence_id,
        "removed": removed or None,
        "evidenceCount": (result.extra or {}).get("evidenceCount"),
    }
    if result.idempotent:
        payload["idempotent"] = True
    if getattr(args, "dry_run", False):
        payload["dry_run"] = True
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    prefix = "[dry-run] " if getattr(args, "dry_run", False) else ""
    print(prefix + "已移除证据 " + str(args.evidence_id)
          + "（" + str(removed.get("kind")) + " · " + str(removed.get("result"))
          + " · " + str(removed.get("ref")) + "）  " + result.entity_id
          + "  rev " + str(result.previous_revision) + " → " + str(result.revision)
          + "  剩 " + str(payload["evidenceCount"]) + " 条  audit " + str(result.audit_event_id))
    return 0


def command_evidence_list(args) -> int:
    """pm task evidence list：只读列出任务的验收证据。"""
    json_mode = bool(getattr(args, "json", False))
    layout, error = _read_layout(args)
    if error is not None:
        return _emit_error(json_mode, error)
    path = tasks_path(layout, args.project)
    try:
        evidence = list_evidence(path, args.task_id)
    except entities.EntityError as exc:
        return _emit_error(json_mode, exc)
    payload = {
        "ok": True,
        "taskId": args.task_id,
        "path": _relative(path, layout),
        "count": len(evidence),
        "evidence": evidence,
    }
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not evidence:
        print("该任务还没有验收证据（*** 证据（验收） 节为空或不存在）。")
        return 0
    print("证据 " + str(len(evidence)) + " 条（" + payload["path"] + "）")
    for row in evidence:
        print("  [" + str(row["criterionId"]) + "] " + str(row["kind"]) + " · " + str(row["result"])
              + " · " + str(row["ref"]) + " · " + str(row["at"]) + " · " + str(row["actor"])
              + ("  " + str(row["note"]) if row["note"] else ""))
    return 0

