"""读取 work-memory 的 inbox.org（「快速笔记」）。

严格只读：只读不写，绝不改人工文件（对齐 humanwrite 的权威归属约定）。

解析复用现有逻辑，不新造 org 解析器：
- humanwrite.find_section  定位「* Inbox」小节范围（标题行 → 下一个一级标题）
- summaries._split_headline 拆 legacy「**」标题的层级与尾部标签

条目有三种来源（真实库里并存）：
1. capture v2：「** INBOX <首行>」+ :PROPERTIES:（:ID: inbox-… / PM_STATUS / …）+ 正文；
   文本可**无损拼回**：首行在标题、余下在正文，单行则正文为空。
2. 旧 capture：「** <标题>」（无 :ID:）→ status = LEGACY_UNTRACKED、id = null；
3. 人手工写的顶层列表项「- 」/「+ 」→ 同样 LEGACY_UNTRACKED。

设计 §9：**不按行号建立长期关联** —— 行号只是展示信息，身份看 :ID:。
"""

from __future__ import annotations

import re
from pathlib import Path

from pm.humanwrite import find_section
from pm.summaries import _split_headline

INBOX_RELATIVE = "inbox.org"

#: Inbox 小节的标题名（capture 用它定位追加位置）。
INBOX_HEADLINE = "Inbox"

#: 有 :ID: 但没写 PM_STATUS 时的默认状态（设计 §5.1）。
DEFAULT_STATUS = "CAPTURED"
#: 旧条目（无 :ID:）的标记（设计 §9）。
LEGACY_STATUS = "LEGACY_UNTRACKED"

#: capture v2 的标题前缀。
INBOX_PREFIX = "INBOX"

_BULLET = re.compile(r"^(?P<indent>[ \t]*)(?P<mark>[-+])(?P<gap>\s+)(?P<text>.*)$")
#: 只有**第 0 列**的星号才是 headline；缩进过的星号属于正文（org 敏感字符）。
_AT_COL0 = re.compile(r"^(?P<stars>\*+)(?:\s+(?P<title>.*))?$")


#: 补充 / 修订块的首行标记（写入端在 inbox_ops，读回时靠它把「原文」与「追加块」分开）。
_BLOCK_MARK = re.compile(
    r"^(?P<kind>补充|修订) \[(?P<at>[^\]]+)\] actor=(?P<actor>\S+) rev=(?P<rev>\d+)$"
)


def headline_text(raw: str) -> str:
    """取 level-2 headline 的可读文本：v2 的「INBOX 原文」原样返回，否则退回标题。"""
    first = _v2_headline_text(raw)
    if first is not None:
        return first
    return _collapse(_split_headline(raw)[1])


def split_body_blocks(body: list[str]) -> tuple[list[str], list[dict]]:
    """把条目正文拆成 (捕获时的原始正文, 追加块列表)。

    追加块：以「补充 [时间] actor=… rev=…」/「修订 [时间] actor=… rev=…」开头的一段。
    块之前的正文就是原文（契约 §0.1：原文只读、只追加不覆盖）。
    """
    original: list[str] = []
    blocks: list[dict] = []
    current: dict | None = None
    for line in body:
        match = _BLOCK_MARK.match(line.strip())
        if match:
            current = {
                "type": "revision" if match.group("kind") == "修订" else "annotation",
                "at": match.group("at"),
                "actor": match.group("actor"),
                "revision": int(match.group("rev")),
                "lines": [],
            }
            blocks.append(current)
            continue
        if current is None:
            original.append(line)
        else:
            current["lines"].append(line)
    for block in blocks:
        lines = block.pop("lines")
        if block["type"] == "revision":
            reason = old_text = new_text = ""
            rest: list[str] = []
            for line in lines:
                if line.startswith("原因："):
                    reason = line[len("原因：") :]
                elif line.startswith("旧值："):
                    old_text = line[len("旧值：") :]
                elif line.startswith("新值："):
                    new_text = line[len("新值：") :]
                else:
                    rest.append(line)
            block.update({"reason": reason, "oldText": old_text, "newText": new_text, "rest": rest})
        else:
            block["text"] = "\n".join(lines)
    while original and not original[-1].strip():
        original.pop()
    return original, blocks


#: org 风格的布尔真值（与 tasks.py 的 PM_AI 判定一致）
_TRUTHY = ("t", "true", "yes", "y", "1")


def is_truthy(value) -> bool:
    """:PM_PIN: 的值 → bool；缺属性 / 不认识的写法一律 False（**永远不是 null**）。"""
    return str(value or "").strip().lower() in _TRUTHY


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _col0_level(raw: str) -> int:
    match = _AT_COL0.match(raw)
    return len(match.group("stars")) if match else 0


def _v2_headline_text(raw: str) -> str | None:
    """从「** INBOX <首行>」里**逐字节**取回首行；不是该形式则返回 None。"""
    match = _AT_COL0.match(raw)
    if match is None or len(match.group("stars")) != 2:
        return None
    content = match.group("title")
    if content is None:
        return None
    if content == INBOX_PREFIX:
        return ""
    if content.startswith(INBOX_PREFIX + " "):
        return content[len(INBOX_PREFIX) + 1 :]
    return None


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
    """读 level-2 标题紧贴的抽屉们（P2a-后端 起还有 :LOGBOOK:）。

    返回 (属性, :PROPERTIES: 的 [start,end) 或 None, 正文起始下标)。
    :LOGBOOK: 里的审计行会被整段跳过，绝不能混进正文（否则文本不再无损）。
    """
    props: dict[str, str] = {}
    property_span: tuple[int, int] | None = None
    cursor = index + 1

    # 1) 显式 :PROPERTIES: 抽屉
    if cursor < end and lines[cursor].strip() == ":PROPERTIES:":
        start = cursor
        cursor += 1
        while cursor < end and lines[cursor].strip() != ":END:":
            parsed = _property_line(lines[cursor])
            if parsed is not None:
                props[parsed[0]] = parsed[1]
            cursor += 1
        if cursor < end:
            cursor += 1  # 吃掉 :END:
        property_span = (start, cursor)
    # 2) 裸属性块（老数据 / 手写，没有 :PROPERTIES: 标记）—— 保持旧解析器的宽容
    elif cursor < end and _property_line(lines[cursor]) is not None:
        start = cursor
        while cursor < end:
            parsed = _property_line(lines[cursor])
            if parsed is None:
                break
            props[parsed[0]] = parsed[1]
            cursor += 1
        if cursor < end and lines[cursor].strip() == ":END:":
            cursor += 1
        property_span = (start, cursor)

    # 3) :LOGBOOK: 审计抽屉整段跳过，绝不能混进正文
    if cursor < end and lines[cursor].strip() == ":LOGBOOK:":
        cursor += 1
        while cursor < end and lines[cursor].strip() != ":END:":
            cursor += 1
        if cursor < end:
            cursor += 1
    return props, property_span, cursor


def _body_v2(lines: list[str], cursor: int, end: int) -> tuple[list[str], int]:
    """capture v2 的正文：写入端每行加 3 空格缩进（空行写空串）。

    因此遇到「非空且未缩进」的行就是条目结束 —— 这样紧跟其后的
    人工列表项不会被吞进上一条 v2 记录的正文里。
    """
    body: list[str] = []
    while cursor < end:
        line = lines[cursor]
        if not line.strip():
            # 空行可能是正文里的空行，也可能是条目分隔：看后面第一个非空行
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


def _body_legacy(lines: list[str], cursor: int, end: int) -> tuple[list[str], int]:
    """旧条目 / 人工子树的正文：读到下一个第 0 列 headline 为止（保持旧行为）。"""
    body: list[str] = []
    while cursor < end and not _col0_level(lines[cursor]):
        body.append(lines[cursor])
        cursor += 1
    while body and not body[-1].strip():
        body.pop()
    return [line[3:] if line.startswith("   ") else line for line in body], cursor


def _first_meaningful(body_lines: list[str]) -> str:
    for line in body_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(":") or stripped.startswith("#"):
            continue
        return _collapse(stripped)
    return ""


def iter_entry_blocks(text: str) -> list[dict]:
    """列出 inbox 小节里的条目块（按文件顺序，含 legacy 列表项）。

    每块：
      line         headline / 列表项所在 1-based 行号
      kind         "headline" | "bullet"
      raw          headline 原文（bullet 为空）
      props        :PROPERTIES: 里的属性
      body         正文行（已去 3 空格缩进）
      start/end    splitlines 后的 0-based 闭开区间
      drawer       :PROPERTIES: 的 [start, end) 或 None
      body_start   正文起始下标（抽屉之后）
      text         bullet 的文本（仅 bullet）
    """
    lines = text.splitlines()
    section = find_section(lines, INBOX_HEADLINE)
    region_start, region_end = section if section is not None else (0, len(lines))

    blocks: list[dict] = []
    bullets: list[tuple[int, int, str]] = []  # (缩进, 下标, 文本)
    index = region_start
    while index < region_end:
        raw = lines[index]
        level = _col0_level(raw)
        if level == 2:
            props, drawer, cursor = _read_drawers(lines, index, region_end)
            if props.get("ID"):
                body, next_index = _body_v2(lines, cursor, region_end)
            else:
                body, next_index = _body_legacy(lines, cursor, region_end)
            blocks.append(
                {
                    "line": index + 1,
                    "kind": "headline",
                    "raw": raw,
                    "props": props,
                    "body": body,
                    "start": index,
                    "end": next_index,
                    "drawer": drawer,
                    "body_start": cursor,
                }
            )
            index = next_index
            continue
        if level:
            index += 1
            continue
        match = _BULLET.match(raw)
        if match:
            bullet_text = _collapse(match.group("text"))
            if bullet_text:
                bullets.append((len(match.group("indent").expandtabs(4)), index, bullet_text))
        index += 1

    # 只取最小缩进层级的列表项：更深的缩进是上一条的子项
    if bullets:
        baseline = min(indent for indent, _index, _text in bullets)
        for indent, at, bullet_text in bullets:
            if indent == baseline:
                blocks.append(
                    {
                        "line": at + 1,
                        "kind": "bullet",
                        "raw": "",
                        "props": {},
                        "body": [],
                        "start": at,
                        "end": at + 1,
                        "drawer": None,
                        "body_start": at + 1,
                        "text": bullet_text,
                    }
                )
    blocks.sort(key=lambda block: block["line"])
    return blocks


def parse_entries(text: str, *, with_annotations: bool = False) -> list[dict]:
    """把 inbox.org 解析成条目列表（1-based 行号，按文件顺序）。

    - text 是**可读文本**：v2 条目无损拼回原文（多行含换行），legacy 条目取标题或正文首行；
    - id  是 :ID: 属性；没有则 null（设计 §9：不按行号建立长期关联）；
    - status 有 :ID: 时取 PM_STATUS（默认 CAPTURED），无 :ID: 一律 LEGACY_UNTRACKED；
    - capturedAt / source / projectHint 分别取 :PM_CAPTURED_AT: / :PM_SOURCE: / :PM_PROJECT_HINT:
      （原样 ISO8601，不转格式）；旧条目没有这些属性 → null；
    - annotationCount / revisionCount / lastAnnotationText：同一趟解析顺带数出来；
      **旧条目一律 null**（0 与「不知道」必须能区分）；
    - pinned：**:PM_PIN: 是否为真**，**永远是 bool**（缺属性 = false，旧条目也是 false）——
      与上面三个计数不同：置顶只有「是/否」两种已知状态，不存在「不知道」；
    - with_annotations=True 时额外带 annotations[{at,actor,revision,text}]（补充块全文，按文件顺序）——
      只有 pm inbox list 要（卡片直接渲染）；ui-cards 走默认 False，保持投影精简。
    """
    entries: list[dict] = []
    for block in iter_entry_blocks(text):
        if block["kind"] == "bullet":
            row = {
                "text": block["text"],
                "line": block["line"],
                "id": None,
                "status": LEGACY_STATUS,
                "capturedAt": None,
                "source": None,
                "projectHint": None,
                "annotationCount": None,
                "revisionCount": None,
                "lastAnnotationText": None,
                "pinned": False,
            }
            if with_annotations:
                row["annotations"] = []
            entries.append(row)
            continue
        props = block["props"]
        inbox_id = props.get("ID") or None
        if inbox_id:
            status = props.get("PM_STATUS") or DEFAULT_STATUS
            # 契约 §0：追加式补充写在正文区，**原文不动**；这里把原文与追加块分开，
            # 所以 entries[].text 永远是捕获时的原文，补充/修订走 pm inbox history。
            body, appended = split_body_blocks(block["body"])
            annotations = [item for item in appended if item["type"] == "annotation"]
            annotation_count = len(annotations)
            revision_count = sum(1 for item in appended if item["type"] == "revision")
            last_annotation = annotations[-1].get("text") if annotations else None
            if "PM_TITLE" in props:
                entry_text = "\n".join(body)  # 显式标题：正文即全文
            else:
                first_line = _v2_headline_text(block["raw"])
                if first_line is None:
                    first_line = _collapse(_split_headline(block["raw"])[1])
                entry_text = first_line + (("\n" + "\n".join(body)) if body else "")
        else:
            status = LEGACY_STATUS
            entry_text = _collapse(_split_headline(block["raw"])[1]) or _first_meaningful(block["body"])
            annotation_count = revision_count = last_annotation = None
            annotations = []
        if not entry_text:
            continue
        row = {
            "text": entry_text,
            "line": block["line"],
            "id": inbox_id,
            "status": status,
            "capturedAt": props.get("PM_CAPTURED_AT") or None,
            "source": props.get("PM_SOURCE") or None,
            "projectHint": props.get("PM_PROJECT_HINT") or None,
            "annotationCount": annotation_count,
            "revisionCount": revision_count,
            "lastAnnotationText": last_annotation,
            "pinned": is_truthy(props.get("PM_PIN")),
        }
        if with_annotations:
            row["annotations"] = [
                {
                    "at": item["at"],
                    "actor": item["actor"],
                    "revision": item["revision"],
                    "text": item.get("text", ""),
                }
                for item in annotations
            ]
        entries.append(row)
    return entries


def read_inbox(library: Path | None, modes=None) -> dict | None:
    """聚合读取多文件 inbox（inbox-human-* / inbox-ai-* / 旧 inbox.org）。

    无库、无任何文件、解码失败 → None（调用方据此输出 inbox: null，不得抛错）。
    返回结构兼容旧调用方：{path, count, entries}，另带 files / counts；
    每条 entry 额外带 origin（human/ai）与 file（相对文件名）。
    """
    if library is None:
        return None
    from pm import inbox_files  # 延迟导入：inbox_files 复用本模块解析器，避免循环
    root = Path(library)
    try:
        files = inbox_files.discover(root)
    except OSError:
        return None
    if not files:
        # 兼容旧契约：文件存在但为空 → 空 payload（不是 null）；坏编码 → null
        legacy = root / INBOX_RELATIVE
        if legacy.is_file():
            try:
                legacy.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return None
            return {"path": INBOX_RELATIVE, "count": 0, "files": [],
                    "counts": {"human": 0, "ai": 0}, "entries": []}
        return None
    return inbox_files.read_entries(root)
