"""Org 文本原语。

不实现完整的 org 解析器 —— 只实现我们**写入**所需的子集，外加一个
极其保守的人工文件读取器（human.py）。对齐 alpha 方案 §4.3：
「编辑时保留不认识的内容，不能用简陋解析器重写整份复杂 Org 文档」。

因此本工具写入策略分两类：
- generated/**     ：整个文件由机器所有，每次整体重写（内容为数据纯函数 → 幂等）。
- 人工文件          ：**只在缺失时创建**，此后永不修改。
"""

from __future__ import annotations

import os
from pathlib import Path

GENERATED_BANNER = [
    "#+PM_GENERATED: t",
    "# do not edit by hand — 本文件由 pm 生成，手工修改会在下次 render 被覆盖。",
    "# 要改内容：改 overrides.org（人工摘要 / pin）或项目目录下的人工文件。",
]

#: org property 值里不能出现换行或裸竖线。
_FORBIDDEN = ("\n", "\r")


def org_timestamp(value) -> str:
    return value.strftime("[%Y-%m-%d %a %H:%M]")


def clean_value(value: str) -> str:
    for bad in _FORBIDDEN:
        value = value.replace(bad, " ")
    return " ".join(value.split())


def property_drawer(properties: dict[str, str], *, indent: str = "") -> list[str]:
    if not properties:
        return []
    lines = [f"{indent}:PROPERTIES:"]
    for key, value in properties.items():
        lines.append(f"{indent}:{key}: {clean_value(str(value))}")
    lines.append(f"{indent}:END:")
    return lines


def headline(
    level: int,
    title: str,
    *,
    todo: str | None = None,
    tags: tuple[str, ...] = (),
    properties: dict[str, str] | None = None,
    body: list[str] | None = None,
) -> list[str]:
    stars = "*" * level
    prefix = f"{todo} " if todo else ""
    tag_text = ("  :" + ":".join(tags) + ":") if tags else ""
    lines = [f"{stars} {prefix}{title}{tag_text}".rstrip()]
    # 属性抽屉必须紧贴标题（中间不能有空行），否则 org 不认
    lines.extend(property_drawer(properties or {}))
    for line in body or []:
        lines.append(line)
    return lines


def file_header(title: str, *, tags: tuple[str, ...] = (), extra: list[str] | None = None) -> list[str]:
    lines = [f"#+TITLE: {title}"]
    if tags:
        lines.append("#+FILETAGS: " + ":".join(("", *tags, "")))
    lines.extend(GENERATED_BANNER)
    lines.extend(extra or [])
    return lines


def detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def write_atomic(path: Path, text: str, *, newline: str = "\n", fsync: bool = False) -> None:
    """原子写：临时文件 + os.replace；fsync=True 时同时 fsync 文件与目录（命令写入用）。

    fsync 是设计 §7 的要求：Web/CLI 的状态变更必须先落盘再 rename，
    避免掉电后出现「rename 成功但内容没持久化」的半成品。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = text.replace("\r\n", "\n").replace("\n", newline)
    tmp = path.with_name(path.name + ".pm-tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            handle.write(payload)
            if fsync:
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(tmp, path)
        if fsync:
            _fsync_dir(path.parent)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _fsync_dir(directory: Path) -> None:
    """fsync 目录项，保证 rename 本身持久化；个别文件系统不支持时安静跳过。"""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def render_text(lines: list[str], *, trailing_newline: bool = True) -> str:
    text = "\n".join(lines)
    return text + "\n" if trailing_newline else text
