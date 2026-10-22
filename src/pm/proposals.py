"""Plan Proposal 模型（backend-design §5.3）：AI 生成计划 → 人批准 / 拒绝。

硬约束
------
1. **提案与正式任务分离**：提案存放在 work-memory/proposals.org（独立文件）。
   文件里存在提案时，tasks.org 一个字节都不受影响。
2. **批准必须 CAS**：approve/reject 都要求 expected_revision == :PM_REVISION:；
   不一致 → REVISION_CONFLICT（退出码 3），**三个文件逐字节不变**。
3. **拒绝的提案不会创建任何正式任务，也不能派发**；拒绝只改 proposals.org。
4. **批准是补偿式多文件事务，不是原子事务**：
      proposals.org + tasks.org + inbox.org
   先全部校验（只读），再按 tasks → inbox → proposals 顺序逐个原子写。
   proposals 的状态是「提交标记」，所以放最后。中途失败如实返回 written / notWritten，
   **不假装原子**（PARTIAL_WRITE）。
   每步都能靠**回链**判定是否已完成，因此重试收敛：
      task  :PM_SOURCE_PROPOSAL_ID: = 本提案 → 跳过创建
      inbox :PM_PROPOSAL_ID:        = 本提案 → 跳过状态迁移
   这正是「已由本提案完成」与「被别人创建」的区别（后者才是 ALREADY_TASK_CREATED 错误）。
5. **不派发任何东西给 DSH** —— 派发是 P3-后端 后半段、且需要明确点击。

实现注记：**criteria 是对 §5.3 的超集扩展** ——「变更」下缩进的子项 = 该变更的验收标准。
§5.3 的必填键一个都没变；不理解该扩展的解析器直接忽略它即可，不会报错。

写入一律走 pm.entities（CAS / 原子写 / 审计 / 幂等）：本模块不自己拼 org、不自己写审计。
CLI：本模块自带 register_cli，pm.cli 会 importlib 自动挂载（不用改 cli.py）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from pm import entities, ids
from pm.humanwrite import append_under_tracked, plan_entry
from pm.layout import Layout
from pm.summaries import _split_headline

# ---------------------------------------------------------------- 常量

#: §5.3 的提案真源：库根下的独立单文件（不是 proposals/ 目录）。
PROPOSALS_RELATIVE = "proposals.org"
#: 提案所在的 org 一级小节（create_entity 需要它来定位插入点）。
PROPOSALS_SECTION = "Proposals"
PROPOSALS_TITLE = "Proposals"
#: 首次创建 proposals.org 时的文件头（与 inbox.org 的 #+TITLE: Inbox 对齐）。
PROPOSALS_HEADER_TEXT = (
    "#+TITLE: Proposals\n"
    "\n"
    "* Proposals\n"
    "  由 pm 维护：AI 计划提案，等人确认；未批准的提案不会创建正式任务。\n"
)
#: 二级标题前缀：** PROPOSAL <标题>
PROPOSAL_PREFIX = "PROPOSAL"

INBOX_SECTION = "Inbox"
TASKS_SECTION = "任务"

PROPOSAL_KIND = "proposal"
TASK_KIND = "task"

STATUS_PENDING = "PENDING"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
LEGACY_STATUS = "LEGACY_UNTRACKED"

TASK_STATUS_TODO = "TODO"
INBOX_STATUS_TASK_CREATED = "TASK_CREATED"
#: create 之后源 inbox 的状态（§5.1：CAPTURED/TRIAGE --propose--> TASK_PROPOSED --approve--> TASK_CREATED）。
PROPOSE_STATUS = "TASK_PROPOSED"
INBOX_RELATIVE = "inbox.org"

SECTION_CHANGES = "变更"
SECTION_RISKS = "风险与待确认"
SECTION_ACTIONS = "操作"
DEFAULT_ACTION = "批准后创建正式任务；拒绝不改变正式任务。"

#: 「新增一条任务」的操作词；其它操作 v1 不静默忽略，明确拒绝。
ADD_OPS = frozenset({"新增", "ADD", "CREATE", "新建"})
#: 允许 → TASK_CREATED 的 source inbox 状态（§5.1）。
INBOX_ACTIONABLE = frozenset({"CAPTURED", "TRIAGE", "TASK_PROPOSED"})

#: 冲突用专用退出码（与 inbox / entities 一致）。
EXIT_CONFLICT = entities.EXIT_CONFLICT
EXIT_INPUT = entities.EXIT_INPUT

_CHANGE_HEAD = re.compile(
    r"^(?P<op>\S+)\s+(?P<task_id>task-\S+?)(?:\s*[：:]\s*(?P<title>.*))?$"
)
_AT_COL0 = re.compile(r"^(?P<stars>\*+)(?:\s+(?P<title>.*))?$")


class ProposalError(Exception):
    """一次提案操作的明确失败；code 是机器可读错误码。"""

    def __init__(self, code: str, message: str, *, exit_code: int = EXIT_INPUT, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.extra = dict(extra or {})


@dataclass
class ProposalResult:
    """提案写操作的统一返回（§5）+ 提案域附加字段。"""

    path: Path
    entity_id: str
    status: str
    revision: int
    previous_status: str = ""
    previous_revision: int = 0
    changed: bool = True
    source: str = entities.SOURCE_ORG
    observed_at: str | None = None
    audit_event_id: str | None = None
    idempotent: bool = False
    dry_run: bool = False
    audit_line: str = ""
    # ---- 提案域 ----
    line: int | None = None
    source_inbox_id: str | None = None
    base_revision: int | None = None
    plan_revision: int | None = None
    project: str | None = None
    inbox_revision: int | None = None
    inbox_status: str | None = None
    #: 两文件（proposals.org + inbox.org）写只完成了一部分时置 True（不假装原子）。
    partial: bool = False
    #: partial 时给出的可复制补救命令。
    hint: str | None = None
    task_ids: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def inbox_id(self) -> str:
        """兼容 inbox 域的命名习惯。"""
        return self.entity_id


# ---------------------------------------------------------------- 工具


def _collapse(value) -> str:
    return " ".join(str(value or "").split())


def _int_or_none(value) -> int | None:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def _col0_level(raw: str) -> int:
    match = _AT_COL0.match(raw)
    return len(match.group("stars")) if match else 0


def _wrap(exc: entities.EntityError) -> ProposalError:
    """把 entities 的错误原样转成本域的 ProposalError（保留 code/exit_code/extra）。"""
    return ProposalError(exc.code, exc.message, exit_code=exc.exit_code, extra=exc.extra)


def as_layout(target) -> Layout:
    """接受 Layout 或库根路径。"""
    return target if isinstance(target, Layout) else Layout(Path(target))


def proposals_path(target) -> Path:
    """提案真源路径（pm.layout.Layout.proposals_file）。"""
    return as_layout(target).proposals_file


def new_proposal_id(now_ms: int | None = None) -> str:
    return "proposal-" + ids.new_ulid(now_ms)


def new_task_id(now_ms: int | None = None) -> str:
    return "task-" + ids.new_ulid(now_ms)


def _read_text(path: Path, *, what: str) -> str:
    try:
        return entities.read_text(path)
    except entities.EntityError as exc:
        if exc.code == "NOT_FOUND":
            raise ProposalError("NOT_FOUND", f"找不到{what}文件 {path}") from exc
        raise _wrap(exc) from exc


def _find_block(text: str, entity_id: str, *, headline: str | None, default_status: str) -> dict:
    """在 org 文本里按 :ID: 找块；找不到区分 LEGACY_UNTRACKED / NOT_FOUND。"""
    blocks = entities.iter_entity_blocks(text, headline=headline)
    for block in blocks:
        if block["props"].get("ID") == entity_id:
            return block
    untracked = [block for block in blocks if not block["props"].get("ID")]
    if untracked:
        raise _wrap(entities.legacy_error(entity_id, len(untracked)))
    raise ProposalError("NOT_FOUND", f"找不到 :ID: 为 {entity_id} 的条目")


def _block_status(block: dict, default_status: str) -> str:
    return (block["props"].get("PM_STATUS") or default_status).strip().upper()


# ---------------------------------------------------------------- 解析


def _proposal_title(headline_title: str) -> str:
    text = (headline_title or "").strip()
    if text.upper().startswith(PROPOSAL_PREFIX):
        text = text[len(PROPOSAL_PREFIX):].strip()
    return text


def _parse_change(text: str) -> dict:
    """把一条「变更」项目解析成 {op, task_id, title, text}。

    例：新增 task-ABC：明确输入范围 → op=新增 / task_id=task-ABC / title=明确输入范围。
    格式不完整时尽量宽容（不丢内容），op 取第一个词，其余进 title。
    """
    raw = _collapse(text)
    if not raw:
        return {"op": "", "task_id": None, "title": "", "text": ""}
    match = _CHANGE_HEAD.match(raw)
    if match:
        return {
            "op": match.group("op").strip(),
            "task_id": match.group("task_id").strip(),
            "title": (match.group("title") or "").strip(),
            "text": raw,
        }
    op, sep, rest = raw.partition("：")
    if not sep:
        op, sep, rest = raw.partition(":")
    if sep:
        return {"op": op.strip(), "task_id": None, "title": rest.strip(), "text": raw}
    head, _gap, tail = raw.partition(" ")
    return {"op": head.strip(), "task_id": None, "title": tail.strip(), "text": raw}


def _parse_criterion(text: str) -> dict | None:
    """一条验收标准：- [ ] 文本 / - [x] 文本 / 纯文本。"""
    item = _collapse(text)
    if not item:
        return None
    match = re.match(r"^\[(?P<mark>[ xX])\]\s*(?P<text>.*)$", item)
    if match:
        return {"text": match.group("text").strip(), "done": match.group("mark").lower() == "x"}
    return {"text": item, "done": False}


def _parse_body_sections(body: list[str]) -> tuple[list[dict], list[str], list[str]]:
    """从实体正文里取 *** 变更 / *** 风险与待确认 / *** 操作 三段。

    「变更」下**缩进**的子列表项是该变更携带的验收标准，不是新变更。
    """
    changes: list[dict] = []
    risks: list[str] = []
    actions: list[str] = []
    current: str | None = None
    for raw in body:
        line = raw.rstrip()
        level = _col0_level(line)
        if level == 3:
            current = _split_headline(line)[1]
            continue
        if level:  # 更深/更浅的其它 headline：不属于这三段
            continue
        stripped = line.strip()
        if not stripped or current is None:
            continue
        indent = len(line) - len(line.lstrip(" "))
        if stripped.startswith(("- ", "+ ")):
            item = stripped[2:].strip()
        else:
            item = stripped
        if not item:
            continue
        if current == SECTION_CHANGES:
            if indent > 0 and changes:
                criterion = _parse_criterion(item)
                if criterion is not None:
                    changes[-1]["criteria"].append(criterion)
                    continue
            change = _parse_change(item)
            change["criteria"] = []
            changes.append(change)
        elif current == SECTION_RISKS:
            risks.append(item)
        elif current == SECTION_ACTIONS:
            actions.append(item)
    return changes, risks, actions


def parse_proposals(text: str, *, section: str | None = PROPOSALS_SECTION) -> list[dict]:
    """解析 proposals.org 文本 → 提案列表（按文件顺序）。

    每项：
      id / kind / status / revision / title / line /
      source_inbox_id / base_revision / plan_revision / created_by / project /
      changes:[{op, task_id, title, text, criteria:[{text, done}]}] / risks:[str] / actions:[str] / props
      （criteria 是 §5.3 的超集扩展：照原文写的旧解析器忽略它不会出错。）
    没有 :ID: 的条目 status = LEGACY_UNTRACKED、id = None（§9：身份只看 :ID:）。
    """
    proposals: list[dict] = []
    for block in entities.iter_entity_blocks(text, headline=section):
        props = dict(block["props"])
        proposal_id = props.get("ID") or None
        _level, headline_title = _split_headline(block["headline"])
        changes, risks, actions = _parse_body_sections(block["body"])
        if proposal_id:
            status = (props.get("PM_STATUS") or STATUS_PENDING).strip().upper()
            kind = props.get("PM_KIND") or PROPOSAL_KIND
            revision = entities.revision_of(props)
        else:
            status, kind, revision = LEGACY_STATUS, None, None
        proposals.append(
            {
                "id": proposal_id,
                "kind": kind,
                "status": status,
                "revision": revision,
                "title": _proposal_title(headline_title),
                "line": block["line"],
                "source_inbox_id": props.get("PM_SOURCE_INBOX_ID") or None,
                "base_revision": _int_or_none(props.get("PM_BASE_REVISION")),
                "plan_revision": _int_or_none(props.get("PM_PLAN_REVISION")),
                "created_by": props.get("PM_CREATED_BY") or None,
                "project": props.get("PM_PROJECT") or None,
                "changes": changes,
                "risks": risks,
                "actions": actions,
                "props": props,
            }
        )
    return proposals


def list_proposals(library_root, *, status: str | None = None) -> dict:
    """列出提案（读命令，无闸门）。文件不存在 → count 0。"""
    path = proposals_path(library_root)
    if not path.is_file():
        return {"path": PROPOSALS_RELATIVE, "count": 0, "proposals": []}
    text = _read_text(path, what="提案")
    rows = parse_proposals(text)
    wanted = (status or "").strip().upper() or None
    if wanted:
        rows = [row for row in rows if (row["status"] or "").upper() == wanted]
    return {"path": PROPOSALS_RELATIVE, "count": len(rows), "proposals": rows}


# ---------------------------------------------------------------- 序列化


def _normalize_criteria(items) -> list[dict]:
    """验收标准归一成 [{text, done}]。"""
    normalized: list[dict] = []
    for item in items or []:
        if isinstance(item, str):
            parsed = _parse_criterion(item)
        elif isinstance(item, dict):
            parsed = _parse_criterion(str(item.get("text") or ""))
            if parsed is not None:
                parsed["done"] = bool(item.get("done"))
        else:
            raise ProposalError("INVALID_CRITERION", f"无法理解的验收标准: {item!r}")
        if parsed is not None:
            normalized.append(parsed)
    return normalized


def normalize_changes(changes) -> list[dict]:
    """把 str / dict 混合的变更列表归一成 {op, task_id, title, text, criteria}。"""
    normalized: list[dict] = []
    for raw in changes or []:
        if isinstance(raw, str):
            change = _parse_change(raw)
            change["criteria"] = []
            normalized.append(change)
            continue
        if isinstance(raw, dict):
            op = _collapse(raw.get("op") or "新增") or "新增"
            if op.upper() in ("ADD", "CREATE"):
                op = "新增"
            task_id = raw.get("task_id") or raw.get("taskId") or None
            title = _collapse(raw.get("title") or "")
            normalized.append(
                {
                    "op": op,
                    "task_id": (str(task_id).strip() or None) if task_id else None,
                    "title": title,
                    "text": _collapse(raw.get("text") or ""),
                    "criteria": _normalize_criteria(raw.get("criteria")),
                }
            )
            continue
        raise ProposalError("INVALID_CHANGE", f"无法理解的变更项: {raw!r}")
    return normalized


def _is_add_op(op: str | None) -> bool:
    text = (op or "").strip()
    return text in ADD_OPS or text.upper() in ADD_OPS


def _change_line(change: dict) -> str:
    parts = [change.get("op") or ""]
    if change.get("task_id"):
        parts.append(change["task_id"])
    head = " ".join(part for part in parts if part).strip() or "新增"
    title = _collapse(change.get("title"))
    return f"- {head}：{title}" if title else f"- {head}"


def _criterion_line(criterion) -> str:
    item = _normalize_criteria([criterion])[0]
    return "- [" + ("x" if item["done"] else " ") + "]" + ((" " + item["text"]) if item["text"] else "")


def _ensure_proposals_file(path: Path) -> None:
    """首次创建时写入 #+TITLE: Proposals 文件头（已存在的文件不重写）。"""
    if path.is_file():
        return
    if path.exists():
        raise ProposalError("NOT_A_FILE", f"提案路径不是普通文件: {path}")
    from pm.org import write_atomic

    try:
        write_atomic(path, PROPOSALS_HEADER_TEXT, fsync=True)
    except OSError as exc:
        raise ProposalError("WRITE_FAILED", f"创建 proposals.org 失败，未写入任何内容: {exc}") from exc


def _planned_create_line(path: Path) -> int:
    """dry-run：算出新提案块会落在第几行（真写同样先建文件头再追加）。"""
    if path.is_file():
        _found, line = plan_entry(path, headline=PROPOSALS_SECTION, block="** placeholder")
        return line
    _updated, _found, index = append_under_tracked(
        PROPOSALS_HEADER_TEXT, headline=PROPOSALS_SECTION, block="** placeholder"
    )
    return index + 1


def proposal_body_lines(changes: list[dict], risks: list[str], actions: list[str] | None) -> list[str]:
    """§5.3 的正文：*** 变更 / *** 风险与待确认 / *** 操作。

    变更下缩进 2 空格的子列表项是该变更的验收标准（缩进 2 而不是 3，
    因为 entities 会把 3 空格缩进剥掉）。
    **criteria 是对 §5.3 的超集扩展**：必填键一个没变，旧解析器忽略子项即可；
    照 §5.3 原文写新解析器时，别把缩进子项当成一条新「变更」。
    """
    lines = ["", f"*** {SECTION_CHANGES}"]
    for change in changes:
        lines.append(_change_line(change))
        for criterion in change.get("criteria") or []:
            lines.append("  " + _criterion_line(criterion))
    lines += ["", f"*** {SECTION_RISKS}"]
    lines.extend(f"- {_collapse(risk)}" for risk in risks or [])
    lines += ["", f"*** {SECTION_ACTIONS}"]
    action_lines = [str(action).strip() for action in (actions or [DEFAULT_ACTION]) if str(action).strip()]
    lines.extend(action_lines or [DEFAULT_ACTION])
    return lines


# ---------------------------------------------------------------- 源 inbox 的 propose 步骤


def _inbox_transition_error(current: str, target: str) -> entities.EntityError | None:
    """用 inbox 域自己的状态机校验迁移，返回 entities 形态的错误（不在这里重写迁移表）。"""
    try:
        from pm import inbox_ops
    except ImportError:  # pragma: no cover - inbox 域总是存在
        return None
    try:
        inbox_ops.validate_transition(current, target)
    except inbox_ops.InboxOpError as exc:
        return entities.EntityError(exc.code, exc.message, exit_code=exc.exit_code, extra=exc.extra)
    return None


def _inbox_can_become_task_proposed(status: str) -> bool:
    """CAPTURED/TRIAGE/TASK_PROPOSED/SNOOZED → TASK_PROPOSED；终态与 TASK_CREATED 不行。"""
    if status == PROPOSE_STATUS:
        return True
    try:
        from pm import inbox_ops
    except ImportError:  # pragma: no cover
        return status in {"CAPTURED", "TRIAGE", "SNOOZED"}
    return PROPOSE_STATUS in inbox_ops.ALLOWED_TRANSITIONS.get(status, frozenset())


def _pending_proposal_for_inbox(proposals_text: str, inbox_id: str) -> dict | None:
    """同一条 inbox 是否已有 PENDING 提案（防呆：避免对同一条重复生成提案）。"""
    for row in parse_proposals(proposals_text):
        if row["status"] == STATUS_PENDING and row["source_inbox_id"] == inbox_id:
            return row
    return None


def _proposed_revision_marker(inbox_text: str, block: dict, proposal_id: str) -> int | None:
    """本提案把源 inbox 标成 TASK_PROPOSED 时产生的 revision。

    优先读 :PM_PROPOSED_REVISION: 属性；老数据（task-47 时代）没有这个属性，
    就从那条审计行（op=propose + proposalId=<本提案>）里的 rev= 恢复。都取不到 → None。
    """
    marked = _int_or_none(block["props"].get("PM_PROPOSED_REVISION"))
    if marked is not None:
        return marked
    lines = inbox_text.splitlines()
    region = "\n".join(lines[block["start"]: block["end"]])
    for line in reversed(region.splitlines()):
        if "op=propose" not in line or ("proposalId=" + proposal_id) not in line:
            continue
        match = re.search(r"(?<!\S)rev=(\d+)", line)
        if match:
            return int(match.group(1))
    return None


def _mark_inbox_proposed(
    inbox_file: Path,
    inbox_id: str,
    *,
    proposal_id: str,
    expected_revision: int,
    actor: str,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> entities.OpResult:
    """把源 inbox CAS 成 TASK_PROPOSED；审计留 op=propose 与 proposalId。"""

    def _validate(entity: entities.Entity, target_status: str) -> None:
        error = _inbox_transition_error(entity.status, target_status)
        if error is not None:
            raise error

    return entities.apply_change(
        inbox_file,
        inbox_id,
        expected_revision=expected_revision,
        status=PROPOSE_STATUS,
        set_properties={
            "PM_PROPOSAL_ID": proposal_id,
            # 记下「这次标记把 revision 推到了几」：approve 判 STALE 时既要排除我们自己的写入，
            # 又不能把 revise 重挂到当前 revision 之后误判成陈旧（见 plan_approve 的 own_propose 规则）。
            "PM_PROPOSED_REVISION": str(int(expected_revision) + 1),
        },
        actor=actor,
        reason=f"proposal {proposal_id} created",
        audit_extra={"proposalId": proposal_id, "op": "propose"},
        idempotency_key=idempotency_key,
        now=now,
        headline=INBOX_SECTION,
        default_status="CAPTURED",
        validate=_validate,
    )


def _create_partial_error(exc: Exception, *, proposal_id: str, source_inbox_id: str) -> ProposalError:
    """proposals.org 已写、inbox.org 未写：如实报告 + 可复制的补救命令（不得假成功）。"""
    cause_code = getattr(exc, "code", "WRITE_FAILED")
    cause_message = getattr(exc, "message", str(exc))
    current = (getattr(exc, "extra", None) or {}).get("currentRevision")
    revision_text = str(current) if current is not None else "<当前值>"
    hint = (
        f"pm inbox set-status {source_inbox_id} TASK_PROPOSED "
        f"--expected-revision {revision_text} --reason 'proposal {proposal_id} created'"
    )
    return ProposalError(
        "PARTIAL_WRITE",
        f"提案 {proposal_id} 已写入 proposals.org，但对源 inbox {source_inbox_id} 标记 "
        f"TASK_PROPOSED 失败（{cause_code}: {cause_message}）。这不是假成功：proposals.org 已落盘、"
        f"inbox.org 未改。补救：{hint}；或用同一 --idempotency-key 重试；"
        "也可以直接 pm proposal approve（approve 保留 CAPTURED 入口）。",
        exit_code=getattr(exc, "exit_code", EXIT_INPUT),
        extra={
            "partial": True,
            "proposalId": proposal_id,
            "entityId": proposal_id,
            "sourceInboxId": source_inbox_id,
            "written": [PROPOSALS_RELATIVE],
            "notWritten": [INBOX_RELATIVE],
            "hint": hint,
            "cause": {"code": cause_code, "message": cause_message},
        },
    )


# ---------------------------------------------------------------- create


def create_proposal(
    library_root,
    *,
    source_inbox_id: str,
    changes,
    risks=None,
    actions=None,
    title: str | None = None,
    expected_revision: int | None = None,
    plan_revision: int = 1,
    created_by: str = "ai",
    reason: str = "",
    project: str | None = None,
    proposal_id: str | None = None,
    idempotency_key: str | None = None,
    actor: str | None = None,
    allow_duplicate: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> ProposalResult:
    """生成一条提案，并把它钉在源 inbox 上（**补偿式两文件写，不是原子写**）。

    顺序（proposals.org 是提交点，先写）：
      1. proposals.org：原子写 + 审计（§5.3），失败则整体失败（一个字节都没写）；
      2. inbox.org：CAS 源条目 → TASK_PROPOSED（§5.1），审计带 op=propose 与 proposalId。
    第 2 步失败时**不得假装成功**：抛 PARTIAL_WRITE，extra 带
      partial:true / written:["proposals.org"] / notWritten:["inbox.org"] / hint（可复制的补救命令），
    退出码沿用底层映射（冲突 3 / 输入 2）。提案本身已经落盘、仍然可 list/show。

    其它约束：
    - source_inbox_id 必须是一条已存在的 inbox :ID:（只读校验）。
    - expected_revision 可选：源 inbox 的 CAS；不一致 → REVISION_CONFLICT（退出码 3），一字节不写。
    - 同一条 inbox 已有 PENDING 提案 → PROPOSAL_EXISTS_FOR_INBOX；显式 allow_duplicate 才放行。
    - project 是**人确认过的项目**（显式参数）。不给就不写 :PM_PROJECT:，
      源 Inbox 的 PM_PROJECT_HINT 只作为 hint 回传，绝不静默采用（§0.2 / §5.1）。
    - 「新增」类变更若没给 task_id，这里**预分配** task-<ULID>，用户看到的就是批准后创建的那个 id。
    - actor 是本次调用的发起者（写两条审计）；缺省回落到 created_by。
    """
    now = now or datetime.now().astimezone()
    layout = as_layout(library_root)
    proposals_file = layout.proposals_file
    inbox_file = layout.inbox

    key = "".join(str(idempotency_key).split()) if idempotency_key else ""
    actor = (actor or created_by or "ai").strip() or "ai"
    if key and proposals_file.is_file():
        replay = _replay_create(proposals_file, key)
        if replay is not None:
            # 重放时把可能没落地的 inbox 步骤补上，否则两文件事务永远收敛不了。
            return _complete_replay_inbox(
                replay, inbox_file=inbox_file, actor=actor, idempotency_key=key, now=now
            )

    inbox_text = _read_text(inbox_file, what="inbox")
    inbox_block = _find_block(inbox_text, source_inbox_id, headline=INBOX_SECTION, default_status="CAPTURED")
    if inbox_block["drawer"] is None:
        raise ProposalError(
            "LEGACY_UNTRACKED",
            f"{source_inbox_id} 没有 :PROPERTIES: 抽屉，无法生成提案；请先补 :ID: / 状态字段。",
        )

    base = entities.revision_of(inbox_block["props"])
    if expected_revision is not None and int(expected_revision) != base:
        raise ProposalError(
            "REVISION_CONFLICT",
            f"revision 冲突：源 inbox 现在是 {base}，你看到的是 {expected_revision}；一个字节都没写",
            exit_code=EXIT_CONFLICT,
            extra={
                "currentRevision": base,
                "expectedRevision": int(expected_revision),
                "diffHint": "源 inbox 已被修改，请重新读取后再生成提案",
            },
        )

    inbox_status = _block_status(inbox_block, "CAPTURED")
    if not _inbox_can_become_task_proposed(inbox_status):
        code = (
            "ALREADY_TASK_CREATED"
            if inbox_status == INBOX_STATUS_TASK_CREATED
            else "PROPOSAL_SOURCE_NOT_ACTIONABLE"
        )
        raise ProposalError(
            code,
            f"源 Inbox {source_inbox_id} 状态是 {inbox_status}，不能再生成提案"
            "（§5.1 只允许 CAPTURED/TRIAGE/TASK_PROPOSED/SNOOZED → TASK_PROPOSED）。",
            extra={"sourceInboxId": source_inbox_id, "sourceStatus": inbox_status},
        )

    proposals_text = entities.read_text(proposals_file) if proposals_file.is_file() else ""
    pending = _pending_proposal_for_inbox(proposals_text, source_inbox_id)
    if pending is not None and not allow_duplicate:
        raise ProposalError(
            "PROPOSAL_EXISTS_FOR_INBOX",
            f"{source_inbox_id} 已有待批准提案 {pending['id']}；先批准或拒绝它，"
            "确需再建一条请显式加 --allow-duplicate。",
            extra={
                "existingProposalId": pending["id"],
                "sourceInboxId": source_inbox_id,
                "revision": pending["revision"],
            },
        )

    hint = (inbox_block["props"].get("PM_PROJECT_HINT") or "").strip() or None
    project = (project or "").strip() or None

    normalized = normalize_changes(changes)
    for change in normalized:
        if not _is_add_op(change.get("op")):
            raise ProposalError(
                "UNSUPPORTED_CHANGE_OP",
                f"v1 只支持「新增」类变更，收到 {change.get('op')!r}；"
                "修改/删除请走 task 域，不要放进提案（提案不能静默忽略变更）。",
            )
        if not change.get("task_id"):
            change["task_id"] = new_task_id(int(now.timestamp() * 1000))

    proposal_id = proposal_id or new_proposal_id(int(now.timestamp() * 1000))
    title = (title or "").strip() or f"从 {source_inbox_id} 生成任务计划"

    properties: dict[str, str] = {
        "PM_SOURCE_INBOX_ID": source_inbox_id,
        "PM_BASE_REVISION": str(base),
        "PM_PLAN_REVISION": str(int(plan_revision)),
        "PM_CREATED_BY": created_by or "ai",
    }
    if project:
        properties["PM_PROJECT"] = project
    if _collapse(reason):
        properties["PM_CREATE_REASON"] = _collapse(reason)
    body = proposal_body_lines(normalized, list(risks or []), list(actions or []))

    if dry_run:
        line = _planned_create_line(proposals_file)
        return ProposalResult(
            path=proposals_file,
            entity_id=proposal_id,
            status=STATUS_PENDING,
            revision=1,
            dry_run=True,
            observed_at=now.isoformat(timespec="seconds"),
            line=line,
            source_inbox_id=source_inbox_id,
            base_revision=base,
            plan_revision=int(plan_revision),
            project=project,
            task_ids=[change["task_id"] for change in normalized],
            inbox_status=PROPOSE_STATUS,
            inbox_revision=base + 1,
            steps=[
                {"name": "proposal", "status": "planned", "line": line},
                {"name": "inbox", "status": "planned", "skip": False},
            ],
            extra={"projectHint": hint, "written": [], "notWritten": []},
        )

    try:
        _ensure_proposals_file(proposals_file)
        created = entities.create_entity(
            proposals_file,
            entity_id=proposal_id,
            kind=PROPOSAL_KIND,
            status=STATUS_PENDING,
            headline=f"{PROPOSAL_PREFIX} {title}",
            section=PROPOSALS_SECTION,
            properties=properties,
            body_lines=body,
            indent_body=False,  # §5.3 的 *** 变更/风险/操作 必须是真子标题，不能缩进
            idempotency_key=key or None,
            actor=actor,
            now=now,
        )
    except entities.EntityError as exc:
        raise _wrap(exc) from exc
    except OSError as exc:
        raise ProposalError("WRITE_FAILED", f"写 proposals.org 失败，未写入任何内容: {exc}") from exc

    # 提交点已落盘。第二步：把源 inbox CAS 成 TASK_PROPOSED —— 失败绝不假装成功。
    try:
        inbox_op = _mark_inbox_proposed(
            inbox_file,
            source_inbox_id,
            proposal_id=proposal_id,
            expected_revision=base,
            actor=actor,
            idempotency_key=key or None,
            now=now,
        )
    except entities.EntityError as exc:
        raise _create_partial_error(exc, proposal_id=proposal_id, source_inbox_id=source_inbox_id) from exc
    except OSError as exc:
        raise _create_partial_error(exc, proposal_id=proposal_id, source_inbox_id=source_inbox_id) from exc

    return ProposalResult(
        path=proposals_file,
        entity_id=proposal_id,
        status=STATUS_PENDING,
        revision=1,
        observed_at=created.observed_at or now.isoformat(timespec="seconds"),
        audit_event_id=created.audit_event_id,
        line=created.line,
        source_inbox_id=source_inbox_id,
        base_revision=base,
        plan_revision=int(plan_revision),
        project=project,
        task_ids=[change["task_id"] for change in normalized],
        inbox_status=inbox_op.status,
        inbox_revision=inbox_op.revision,
        partial=False,
        steps=[
            {
                "name": "proposal",
                "status": "written",
                "entityId": proposal_id,
                "line": created.line,
                "auditEventId": created.audit_event_id,
            },
            {
                "name": "inbox",
                "status": "written",
                "entityId": source_inbox_id,
                "revision": inbox_op.revision,
                "auditEventId": inbox_op.audit_event_id,
            },
        ],
        extra={"projectHint": hint, "written": [PROPOSALS_RELATIVE, INBOX_RELATIVE], "notWritten": []},
    )


# ---------------------------------------------------------------- 计划（纯逻辑，不落盘）


def _find_proposal_item(text: str, proposal_id: str) -> dict:
    rows = parse_proposals(text)
    for row in rows:
        if row["id"] == proposal_id:
            return row
    untracked = [row for row in rows if not row["id"]]
    if untracked:
        raise _wrap(entities.legacy_error(proposal_id, len(untracked)))
    raise ProposalError(
        "NOT_FOUND",
        f"找不到 :ID: 为 {proposal_id} 的提案；可用 pm proposal list 查看现有提案。",
    )


def _resolve_project(explicit: str | None, item: dict, inbox_block: dict | None) -> str:
    """显式 project > 提案 :PM_PROJECT:；都没有 → PROJECT_REQUIRED（**不静默用 hint**）。"""
    project = (explicit or "").strip() or item.get("project") or None
    if project:
        return str(project)
    hint = None
    if inbox_block is not None:
        hint = (inbox_block["props"].get("PM_PROJECT_HINT") or "").strip() or None
    message = (
        "批准提案必须明确项目：请传 --project（或先把确认过的项目写进提案的 :PM_PROJECT:）。"
        "源 Inbox 的项目只是猜测，未被用户确认，不能自动建立正式关联。"
    )
    if hint:
        message += f" 可预填的 :PM_PROJECT_HINT: = {hint}。"
    raise ProposalError(
        "PROJECT_REQUIRED", message, extra={"projectHint": hint, "sourceInboxId": item.get("source_inbox_id")}
    )


def plan_reject(proposals_text: str, *, proposal_id: str, expected_revision: int, reason: str) -> dict:
    """拒绝的纯计划：校验 + 算出目标状态；不写任何字节。"""
    if not _collapse(reason):
        raise ProposalError("INVALID_REASON", "拒绝提案必须给 reason：审计必须留下为什么拒绝。")
    item = _find_proposal_item(proposals_text, proposal_id)
    if item["status"] == STATUS_APPROVED:
        raise ProposalError(
            "PROPOSAL_NOT_PENDING",
            f"{proposal_id} 已批准（rev {item['revision']}），不能拒绝；正式任务已经创建。",
        )
    current = item["revision"] or 1
    if current != expected_revision:
        raise ProposalError(
            "REVISION_CONFLICT",
            f"revision 冲突：文件里是 {current}，你看到的是 {expected_revision}；一个字节都没写",
            exit_code=EXIT_CONFLICT,
            extra={
                "currentRevision": current,
                "expectedRevision": expected_revision,
                "diffHint": "提案已被其它人/进程修改，请重新读（pm proposal list）后按新 revision 再提交",
            },
        )
    already = item["status"] == STATUS_REJECTED
    return {
        "proposalId": proposal_id,
        "status": STATUS_REJECTED,
        "revision": current if already else current + 1,
        "previousStatus": item["status"],
        "previousRevision": current,
        "changed": not already,
        "reason": _collapse(reason),
    }


def plan_approve(
    proposals_text: str,
    inbox_text: str,
    tasks_text: str,
    *,
    proposal_id: str,
    expected_revision: int,
    project: str | None = None,
    actor: str = "human",
    allow_stale: bool = False,
) -> dict:
    """批准的纯计划：全部校验 + 算出三份文件该做什么；**一个字节都不写**。

    抛 ProposalError 即表示「什么都不该写」。返回：
      tasks:[{taskId,title,criteria,todo,skip}]、inboxSkipped、staleOverride、project、revision …
    """
    item = _find_proposal_item(proposals_text, proposal_id)
    if item["status"] == STATUS_APPROVED:
        raise ProposalError(
            "PROPOSAL_NOT_PENDING",
            f"{proposal_id} 已经是 APPROVED（rev {item['revision']}），不能重复批准（会重复创建任务）。",
        )
    if item["status"] == STATUS_REJECTED:
        raise ProposalError(
            "PROPOSAL_REJECTED",
            f"{proposal_id} 已被拒绝，不能批准，也不会创建任何正式任务。",
        )
    if item["status"] != STATUS_PENDING:
        raise ProposalError(
            "PROPOSAL_NOT_PENDING", f"{proposal_id} 当前状态 {item['status']}，不是 PENDING，不能批准。"
        )

    current = item["revision"] or 1
    if current != expected_revision:
        raise ProposalError(
            "REVISION_CONFLICT",
            f"revision 冲突：文件里是 {current}，你看到的是 {expected_revision}；三个文件都未写",
            exit_code=EXIT_CONFLICT,
            extra={
                "currentRevision": current,
                "expectedRevision": expected_revision,
                "diffHint": "提案已被其它人/进程修改，请重新读（pm proposal list）后按新 revision 再提交",
            },
        )

    source_inbox_id = item["source_inbox_id"]
    if not source_inbox_id:
        raise ProposalError(
            "PROPOSAL_NO_SOURCE", f"{proposal_id} 没有 :PM_SOURCE_INBOX_ID:，无法回链 source inbox"
        )

    try:
        inbox_block = _find_block(inbox_text, source_inbox_id, headline=INBOX_SECTION, default_status="CAPTURED")
    except ProposalError as exc:
        if exc.code in ("NOT_FOUND", "LEGACY_UNTRACKED"):
            raise ProposalError(
                "PROPOSAL_SOURCE_NOT_FOUND",
                f"提案的源 Inbox {source_inbox_id} 不在 inbox.org 里（{exc.code}）；不批准，避免产生孤儿任务。",
            ) from exc
        raise
    if inbox_block["drawer"] is None:
        raise ProposalError(
            "PROPOSAL_SOURCE_NOT_FOUND",
            f"源 Inbox {source_inbox_id} 没有 :PROPERTIES: 抽屉，无法写状态。",
        )

    inbox_status = _block_status(inbox_block, "CAPTURED")
    inbox_revision = entities.revision_of(inbox_block["props"])
    inbox_skipped = False
    if inbox_status == INBOX_STATUS_TASK_CREATED:
        # 回链判定：已由**本提案**标记 → 重试，跳过该步（收敛）；
        # 被别人创建 → 拒绝（真正的重复）。
        if (inbox_block["props"].get("PM_PROPOSAL_ID") or "") == proposal_id:
            inbox_skipped = True
        else:
            raise ProposalError(
                "ALREADY_TASK_CREATED",
                f"源 Inbox {source_inbox_id} 已是 TASK_CREATED，但不是本提案创建的，拒绝重复出任务。",
                extra={"sourceInboxId": source_inbox_id},
            )
    elif inbox_status not in INBOX_ACTIONABLE:
        raise ProposalError(
            "PROPOSAL_SOURCE_NOT_ACTIONABLE",
            f"源 Inbox {source_inbox_id} 状态是 {inbox_status}，"
            f"只有 {'/'.join(sorted(INBOX_ACTIONABLE))} 才能批准出任务。",
            extra={"sourceInboxId": source_inbox_id, "sourceStatus": inbox_status},
        )

    # §5.3：PM_BASE_REVISION 是生成提案时源 inbox 的 revision。它变了 = 需求可能已变，
    # 按 CAS 的同一精神拒绝（不要基于陈旧读取做不可逆动作）；--allow-stale 显式覆盖。
    # 例外：本提案自己已经完成该步（重试收敛）时不再判陈旧，否则永远收敛不了。
    # 例外 2：create 自己把 inbox 标成了 TASK_PROPOSED（rev +1）——那是**我们自己的**写入，
    #         比对时要把它排除，否则每次批准都会被自己的 propose 步骤判成 STALE_PLAN；
    #         但 revise 会把 base 重挂到「标记之后」的 revision，所以两种 base 都要接受。
    #   marked = 我们的 propose 标记产生的 revision（属性或审计行）；
    #     inbox == marked → 接受 base ∈ {marked-1（create 写的）, marked（revise 重挂的）}
    #     inbox != marked → 标记之后又被改过 → 只有 base == 当前 inbox rev（revise 刚重挂）才不算陈旧
    #     老数据完全取不到 marked → 回落 base == inbox-1（保持 task-47 之前的行为）
    base_revision = item.get("base_revision")
    own_propose = inbox_status == PROPOSE_STATUS and (
        (inbox_block["props"].get("PM_PROPOSAL_ID") or "") == proposal_id
    )
    if own_propose:
        marked = _proposed_revision_marker(inbox_text, inbox_block, proposal_id)
        if marked is None:
            acceptable = {inbox_revision - 1}
        elif inbox_revision == marked:
            acceptable = {marked - 1, marked}
        else:
            acceptable = {inbox_revision}
        stale = base_revision is not None and base_revision not in acceptable
    else:
        stale = base_revision is not None and base_revision != inbox_revision
    stale_override = bool(stale and not inbox_skipped and allow_stale)
    if stale and not inbox_skipped and not allow_stale:
        raise ProposalError(
            "STALE_PLAN",
            f"提案基于源 Inbox 的 rev {base_revision} 生成，但它现在是 rev {inbox_revision}："
            "需求可能已经变了。请复核后用 --allow-stale 显式批准，或重新生成提案。",
            extra={
                "baseRevision": base_revision,
                "currentRevision": inbox_revision,
                "inboxId": source_inbox_id,
            },
        )

    if not item["changes"]:
        raise ProposalError("PROPOSAL_EMPTY", f"{proposal_id} 没有任何「变更」条目，批准不会创建任务；请先补计划。")

    existing = {
        block["props"].get("ID"): block
        for block in entities.iter_entity_blocks(tasks_text, headline=TASKS_SECTION)
        if block["props"].get("ID")
    }
    tasks: list[dict] = []
    seen: set[str] = set()
    for change in item["changes"]:
        op = (change.get("op") or "").strip()
        if not _is_add_op(op):
            raise ProposalError(
                "UNSUPPORTED_CHANGE_OP",
                f"v1 只支持「新增」类变更，收到 {op!r}；拒绝批准（不静默忽略变更）。",
            )
        task_id = change.get("task_id") or new_task_id()
        if task_id in seen:
            raise ProposalError("DUPLICATE_TASK_ID", f"提案里有重复的任务 id {task_id}")
        seen.add(task_id)
        block = existing.get(task_id)
        if block is not None:
            if (block["props"].get("PM_SOURCE_PROPOSAL_ID") or "") == proposal_id:
                tasks.append(
                    {
                        "taskId": task_id,
                        "title": change.get("title") or "",
                        "criteria": change.get("criteria") or [],
                        "todo": TASK_STATUS_TODO,
                        "skip": True,
                    }
                )
                continue
            raise ProposalError(
                "TASK_ID_CONFLICT",
                f"任务 id {task_id} 已存在于 tasks.org，但不是本提案创建的，拒绝覆盖。",
                extra={"taskId": task_id},
            )
        tasks.append(
            {
                "taskId": task_id,
                "title": change.get("title") or "",
                "criteria": change.get("criteria") or [],
                "todo": TASK_STATUS_TODO,
                "skip": False,
            }
        )

    resolved_project = _resolve_project(project, item, inbox_block)
    return {
        "proposalId": proposal_id,
        "status": STATUS_APPROVED,
        "revision": current + 1,
        "previousStatus": item["status"],
        "previousRevision": current,
        "sourceInboxId": source_inbox_id,
        "inboxStatus": INBOX_STATUS_TASK_CREATED,
        "inboxRevision": inbox_revision + 1,
        "inboxSkipped": inbox_skipped,
        "staleOverride": stale_override,
        "project": resolved_project,
        "tasks": tasks,
        "taskIds": [task["taskId"] for task in tasks],
    }


# ---------------------------------------------------------------- 任务路径 / 回链


def tasks_path_for(layout: Layout, project: str) -> Path:
    """把提案里的 project 解析成 tasks.org 路径（key 或 proj-<key> 都能用）。"""
    for candidate in (project, f"proj-{project}"):
        path = layout.tasks_file(candidate)
        if path.parent.is_dir():
            return path
    raise ProposalError(
        "PROJECT_NOT_FOUND",
        f"找不到项目目录 projects/{project}（也没有 projects/proj-{project}）；"
        "批准不会自动新建项目，请先在库里有该项目。",
        extra={
            "project": project,
            # task-43：错误要可操作 —— 前端据此显示「新建项目」按钮（HTTP 仍是 422）
            "hint": f"先运行 pm project create {project}（或在前端点『新建项目』），再批准这条提案。",
            "canCreate": True,
        },
    )


def _key_audit(text: str, block: dict, idempotency_key: str) -> tuple[str | None, str | None]:
    lines = text.splitlines()
    region = "\n".join(lines[block["start"]: block["end"]])
    return entities.audit_from_region(region, idempotency_key)


def _complete_replay_inbox(
    replay: ProposalResult,
    *,
    inbox_file: Path,
    actor: str,
    idempotency_key: str,
    now: datetime | None,
) -> ProposalResult:
    """重放 create 时补做可能没落地的 inbox 步骤（两文件事务的收敛点）。

    - 源条目已不在 / 已是 TASK_CREATED → 没什么可补，原样返回；
    - 已是本提案标的 TASK_PROPOSED → 原样返回（幂等）；
    - 否则补一次 CAS；失败按 PARTIAL_WRITE 如实报告。
    """
    if replay.status != STATUS_PENDING or not replay.source_inbox_id or not inbox_file.is_file():
        return replace(replay, partial=False)
    try:
        block = _find_block(
            entities.read_text(inbox_file),
            replay.source_inbox_id,
            headline=INBOX_SECTION,
            default_status="CAPTURED",
        )
    except ProposalError as exc:
        if exc.code in ("NOT_FOUND", "LEGACY_UNTRACKED"):
            return replace(replay, partial=False)
        raise
    status = _block_status(block, "CAPTURED")
    own = (block["props"].get("PM_PROPOSAL_ID") or "") == replay.entity_id
    revision = entities.revision_of(block["props"])
    if (status == PROPOSE_STATUS and own) or status == INBOX_STATUS_TASK_CREATED:
        return replace(replay, inbox_status=status, inbox_revision=revision, partial=False)

    try:
        op = _mark_inbox_proposed(
            inbox_file,
            replay.source_inbox_id,
            proposal_id=replay.entity_id,
            expected_revision=revision,
            actor=actor,
            idempotency_key=idempotency_key,
            now=now,
        )
    except entities.EntityError as exc:
        raise _create_partial_error(
            exc, proposal_id=replay.entity_id, source_inbox_id=replay.source_inbox_id
        ) from exc
    except OSError as exc:
        raise _create_partial_error(
            exc, proposal_id=replay.entity_id, source_inbox_id=replay.source_inbox_id
        ) from exc
    return replace(
        replay,
        inbox_status=op.status,
        inbox_revision=op.revision,
        partial=False,
        steps=[
            {"name": "proposal", "status": "skipped", "reason": "same idempotency-key, already created"},
            {"name": "inbox", "status": "written", "revision": op.revision, "auditEventId": op.audit_event_id},
        ],
        extra={**replay.extra, "written": [INBOX_RELATIVE], "notWritten": []},
    )


def _replay_create(proposals_file: Path, idempotency_key: str) -> ProposalResult | None:
    """create 的幂等重放：entities 的 key 已落在某条提案 LOGBOOK 里 → 返回首次结果。

    复用 entities.find_idempotent_block（与 apply_change / create_entity 同一套键语义），
    不自己实现一套幂等表。
    """
    holder = entities.find_idempotent_block(proposals_file, idempotency_key)
    if holder is None:
        return None
    props = holder["props"]
    lines = entities.read_text(proposals_file).split("\n")
    region = "\n".join(lines[holder["start"]: holder["end"]])
    audit_id, observed_at = entities.audit_from_region(region, idempotency_key)
    task_ids = [part for part in (props.get("PM_TASK_IDS") or "").split(",") if part]
    return ProposalResult(
        path=proposals_file,
        entity_id=props.get("ID") or "",
        status=(props.get("PM_STATUS") or STATUS_PENDING).strip().upper(),
        revision=entities.revision_of(props),
        previous_status=(props.get("PM_STATUS") or STATUS_PENDING).strip().upper(),
        previous_revision=entities.revision_of(props),
        changed=False,
        idempotent=True,
        observed_at=observed_at,
        audit_event_id=audit_id,
        line=holder["line"],
        source_inbox_id=props.get("PM_SOURCE_INBOX_ID") or None,
        base_revision=_int_or_none(props.get("PM_BASE_REVISION")),
        plan_revision=_int_or_none(props.get("PM_PLAN_REVISION")),
        project=props.get("PM_PROJECT") or None,
        task_ids=task_ids,
        extra={"written": [], "notWritten": [], "replay": True},
    )


def _replay_approve(proposals_file: Path, text: str, proposal_id: str, idempotency_key: str):
    """同一 idempotency-key 的重放：返回首次结果（不产生第二次变更）。"""
    try:
        block = _find_block(text, proposal_id, headline=PROPOSALS_SECTION, default_status=STATUS_PENDING)
    except ProposalError:
        return None
    audit_id, observed_at = _key_audit(text, block, idempotency_key)
    if not audit_id:
        return None
    props = block["props"]
    status = _block_status(block, STATUS_PENDING)
    if status != STATUS_APPROVED:
        raise ProposalError(
            "IDEMPOTENCY_KEY_REUSED",
            f"idempotency key 之前用在 {status} 操作上，不能换个操作重复使用。",
        )
    task_ids = [part for part in (props.get("PM_TASK_IDS") or "").split(",") if part]
    revision = entities.revision_of(props)
    return ProposalResult(
        path=proposals_file,
        entity_id=proposal_id,
        status=status,
        revision=revision,
        previous_status=status,
        previous_revision=revision,
        changed=False,
        idempotent=True,
        observed_at=observed_at,
        audit_event_id=audit_id,
        source_inbox_id=props.get("PM_SOURCE_INBOX_ID") or None,
        project=props.get("PM_PROJECT") or None,
        task_ids=task_ids,
        extra={"written": [], "notWritten": [], "replay": True},
    )


# ---------------------------------------------------------------- reject


def reject(
    library_root,
    proposal_id: str,
    *,
    expected_revision: int,
    reason: str,
    actor: str = "human",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> ProposalResult:
    """拒绝一条提案：只改 proposals.org，**正式任务零变化**。"""
    if not _collapse(reason):
        raise ProposalError("INVALID_REASON", "拒绝提案必须给 reason：审计必须留下为什么拒绝。")
    now = now or datetime.now().astimezone()
    path = proposals_path(library_root)
    text = _read_text(path, what="提案")
    plan_reject(text, proposal_id=proposal_id, expected_revision=expected_revision, reason=reason)

    def _validate(entity: entities.Entity, target_status: str) -> None:
        if entity.status == STATUS_APPROVED:
            raise entities.EntityError(
                "PROPOSAL_NOT_PENDING", f"{proposal_id} 已批准，不能拒绝：正式任务已经创建。"
            )

    try:
        op = entities.apply_change(
            path,
            proposal_id,
            expected_revision=expected_revision,
            status=STATUS_REJECTED,
            actor=actor,
            reason=_collapse(reason),
            idempotency_key=idempotency_key,
            dry_run=dry_run,
            now=now,
            headline=PROPOSALS_SECTION,
            default_status=STATUS_PENDING,
            validate=_validate,
        )
    except entities.EntityError as exc:
        raise _wrap(exc) from exc

    return ProposalResult(
        path=path,
        entity_id=proposal_id,
        status=op.status,
        revision=op.revision,
        previous_status=op.previous_status,
        previous_revision=op.previous_revision,
        changed=op.changed,
        observed_at=op.observed_at,
        audit_event_id=op.audit_event_id,
        idempotent=op.idempotent,
        dry_run=op.dry_run,
        audit_line=op.audit_line,
        extra={"written": [] if dry_run else [PROPOSALS_RELATIVE], "notWritten": []},
    )


# ---------------------------------------------------------------- revise


def _has_replace_body() -> bool:
    """entities.apply_change 是否已支持 replace_body（task-64）。"""
    import inspect

    try:
        return "replace_body" in inspect.signature(entities.apply_change).parameters
    except (TypeError, ValueError):  # pragma: no cover
        return False


def _merged_plan_changes(item: dict, changes) -> list[dict]:
    """revise 的变更合并：给了就用新的（复用同一套校验 + 预分配 task id），否则沿用旧的。"""
    if changes is None:
        merged = [
            {
                "op": change.get("op") or "新增",
                "task_id": change.get("task_id"),
                "title": change.get("title") or "",
                "criteria": list(change.get("criteria") or []),
            }
            for change in item["changes"]
        ]
    else:
        merged = normalize_changes(changes)
    for change in merged:
        if not _is_add_op(change.get("op")):
            raise ProposalError(
                "UNSUPPORTED_CHANGE_OP",
                f"v1 只支持「新增」类变更，收到 {change.get('op')!r}；"
                "修改/删除请走 task 域，不要放进提案（提案不能静默忽略变更）。",
            )
        if not change.get("task_id"):
            change["task_id"] = new_task_id()
    return merged


def _validate_revise(entity: entities.Entity, target_status: str) -> None:
    if entity.status != STATUS_PENDING:
        raise entities.EntityError(
            "PROPOSAL_NOT_REVISABLE",
            f"提案当前状态 {entity.status}，只有 PENDING 的提案可以修改。",
            extra={"status": entity.status},
        )


def revise(
    library_root,
    proposal_id: str,
    *,
    expected_revision: int,
    title: str | None = None,
    changes=None,
    risks=None,
    actions=None,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> ProposalResult:
    """修改一条 PENDING 提案：**保留 proposal id**，重挂到源 inbox 当前 revision，计划版本 +1。

    - 只改 proposals.org：**不碰 tasks.org、不改源 inbox 状态、不创建任务**。
    - CAS 对提案自身的 :PM_REVISION:；冲突 exit 3，一字节不写。
    - :PM_BASE_REVISION: ← 源 inbox 当前 revision；:PM_PLAN_REVISION: +1。
    - title / changes / risks / actions 给了才替换（整组替换，不是追加）；没给的保持不变。
    - 审计：op=revise planRev=<new> basedOnInboxRevision=<n> prevBaseRevision=<m>。
    """
    now = now or datetime.now().astimezone()
    layout = as_layout(library_root)
    proposals_file = layout.proposals_file
    inbox_file = layout.inbox
    text = _read_text(proposals_file, what="提案")
    item = _find_proposal_item(text, proposal_id)

    if item["status"] != STATUS_PENDING:
        raise ProposalError(
            "PROPOSAL_NOT_REVISABLE",
            f"{proposal_id} 当前状态 {item['status']}，只有 PENDING 的提案可以修改。",
            extra={"proposalId": proposal_id, "status": item["status"]},
        )
    current = item["revision"] or 1
    if current != expected_revision:
        raise ProposalError(
            "REVISION_CONFLICT",
            f"revision 冲突：文件里是 {current}，你看到的是 {expected_revision}；一个字节都没写",
            exit_code=EXIT_CONFLICT,
            extra={
                "currentRevision": current,
                "expectedRevision": expected_revision,
                "diffHint": "提案已被其它人/进程修改，请重新读（pm proposal show）后按新 revision 再提交",
            },
        )

    source_inbox_id = item["source_inbox_id"]
    if not source_inbox_id:
        raise ProposalError(
            "PROPOSAL_NO_SOURCE", f"{proposal_id} 没有 :PM_SOURCE_INBOX_ID:，无法重挂源 revision"
        )
    inbox_text = _read_text(inbox_file, what="inbox")
    try:
        inbox_block = _find_block(
            inbox_text, source_inbox_id, headline=INBOX_SECTION, default_status="CAPTURED"
        )
    except ProposalError as exc:
        if exc.code in ("NOT_FOUND", "LEGACY_UNTRACKED"):
            raise ProposalError(
                "PROPOSAL_SOURCE_NOT_FOUND",
                f"提案的源 Inbox {source_inbox_id} 不在 inbox.org 里（{exc.code}）；无法重挂 revision。",
            ) from exc
        raise
    inbox_status = _block_status(inbox_block, "CAPTURED")
    if inbox_status == INBOX_STATUS_TASK_CREATED:
        raise ProposalError(
            "ALREADY_TASK_CREATED",
            f"源 Inbox {source_inbox_id} 已是 TASK_CREATED（已经出过任务），不能再修订这条提案。",
            extra={"sourceInboxId": source_inbox_id, "sourceStatus": inbox_status},
        )
    if inbox_status not in INBOX_ACTIONABLE:
        raise ProposalError(
            "PROPOSAL_SOURCE_NOT_ACTIONABLE",
            f"源 Inbox {source_inbox_id} 状态是 {inbox_status}，无法重挂 revision"
            f"（需要 {'/'.join(sorted(INBOX_ACTIONABLE))}）。",
            extra={"sourceInboxId": source_inbox_id, "sourceStatus": inbox_status},
        )
    new_base = entities.revision_of(inbox_block["props"])
    prev_base = item["base_revision"]
    plan_revision = int(item["plan_revision"] or 1) + 1

    has_content_change = any(value is not None for value in (changes, risks, actions))
    replace_body = None
    if has_content_change:
        if not _has_replace_body():
            raise ProposalError(
                "ENTITY_CAPABILITY_MISSING",
                "entities.apply_change 尚不支持 replace_body（task-64 未落地）：现在只能改 title / 重挂 revision；"
                "正文替换等 pm-api 加上再启用。",
            )
        merged_changes = _merged_plan_changes(item, changes)
        merged_risks = list(risks) if risks is not None else list(item["risks"])
        merged_actions = list(actions) if actions is not None else (list(item["actions"]) or None)
        replace_body = proposal_body_lines(merged_changes, merged_risks, merged_actions)

    replace_lines: dict[int, str] = {}
    if title is not None and _collapse(title):
        replace_lines[0] = f"** {PROPOSAL_PREFIX} {_collapse(title)}"

    apply_kwargs: dict = {
        "expected_revision": expected_revision,
        "status": None,
        "set_properties": {
            "PM_BASE_REVISION": str(new_base),
            "PM_PLAN_REVISION": str(plan_revision),
        },
        "actor": actor,
        "reason": _collapse(reason) or f"revise proposal {proposal_id}",
        "audit_extra": {
            "op": "revise",
            "planRev": plan_revision,
            "basedOnInboxRevision": new_base,
            "prevBaseRevision": prev_base if prev_base is not None else "-",
        },
        "idempotency_key": idempotency_key,
        "dry_run": dry_run,
        "now": now,
        "headline": PROPOSALS_SECTION,
        "default_status": STATUS_PENDING,
        "validate": _validate_revise,
    }
    if replace_lines:
        apply_kwargs["replace_lines"] = replace_lines
    if replace_body is not None:
        apply_kwargs["replace_body"] = replace_body
    try:
        op = entities.apply_change(proposals_file, proposal_id, **apply_kwargs)
    except entities.EntityError as exc:
        raise _wrap(exc) from exc
    except TypeError as exc:  # pragma: no cover - replace_body 未落地时的兜底
        raise ProposalError(
            "ENTITY_CAPABILITY_MISSING", f"entities.apply_change 不接受 replace_body：{exc}"
        ) from exc

    if op.idempotent:
        stored = _find_proposal_item(entities.read_text(proposals_file), proposal_id)
        plan_revision = int(stored["plan_revision"] or plan_revision)
        if stored["base_revision"] is not None:
            new_base = int(stored["base_revision"])

    return ProposalResult(
        path=proposals_file,
        entity_id=proposal_id,
        status=op.status,
        revision=op.revision,
        previous_status=op.previous_status,
        previous_revision=op.previous_revision,
        changed=op.changed,
        observed_at=op.observed_at,
        audit_event_id=op.audit_event_id,
        idempotent=op.idempotent,
        dry_run=op.dry_run,
        audit_line=op.audit_line,
        source_inbox_id=source_inbox_id,
        base_revision=new_base,
        plan_revision=plan_revision,
        inbox_status=inbox_status,
        inbox_revision=entities.revision_of(inbox_block["props"]),
        extra={
            "written": [] if dry_run else [PROPOSALS_RELATIVE],
            "notWritten": [],
            "prevBaseRevision": prev_base,
            "sourceInboxRevision": new_base,
        },
    )


# ---------------------------------------------------------------- approve（补偿式多文件事务）


def _validate_approve(entity: entities.Entity, target_status: str) -> None:
    if entity.status != STATUS_PENDING:
        raise entities.EntityError(
            "PROPOSAL_NOT_PENDING",
            f"提案当前状态 {entity.status}，不是 PENDING，不能批准（拒绝重复创建任务）。",
        )


def _create_task_entity(
    tasks_file: Path,
    *,
    task_id: str,
    title: str,
    criteria,
    project: str,
    source_inbox_id: str,
    proposal_id: str,
    actor: str,
    at_iso: str,
    now: datetime | None,
) -> tuple[int, str]:
    """用 pm.tasks 的 build_task/create_task 建任务，保证与 task 域形状一致。

    跨模块接缝：**任务形状的唯一所有者是 pm.tasks，禁止在此重拼 task org。**
    自己拼（如 "** TODO" + 手写 props）会漏掉 "*** 验收标准" 等结构，pm task list/show
    就读不回来；而两边的单元测试各自只看自己那一半，谁都不会发现 ——
    这正是必须有跨模块往返测试的原因（tests/test_proposals.py 的
    test_approved_task_round_trips_through_pm_tasks）。
    """
    try:
        from pm import tasks as tasks_mod
    except ImportError as exc:  # pragma: no cover - 正常 checkout 里存在
        raise ProposalError("TASK_MODULE_MISSING", f"批准需要 pm.tasks 来创建任务: {exc}") from exc
    task = tasks_mod.build_task(
        title or task_id,
        task_id=task_id,
        project_id=project,
        status=TASK_STATUS_TODO,
        source_inbox_id=source_inbox_id,
        criteria=list(criteria or []),
        has_criteria=True,
        extra_properties={
            "PM_SOURCE_PROPOSAL_ID": proposal_id,
            "PM_CREATED_BY": actor,
            "PM_ADDED_AT": at_iso,
        },
    )
    try:
        line, audit_id, _preview = tasks_mod.create_task(tasks_file, task, actor=actor, now=now)
    except entities.EntityError as exc:
        raise _wrap(exc) from exc
    return line, audit_id


def approve(
    library_root,
    proposal_id: str,
    *,
    expected_revision: int,
    project: str | None = None,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    allow_stale: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> ProposalResult:
    """批准一条提案（**补偿式**多文件事务：tasks → inbox → proposals）。

    先全部只读校验，再逐个原子写；中途失败抛 PARTIAL_WRITE，extra 里带 written / notWritten。
    重试靠回链收敛（见模块 docstring）。
    """
    now = now or datetime.now().astimezone()
    layout = as_layout(library_root)
    proposals_file = layout.proposals_file
    inbox_file = layout.inbox
    proposals_text = _read_text(proposals_file, what="提案")

    if idempotency_key:
        replay = _replay_approve(
            proposals_file, proposals_text, proposal_id, "".join(str(idempotency_key).split())
        )
        if replay is not None:
            return replay

    inbox_text = _read_text(inbox_file, what="inbox")
    item = _find_proposal_item(proposals_text, proposal_id)

    inbox_block = None
    if item["source_inbox_id"]:
        try:
            inbox_block = _find_block(
                inbox_text, item["source_inbox_id"], headline=INBOX_SECTION, default_status="CAPTURED"
            )
        except ProposalError as exc:
            if exc.code not in ("NOT_FOUND", "LEGACY_UNTRACKED"):
                raise
    resolved_project = _resolve_project(project, item, inbox_block)

    tasks_file = tasks_path_for(layout, resolved_project)
    tasks_text = entities.read_text(tasks_file) if tasks_file.is_file() else ""

    plan = plan_approve(
        proposals_text,
        inbox_text,
        tasks_text,
        proposal_id=proposal_id,
        expected_revision=expected_revision,
        project=resolved_project,
        actor=actor,
        allow_stale=allow_stale,
    )

    if dry_run:
        return ProposalResult(
            path=proposals_file,
            entity_id=proposal_id,
            status=STATUS_APPROVED,
            revision=plan["revision"],
            previous_status=plan["previousStatus"],
            previous_revision=plan["previousRevision"],
            dry_run=True,
            observed_at=now.isoformat(timespec="seconds"),
            source_inbox_id=plan["sourceInboxId"],
            inbox_status=INBOX_STATUS_TASK_CREATED,
        inbox_revision=plan["inboxRevision"],
            project=plan["project"],
            task_ids=plan["taskIds"],
            steps=_planned_steps(plan),
            extra={
                "written": [],
                "notWritten": [],
                **({"staleOverride": True} if plan.get("staleOverride") else {}),
            },
        )

    at_iso = now.isoformat(timespec="seconds")
    task_ids = plan["taskIds"]
    audit_reason = _collapse(reason) or f"批准提案 {proposal_id}"
    audit_extra = {"stale": "override"} if plan.get("staleOverride") else None
    step_names = [f"task:{task['taskId']}" for task in plan["tasks"]] + ["inbox", "proposal"]
    steps: list[dict] = []

    def _mark(name: str, status: str, **extra) -> None:
        steps.append({"name": name, "status": status, **extra})

    def _on_failure(name: str, exc: Exception) -> None:
        written = [step["name"] for step in steps if step["status"] == "written"]
        not_written = step_names[len(steps):]
        already_done = [step["name"] for step in steps if step["status"] == "skipped"]
        detail = {
            "written": written,
            "alreadyDone": already_done,
            "notWritten": not_written,
            "internal": "proposals.org/tasks.org/inbox.org 是补偿式事务，不是原子事务",
            "failedStep": name,
            # 注意：键不能叫 error —— 会和 JSON 错误信封的 error 键冲突（曾把 code 盖成底层码）。
            "cause": {
                "code": getattr(exc, "code", "WRITE_FAILED"),
                "message": getattr(exc, "message", str(exc)),
            },
        }
        if not steps:  # 一个步骤都没走完 → 第一步就失败，不成其为「部分完成」
            if isinstance(exc, entities.EntityError):
                raise _wrap(exc) from exc
            raise ProposalError("WRITE_FAILED", f"第一步就失败，未写入任何文件: {exc}") from exc
        parts: list[str] = []
        if written:
            parts.append("本轮已写 [" + ", ".join(written) + "]")
        if already_done:
            parts.append("此前已完成 [" + ", ".join(already_done) + "]")
        parts.append("未写 [" + ", ".join(not_written) + "]")
        raise ProposalError(
            "PARTIAL_WRITE",
            "多文件事务只完成了一部分（补偿式事务，非原子）：" + "；".join(parts)
            + "。失败于 " + name + "：" + getattr(exc, "message", str(exc)),
            exit_code=getattr(exc, "exit_code", EXIT_INPUT),
            extra=detail,
        ) from exc

    # 1) tasks.org —— 新任务（带回链；已由本提案创建的跳过）
    for task in plan["tasks"]:
        name = f"task:{task['taskId']}"
        if task["skip"]:
            _mark(name, "skipped", reason="task already created by this proposal", entityId=task["taskId"])
            continue
        try:
            line, audit_id = _create_task_entity(
                tasks_file,
                task_id=task["taskId"],
                title=task["title"],
                criteria=task.get("criteria") or [],
                project=plan["project"],
                source_inbox_id=plan["sourceInboxId"],
                proposal_id=proposal_id,
                actor=actor,
                at_iso=at_iso,
                now=now,
            )
        except (entities.EntityError, OSError) as exc:
            _on_failure(name, exc)
        _mark(name, "written", entityId=task["taskId"], line=line, auditEventId=audit_id, path=str(tasks_file))

    # 2) inbox.org —— 标 TASK_CREATED（已由本提案标记的跳过）
    if plan["inboxSkipped"]:
        _mark(
            "inbox", "skipped",
            reason="inbox already TASK_CREATED by this proposal",
            entityId=plan["sourceInboxId"],
        )
    else:
        try:
            inbox_op = entities.apply_change(
                inbox_file,
                plan["sourceInboxId"],
                expected_revision=plan["inboxRevision"] - 1,
                status=INBOX_STATUS_TASK_CREATED,
                set_properties={"PM_PROPOSAL_ID": proposal_id, "PM_TASK_IDS": ",".join(task_ids)},
                actor=actor,
                reason=audit_reason,
                audit_extra=audit_extra,
                now=now,
                headline=INBOX_SECTION,
            )
        except (entities.EntityError, OSError) as exc:
            _on_failure("inbox", exc)
        _mark(
            "inbox", "written", entityId=plan["sourceInboxId"],
            revision=inbox_op.revision, auditEventId=inbox_op.audit_event_id,
        )

    # 3) proposals.org —— 提交标记（放最后；失败则前两步已落地，如实报出）
    try:
        op = entities.apply_change(
            proposals_file,
            proposal_id,
            expected_revision=expected_revision,
            status=STATUS_APPROVED,
            set_properties={
                "PM_APPROVED_BY": actor,
                "PM_APPROVED_AT": at_iso,
                "PM_TASK_IDS": ",".join(task_ids),
            },
            actor=actor,
            reason=audit_reason,
            idempotency_key=idempotency_key,
            audit_extra=audit_extra,
            now=now,
            headline=PROPOSALS_SECTION,
            default_status=STATUS_PENDING,
            validate=_validate_approve,
        )
    except (entities.EntityError, OSError) as exc:
        _on_failure("proposal", exc)
    _mark("proposal", "written", entityId=proposal_id, revision=op.revision, auditEventId=op.audit_event_id)

    return ProposalResult(
        path=proposals_file,
        entity_id=proposal_id,
        status=op.status,
        revision=op.revision,
        previous_status=op.previous_status,
        previous_revision=op.previous_revision,
        changed=op.changed,
        observed_at=op.observed_at,
        audit_event_id=op.audit_event_id,
        idempotent=op.idempotent,
        dry_run=op.dry_run,
        audit_line=op.audit_line,
        source_inbox_id=plan["sourceInboxId"],
        inbox_status=INBOX_STATUS_TASK_CREATED,
        inbox_revision=plan["inboxRevision"],
        project=plan["project"],
        task_ids=task_ids,
        steps=steps,
        extra={
            "written": [step["name"] for step in steps if step["status"] == "written"],
            "notWritten": [],
            **({"staleOverride": True} if plan.get("staleOverride") else {}),
        },
    )


def _planned_steps(plan: dict) -> list[dict]:
    steps = [
        {"name": f"task:{task['taskId']}", "status": "planned", "skip": task["skip"]}
        for task in plan["tasks"]
    ]
    steps.append({"name": "inbox", "status": "planned", "skip": plan["inboxSkipped"]})
    steps.append({"name": "proposal", "status": "planned"})
    return steps


# ---------------------------------------------------------------- CLI


def _parse_cli_changes(values: list) -> list:
    """CLI 的 --change：普通文本走 §5.3 解析；以 { 开头的当 JSON 对象（可带 criteria）。"""
    parsed: list = []
    for raw in values:
        text = str(raw)
        if text.lstrip().startswith("{"):
            try:
                item = json.loads(text)
            except ValueError as exc:
                raise ProposalError("INVALID_CHANGE", f"--change 的 JSON 解析失败: {exc}") from exc
            if not isinstance(item, dict):
                raise ProposalError("INVALID_CHANGE", "--change 的 JSON 必须是对象")
            parsed.append(item)
        else:
            parsed.append(text)
    return parsed


def register_cli(subparsers) -> None:
    """把 pm proposal … 挂到 CLI 上（由 pm.cli 自动发现调用，不用改 cli.py）。"""
    from pm.cli import _add_common_options

    proposal = subparsers.add_parser("proposal", help="AI 计划提案：生成 / 修改 / 批准 / 拒绝（§5.3）")
    proposal_sub = proposal.add_subparsers(dest="proposal_command")

    listing = proposal_sub.add_parser("list", help="列出提案（读命令，不需要写入闸门）")
    listing.add_argument("--status", metavar="S", help="只看某个状态，如 PENDING / APPROVED / REJECTED")
    listing.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(listing, as_defaults=True)
    listing.set_defaults(handler=command_proposal_list)

    show = proposal_sub.add_parser("show", help="查看一条提案（含变更 / 风险 / 操作）")
    show.add_argument("proposal_id", metavar="PROPOSAL_ID", help="提案 :ID:（身份只看 ID，不看行号）")
    show.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(show, as_defaults=True)
    show.set_defaults(handler=command_proposal_show)

    def _add_write_flags(parser: argparse.ArgumentParser, *, reason_required: bool = False) -> None:
        parser.add_argument(
            "--actor",
            default="human",
            choices=["human", "ai", "system"],
            help="谁发起的，写入审计（默认 human）",
        )
        parser.add_argument(
            "--reason",
            default="" if not reason_required else None,
            required=reason_required,
            metavar="R",
            help="变更原因，写入审计" + ("（本项目拒绝必填）" if reason_required else ""),
        )
        parser.add_argument(
            "--idempotency-key",
            dest="idempotency_key",
            default=None,
            metavar="KEY",
            help="同一 key 重复提交不会产生第二次变更",
        )
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="只预演，一字节不落盘")
        parser.add_argument(
            "--yes",
            action="store_true",
            help="确认要写「默认配置指向的库」；未显式 --config 且非 --dry-run 时必需",
        )
        parser.add_argument("--json", action="store_true", help="stdout 只输出纯 JSON")
        # 公共参数（--config / --dsh-home）也挂到**子命令**上：父子同名选项必须给 SUPPRESS 默认值，
        # 否则子解析器会用默认值覆盖父级值；两处都认才是"同一件事一个来源"（同 index 那次的修法）。
        _add_common_options(parser, as_defaults=True)

    create = proposal_sub.add_parser("create", help="生成一条提案（只写 proposals.org，不碰 tasks.org）")
    create.add_argument("--source-inbox", dest="source_inbox", required=True, metavar="INBOX_ID",
                        help="源 inbox 的 :ID:，写入 :PM_SOURCE_INBOX_ID: 并作为 CAS 来源")
    create.add_argument("--change", dest="changes", action="append", default=[], metavar="TEXT",
                        help='一条变更：如 "新增：明确输入范围"，或 JSON 对象 '
                             '{"op":"新增","title":"...","criteria":["..."]}（可重复）')
    create.add_argument("--criterion", dest="criteria", action="append", default=[], metavar="TEXT",
                        help="验收标准（可重复）；只在恰好一条 --change 时可用，多条请用 --change 的 JSON 形式")
    create.add_argument("--risk", dest="risks", action="append", default=[], metavar="TEXT",
                        help="一条风险/待确认（可重复）")
    create.add_argument("--action", dest="actions", action="append", default=[], metavar="TEXT",
                        help="一条操作说明（可重复；默认写「批准后创建正式任务；拒绝不改变正式任务。」）")
    create.add_argument("--title", metavar="T", help="提案标题（默认「从 <inbox> 生成任务计划」）")
    create.add_argument("--project", metavar="KEY", help="用户已确认的项目，写入 :PM_PROJECT:")
    create.add_argument(
        "--allow-duplicate", dest="allow_duplicate", action="store_true",
        help="同一条 inbox 已有 PENDING 提案时仍再建一条（默认拒绝 PROPOSAL_EXISTS_FOR_INBOX）",
    )
    create.add_argument(
        "--expected-revision", dest="expected_revision", type=int, default=None, metavar="N",
        help="源 inbox 的 :PM_REVISION:；不匹配 → 409，一字节不写（可选）",
    )
    create.add_argument("--plan-revision", dest="plan_revision", type=int, default=1, metavar="N")
    create.add_argument("--created-by", dest="created_by", default="ai", metavar="WHO",
                        help="生成者（默认 ai），写入 :PM_CREATED_BY: 与审计")
    _add_write_flags(create)
    create.set_defaults(handler=command_proposal_create)

    approve = proposal_sub.add_parser("approve", help="批准提案：创建正式任务 + 标记 inbox + 提案 APPROVED")
    approve.add_argument("proposal_id", metavar="PROPOSAL_ID", help="提案 :ID:")
    approve.add_argument("--expected-revision", dest="expected_revision", type=int, required=True, metavar="N",
                         help="你看到的 :PM_REVISION:；不匹配 → 409，一字节不写（CAS）")
    approve.add_argument("--project", metavar="KEY",
                         help="要创建任务的项目；默认取提案 :PM_PROJECT:，都没有 → 拒绝")
    approve.add_argument(
        "--allow-stale", dest="allow_stale", action="store_true",
        help="STALE_PLAN（源 inbox 在提案生成后已变）时仍批准；知道风险才用",
    )
    _add_write_flags(approve)
    approve.set_defaults(handler=command_proposal_approve)

    reject = proposal_sub.add_parser("reject", help="拒绝提案（只改 proposals.org，正式任务零变化）")
    reject.add_argument("proposal_id", metavar="PROPOSAL_ID", help="提案 :ID:")
    reject.add_argument("--expected-revision", dest="expected_revision", type=int, required=True, metavar="N",
                        help="你看到的 :PM_REVISION:；不匹配 → 409，一字节不写（CAS）")
    _add_write_flags(reject, reason_required=True)
    reject.set_defaults(handler=command_proposal_reject)

    revise = proposal_sub.add_parser(
        "revise", help="修改提案：保留 ID，重挂到源 inbox 当前 revision（plan rev +1）"
    )
    revise.add_argument("proposal_id", metavar="PROPOSAL_ID", help="提案 :ID:")
    revise.add_argument("--expected-revision", dest="expected_revision", type=int, required=True, metavar="N",
                        help="你看到的提案 :PM_REVISION:；不匹配 → 409，一字节不写（CAS）")
    revise.add_argument("--title", metavar="T", help="替换标题；不传则保持")
    revise.add_argument("--change", dest="changes", action="append", default=None, metavar="TEXT",
                        help='替换整组「变更」：如 "新增：明确输入范围" 或 JSON 对象（可重复）；不传则保持原计划')
    revise.add_argument("--change-op", dest="change_ops", action="append", default=None, metavar="OP",
                        help="与 --change-title 配对使用（可重复），等价于 --change OP:TITLE")
    revise.add_argument("--change-title", dest="change_titles", action="append", default=None, metavar="TITLE")
    revise.add_argument("--criterion", dest="criteria", action="append", default=[], metavar="TEXT",
                        help="验收标准（可重复）；只在恰好一条变更时可用")
    revise.add_argument("--risk", dest="risks", action="append", default=None, metavar="TEXT",
                        help="替换整组风险（可重复）；不传则保持")
    revise.add_argument("--action", dest="actions", action="append", default=None, metavar="TEXT",
                        help="替换整组操作说明（可重复）；不传则保持")
    _add_write_flags(revise)
    revise.set_defaults(handler=command_proposal_revise)


def _json_error(json_mode: bool, error: ProposalError) -> int:
    payload = {"ok": False, "error": {"code": error.code, "message": error.message}}
    payload.update(error.extra)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
    print(f"pm: [{error.code}] {error.message}", file=sys.stderr)
    return error.exit_code


def _result_payload(result: ProposalResult, **domain) -> dict:
    payload = {
        "ok": True,
        "entityId": result.entity_id,
        "proposalId": result.entity_id,
        "source": result.source,
        "observedAt": result.observed_at,
        "auditEventId": result.audit_event_id,
        "status": result.status,
        "revision": result.revision,
        "previousStatus": result.previous_status,
        "previousRevision": result.previous_revision,
        "changed": result.changed,
        "path": PROPOSALS_RELATIVE,
    }
    if result.idempotent:
        payload["idempotent"] = True
    if result.dry_run:
        payload["dry_run"] = True
    if result.source_inbox_id:
        payload["sourceInboxId"] = result.source_inbox_id
    if result.base_revision is not None:
        payload["baseRevision"] = result.base_revision
    if result.plan_revision is not None:
        payload["planRevision"] = result.plan_revision
    if result.project:
        payload["project"] = result.project
    if result.inbox_revision is not None:
        payload["inboxRevision"] = result.inbox_revision
    if result.inbox_status is not None or result.source_inbox_id:
        payload["inbox"] = {
            "id": result.source_inbox_id,
            "status": result.inbox_status,
            "revision": result.inbox_revision,
        }
    if result.partial:
        payload["partial"] = True
    if result.hint:
        payload["hint"] = result.hint
    if result.task_ids:
        payload["taskIds"] = result.task_ids
    if result.line is not None:
        payload["line"] = result.line
    if result.steps:
        payload["steps"] = result.steps
    if result.extra:
        payload.update({key: value for key, value in result.extra.items() if key not in payload})
    payload.update(domain)
    return payload


def _gate(args, json_mode: bool) -> Layout:
    """复用 pm 的统一写入闸门（延迟 import，避免循环导入）。"""
    from pm.cli import resolve_write_target

    layout, gate_error = resolve_write_target(args, json_mode)
    if layout is None:
        code, message, exit_code = gate_error
        raise ProposalError(code, message, exit_code=exit_code)
    return layout


def _read_layout(args) -> Layout:
    from pm.cli import load_config

    config, _warnings = load_config(getattr(args, "config", None))
    if config.library is None:
        raise ProposalError("NO_LIBRARY", "未配置 work-memory 库（pm.toml 缺 library）")
    return Layout(Path(config.library))


def command_proposal_list(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        layout = _read_layout(args)
        payload = list_proposals(layout.root, status=getattr(args, "status", None))
    except ProposalError as exc:
        return _json_error(json_mode, exc)
    if json_mode:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
        return 0
    if not payload["proposals"]:
        print("没有符合条件的提案。")
        return 0
    print(f"提案 {payload['count']} 条（{payload['path']}，库 {layout.root}）")
    for row in payload["proposals"]:
        revision = row["revision"] if row["revision"] is not None else "-"
        identity = row["id"] or "(无 :ID:)"
        print(
            f"  [{row['status']}] {identity}  rev {revision}  变更 {len(row['changes'])} 条  "
            f"源 {row['source_inbox_id'] or '-'}  第 {row['line']} 行  {row['title'][:40]}"
        )
    return 0


def _change_summary(row: dict) -> str:
    head = " ".join(part for part in (row.get("op") or "", row.get("task_id") or "") if part)
    return head + (f"：{row['title']}" if row.get("title") else "")


def command_proposal_show(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        layout = _read_layout(args)
        path = layout.proposals_file
        if not path.is_file():
            raise ProposalError("NOT_FOUND", f"找不到 {path}；还没有任何提案")
        text = _read_text(path, what="提案")
        item = _find_proposal_item(text, args.proposal_id)
    except ProposalError as exc:
        return _json_error(json_mode, exc)

    if json_mode:
        print(json.dumps({"ok": True, "proposal": item}, ensure_ascii=False, indent=2))
        return 0
    print(f"{item['id']}  [{item['status']}]  rev {item['revision']}  {item['title']}")
    print(
        f"  源 inbox {item['source_inbox_id']}  base rev {item['base_revision']}  "
        f"plan rev {item['plan_revision']}  by {item['created_by']}"
    )
    for label, rows in (
        (SECTION_CHANGES, item["changes"]),
        (SECTION_RISKS, item["risks"]),
        (SECTION_ACTIONS, item["actions"]),
    ):
        print(f"  {label}:")
        if not rows:
            print("    -")
        for row in rows:
            print("    - " + (_change_summary(row) if isinstance(row, dict) else str(row)))
    return 0


def command_proposal_create(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        layout = _gate(args, json_mode)
        changes = _parse_cli_changes(list(getattr(args, "changes", []) or []))
        if not changes:
            raise ProposalError("PROPOSAL_EMPTY", '至少要给一条 --change（如 --change "新增：明确输入范围"）')
        criteria = [str(item) for item in (getattr(args, "criteria", []) or []) if str(item).strip()]
        if criteria:
            if len(changes) != 1:
                raise ProposalError(
                    "CRITERION_AMBIGUOUS",
                    "--criterion 只能配合恰好一条 --change 使用；多条变更请改用 --change 的 JSON 对象形式，"
                    "为每条变更分别带上 criteria。",
                )
            only = changes[0]
            if isinstance(only, str):
                only = _parse_change(only)
            changes = [dict(only, criteria=list(only.get("criteria") or []) + criteria)]
        result = create_proposal(
            layout,
            source_inbox_id=args.source_inbox,
            changes=changes,
            risks=getattr(args, "risks", None),
            actions=getattr(args, "actions", None),
            title=getattr(args, "title", None),
            expected_revision=getattr(args, "expected_revision", None),
            plan_revision=int(getattr(args, "plan_revision", 1) or 1),
            created_by=getattr(args, "created_by", "ai") or "ai",
            reason=getattr(args, "reason", ""),
            project=getattr(args, "project", None),
            idempotency_key=getattr(args, "idempotency_key", None),
            actor=getattr(args, "actor", "human"),
            allow_duplicate=bool(getattr(args, "allow_duplicate", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    except ProposalError as exc:
        return _json_error(json_mode, exc)

    if json_mode:
        print(json.dumps(_result_payload(result), ensure_ascii=False))
        return 0
    prefix = "[dry-run] " if result.dry_run else ""
    if result.idempotent:
        print(prefix + f"该 idempotency-key 已处理过：{result.entity_id} 仍是 {result.status} rev {result.revision}")
        return 0
    print(f"{prefix}提案 {result.entity_id} 已生成（{PROPOSALS_RELATIVE}:{result.line}，rev {result.revision}）")
    print(f"  源 inbox {result.source_inbox_id}  base rev {result.base_revision}  项目 {result.project or '-'}")
    if result.inbox_status:
        print(f"  源 inbox 已标记 {result.inbox_status}（rev {result.inbox_revision}，audit op=propose）")
    if result.task_ids:
        print("  计划的正式任务: " + ", ".join(result.task_ids))
    hint = (result.extra or {}).get("projectHint")
    if hint and not result.project:
        print(f"  提示：源 inbox 的 :PM_PROJECT_HINT: = {hint}（只是猜测，批准前请显式 --project 确认）")
    if result.dry_run:
        print("  --dry-run：一个字节都没落盘")
    return 0


def command_proposal_approve(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        layout = _gate(args, json_mode)
        result = approve(
            layout,
            args.proposal_id,
            expected_revision=args.expected_revision,
            project=getattr(args, "project", None),
            actor=getattr(args, "actor", "human"),
            reason=getattr(args, "reason", ""),
            idempotency_key=getattr(args, "idempotency_key", None),
            allow_stale=bool(getattr(args, "allow_stale", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    except ProposalError as exc:
        return _json_error(json_mode, exc)

    if json_mode:
        print(json.dumps(_result_payload(result), ensure_ascii=False))
        return 0
    prefix = "[dry-run] " if result.dry_run else ""
    if result.idempotent:
        print(prefix + f"该 idempotency-key 已处理过：{result.entity_id} 仍是 {result.status} rev {result.revision}")
        return 0
    stale = "  （已用 --allow-stale 覆盖 STALE_PLAN）" if (result.extra or {}).get("staleOverride") else ""
    print(prefix + f"已批准 {result.entity_id}  rev {result.previous_revision} → {result.revision}  项目 {result.project}{stale}")
    if result.task_ids:
        print("  创建/复用任务: " + ", ".join(result.task_ids))
    for step in result.steps:
        print(f"  {step['name']}: {step['status']}")
    if result.audit_event_id:
        print(f"  audit {result.audit_event_id}")
    return 0


def command_proposal_reject(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        layout = _gate(args, json_mode)
        result = reject(
            layout,
            args.proposal_id,
            expected_revision=args.expected_revision,
            reason=args.reason,
            actor=getattr(args, "actor", "human"),
            idempotency_key=getattr(args, "idempotency_key", None),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    except ProposalError as exc:
        return _json_error(json_mode, exc)

    if json_mode:
        print(json.dumps(_result_payload(result), ensure_ascii=False))
        return 0
    prefix = "[dry-run] " if result.dry_run else ""
    if result.idempotent:
        print(prefix + f"该 idempotency-key 已处理过：{result.entity_id} 仍是 {result.status} rev {result.revision}")
        return 0
    if not result.changed:
        print(prefix + f"无需变更：{result.entity_id} 已是 {result.status} rev {result.revision}")
        return 0
    print(prefix + f"已拒绝 {result.entity_id}  rev {result.previous_revision} → {result.revision}（正式任务零变化）")
    if result.audit_event_id:
        print(f"  audit {result.audit_event_id}")
    return 0


def _cli_revise_changes(args):
    """revise 的变更输入：--change（可 JSON）或 --change-op + --change-title；都没给 → None（保持原计划）。"""
    raw_values = list(getattr(args, "changes", None) or [])
    ops = list(getattr(args, "change_ops", None) or [])
    titles = list(getattr(args, "change_titles", None) or [])
    if raw_values and ops:
        raise ProposalError("CONFLICTING_CHANGE_FLAGS", "不要同时使用 --change 与 --change-op/--change-title")
    criteria = [str(item) for item in (getattr(args, "criteria", None) or []) if str(item).strip()]
    changes: list = []
    if ops:
        if len(ops) != len(titles):
            raise ProposalError("INVALID_CHANGE", "--change-op 与 --change-title 必须成对且数量一致")
        changes = [{"op": str(op), "title": str(title)} for op, title in zip(ops, titles)]
    else:
        changes = _parse_cli_changes(raw_values)
    if not changes:
        if criteria:
            raise ProposalError("INVALID_CHANGE", "--criterion 需要配合 --change 或 --change-op 使用")
        return None
    if criteria:
        if len(changes) != 1:
            raise ProposalError(
                "CRITERION_AMBIGUOUS",
                "--criterion 只能配合恰好一条变更使用；多条变更请用 --change 的 JSON 对象形式分别带上 criteria。",
            )
        only = changes[0]
        if isinstance(only, str):
            only = _parse_change(only)
        changes = [dict(only, criteria=list(only.get("criteria") or []) + criteria)]
    return changes


def command_proposal_revise(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        layout = _gate(args, json_mode)
        changes = _cli_revise_changes(args)
        risks = None if getattr(args, "risks", None) is None else [str(item) for item in args.risks]
        actions = None if getattr(args, "actions", None) is None else [str(item) for item in args.actions]
        result = revise(
            layout,
            args.proposal_id,
            expected_revision=args.expected_revision,
            title=getattr(args, "title", None),
            changes=changes,
            risks=risks,
            actions=actions,
            actor=getattr(args, "actor", "human"),
            reason=getattr(args, "reason", ""),
            idempotency_key=getattr(args, "idempotency_key", None),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    except ProposalError as exc:
        return _json_error(json_mode, exc)

    if json_mode:
        print(json.dumps(_result_payload(result), ensure_ascii=False))
        return 0
    prefix = "[dry-run] " if result.dry_run else ""
    if result.idempotent:
        print(prefix + f"该 idempotency-key 已处理过：{result.entity_id} plan rev {result.plan_revision}")
        return 0
    print(
        prefix + f"已修改 {result.entity_id}  rev {result.previous_revision} → {result.revision}"
        f"  plan rev {result.plan_revision}  重挂到源 inbox rev {result.base_revision}"
    )
    if result.audit_event_id:
        print(f"  audit {result.audit_event_id}")
    return 0
