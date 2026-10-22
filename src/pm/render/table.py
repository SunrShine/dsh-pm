"""列宽感知的等宽表格渲染（正确处理全角字符）。"""

from __future__ import annotations

from dataclasses import dataclass

from pm.width import display_width, pad


@dataclass(frozen=True)
class Column:
    header: str
    align: str = "left"
    max_width: int | None = None
    min_width: int = 0


def render_table(columns: list[Column], rows: list[list[str]], *, indent: str = "") -> list[str]:
    """把 rows 渲染成对齐的文本行。最后一列通常用于弹性扩展。"""
    if not columns:
        return []
    widths = [max(c.min_width, display_width(c.header)) for c in columns]
    for row in rows:
        for index, cell in enumerate(row[: len(columns)]):
            widths[index] = max(widths[index], display_width(cell))
    for index, column in enumerate(columns):
        if column.max_width is not None:
            widths[index] = min(widths[index], column.max_width)

    lines: list[str] = []
    header_cells = [
        pad(column.header, widths[i], column.align) for i, column in enumerate(columns)
    ]
    lines.append(indent + "  ".join(header_cells).rstrip())
    lines.append(indent + "  ".join("-" * widths[i] for i in range(len(columns))))
    for row in rows:
        cells = []
        for index, column in enumerate(columns):
            value = row[index] if index < len(row) else ""
            if column.max_width is not None and display_width(value) > widths[index]:
                from pm.width import truncate

                value = truncate(value, widths[index])
            cells.append(pad(value, widths[index], column.align))
        lines.append(indent + "  ".join(cells).rstrip())
    return lines


def fit_widths(columns: list[Column], rows: list[list[str]], total_width: int, *, flexible: int) -> list[Column]:
    """按总宽度收缩指定列（通常是最后一列的说明文本）。"""
    natural = [max(display_width(c.header), max((display_width(r[i]) for r in rows if i < len(r)), default=0)) for i, c in enumerate(columns)]
    fixed = sum(w for i, w in enumerate(natural) if i != flexible)
    separators = 2 * (len(columns) - 1)
    budget = total_width - fixed - separators
    result = list(columns)
    column = result[flexible]
    result[flexible] = Column(
        header=column.header,
        align=column.align,
        max_width=max(column.min_width, min(column.max_width or budget, budget)),
        min_width=column.min_width,
    )
    return result
