"""往**人工文件**里追加条目。

设计约束（对齐 alpha 方案 §8 权威归属）：

- 人工文件由人所有。机器**只能追加**新条目，绝不能改写已有文本。
- 追加位置是确定的：插到指定一级标题所属小节的**末尾**，而不是文件末尾。
  文件末尾可能属于另一个小节 —— 插错地方会让 org 结构错乱。
- 每台机器写入的条目都带来源属性，方便人日后分辨哪些不是自己写的。
- 全程不做「解析整份 org 再重写」，只做行级插入，未知内容原样保留。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from pm.org import write_atomic

_HEADLINE = re.compile(r"^(\*+)\s+(.*)$")


def find_section(lines: list[str], headline: str) -> tuple[int, int] | None:
    """定位一级标题 headline 所属小节的 [start, end)。

    start 是标题行下标，end 是下一个一级标题（或文件末尾）的下标。
    """
    start = None
    for index, line in enumerate(lines):
        match = _HEADLINE.match(line)
        if not match:
            continue
        if len(match.group(1)) != 1:
            continue
        title = match.group(2)
        if "  :" in title:
            title = title[: title.rindex("  :")]
        if start is None:
            if title.strip() == headline:
                start = index
            continue
        return (start, index)
    if start is not None:
        return (start, len(lines))
    return None


def append_under_tracked(text: str, *, headline: str, block: str) -> tuple[str, bool, int]:
    """同 append_under，但额外返回插入块**首行的 0-based 下标**。

    写入位置只有这一处实现：append_under / append_entry 都走它，
    需要行号的调用方（如 capture 回填 line）也走它。
    """
    lines = text.split("\n")
    section = find_section(lines, headline)
    block_lines = block.rstrip("\n").split("\n")

    if section is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.append("")
        index = len(lines)  # 下面 extend 后，块首行就在这里
        lines.extend(block_lines)
        lines.append("")
        return "\n".join(lines), False, index

    _start, end = section
    insert_at = end
    while insert_at > 0 and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines[insert_at:insert_at] = [""] + block_lines + [""]
    return "\n".join(lines), True, insert_at + 1


def append_under(text: str, *, headline: str, block: str) -> tuple[str, bool]:
    """把 block 追加到一级标题 headline 的小节末尾。

    返回 (新文本, 是否找到了该小节)。找不到就追加到文件末尾 —— 仍然只追加。
    """
    updated, found, _index = append_under_tracked(text, headline=headline, block=block)
    return updated, found


def entry_block(
    body: str,
    *,
    title: str | None = None,
    todo: str | None = None,
    properties: dict[str, str] | None = None,
) -> str:
    """构造一个二级条目：标题 + 属性抽屉 + 正文。"""
    from pm.org import clean_value

    head = "** "
    if todo:
        head += todo + " "
    if title:
        head += clean_value(title)
    lines = [head.rstrip()]
    drawer = dict(properties or {})
    if drawer:
        lines.append("   :PROPERTIES:")
        for key, value in drawer.items():
            lines.append(f"   :{key}: {clean_value(str(value))}")
        lines.append("   :END:")
    for line in body.rstrip("\n").split("\n"):
        lines.append(("   " + line) if line.strip() else "")
    return "\n".join(lines)


def verbatim_entry_block(
    headline: str,
    *,
    properties: dict[str, str] | None = None,
    body_lines: list[str] | None = None,
) -> str:
    """构造一个**逐字节保真**的二级条目（capture v2 用）。

    与 entry_block 的区别：headline 不做空白折叠、正文行原样保留
    （只加 3 空格缩进，空行保持空串）。设计 §11「原始文本只保存一份」靠它：
    首行进 headline、余下行进 body，读回时可无损拼回。
    """
    from pm.org import clean_value

    lines = [headline]
    drawer = dict(properties or {})
    if drawer:
        lines.append("   :PROPERTIES:")
        for key, value in drawer.items():
            lines.append(f"   :{key}: {clean_value(str(value))}")
        lines.append("   :END:")
    for line in body_lines or []:
        lines.append(("   " + line) if line != "" else "")
    return "\n".join(lines)


def stamp(now: datetime | None = None) -> str:
    return (now or datetime.now().astimezone()).strftime("%Y-%m-%d %a %H:%M")


def _append_source(path: Path, headline: str) -> tuple[str, str]:
    """读追加目标的现状：返回 (归一化文本, 换行风格)。

    文件不存在时按「只有标题」预演（与 append_entry 的创建规则一致）。
    """
    if path.is_file():
        # 必须按原始字节判断换行：Path.read_text 默认会做通用换行转换，
        # 那样 CRLF 会被静默吃成 LF，写回去就把别人的文件改了行尾风格。
        try:
            raw = path.read_bytes()
        except OSError:
            raw = b""
        newline = "\r\n" if b"\r\n" in raw else "\n"
        return raw.decode("utf-8", "replace").replace("\r\n", "\n"), newline
    return f"* {headline}\n", "\n"


def plan_entry(path: Path, *, headline: str, block: str) -> tuple[bool, int]:
    """算出 append_entry 将会写入的位置，**绝不落盘**（capture --dry-run 用）。

    返回 (是否找到小节, 追加块首行的 1-based 行号)，与 append_entry_tracked 同源。
    """
    text, _newline = _append_source(Path(path), headline)
    _updated, found, index = append_under_tracked(text, headline=headline, block=block)
    return found, index + 1


def append_entry_tracked(path: Path, *, headline: str, block: str) -> tuple[Path, bool, int]:
    """同 append_entry，但额外返回追加块首行的 **1-based 行号**。"""
    path = Path(path)
    text, newline = _append_source(path, headline)
    updated, found, index = append_under_tracked(text, headline=headline, block=block)
    write_atomic(path, updated, newline=newline)
    return path, found, index + 1


def append_entry(path: Path, *, headline: str, block: str) -> tuple[Path, bool]:
    """把 block 追加进人工文件。文件不存在则创建（只有标题）。"""
    written, found, _line = append_entry_tracked(path, headline=headline, block=block)
    return written, found
