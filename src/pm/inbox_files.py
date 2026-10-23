"""inbox 多文件布局：命名 / 发现 / 聚合读取 / 生成视图 / 迁移。

用户 2026-10-22 设计（方案 A 的细化版）：
- 真源按**来源 + 周期轮转**分文件，不做 archive 搬运：
    inbox-human-<period>.org   人工写入（默认 weekly：2026-W43）
    inbox-ai-<period>.org      AI/MCP 写入（默认 monthly：2026-10）
- `inbox.org` 是**自动生成的汇总视图**（只读，勿手改）：顶部说明 + 当前人工/AI 文件内联 +
  历史文件链接；生成逻辑在 `render()`。
- 旧库（单文件 `inbox.org` 里混着人/AI/已处理条目）由 `migrate()` 拆分；迁移后
  `inbox.org` 变成生成视图（首行带 GENERATED_MARKER，聚合读取会跳过它）。

本模块只做**文件层**：解析复用 pm.inbox（单一解析器），写入复用 pm.entities（CAS/审计）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pm import inbox

GENERATED_MARKER = "# 由 pm 自动生成（inbox 汇总视图）"
HUMAN_PREFIX = "inbox-human"
AI_PREFIX = "inbox-ai"

#: 人工/AI 默认轮转粒度（用户裁定：human weekly / ai monthly）。
DEFAULT_HUMAN_MODE = "single"
DEFAULT_AI_MODE = "single"

HUMAN_MODES = ("weekly", "monthly", "quarterly", "yearly", "single", "per-entry")
AI_MODES = ("monthly", "quarterly", "yearly", "single")

TODO_LINE = "#+TODO: INBOX(i) TODO(t) NEXT(n) DOING(s) WAITING(w@) BLOCKED(b@) REVIEW(r) | DONE(d!) CANCELLED(c@)"


@dataclass(frozen=True)
class InboxModes:
    human: str = DEFAULT_HUMAN_MODE
    ai: str = DEFAULT_AI_MODE

    def as_dict(self) -> dict:
        return {"human": self.human, "ai": self.ai}


DEFAULT_MODES = InboxModes()


def modes_of(modes) -> InboxModes:
    """接受 None / InboxModes / dict / Config.inbox 之类的宽松入参。"""
    if modes is None:
        return DEFAULT_MODES
    if isinstance(modes, InboxModes):
        return modes
    if hasattr(modes, "human_mode"):  # pm.config.InboxConfig
        return InboxModes(human=str(getattr(modes, "human_mode")), ai=str(getattr(modes, "ai_mode")))
    if isinstance(modes, dict):
        return InboxModes(
            human=str(modes.get("human") or modes.get("human_mode") or DEFAULT_HUMAN_MODE),
            ai=str(modes.get("ai") or modes.get("ai_mode") or DEFAULT_AI_MODE),
        )
    return DEFAULT_MODES


def period_suffix(mode: str, now: datetime) -> str:
    """按粒度算周期后缀；single 返回空串；per-entry 用秒级时间戳。"""
    mode = (mode or "").strip().lower()
    if mode == "single":
        return ""
    if mode == "per-entry":
        return now.strftime("%Y%m%d-%H%M%S")
    if mode == "weekly":
        iso = now.isocalendar()
        return "%04d-W%02d" % (iso.year, iso.week)
    if mode == "monthly":
        return now.strftime("%Y-%m")
    if mode == "quarterly":
        return "%04d-Q%d" % (now.year, (now.month - 1) // 3 + 1)
    if mode == "yearly":
        return now.strftime("%Y")
    return ""


def _path_for(prefix: str, mode: str, library: Path, now: datetime) -> Path:
    suffix = period_suffix(mode, now)
    name = prefix + (("-" + suffix) if suffix else "") + ".org"
    return Path(library) / name


def human_path(library: Path, now: datetime | None = None, modes=None) -> Path:
    now = now or datetime.now().astimezone()
    mode = modes_of(modes).human
    if mode == "single":  # 兼容旧单文件行为：人工写 inbox.org
        return Path(library) / inbox.INBOX_RELATIVE
    return _path_for(HUMAN_PREFIX, mode, Path(library), now)


def ai_path(library: Path, now: datetime | None = None, modes=None) -> Path:
    now = now or datetime.now().astimezone()
    mode = modes_of(modes).ai
    if mode == "single":  # 兼容旧单文件行为：AI 也写 inbox.org
        return Path(library) / inbox.INBOX_RELATIVE
    return _path_for(AI_PREFIX, mode, Path(library), now)


def path_for_origin(origin: str, library: Path, now: datetime | None = None, modes=None) -> Path:
    return ai_path(library, now, modes) if origin == "ai" else human_path(library, now, modes)


def origin_of(path: Path) -> str:
    name = Path(path).name
    if name.startswith(AI_PREFIX):
        return "ai"
    return "human"


def is_generated(path: Path) -> bool:
    """inbox.org 是否是生成视图（首 5 行里带 GENERATED_MARKER）。"""
    try:
        head = "\n".join(Path(path).read_text(encoding="utf-8").splitlines()[:5])
    except (OSError, UnicodeDecodeError):
        return False
    return GENERATED_MARKER in head


def _period_sort_key(name: str) -> str:
    return name


def discover(library: Path) -> list[dict]:
    """列出所有 inbox 真源文件（不含生成视图 inbox.org）。

    返回 [{path, origin, name, legacy}]，顺序：人工文件（新→旧）、AI 文件（新→旧）；
    旧单文件 inbox.org（非生成视图）作为 legacy 人工文件排在最后。
    """
    library = Path(library)
    found: list[dict] = []

    def collect(prefix: str, origin: str) -> list[dict]:
        items = []
        for path in library.glob(prefix + "-*.org"):
            if not path.is_file():
                continue
            items.append({"path": path, "origin": origin, "name": path.name, "legacy": False})
        items.sort(key=lambda row: row["name"], reverse=True)
        return items

    found.extend(collect(HUMAN_PREFIX, "human"))
    found.extend(collect(AI_PREFIX, "ai"))

    legacy = library / inbox.INBOX_RELATIVE
    if legacy.is_file() and not is_generated(legacy):
        try:
            legacy_text = legacy.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            legacy_text = ""
        # 空骨架（只有 #+TITLE/* Inbox/模板注释）不算旧数据，不提示迁移
        if inbox.parse_entries(legacy_text):
            found.append({"path": legacy, "origin": "human", "name": legacy.name, "legacy": True})
    return found


def read_entries(library: Path, *, with_annotations: bool = False) -> dict:
    """聚合读取所有 inbox 真源文件：条目带 origin/file，结构兼容旧 read_inbox()。"""
    library = Path(library)
    files = discover(library)
    entries: list[dict] = []
    file_rows: list[dict] = []
    for row in files:
        try:
            text = Path(row["path"]).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        parsed = inbox.parse_entries(text, with_annotations=with_annotations)
        for entry in parsed:
            entry["origin"] = row["origin"]
            entry["file"] = row["name"]
        entries.extend(parsed)
        file_rows.append(
            {"path": row["name"], "origin": row["origin"], "count": len(parsed), "legacy": row["legacy"]}
        )
    return {
        "path": inbox.INBOX_RELATIVE,
        "count": len(entries),
        "files": file_rows,
        "counts": {
            "human": sum(row["count"] for row in file_rows if row["origin"] == "human"),
            "ai": sum(row["count"] for row in file_rows if row["origin"] == "ai"),
        },
        "entries": entries,
    }


def header_text(origin: str) -> str:
    """新文件的文件头。人工文件带**手写模板**（用户要求）；AI 文件明确「勿手改」。"""
    if origin == "ai":
        return "\n".join(
            [
                "#+TITLE: Inbox (AI)",
                TODO_LINE,
                "",
                "* Inbox",
                "  本文件由 pm / MCP 自动追加（AI 产生的快速笔记）；不要手改条目属性。",
                "",
            ]
        )
    return "\n".join(
        [
            "#+TITLE: Inbox (human)",
            TODO_LINE,
            "",
            "* Inbox",
            "  人工快速笔记：随笔可写在这里；要纳入 pm 管理，按下述模板写一个条目。",
            "",
            "# ==== 手动条目模板（复制下面这段，把内容改掉；:ID: 必须唯一）====",
            "# ** INBOX 一句话标题",
            "#    :PROPERTIES:",
            "#    :ID: inbox-manual-<YYYYMMDD-HHMMSS>",
            "#    :PM_KIND: inbox",
            "#    :PM_STATUS: CAPTURED",
            "#    :PM_SOURCE: manual",
            "#    :PM_ADDED_BY: human",
            "#    :PM_CAPTURED_AT: 2026-10-22T19:30:00+08:00",
            "#    :END:",
            "#    正文（Org 语法可用：- 列表 / - [ ] 待办 / #+BEGIN_SRC …）",
            "",
        ]
    )


def ensure_file(path: Path, origin: str) -> bool:
    """文件不存在时用 header_text 创建；返回是否新建。"""
    path = Path(path)
    if path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header_text(origin), encoding="utf-8")
    return True


def _block_raw(text: str) -> list[tuple[str, dict]]:
    """返回 [(raw_block_text, block)]：raw 从 headline 到 end（保留属性/LOGBOOK/正文）。"""
    lines = text.splitlines()
    out = []
    for block in inbox.iter_entry_blocks(text):
        raw = "\n".join(lines[block["start"] : block["end"]])
        out.append((raw, block))
    return out


def _append_blocks(path: Path, blocks: list[str], origin: str) -> None:
    ensure_file(path, origin)
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    text += "\n" + "\n\n".join(blocks) + "\n"
    path.write_text(text, encoding="utf-8")


def _parse_captured_at(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed


def is_ai_block(block: dict) -> bool:
    """AI/MCP 产生的条目判定（用户裁定：两者取或）。"""
    props = block.get("props") or {}
    source = str(props.get("PM_SOURCE") or "").strip().lower()
    added_by = str(props.get("PM_ADDED_BY") or "").strip().lower()
    if source == "mcp":
        return True
    return added_by not in ("", "cli", "human")


def render_text(library: Path, modes=None) -> str:
    """生成 inbox.org 汇总视图文本：当前人工/AI 文件内联，历史文件只列链接。"""
    modes = modes_of(modes)
    library = Path(library)
    now = datetime.now().astimezone()
    if modes.human == "single":
        return "#+TITLE: Inbox\n" + TODO_LINE + "\n" + GENERATED_MARKER + "（当前是单文件模式，无需汇总视图）\n"
    cur_human = human_path(library, now, modes)
    cur_ai = ai_path(library, now, modes)
    target = library / inbox.INBOX_RELATIVE
    files = [row for row in discover(library) if Path(row["path"]) != target]
    human_files = [row for row in files if row["origin"] == "human"]
    ai_files = [row for row in files if row["origin"] == "ai"]

    parts: list[str] = [
        "#+TITLE: Inbox",
        TODO_LINE,
        GENERATED_MARKER + "（只读：真源是 inbox-human-*.org / inbox-ai-*.org；手改会被下一次 render 覆盖）",
        "",
        "* Inbox",
        "  本文件只是汇总视图。人工记录请打开 %s；AI 记录在 %s。" % (cur_human.name, cur_ai.name),
        "  刷新：pm inbox render",
        "",
        "** 当前人工收件箱（%s）" % cur_human.name,
    ]
    def inline_blocks(path: Path) -> list[str]:
        if not path.is_file():
            return []
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        return [raw for raw, _block in _block_raw(text)]

    human_blocks = inline_blocks(cur_human)
    if human_blocks:
        parts.extend(["", *human_blocks])
    else:
        parts.extend(["", "  （本周还没有人工记录）"])
    parts.extend(["", "** 当前 AI 收件箱（%s）" % cur_ai.name])
    ai_blocks = inline_blocks(cur_ai)
    if ai_blocks:
        parts.extend(["", *ai_blocks])
    else:
        parts.extend(["", "  （本月还没有 AI 记录）"])
    parts.extend(["", "** 历史与归档（只列链接）"])
    for row in human_files + ai_files:
        if row["path"] in (cur_human, cur_ai):
            continue
        parts.append("  - [[file:%s][%s]]（%s）" % (row["name"], row["name"], row["origin"]))
    if not any(row["path"] not in (cur_human, cur_ai) for row in human_files + ai_files):
        parts.append("  （暂无历史文件）")
    return "\n".join(parts) + "\n"


def render(library: Path, modes=None, *, check: bool = False) -> dict:
    """生成/校验 inbox.org 汇总视图。check=True 时不写，返回是否一致。"""
    library = Path(library)
    target = library / inbox.INBOX_RELATIVE
    if modes_of(modes).human == "single":
        return {"ok": True, "path": inbox.INBOX_RELATIVE, "changed": False, "written": False,
                "skipped": "单文件模式（human_mode=single）不需要汇总视图"}
    wanted = render_text(library, modes)
    current = ""
    if target.is_file():
        try:
            current = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            current = ""
    same = current == wanted
    if not check and not same:
        target.write_text(wanted, encoding="utf-8")
    return {"ok": True, "path": inbox.INBOX_RELATIVE, "changed": not same, "written": (not check and not same)}


def migrate(library: Path, modes=None, *, dry_run: bool = True, now: datetime | None = None) -> dict:
    """把旧单文件 inbox.org（混装）拆成来源/周期文件，然后把 inbox.org 重写为生成视图。

    规则（用户 2026-10-22）：
    - 有 :ID: 的条目按来源（AI/人）+ PM_CAPTURED_AT 周期归档到对应文件；
    - 无 :ID: 的 legacy 块（bullet/旧 headline）留在人工文件；
    - 原文件先备份为 inbox.org.bak.<YYYYmmdd-HHMMSS>（dry-run 不写）。
    """
    modes = modes_of(modes)
    library = Path(library)
    now = now or datetime.now().astimezone()
    legacy = library / inbox.INBOX_RELATIVE
    if not legacy.is_file():
        return {"ok": True, "dry_run": dry_run, "reason": "没有 inbox.org（无需迁移）", "moves": []}
    text = legacy.read_text(encoding="utf-8")
    if is_generated(legacy):
        return {"ok": True, "dry_run": dry_run, "reason": "inbox.org 已是生成视图（无需迁移）", "moves": []}

    moves: list[dict] = []
    grouped: dict[Path, list[str]] = {}
    legacy_blocks: list[str] = []
    for raw, block in _block_raw(text):
        if block["kind"] != "headline" or not block["props"].get("ID"):
            legacy_blocks.append(raw)
            continue
        origin = "ai" if is_ai_block(block) else "human"
        captured = _parse_captured_at(block["props"].get("PM_CAPTURED_AT") or "")
        target = path_for_origin(origin, library, captured or now, modes)
        grouped.setdefault(target, []).append(raw)
        moves.append(
            {
                "id": block["props"].get("ID"),
                "origin": origin,
                "status": block["props"].get("PM_STATUS") or inbox.DEFAULT_STATUS,
                "target": target.name,
            }
        )
    if legacy_blocks:
        human_target = human_path(library, now, modes)
        grouped.setdefault(human_target, []).extend(legacy_blocks)
        for raw in legacy_blocks:
            moves.append({"id": None, "origin": "human", "status": "LEGACY_UNTRACKED", "target": human_target.name})

    report = {
        "ok": True,
        "dry_run": dry_run,
        "path": inbox.INBOX_RELATIVE,
        "moves": moves,
        "targets": [
            {"path": path.name, "count": len(blocks)}
            for path, blocks in sorted(grouped.items(), key=lambda item: item[0].name)
        ],
    }
    if dry_run:
        return report

    stamp = now.strftime("%Y%m%d-%H%M%S")
    backup = legacy.with_name(legacy.name + ".bak." + stamp)
    backup.write_text(text, encoding="utf-8")
    for path, blocks in grouped.items():
        _append_blocks(path, blocks, origin_of(path))
    render(library, modes)
    report["backup"] = backup.name
    report["rendered"] = inbox.INBOX_RELATIVE
    return report
