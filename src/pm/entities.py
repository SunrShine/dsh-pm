"""任意 org 实体的通用写骨架：定位 / CAS / 原子写 / 审计 / 幂等。

被 inbox / task / proposal / memory 共用（backend-design §5 / §6 / §7 / §9），
各域模块不要再各写一套。

实体约定（所有域一致）：
  :ID: <prefix>-<ULID>    身份唯一来源，**永不按行号建立关联**
  :PM_KIND: inbox|task|proposal|memory
  :PM_STATUS: <域内状态>
  :PM_REVISION: <int>     每次成功写入 +1

写操作统一返回（§5）：
  {ok, entityId, revision, source:"org", observedAt, auditEventId, status,
   previousStatus, previousRevision, changed, path}
冲突：退出码 3 + REVISION_CONFLICT + currentRevision/expectedRevision/diffHint，
      且**文件逐字节不变**。

缩进约定（**有意偏离设计示例，留档**）：
  backend-design §5.1/§5.2 的示例把抽屉与正文顶格写；我们写出的是**三空格缩进**。
  原因：inbox.org 里 capture 的正文必须能与后续人工写的顶层 `- ` 列表项区分开
  （§9 的 LEGACY_UNTRACKED 共存场景），parse/编辑都依赖这个缩进边界。
  需要顶格正文的域（如 §5.2 的 `*** 验收标准` 子标题）用 create_entity(indent_body=False)。

审计：写在该实体条目自己的 :LOGBOOK: 里，行形如
  - State "<new>" from "<old>" [<人类时间>] id=<entityId> audit=<audit-ULID>
    at=<ISO8601> actor=<a> rev=<n> raison=<r>
状态与审计在**同一次原子写**里落地（单文件要么都写要么都不写）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pm import ids
from pm.humanwrite import append_entry_tracked, plan_entry, verbatim_entry_block
from pm.org import write_atomic

#: 冲突用专用退出码（2 留给输入错误）。
EXIT_CONFLICT = 3
EXIT_INPUT = 2

SOURCE_ORG = "org"

#: 没有 :PM_STATUS: 时的兜底状态（域可以传自己的 default_status）。
DEFAULT_STATUS = "CAPTURED"

_AT_COL0 = re.compile(r"^(?P<stars>\*+)(?:\s+(?P<title>.*))?$")
_AUDIT_STAMP = re.compile(r"\[(\d{4}-\d{2}-\d{2}) \w+ (\d{2}:\d{2})\]")


class EntityError(Exception):
    """一次实体操作的明确失败；code 是机器可读错误码。"""

    def __init__(self, code: str, message: str, *, exit_code: int = EXIT_INPUT, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.extra = dict(extra or {})


@dataclass
class OpResult:
    """写操作统一返回。extra 放域特有的附加信息（如 noteId / mergedInto）。"""

    path: Path
    entity_id: str
    status: str
    revision: int
    previous_status: str
    previous_revision: int
    changed: bool
    idempotent: bool = False
    dry_run: bool = False
    audit_line: str = ""
    source: str = SOURCE_ORG
    observed_at: str | None = None
    audit_event_id: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def inbox_id(self) -> str:
        """兼容 P2a-后端 的命名（inbox 域内 entity_id == inbox_id）。"""
        return self.entity_id

    @property
    def snooze_until(self) -> str | None:
        """兼容 P2a-后端：延期到期时间放在 extra["snoozeUntil"]。"""
        return self.extra.get("snoozeUntil")


@dataclass
class Entity:
    """一个 org 实体条目（headline + 抽屉 + 正文）在文件里的位置与内容。"""

    path: Path
    entity_id: str
    kind: str
    status: str
    revision: int
    props: dict[str, str]
    line: int  # 1-based headline 行号（只用于展示）
    start: int  # 0-based headline 下标
    end: int  # 0-based 闭开区间终点
    drawer: tuple[int, int] | None  # :PROPERTIES: 的 [start, end)
    body_start: int
    body: list[str]
    headline: str = ""
    level: int = 2


# ---------------------------------------------------------------- 读取


def read_text(path: Path) -> str:
    """读 org 文件（换行归一化为 \\n）；不存在 → EntityError(NOT_FOUND)。"""
    path = Path(path)
    if not path.is_file():
        raise EntityError("NOT_FOUND", f"找不到 {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EntityError("UNREADABLE", f"读不了 {path}: {exc}")
    return raw.decode("utf-8", "replace").replace("\r\n", "\n")


def _read_source(path: Path) -> tuple[str, list[str], str]:
    path = Path(path)
    if not path.is_file():
        raise EntityError("NOT_FOUND", f"找不到 {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EntityError("UNREADABLE", f"读不了 {path}: {exc}")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
    return newline, text.split("\n"), text


def _col0_level(raw: str) -> int:
    match = _AT_COL0.match(raw)
    return len(match.group("stars")) if match else 0


def _property_line(raw: str) -> tuple[str, str] | None:
    stripped = raw.strip()
    if stripped in (":PROPERTIES:", ":END:", ":LOGBOOK:"):
        return None
    if not stripped.startswith(":") or ":" not in stripped[1:]:
        return None
    name, _, value = stripped[1:].partition(":")
    name = name.strip().upper()
    return (name, value.strip()) if name else None


def _read_drawers(
    lines: list[str], index: int, end: int
) -> tuple[dict[str, str], tuple[int, int] | None, int]:
    """读 headline 后紧贴的 PROPERTIES / LOGBOOK 抽屉。

    返回 (属性, :PROPERTIES: 的 [start,end) 或 None, 抽屉结束后的下标)。
    LOGBOOK 整段跳过，绝不混进正文。
    """
    props: dict[str, str] = {}
    drawer: tuple[int, int] | None = None
    cursor = index + 1
    if cursor < end and lines[cursor].strip() == ":PROPERTIES:":
        start = cursor
        cursor += 1
        while cursor < end and lines[cursor].strip() != ":END:":
            parsed = _property_line(lines[cursor])
            if parsed is not None:
                props[parsed[0]] = parsed[1]
            cursor += 1
        if cursor < end:
            cursor += 1
        drawer = (start, cursor)
    elif cursor < end and _property_line(lines[cursor]) is not None:
        # 裸属性块（没有 :PROPERTIES: 标记的旧数据）
        start = cursor
        while cursor < end:
            parsed = _property_line(lines[cursor])
            if parsed is None:
                break
            props[parsed[0]] = parsed[1]
            cursor += 1
        if cursor < end and lines[cursor].strip() == ":END:":
            cursor += 1
        drawer = (start, cursor)
    if cursor < end and lines[cursor].strip() == ":LOGBOOK:":
        cursor += 1
        while cursor < end and lines[cursor].strip() != ":END:":
            cursor += 1
        if cursor < end:
            cursor += 1
    return props, drawer, cursor


def iter_entity_blocks(text: str, *, headline: str | None = None, level: int = 2) -> list[dict]:
    """扫描 org 文本里的实体内块（第 level 层 headline + 抽屉 + 正文）。

    headline 非空时只在那个一级小节内扫描（如 "Inbox"）；否则扫全文件。
    每块：{line, headline, props, body, start, end, drawer, body_start, body_end, body_region_start}

    - body_start：**正文末尾的插入点**（append_body 往里追加；tasks.py 依赖这个语义，别改）；
    - body_end：最后一行非空正文之后（追加/替换后保留尾部空行用）；
    - body_region_start：正文区真正的起点（抽屉之后）—— replace_body 用。
    """
    from pm.humanwrite import find_section

    lines = text.splitlines()
    if headline:
        section = find_section(lines, headline)
        start, end = section if section is not None else (0, len(lines))
    else:
        start, end = 0, len(lines)

    blocks: list[dict] = []
    index = start
    while index < end:
        raw = lines[index]
        if _col0_level(raw) == level:
            props, drawer, cursor = _read_drawers(lines, index, end)
            body_region_start = cursor  # 正文区起点（抽屉之后；可能紧接着尾部空行）
            body: list[str] = []
            while cursor < end:
                level_here = _col0_level(lines[cursor])
                if 0 < level_here <= level:  # 下一个同级/更高级 headline 才是边界
                    break
                body.append(lines[cursor])
                cursor += 1
            while body and not body[-1].strip():
                body.pop()
            # body_end：正文里**最后一行非空内容**之后的位置（折叠 tail 连续空行）。
            # 追加内容要插在这里，否则会落在条目尾部那几个空行之后（org 不好看）。
            body_end = body_region_start + len(body)
            blocks.append(
                {
                    "line": index + 1,
                    "level": level,
                    "headline": raw,
                    "props": props,
                    "body": [line[3:] if line.startswith("   ") else line for line in body],
                    "start": index,
                    "end": cursor,
                    "drawer": drawer,
                    # body_start 保持「正文末尾插入点」的既有语义（tasks.py 有依赖）
                    "body_start": cursor,
                    "body_end": body_end,
                    "body_region_start": body_region_start,
                }
            )
            index = cursor
            continue
        index += 1
    return blocks


def _revision_of(props: dict) -> int:
    raw = str(props.get("PM_REVISION", "") or "").strip()
    try:
        return int(raw)
    except ValueError:
        return 1


def iter_entities(path: Path, *, headline: str | None = None, default_status: str = DEFAULT_STATUS) -> list[Entity]:
    """文件里的全部实体（含没有 :ID: 的块，entity_id 为空串）。"""
    path = Path(path)
    text = read_text(path)
    entities: list[Entity] = []
    for block in iter_entity_blocks(text, headline=headline):
        props = block["props"]
        entities.append(
            Entity(
                path=path,
                entity_id=props.get("ID", ""),
                kind=props.get("PM_KIND", ""),
                status=props.get("PM_STATUS") or default_status,
                revision=_revision_of(props),
                props=props,
                line=block["line"],
                start=block["start"],
                end=block["end"],
                drawer=block["drawer"],
                body_start=block["body_start"],
                body=block["body"],
                headline=block["headline"],
                level=block["level"],
            )
        )
    return entities


def revision_of(props: dict) -> int:
    """读 :PM_REVISION:（缺失/坏值按初始 revision 1 处理）。"""
    return _revision_of(props)


def legacy_error(entity_id: str, count: int) -> EntityError:
    """统一的 LEGACY_UNTRACKED 错误（headline 块与 inbox 列表项共用同一口径）。"""
    return EntityError(
        "LEGACY_UNTRACKED",
        f"找不到 :ID: 为 {entity_id} 的条目；文件里还有 {count} 条没有 :ID: 的旧条目"
        "（LEGACY_UNTRACKED），无法按身份处理 —— 请先补 :ID: 再操作（不按行号处理）。",
    )


def not_found_message(path: Path, entity_id: str) -> str:
    """NOT_FOUND 也要能**自诊断**：写清查了哪个文件；如果文件里**有**这个 :ID: 却寻址不到，
    再点出"抽屉没闭合 / headline 缩进坏了"这条最可能的原因。

    来历（task-01M52D77…）：一个漏了 `:END:` 的 `:LOGBOOK:` 把后面的任务块吞进抽屉，
    于是 `pm task list/show`（整文件读）正常、而按实体寻址的写路径报"找不到条目"——用户完全没法猜。
    """
    location = f"（查了 {path}）"
    try:
        text = read_text(path)
    except EntityError:
        return f"找不到 :ID: 为 {entity_id} 的条目{location}：文件不存在或读不了"
    if entity_id in text:
        return (
            f"找不到 :ID: 为 {entity_id} 的条目{location}；"
            "注意：该 :ID: 在文件里**出现过**，但不在任何可寻址的块里 —— 多半是抽屉"
            "（:PROPERTIES:/:LOGBOOK:）没闭合、或 headline 缩进坏了，把后面的块吞进去了。"
            "先人工补上 :END:（或跑 pm task init-ids 检查），不要按行号硬处理。"
        )
    return f"找不到 :ID: 为 {entity_id} 的条目{location}；文件里没有这个 :ID:"


def load_entity(
    path: Path, entity_id: str, *, headline: str | None = None, default_status: str = DEFAULT_STATUS
) -> Entity:
    """按 :ID: 定位一个实体。

    找不到时：文件里存在没有 :ID: 的块 → LEGACY_UNTRACKED（§9，提示先补 ID）；
    否则 → NOT_FOUND。
    """
    entities = iter_entities(path, headline=headline, default_status=default_status)
    for entity in entities:
        if entity.entity_id == entity_id:
            return entity
    untracked = [entity for entity in entities if not entity.entity_id]
    if untracked:
        raise legacy_error(entity_id, len(untracked))
    raise EntityError("NOT_FOUND", not_found_message(path, entity_id))


# ---------------------------------------------------------------- 审计


def new_audit_id(at: datetime) -> str:
    """一条审计事件的稳定标识（零依赖 ULID）。"""
    return "audit-" + ids.new_ulid(int(at.timestamp() * 1000))


def audit_line(
    *, at: datetime, entity_id: str, audit_id: str, actor: str, from_status: str,
    to_status: str, revision: int, reason: str, key: str = "",
    snooze_until: str | None = None, extra: dict | None = None,
) -> str:
    """生成一条 LOGBOOK 审计行（各域共用同一形状）。"""
    parts = [
        f'- State "{to_status}" from "{from_status}" [{at.strftime("%Y-%m-%d %a %H:%M")}]',
        f"id={entity_id}",
        f"audit={audit_id}",
        f"at={at.isoformat(timespec='seconds')}",
        f"actor={actor or 'human'}",
        f"rev={revision}",
    ]
    if snooze_until:
        parts.append("until=" + snooze_until)
    if reason:
        parts.append("reason=" + " ".join(str(reason).split()))
    if key:
        parts.append("key=" + key)
    for name, value in (extra or {}).items():
        if value:
            parts.append(f"{name}=" + " ".join(str(value).split()))
    return "   " + " ".join(parts)


def audit_from_region(region: str, key: str | None = None) -> tuple[str | None, str | None]:
    """从已有 LOGBOOK 里取 (auditEventId, observedAt)；给了 key 只看该 key 的那条。"""
    for line in reversed(region.splitlines()):
        if "audit=" not in line:
            continue
        if key and not re.search(r"(?<!\S)key=" + re.escape(key) + r"(?=\s|$)", line):
            continue
        found = re.search(r"(?<!\S)audit=(\S+)", line)
        observed = None
        exact = re.search(r"(?<!\S)at=(\S+)", line)
        if exact:
            try:
                observed = datetime.fromisoformat(exact.group(1)).isoformat(timespec="seconds")
            except ValueError:
                observed = None
        if observed is None:
            stamp = _AUDIT_STAMP.search(line)
            if stamp:
                parsed = datetime.strptime(stamp.group(1) + " " + stamp.group(2), "%Y-%m-%d %H:%M")
                observed = parsed.astimezone().isoformat(timespec="seconds")
        return (found.group(1) if found else None), observed
    return None, None


def find_logbook_span(lines: list[str], begin: int, end: int) -> tuple[int, int] | None:
    """找 :LOGBOOK: 到 :END: 的 [start, end) 区间。"""
    start = None
    for index in range(begin, min(end, len(lines))):
        stripped = lines[index].strip()
        if start is None:
            if stripped == ":LOGBOOK:":
                start = index
            continue
        if stripped == ":END:":
            return (start, index + 1)
    return None


# ---------------------------------------------------------------- 写入


def _norm_key(key: str | None) -> str:
    return "".join(str(key).split()) if key else ""


def _update_drawer(
    lines: list[str], span: tuple[int, int], updates: dict[str, str], removals: set[str]
) -> list[str]:
    """按 updates/removals 重写 :PROPERTIES: 抽屉（保持原有属性顺序）。"""
    span_start, span_end = span
    written: set[str] = set()
    kept: list[str] = []
    for line in lines[span_start:span_end]:
        stripped = line.strip()
        name = stripped[1:].partition(":")[0].strip().upper() if stripped.startswith(":") else ""
        if stripped == ":END:":
            for key, value in updates.items():
                if key not in written:
                    kept.append(f"   :{key}: {value}")
                    written.add(key)
            kept.append(line)
            continue
        if name and name in removals:
            continue
        if name in updates:
            indent = line[: len(line) - len(line.lstrip())] or "   "
            kept.append(f"{indent}:{name}: {updates[name]}")
            written.add(name)
            continue
        kept.append(line)
    for key, value in updates.items():
        if key not in written:
            kept.append(f"   :{key}: {value}")
    return kept


def apply_replace_lines(
    lines: list[str], block: dict, replace_lines: dict[int, str]
) -> list[str]:
    """按「相对 headline 的 0-based 偏移」整行替换，返回替换后的新副本。

    安全约束（由 Lead 冻结；违反一律抛 EntityError，绝不静默忽略）：
      a) 越界 index → 拒绝；
      b) offset 0 必须仍是同一层级的 headline（同样多的 *）；
      c) offset > 0 允许 col-0 的 *+ 子标题，但层级不能 <= 实体自身层级
         （** 实体下可以写 *** 子标题，不能写 ** / *）；
      d) 不能替换 :PROPERTIES: / :LOGBOOK: 区间里的行。
    """
    start = block["start"]
    end = block["end"]
    level = block.get("level", 2)
    drawer = block.get("drawer")
    logbook = find_logbook_span(lines, drawer[1] if drawer else start + 1, end)
    prepared: dict[int, str] = {}
    for offset, replacement in (replace_lines or {}).items():
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise EntityError("INVALID_REPLACE_RANGE", f"replace_lines 的偏移必须是 >=0 的整数: {offset!r}")
        if offset >= end - start:
            raise EntityError(
                "INVALID_REPLACE_RANGE",
                f"replace_lines 偏移 {offset} 超出实体范围（合法 0..{end - start - 1}）",
            )
        if not isinstance(replacement, str) or "\n" in replacement or "\r" in replacement:
            raise EntityError("INVALID_REPLACE_LINE", f"偏移 {offset} 的替换行必须是单行字符串")
        absolute = start + offset
        if drawer and drawer[0] <= absolute < drawer[1]:
            raise EntityError("INVALID_REPLACE_RANGE", f"偏移 {offset} 落在 :PROPERTIES: 抽屉里，不能替换")
        if logbook and logbook[0] <= absolute < logbook[1]:
            raise EntityError("INVALID_REPLACE_RANGE", f"偏移 {offset} 落在 :LOGBOOK: 里，不能替换")
        new_level = _col0_level(replacement)
        if offset == 0:
            if new_level != level:
                raise EntityError(
                    "INVALID_REPLACE_LINE",
                    f"headline 必须保持同一层级（{level} 个 *），收到 {new_level or 0} 个 *",
                )
        elif new_level and new_level <= level:
            raise EntityError(
                "INVALID_REPLACE_LINE",
                f"偏移 {offset} 不能造出同级/更高级标题（{new_level} 个 *，实体是 {level} 个 *）",
            )
        prepared[absolute] = replacement
    result = list(lines)
    for absolute, replacement in prepared.items():
        result[absolute] = replacement
    return result


def _plan_change(
    lines: list[str],
    block: dict,
    *,
    updates: dict[str, str],
    removals: set[str],
    target_status: str,
    append_body: list[str] | None,
    actor: str,
    at: datetime,
    reason: str,
    key: str,
    audit_extra: dict | None,
    until: str | None = None,
    replace_lines: dict[int, str] | None = None,
    replace_body: list[str] | None = None,
) -> tuple[list[str], int, str, str]:
    span = block["drawer"]
    if span is None:  # pragma: no cover - 调用方已先拦
        raise EntityError("LEGACY_UNTRACKED", "该条目没有 :PROPERTIES: 抽屉，无法写入状态")
    new_revision = _revision_of(block["props"]) + 1
    full_updates = dict(updates)
    full_updates["PM_REVISION"] = str(new_revision)

    # 先做整行替换（不改行数，所以后面的抽屉/正文偏移仍然对得上）
    base = apply_replace_lines(lines, block, replace_lines) if replace_lines else list(lines)
    new_drawer = _update_drawer(base, span, full_updates, removals)

    result = list(base)
    result[span[0] : span[1]] = new_drawer
    # 抽屉改写带来的行数位移（只影响抽屉之后的所有行）
    drawer_delta = len(new_drawer) - (span[1] - span[0])
    # 追加正文插在正文区起点（也就是所有抽屉之后），所以它**不影响 LOGBOOK 的位置**。
    body_delta = 0
    if replace_body is not None:
        # 原样替换整个正文区（抽屉之后 → 条目区域末尾），**不加缩进**：
        # 提案正文里的 "*** 变更" 是真子标题，必须保持第 0 列。
        # 尾部原有的分隔空行（最后一行非空正文之后那一段）保留，避免和下一条目粘在一起。
        start = block.get("body_region_start", block["body_start"]) + drawer_delta
        stop = block["end"] + drawer_delta
        trailing = list(result[block.get("body_end", start) + drawer_delta : stop])
        result[start:stop] = list(replace_body) + trailing
        body_delta = len(replace_body) + len(trailing) - (stop - start)
    elif append_body:
        # 插在「最后一行非空正文之后」（body_end），而不是条目区域的末尾：
        # 条目与下一条之间的分隔空行要留在追加块之后，不能被顶到块前面去。
        insert_at = block.get("body_end", block["body_start"]) + drawer_delta
        result[insert_at:insert_at] = [("   " + line) if line != "" else "" for line in append_body]
        body_delta = len(append_body)

    entry_end = block["end"] + drawer_delta + body_delta
    search_from = span[1] + drawer_delta

    audit_id = new_audit_id(at)
    log_line = audit_line(
        at=at, entity_id=block["props"].get("ID", ""), audit_id=audit_id, actor=actor,
        from_status=block["props"].get("PM_STATUS") or DEFAULT_STATUS, to_status=target_status,
        revision=new_revision, reason=reason, key=key, snooze_until=until, extra=audit_extra,
    )
    log_span = find_logbook_span(result, search_from, entry_end)
    if log_span is not None:
        result.insert(log_span[1] - 1, log_line)
    else:
        result[search_from:search_from] = ["   :LOGBOOK:", log_line, "   :END:"]
    return result, new_revision, log_line, audit_id


def apply_change(
    path: Path,
    entity_id: str,
    *,
    expected_revision: int,
    status: str | None = None,
    set_properties: dict[str, str] | None = None,
    clear_properties: tuple[str, ...] = (),
    replace_lines: dict[int, str] | None = None,
    append_body: list[str] | None = None,
    replace_body: list[str] | None = None,
    headline: str | None = None,
    actor: str = "human",
    reason: str = "",
    idempotency_key: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
    audit_extra: dict | None = None,
    until: str | None = None,
    validate=None,
    default_status: str = DEFAULT_STATUS,
) -> OpResult:
    """对一个 org 实体做 CAS + 原子写 + 审计；任意域共用。

    status=None 表示不改 PM_STATUS（只改其它属性/正文）。
    validate(entity, target_status) 可选：抛 EntityError 即拒绝（如状态机校验）。

    正文有两种写法，**互斥**：
    - append_body：在正文末尾追加（自动加 3 空格缩进），适合「补充」；
    - replace_body：用给的行**原样替换**整个正文区（不加缩进），空列表 = 清空正文；
      提案正文里的 "*** 变更" 是真子标题，必须保持第 0 列，所以用它。
    替换会保留正文尾部原有的分隔空行；与上一次相同的内容算零变更（不写、不加审计）。
    """
    path = Path(path)
    newline, lines, text = _read_source(path)
    blocks = iter_entity_blocks(text, headline=headline)
    target_block: dict | None = None
    for block in blocks:
        if block["props"].get("ID") == entity_id:
            target_block = block
            break
    if target_block is None:
        untracked = [block for block in blocks if not block["props"].get("ID")]
        if untracked:
            raise legacy_error(entity_id, len(untracked))
        raise EntityError("NOT_FOUND", not_found_message(Path(path), entity_id))
    if target_block["drawer"] is None:
        raise EntityError(
            "LEGACY_UNTRACKED",
            f"{entity_id} 没有 :PROPERTIES: 抽屉，无法按身份处理；请先补 :ID: / 状态字段。",
        )

    props = target_block["props"]
    current_revision = _revision_of(props)
    current_status = props.get("PM_STATUS") or default_status
    updates: dict[str, str] = dict(set_properties or {})
    if status is not None:
        updates["PM_STATUS"] = status
    removals = {name.strip().upper() for name in clear_properties if name.strip()}
    at = now or datetime.now().astimezone()
    key = _norm_key(idempotency_key)
    actor = (actor or "human").strip() or "human"
    target_status = status or current_status

    # 输入层的冲突先于 CAS：即使 revision 也不对，也要先报「一次只能选一种正文方式」
    if append_body and replace_body is not None:
        raise EntityError(
            "BODY_MODE_CONFLICT",
            "append_body 与 replace_body 互斥：一次写入只能选一种正文方式"
            "（追加用 append_body，整体替换/清空用 replace_body）。",
        )

    if key:
        for block in blocks:
            region = "\n".join(lines[block["start"] : block["end"]])
            if not re.search(r"(?<!\S)key=" + re.escape(key) + r"(?=\s|$)", region, re.MULTILINE):
                continue
            holder_id = block["props"].get("ID", "")
            if holder_id != entity_id:
                raise EntityError(
                    "IDEMPOTENCY_KEY_REUSED",
                    f"idempotency key {key} 已经用在 {holder_id} 上，不能换目标重复使用",
                )
            held_audit, held_observed = audit_from_region(region, key)
            return OpResult(
                path=path,
                entity_id=entity_id,
                status=block["props"].get("PM_STATUS") or default_status,
                revision=_revision_of(block["props"]),
                previous_status=current_status,
                previous_revision=current_revision,
                changed=False,
                idempotent=True,
                observed_at=held_observed,
                audit_event_id=held_audit,
            )

    if current_revision != expected_revision:
        raise EntityError(
            "REVISION_CONFLICT",
            f"revision 冲突：现在写会覆盖别人的修改（文件里 {current_revision}，你看到的是 {expected_revision}）",
            exit_code=EXIT_CONFLICT,
            extra={
                "currentRevision": current_revision,
                "expectedRevision": expected_revision,
                "diffHint": "文件已被其他编辑器/命令修改，请重新读取（pm inbox list）后按新 revision 再提交",
            },
        )

    replacements = dict(replace_lines or {})
    # 计划写入的正文区（含保留的尾部空行）；用来判定「内容没变」的零变更
    planned_body: list[str] | None = None
    if replace_body is not None:
        trailing = list(lines[block.get("body_end", block["body_start"]) : target_block["end"]])
        planned_body = list(replace_body) + trailing
    unchanged = (
        all(str(props.get(name, "")) == str(value) for name, value in updates.items())
        and all(name not in props for name in removals)
        and not append_body
        and (
            replace_body is None
            or planned_body
            == list(
                lines[
                    target_block.get("body_region_start", target_block["body_start"]) :
                    target_block["end"]
                ]
            )
        )
        and not replacements
    )
    if unchanged:
        region = "\n".join(lines[target_block["start"] : target_block["end"]])
        last_audit, last_observed = audit_from_region(region)
        return OpResult(
            path=path,
            entity_id=entity_id,
            status=current_status,
            revision=current_revision,
            previous_status=current_status,
            previous_revision=current_revision,
            changed=False,
            observed_at=last_observed or at.isoformat(timespec="seconds"),
            audit_event_id=last_audit,
        )

    if validate is not None:
        entity = Entity(
            path=path, entity_id=entity_id, kind=props.get("PM_KIND", ""), status=current_status,
            revision=current_revision, props=props, line=target_block["line"],
            start=target_block["start"], end=target_block["end"], drawer=target_block["drawer"],
            body_start=target_block["body_start"], body=target_block["body"], headline=target_block["headline"],
        )
        validate(entity, target_status)

    new_lines, new_revision, log_line, audit_id = _plan_change(
        lines, target_block, updates=updates, removals=removals, target_status=target_status,
        append_body=append_body, actor=actor, at=at, reason=reason, key=key,
        audit_extra=audit_extra, until=until, replace_lines=replacements,
        replace_body=replace_body,
    )
    if not dry_run:
        write_atomic(path, "\n".join(new_lines), newline=newline, fsync=True)
    return OpResult(
        path=path,
        entity_id=entity_id,
        status=target_status,
        revision=new_revision,
        previous_status=current_status,
        previous_revision=current_revision,
        changed=True,
        dry_run=dry_run,
        audit_line=log_line,
        observed_at=at.isoformat(timespec="seconds"),
        audit_event_id=audit_id,
    )


@dataclass(frozen=True)
class CreateResult:
    """一次 create 的结果。

    主字段是 line / audit_event_id；**二元解包仍然可用**（`line, audit = result`），
    调用方靠 `created` / `idempotent` 区分「新建」与「同一 idempotency-key 重放」。
    """

    line: int
    audit_event_id: str
    entity_id: str
    path: Path
    created: bool
    idempotent: bool = False
    observed_at: str | None = None
    revision: int = 1
    found_section: bool = True

    def __iter__(self):
        return iter((self.line, self.audit_event_id))

    def __getitem__(self, index):
        return (self.line, self.audit_event_id)[index]

    def __len__(self) -> int:
        return 2


def _block_revision(block: str) -> str:
    """从刚构造的块里读回 :PM_REVISION:（用于把 CreateResult.revision 报准）。"""
    match = re.search(r"^\s*:PM_REVISION:\s*(\S+)\s*$", block, re.MULTILINE)
    return match.group(1) if match else "1"


def find_idempotent_block(path: Path, key: str) -> dict | None:
    """在文件里找哪条实体的 LOGBOOK 已经用过这个 idempotency key。"""
    path = Path(path)
    if not path.is_file():
        return None
    text = read_text(path)
    lines = text.split("\n")
    pattern = re.compile(r"(?<!\S)key=" + re.escape(key) + r"(?=\s|$)", re.MULTILINE)
    for block in iter_entity_blocks(text):
        region = "\n".join(lines[block["start"] : block["end"]])
        if pattern.search(region):
            return block
    return None


def build_entity_block(
    *,
    entity_id: str,
    kind: str,
    status: str,
    headline: str,
    properties: dict[str, str] | None = None,
    body_lines: list[str] | None = None,
    indent_body: bool = True,
    actor: str = "human",
    at: datetime | None = None,
    idempotency_key: str | None = None,
) -> tuple[str, str]:
    """构造一个新实体的 org 块与它的创建审计 id（纯函数，不落盘）。"""
    from pm.org import clean_value

    moment = at or datetime.now().astimezone()
    audit_id = new_audit_id(moment)
    props: dict[str, str] = {
        "ID": entity_id,
        "PM_KIND": kind,
        "PM_STATUS": status,
        **dict(properties or {}),
    }
    # 尊重调用方显式给的 revision（默认 1）。create_entity 不应该无条件覆盖明确传入的属性：
    # memory 的 verify 需要「正式副本的 revision 与候选一致」，否则后续 CAS 会对不上。
    props.setdefault("PM_REVISION", "1")
    try:
        revision = int(str(props["PM_REVISION"]).strip())
    except (TypeError, ValueError):
        raise EntityError(
            "INVALID_REVISION", f"PM_REVISION 必须是整数，收到 {props['PM_REVISION']!r}"
        )
    log = audit_line(
        at=moment, entity_id=entity_id, audit_id=audit_id, actor=actor,
        from_status="(created)", to_status=status, revision=revision, reason="",
        key=_norm_key(idempotency_key),
    )
    lines = [f"** {headline}", "   :PROPERTIES:"]
    for name, value in props.items():
        lines.append(f"   :{name}: {clean_value(str(value))}")
    lines.extend(["   :END:", "   :LOGBOOK:", log, "   :END:"])
    for line in body_lines or []:
        if line == "":
            lines.append("")
        elif indent_body:
            lines.append("   " + line)
        else:
            lines.append(line)
    return "\n".join(lines), audit_id


def create_entity(
    path: Path,
    *,
    entity_id: str,
    kind: str,
    status: str,
    headline: str,
    section: str,
    properties: dict[str, str] | None = None,
    body_lines: list[str] | None = None,
    indent_body: bool = True,
    actor: str = "human",
    now: datetime | None = None,
    dry_run: bool = False,
    idempotency_key: str | None = None,
) -> CreateResult:
    """向（可能不存在的）org 文件追加一个新实体。返回 CreateResult（可二元解包）。

    - 新实体自带 :ID:/:PM_KIND:/:PM_STATUS:/:PM_REVISION: 与一条创建审计；
    - `indent_body=True`（默认）正文行 +3 空格（inbox 现有行为，一字不变）；
      False 则原样写入 —— §5.2 的 `*** 验收标准` 缩进后会变成正文，任务域要用 False；
    - `dry_run=True` 只算插入位置与块内容（返回将用的行号/审计 id），不落盘；
    - `idempotency_key`：与 apply_change 同一套语义 —— 同一 key 重放**不重复创建**，
      返回首次的 line/auditEventId（created=False, idempotent=True）；key 换目标 → 码 2 拒绝；
      key 写进创建审计行（`key=…`）。默认 None 时行为一字不变。
    """
    path = Path(path)
    key = _norm_key(idempotency_key)
    if key:
        holder = find_idempotent_block(path, key)
        if holder is not None:
            holder_id = holder["props"].get("ID", "")
            if holder_id != entity_id:
                raise EntityError(
                    "IDEMPOTENCY_KEY_REUSED",
                    f"idempotency key {key} 已经用在 {holder_id} 上，不能换目标重复使用",
                )
            lines = read_text(path).split("\n")
            region = "\n".join(lines[holder["start"] : holder["end"]])
            held_audit, held_observed = audit_from_region(region, key)
            return CreateResult(
                line=holder["line"],
                audit_event_id=held_audit or "",
                entity_id=entity_id,
                path=path,
                created=False,
                idempotent=True,
                observed_at=held_observed,
                revision=_revision_of(holder["props"]),
            )

    block, audit_id = build_entity_block(
        entity_id=entity_id, kind=kind, status=status, headline=headline,
        properties=properties, body_lines=body_lines, indent_body=indent_body,
        actor=actor, at=now, idempotency_key=key,
    )
    revision = _revision_of({"PM_REVISION": _block_revision(block)})
    if dry_run:
        found, number = plan_entry(path, headline=section, block=block)
        return CreateResult(
            line=number, audit_event_id=audit_id, entity_id=entity_id,
            path=path, created=True, revision=revision, found_section=found,
        )
    _path, found, number = append_entry_tracked(path, headline=section, block=block)
    return CreateResult(
        line=number, audit_event_id=audit_id, entity_id=entity_id,
        path=path, created=True, revision=revision, found_section=found,
    )
