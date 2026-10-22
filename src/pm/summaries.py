"""摘要的存储与解析。

三类摘要，权威性不同（对齐 alpha 方案 §8 权威归属）：

  人工摘要  overrides.org      —— 人写；机器**只读**，优先级最高
  AI 摘要   ai-summaries.org   —— pm summary set 写；带来源与时间；不覆盖人工摘要
  未生成    —                  —— 显示占位符，不拿 DSH 自动标题冒充摘要

解析策略：**全文件扫描**，认任何带 PM_SESSION 属性的二级标题。
刻意不限定小节名 —— 人往往是往文件末尾追加，限定小节会让追加静默失效。
其余内容一律忽略，因此人在同一文件里写复杂 org 内容也不会被误读。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pm import __version__
from pm.org import file_header, render_text, write_atomic

HUMAN = "human"
AI = "ai"
NOT_GENERATED = "not_generated"

HUMAN_FILE = "overrides.org"
AI_FILE = "ai-summaries.org"

#: 写入 ai-summaries.org 时使用的小节名
AI_SECTION = "AI 摘要"


@dataclass(frozen=True)
class SummaryEntry:
    identity_key: str
    text: str
    source: str
    generated_by: str = ""
    generated_at: str = ""


def _split_headline(line: str) -> tuple[int, str]:
    stripped = line.lstrip()
    if not stripped.startswith("*"):
        return 0, ""
    level = len(stripped) - len(stripped.lstrip("*"))
    title = stripped[level:].strip()
    if "  :" in title:
        title = title[: title.rindex("  :")].rstrip()
    return level, title


def parse_summary_blocks(text: str, *, source: str) -> dict[str, SummaryEntry]:
    """扫描全文，收集所有带 PM_SESSION 属性的二级标题块。"""
    found: dict[str, SummaryEntry] = {}
    props: dict[str, str] | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal props, body
        if props is not None:
            session = props.get("PM_SESSION", "")
            if session:
                instance = props.get("PM_SOURCE_INSTANCE", "dsh-default")
                line = next(
                    (ln.strip() for ln in body if ln.strip() and not ln.lstrip().startswith("#")),
                    "",
                )
                if line:
                    key = instance + "/" + session
                    found[key] = SummaryEntry(
                        identity_key=key,
                        text=line,
                        source=props.get("PM_SUMMARY_SOURCE", source),
                        generated_by=props.get("PM_GENERATED_BY", ""),
                        generated_at=props.get("PM_GENERATED_AT", ""),
                    )
        props = None
        body = []

    for raw in text.splitlines():
        level, _title = _split_headline(raw)
        if level == 1:
            flush()
            continue
        if level >= 3:
            continue
        if level == 2:
            flush()
            props = {}
            continue
        if props is None:
            continue
        stripped = raw.strip()
        if stripped in (":PROPERTIES:", ":END:"):
            continue
        if stripped.startswith(":") and ": " in stripped:
            name, _, value = stripped[1:].partition(":")
            props[name.strip().upper()] = value.strip()
            continue
        if stripped:
            body.append(raw)
    flush()
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def load_human(root: Path) -> dict[str, SummaryEntry]:
    return parse_summary_blocks(_read(Path(root) / HUMAN_FILE), source=HUMAN)


def load_ai(root: Path) -> dict[str, SummaryEntry]:
    return parse_summary_blocks(_read(Path(root) / AI_FILE), source=AI)


def resolve(
    identity_key: str,
    human: dict[str, SummaryEntry],
    ai: dict[str, SummaryEntry],
) -> SummaryEntry | None:
    """人工 > AI > 无。人工摘要永不被自动摘要覆盖。"""
    return human.get(identity_key) or ai.get(identity_key)


def render_ai_file(entries: dict[str, SummaryEntry]) -> str:
    lines = file_header("AI 生成的摘要", tags=("pm", "summary"))
    lines.append("#+PM_GENERATOR: pm " + __version__)
    lines.append("")
    lines.append("* 说明")
    lines.append("  本文件由 =pm summary set= 维护，**不要手改**。")
    lines.append("  人工摘要请写 " + HUMAN_FILE + "，它优先于本文件；自动摘要永不覆盖人工摘要。")
    lines.append("")
    lines.append("* " + AI_SECTION)
    for key in sorted(entries):
        entry = entries[key]
        instance, _, session = key.partition("/")
        lines.append("** " + session)
        lines.append("   :PROPERTIES:")
        lines.append("   :PM_IDENTITY: " + key)
        lines.append("   :PM_SESSION: " + session)
        lines.append("   :PM_SOURCE_INSTANCE: " + instance)
        lines.append("   :PM_SUMMARY_SOURCE: " + entry.source)
        if entry.generated_by:
            lines.append("   :PM_GENERATED_BY: " + entry.generated_by)
        if entry.generated_at:
            lines.append("   :PM_GENERATED_AT: " + entry.generated_at)
        lines.append("   :END:")
        lines.append("   " + entry.text)
    return render_text(lines)


def upsert_ai_summary(
    root: Path,
    *,
    identity_key: str,
    text: str,
    model: str = "",
    generated_at: datetime | None = None,
) -> Path:
    root = Path(root)
    entries = load_ai(root)
    entries[identity_key] = SummaryEntry(
        identity_key=identity_key,
        text=" ".join(text.split()),
        source=AI,
        generated_by=model,
        generated_at=(generated_at or datetime.now().astimezone()).strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    path = root / AI_FILE
    write_atomic(path, render_ai_file(entries))
    return path
