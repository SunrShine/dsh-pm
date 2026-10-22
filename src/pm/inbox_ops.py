"""Inbox 分流：状态机 + archive / snooze / merge / note / dismiss / set-status。

通用骨架（定位 / CAS / 原子写 / 审计 / 幂等）在 **pm.entities** —— 本模块只表达 inbox 语义：
状态机（§5.1）、:PM_SNOOZE_UNTIL:、merge 链接、note 落到 memory 候选、dismiss 必须给 reason。
命令实现与 MCP 共用同一套函数，不另写写入逻辑。
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

from pm import entities, ids, inbox

STATUS_CAPTURED = "CAPTURED"
STATUS_TRIAGE = "TRIAGE"
STATUS_TASK_PROPOSED = "TASK_PROPOSED"
STATUS_TASK_CREATED = "TASK_CREATED"
STATUS_NOTE = "NOTE"
STATUS_ARCHIVED = "ARCHIVED"
STATUS_SNOOZED = "SNOOZED"
STATUS_MERGED = "MERGED"
STATUS_DISMISSED = "DISMISSED"

#: memory 候选区（设计 §5.4；note 写这里，不进任务列表）。
STATUS_CANDIDATE = "CANDIDATE"
MEMORY_CANDIDATES = "memory-candidates.org"

#: 置顶标记（inbox 条目属性；值是 org 风格的 t，缺属性 = 没置顶）
PROP_PIN = "PM_PIN"
MEMORY_SECTION = "Memory 候选"

EXIT_CONFLICT = entities.EXIT_CONFLICT
EXIT_INPUT = entities.EXIT_INPUT
#: 兼容 P2a-后端 命名：错误类型与返回类型都来自通用层。
InboxOpError = entities.EntityError
OpResult = entities.OpResult

KNOWN_STATUSES = (
    STATUS_CAPTURED, STATUS_TRIAGE, STATUS_TASK_PROPOSED, STATUS_TASK_CREATED,
    STATUS_NOTE, STATUS_ARCHIVED, STATUS_SNOOZED, STATUS_MERGED, STATUS_DISMISSED,
)

#: 终态：没有出边（§5.1；MERGED / DISMISSED 明确为终态，ARCHIVED 同理）。
TERMINAL_STATUSES = frozenset({STATUS_ARCHIVED, STATUS_MERGED, STATUS_DISMISSED})

#: 合法迁移表（§5.1）：
#:   CAPTURED → TRIAGE → TASK_PROPOSED → TASK_CREATED
#:   CAPTURED / TRIAGE / SNOOZED → NOTE / ARCHIVED / SNOOZED / MERGED / DISMISSED
ALLOWED_TRANSITIONS: dict[str, frozenset] = {
    STATUS_CAPTURED: frozenset({
        STATUS_TRIAGE, STATUS_TASK_PROPOSED, STATUS_NOTE,
        STATUS_ARCHIVED, STATUS_SNOOZED, STATUS_MERGED, STATUS_DISMISSED,
    }),
    STATUS_TRIAGE: frozenset({
        STATUS_TASK_PROPOSED, STATUS_NOTE,
        STATUS_ARCHIVED, STATUS_SNOOZED, STATUS_MERGED, STATUS_DISMISSED,
    }),
    STATUS_TASK_PROPOSED: frozenset({
        STATUS_TASK_CREATED, STATUS_NOTE,
        STATUS_ARCHIVED, STATUS_SNOOZED, STATUS_MERGED, STATUS_DISMISSED,
    }),
    STATUS_TASK_CREATED: frozenset({
        STATUS_NOTE, STATUS_ARCHIVED, STATUS_MERGED, STATUS_DISMISSED,
    }),
    STATUS_SNOOZED: frozenset({
        STATUS_TRIAGE, STATUS_TASK_PROPOSED, STATUS_NOTE,
        STATUS_ARCHIVED, STATUS_MERGED, STATUS_DISMISSED,
    }),
    STATUS_NOTE: frozenset({STATUS_ARCHIVED, STATUS_MERGED, STATUS_DISMISSED}),
    STATUS_ARCHIVED: frozenset(),
    STATUS_MERGED: frozenset(),
    STATUS_DISMISSED: frozenset(),
}


def validate_transition(current: str, target: str) -> None:
    """状态机校验（P2b-后端）：非法迁移抛 ILLEGAL_TRANSITION，调用方不写文件。"""
    if current == target:
        return
    if current in TERMINAL_STATUSES:
        raise InboxOpError(
            "ILLEGAL_TRANSITION",
            f"{current} 是终态，不能再迁移到 {target}",
            exit_code=EXIT_INPUT,
            extra={"currentStatus": current, "targetStatus": target, "allowed": []},
        )
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InboxOpError(
            "ILLEGAL_TRANSITION",
            f"不允许的状态迁移：{current} → {target}",
            exit_code=EXIT_INPUT,
            extra={
                "currentStatus": current,
                "targetStatus": target,
                "allowed": sorted(allowed),
            },
        )


def _validate(entity: entities.Entity, target_status: str) -> None:
    validate_transition(entity.status, target_status)


def parse_until(value: str) -> str:
    """把 --until 归一化：YYYY-MM-DD 原样；ISO8601 保留时区（naive 按本地时区补全）。"""
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            date.fromisoformat(text)
        except ValueError:
            raise InboxOpError("INVALID_UNTIL", f"--until 不是合法日期: {value}")
        return text
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise InboxOpError("INVALID_UNTIL", f"--until 需要 YYYY-MM-DD 或 ISO8601: {value}")
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.isoformat(timespec="seconds")


def _inbox_path(library_root: Path) -> Path:
    return Path(library_root) / inbox.INBOX_RELATIVE


def _load_target(library_root: Path, inbox_id: str):
    """按 :ID: 取 inbox 条目；inbox 特有的 LEGACY 判定也在这里。"""
    path = _inbox_path(library_root)
    if path.is_file():
        try:
            return entities.load_entity(path, inbox_id, headline=inbox.INBOX_HEADLINE)
        except entities.EntityError as exc:
            if exc.code == "NOT_FOUND":
                # inbox 里「没有 :ID: 的顶层列表项」也算旧条目（entities 只认 headline 块）
                untracked = [
                    entry
                    for entry in inbox.parse_entries(entities.read_text(path))
                    if not entry["id"]
                ]
                if untracked:
                    raise entities.legacy_error(inbox_id, len(untracked)) from None
            raise
    return entities.load_entity(path, inbox_id, headline=inbox.INBOX_HEADLINE)


def _apply(library_root: Path, inbox_id: str, **kwargs) -> OpResult:
    """inbox 语义的一次通用变更：先做 inbox 特有的 LEGACY 判定，再走 entities。"""
    path = _inbox_path(library_root)
    _load_target(library_root, inbox_id)
    kwargs.setdefault("headline", inbox.INBOX_HEADLINE)
    kwargs.setdefault("validate", _validate)
    return entities.apply_change(path, inbox_id, **kwargs)


def _entry_text(text: str, inbox_id: str) -> str:
    for entry in inbox.parse_entries(text):
        if entry["id"] == inbox_id:
            return entry["text"]
    return ""


def archive(
    library_root: Path,
    inbox_id: str,
    *,
    expected_revision: int,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> OpResult:
    """归档（§8「仅归档」）：CAPTURED/TRIAGE → ARCHIVED。"""
    return _apply(
        library_root, inbox_id, expected_revision=expected_revision, status=STATUS_ARCHIVED,
        actor=actor, reason=reason, idempotency_key=idempotency_key, dry_run=dry_run, now=now,
    )


def snooze(
    library_root: Path,
    inbox_id: str,
    *,
    until: str,
    expected_revision: int,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> OpResult:
    """延期（§8）：写 :PM_SNOOZE_UNTIL:（inbox 语义，留在本模块）并置 SNOOZED。"""
    parsed = parse_until(until)
    result = _apply(
        library_root, inbox_id, expected_revision=expected_revision, status=STATUS_SNOOZED,
        set_properties={"PM_SNOOZE_UNTIL": parsed}, until=parsed,
        actor=actor, reason=reason, idempotency_key=idempotency_key, dry_run=dry_run, now=now,
    )
    if "snoozeUntil" not in result.extra:
        try:
            entity = entities.load_entity(
                _inbox_path(library_root), inbox_id, headline=inbox.INBOX_HEADLINE
            )
            result.extra["snoozeUntil"] = entity.props.get("PM_SNOOZE_UNTIL") or parsed
        except entities.EntityError:  # pragma: no cover - dry-run 时文件仍应可读
            result.extra["snoozeUntil"] = parsed
    return result


def pin(
    library_root: Path,
    inbox_id: str,
    *,
    expected_revision: int,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> OpResult:
    """置顶：写 :PM_PIN: t。不改状态；已经是置顶（且没有新理由）时是幂等 no-op。"""
    result = _apply(
        library_root, inbox_id, expected_revision=expected_revision, status=None,
        set_properties={PROP_PIN: "t"}, actor=actor, reason=reason,
        audit_extra={"op": "pin"}, idempotency_key=idempotency_key,
        dry_run=dry_run, now=now,
    )
    result.extra["op"] = "pin"
    result.extra["pinned"] = True
    return result


def unpin(
    library_root: Path,
    inbox_id: str,
    *,
    expected_revision: int,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> OpResult:
    """取消置顶：删掉 :PM_PIN:。不改状态；本来就没置顶时是幂等 no-op。"""
    result = _apply(
        library_root, inbox_id, expected_revision=expected_revision, status=None,
        clear_properties=(PROP_PIN,), actor=actor, reason=reason,
        audit_extra={"op": "unpin"}, idempotency_key=idempotency_key,
        dry_run=dry_run, now=now,
    )
    result.extra["op"] = "unpin"
    result.extra["pinned"] = False
    return result


def annotate(
    library_root: Path,
    inbox_id: str,
    *,
    text: str,
    expected_revision: int,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> OpResult:
    """追加式补充（契约 §0.2 / §1）：写进同一条目正文末尾，**原文不动、不改状态**。"""
    body_text = str(text or "").strip("\n")
    if not body_text.strip():
        raise InboxOpError("REQUIRED_TEXT", "annotate 需要 --text（补充内容不能为空）")
    entity = _load_target(library_root, inbox_id)
    at = now or datetime.now().astimezone()
    revision = entity.revision + 1
    actor_value = (str(actor or "human").strip() or "human")
    block = [
        f"补充 [{at.strftime('%Y-%m-%d %a %H:%M')}] actor={actor_value} rev={revision}"
    ]
    block.extend(body_text.split("\n"))
    result = _apply(
        library_root, inbox_id, expected_revision=expected_revision, status=None,
        append_body=block, actor=actor_value, reason=reason,
        audit_extra={"op": "annotate"}, idempotency_key=idempotency_key,
        dry_run=dry_run, now=at,
    )
    result.extra["op"] = "annotate"
    return result


def edit(
    library_root: Path,
    inbox_id: str,
    *,
    text: str,
    reason: str,
    expected_revision: int,
    actor: str = "human",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> OpResult:
    """显式修订原文（契约 §0.3 / §1）：必须给 reason，旧值逐字留在条目里、不改状态。"""
    new_text = str(text or "").strip()
    if not new_text:
        raise InboxOpError("REQUIRED_TEXT", "edit 需要 --text（新原文不能为空）")
    if "\n" in new_text or "\r" in new_text:
        raise InboxOpError(
            "INVALID_HEADLINE",
            "edit 的 --text 必须是单行（headline 不能换行；多行内容请用 annotate 补充）",
        )
    if not str(reason or "").strip():
        raise InboxOpError("REASON_REQUIRED", "edit 必须给 --reason（修订要留下为什么）")
    entity = _load_target(library_root, inbox_id)
    old_text = inbox.headline_text(entity.headline)
    at = now or datetime.now().astimezone()
    revision = entity.revision + 1
    actor_value = (str(actor or "human").strip() or "human")
    reason_line = " ".join(str(reason).split())
    block = [
        f"修订 [{at.strftime('%Y-%m-%d %a %H:%M')}] actor={actor_value} rev={revision}",
        "原因：" + reason_line,
        "旧值：" + old_text,
        "新值：" + new_text,
    ]
    oldsha = hashlib.sha256(old_text.encode("utf-8")).hexdigest()[:12]
    result = _apply(
        library_root, inbox_id, expected_revision=expected_revision, status=None,
        replace_lines={0: "** INBOX " + new_text},
        append_body=block, actor=actor_value, reason=reason,
        audit_extra={
            "op": "edit",
            "oldText": old_text,
            "newText": new_text,
            "oldsha": oldsha,
            "oldlen": len(old_text),
        },
        idempotency_key=idempotency_key, dry_run=dry_run, now=at,
    )
    result.extra["op"] = "edit"
    return result


def history(library_root: Path, inbox_id: str) -> dict:
    """只读：原文 + 补充块 + 修订块（按文件顺序 = 时间顺序）。"""
    entity = _load_target(library_root, inbox_id)
    text = entities.read_text(_inbox_path(library_root))
    target = None
    for block in inbox.iter_entry_blocks(text):
        if block["kind"] == "headline" and block["props"].get("ID") == inbox_id:
            target = block
            break
    if target is None:  # pragma: no cover - _load_target 已保证存在
        raise InboxOpError("NOT_FOUND", f"找不到 :ID: 为 {inbox_id} 的条目")
    original_body, blocks = inbox.split_body_blocks(target["body"])
    if "PM_TITLE" in target["props"]:
        original = "\n".join(original_body)  # 显式标题模式：正文即全文
    else:
        original = inbox.headline_text(target["raw"])
        if original_body:
            original = original + "\n" + "\n".join(original_body)
    annotations = [
        {
            "at": block["at"],
            "actor": block["actor"],
            "revision": block["revision"],
            "text": block.get("text", ""),
        }
        for block in blocks
        if block["type"] == "annotation"
    ]
    revisions = [
        {
            "at": block["at"],
            "actor": block["actor"],
            "revision": block["revision"],
            "reason": block.get("reason", ""),
            "oldText": block.get("oldText", ""),
            "newText": block.get("newText", ""),
        }
        for block in blocks
        if block["type"] == "revision"
    ]
    return {
        "id": entity.entity_id,
        "revision": entity.revision,
        "status": entity.status,
        "text": original,
        "annotations": annotations,
        "revisions": revisions,
    }


def set_status(
    library_root: Path,
    inbox_id: str,
    *,
    status: str,
    expected_revision: int,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> OpResult:
    """显式状态迁移（如 CAPTURED → TRIAGE）；合法性由状态机把关。"""
    target = str(status or "").strip().upper()
    if target not in KNOWN_STATUSES:
        raise InboxOpError(
            "UNKNOWN_STATUS", f"未知状态 {status!r}；可用: " + ", ".join(KNOWN_STATUSES)
        )
    return _apply(
        library_root, inbox_id, expected_revision=expected_revision, status=target,
        actor=actor, reason=reason, idempotency_key=idempotency_key, dry_run=dry_run, now=now,
    )


def dismiss(
    library_root: Path,
    inbox_id: str,
    *,
    expected_revision: int,
    reason: str,
    actor: str = "human",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> OpResult:
    """丢弃：**必须给 reason**（§5.1 / §11 可追溯）。"""
    if not str(reason or "").strip():
        raise InboxOpError("REASON_REQUIRED", "dismiss 必须给 --reason（丢弃要留下原因）")
    return _apply(
        library_root, inbox_id, expected_revision=expected_revision, status=STATUS_DISMISSED,
        actor=actor, reason=reason, idempotency_key=idempotency_key, dry_run=dry_run, now=now,
    )


def merge(
    library_root: Path,
    inbox_id: str,
    *,
    into: str,
    expected_revision: int,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> OpResult:
    """合并：源记录标 MERGED，:PM_MERGED_INTO: 留主记录 ID，审计带 into=…（不删历史）。

    主记录可能是别的域（task-…）；跨域改主记录需要对方模块的事务，P2b-后端 只在源记录留链接。
    """
    target = str(into or "").strip()
    if not target:
        raise InboxOpError("INVALID_TARGET", "merge 需要 --into <主记录 ID>")
    if target == inbox_id:
        raise InboxOpError("INVALID_TARGET", "merge 的 --into 不能是自己")
    result = _apply(
        library_root, inbox_id, expected_revision=expected_revision, status=STATUS_MERGED,
        set_properties={"PM_MERGED_INTO": target}, audit_extra={"into": target},
        actor=actor, reason=reason, idempotency_key=idempotency_key, dry_run=dry_run, now=now,
    )
    result.extra["mergedInto"] = target
    return result


def note(
    library_root: Path,
    inbox_id: str,
    *,
    expected_revision: int,
    project: str | None = None,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> OpResult:
    """保存为项目笔记：写入 memory 候选区（不进任务列表），源记录标 NOTE。"""
    path = _inbox_path(library_root)
    at = now or datetime.now().astimezone()
    candidate_id = ids.new_entity_id("memory", int(at.timestamp() * 1000))
    audit_extra = {"note": candidate_id}

    # 先 dry-run 预检：CAS / 状态机 / LEGACY / 幂等；失败时不留下任何副作用
    probe = _apply(
        library_root, inbox_id, expected_revision=expected_revision, status=STATUS_NOTE,
        set_properties={"PM_NOTE_ID": candidate_id}, audit_extra=audit_extra,
        actor=actor, reason=reason, idempotency_key=idempotency_key, dry_run=True, now=at,
    )
    if probe.idempotent:
        entity = entities.load_entity(path, inbox_id, headline=inbox.INBOX_HEADLINE)
        probe.extra.update({
            "noteId": entity.props.get("PM_NOTE_ID") or None,
            "notePath": MEMORY_CANDIDATES,
        })
        return probe

    entity = entities.load_entity(path, inbox_id, headline=inbox.INBOX_HEADLINE)
    project_key = (project or entity.props.get("PM_PROJECT_HINT") or "").strip()
    entry_text = _entry_text(entities.read_text(path), inbox_id)
    if not dry_run:
        first_line = entry_text.splitlines()[0] if entry_text else "(empty)"
        entities.create_entity(
            Path(library_root) / MEMORY_CANDIDATES,
            entity_id=candidate_id,
            kind="memory",
            status=STATUS_CANDIDATE,
            headline="MEMORY " + first_line[:60],
            section=MEMORY_SECTION,
            properties={
                "PM_SCOPE": project_key or "inbox",
                **({"PM_PROJECT_HINT": project_key} if project_key else {}),
                "PM_SOURCE_INBOX_ID": inbox_id,
            },
            body_lines=entry_text.split("\n") if entry_text else [],
            actor=actor,
            now=at,
        )

    result = _apply(
        library_root, inbox_id, expected_revision=expected_revision, status=STATUS_NOTE,
        set_properties={"PM_NOTE_ID": candidate_id}, audit_extra=audit_extra,
        actor=actor, reason=reason, idempotency_key=idempotency_key, dry_run=dry_run, now=at,
    )
    result.extra.update({"noteId": candidate_id, "notePath": MEMORY_CANDIDATES})
    return result


def list_entries(library_root: Path, *, status: str | None = None) -> dict:
    """列出 inbox 条目（含 revision / snoozeUntil），可按 status 过滤。"""
    path = _inbox_path(library_root)
    if not path.is_file():
        return {"path": inbox.INBOX_RELATIVE, "count": 0, "entries": []}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InboxOpError("UNREADABLE", f"读不了 {path}: {exc}")
    detail = {
        block["line"]: block
        for block in inbox.iter_entry_blocks(text)
        if block["kind"] == "headline"
    }
    wanted = (status or "").strip().upper() or None
    entries: list[dict] = []
    # with_annotations=True：同一趟解析就带出补充块全文（卡片直接渲染，不再 per-entry 调用）
    for entry in inbox.parse_entries(text, with_annotations=True):
        block = detail.get(entry["line"])
        tracked = bool(entry["id"])
        row = {
            "id": entry["id"],
            "status": entry["status"],
            "revision": entities.revision_of(block["props"]) if (tracked and block) else None,
            "snoozeUntil": (block["props"].get("PM_SNOOZE_UNTIL") or None) if block else None,
            "text": entry["text"],
            "line": entry["line"],
            # 与 ui-cards 的 inbox.entries[] 保持同一组字段（前端要显示捕获时间/来源/项目提示）
            "capturedAt": entry.get("capturedAt"),
            "source": entry.get("source"),
            "projectHint": entry.get("projectHint"),
            # 补充/修订计数 + 补充块全文（同一趟解析的结果；旧条目计数一律 null、annotations 为 []）
            "annotationCount": entry.get("annotationCount"),
            "revisionCount": entry.get("revisionCount"),
            "lastAnnotationText": entry.get("lastAnnotationText"),
            "annotations": entry.get("annotations", []),
            # 置顶：永远是 bool（缺 :PM_PIN: 或旧条目都是 false）
            "pinned": bool(entry.get("pinned")),
        }
        if wanted is None or row["status"].upper() == wanted:
            entries.append(row)
    return {"path": inbox.INBOX_RELATIVE, "count": len(entries), "entries": entries}
