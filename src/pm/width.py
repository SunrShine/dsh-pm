"""终端显示宽度工具：正确处理中日韩全角字符。

Python 的 len() 与终端列宽不一致（"中文" 的 len 是 2，显示宽度是 4），
表格对齐必须用显示宽度计算，否则全角内容一多整个表就歪。
"""

from __future__ import annotations

import re
import unicodedata

_WIDE = frozenset({"W", "F"})
_ELLIPSIS = "…"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """去掉 ANSI SGR 颜色序列。"""
    return _ANSI.sub("", text)


def char_width(ch: str) -> int:
    """单个字符的显示宽度（组合字符记 0）。"""
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in _WIDE else 1


def display_width(text: str) -> int:
    """字符串在等宽终端中占用的列数（忽略 ANSI 颜色序列）。"""
    return sum(char_width(ch) for ch in strip_ansi(text))


def truncate(text: str, limit: int, ellipsis: str = _ELLIPSIS) -> str:
    """按显示宽度截断，超长时追加省略号（省略号计入 limit）。"""
    if limit <= 0:
        return ""
    if display_width(text) <= limit:
        return text
    ellipsis_width = display_width(ellipsis)
    budget = max(0, limit - ellipsis_width)
    used = 0
    out: list[str] = []
    for ch in text:
        width = char_width(ch)
        if used + width > budget:
            break
        out.append(ch)
        used += width
    return "".join(out) + ellipsis


def pad(text: str, width: int, align: str = "left") -> str:
    """按显示宽度补齐到 width 列。"""
    gap = max(0, width - display_width(text))
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def ellipsize_lines(text: str, limit: int) -> str:
    """折叠所有空白为单行空格，再按宽度截断。"""
    return truncate(" ".join(text.split()), limit)
