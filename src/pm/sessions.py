"""读 DSH 会话日志，提炼「这个会话到底做了什么」。

为什么需要它：投影缓存里只有标题、goal、todos。实测 demo 88 张卡里
58 张连 goal/todos 都是空的，包括 1555 步的主力会话 —— 从缓存永远写不出进展。
真正的证据在日志里：用户请求、AI 的待办变迁、deliverables/presented 带路径的交付物。

隐私边界（重要）：
- 本模块的输出**只打印到 stdout**，绝不自动写进 work-memory。
- 调用方（agent）读完自己提炼成一句话结论写回；正文不入库。
- 日志是拼接的多帧 zstd，解码交给 bin/zstd-decode.cjs（Node 提供 zstd）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from pm.config import Instance

REPO_ROOT = Path(__file__).resolve().parents[2]
DECODER = REPO_ROOT / "bin" / "zstd-decode.cjs"

#: 不是真实用户请求的 user/message 来源（系统注入）。
NON_USER_SOURCES = frozenset({"plugin", "system"})


class LogError(Exception):
    """会话日志不可读。"""


@dataclass
class Deliverable:
    at: datetime | None
    path: str
    description: str


@dataclass
class TodoSnapshot:
    at: datetime | None
    todos: list[tuple[str, str]]

    @property
    def done(self) -> int:
        return sum(1 for _, status in self.todos if status in ("completed", "cancelled"))


@dataclass
class Digest:
    session_id: str
    instance: str = ""
    cwd: str = ""
    log_path: str = ""
    frames: int = 0
    events: int = 0
    first_at: datetime | None = None
    last_at: datetime | None = None
    turns: int = 0
    steps: int = 0
    user_requests: list[tuple[datetime | None, str]] = field(default_factory=list)
    todo_snapshots: list[TodoSnapshot] = field(default_factory=list)
    deliverables: list[Deliverable] = field(default_factory=list)
    last_assistant: str = ""
    titles: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def final_todos(self) -> TodoSnapshot | None:
        return self.todo_snapshots[-1] if self.todo_snapshots else None


def _ms(value: object) -> datetime | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).astimezone()
    except (OverflowError, OSError, ValueError):
        return None


def _is_injected(text: str) -> bool:
    """系统提示 / 工具回灌常被记成 user/message，但它们不是用户说的话。"""
    head = text.lstrip()[:40].lower()
    return head.startswith("<system-reminder>")


def _text_of(data: dict[str, Any]) -> str:
    """从 message 事件的 data.content 里取纯文本。"""
    content = data.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def unique_deliverables(digest: Digest) -> list[Deliverable]:
    """按路径去重，保留最后一次的描述（同一文件常被反复 present）。"""
    seen: dict[str, Deliverable] = {}
    for item in digest.deliverables:
        seen[item.path] = item
    return list(seen.values())


def render_digest(
    digest: Digest,
    *,
    prompts: int = 12,
    prompt_chars: int = 160,
    deliverables: int = 15,
    show_prompts: bool = True,
    todo_items: int = 12,
    assistant_chars: int = 600,
) -> str:
    """把 digest 渲染成给 agent 读的材料。**只打印，不落库。**"""
    lines: list[str] = []
    lines.append("会话 " + digest.session_id)
    lines.append("  数据实例 " + (digest.instance or "-") + "    工作目录 " + (digest.cwd or "-"))
    span = "-"
    if digest.first_at and digest.last_at:
        span = digest.first_at.strftime("%Y-%m-%d %H:%M") + " → " + digest.last_at.strftime("%Y-%m-%d %H:%M %z")
    lines.append("  时间范围 " + span)
    lines.append("  规模     %d 轮 / %d 步 / %d 事件" % (digest.turns, digest.steps, digest.events))
    kinds = digest.counts
    lines.append(
        "  结构     用户请求 %d · AI 消息 %d · 工具调用 %d · 待办快照 %d · 交付物 %d"
        % (
            len(digest.user_requests),
            kinds.get("assistant/message", 0),
            kinds.get("tool/call", 0),
            len(digest.todo_snapshots),
            len(unique_deliverables(digest)),
        )
    )
    if digest.titles:
        lines.append("  会话标题 " + " / ".join(dict.fromkeys(digest.titles)))
    lines.append("")

    if show_prompts and digest.user_requests:
        lines.append("== 用户请求（source.kind=user，已滤掉系统注入）==")
        total = len(digest.user_requests)
        head_n = min(2, total)
        tail_n = max(0, min(prompts, total) - head_n)
        picked = list(range(head_n))
        if tail_n:
            picked += list(range(max(head_n, total - tail_n), total))
        for index in picked:
            at, text = digest.user_requests[index]
            stamp = at.strftime("%m-%d %H:%M") if at else "--"
            body = " ".join(text.split())
            if len(body) > prompt_chars:
                body = body[:prompt_chars] + "…"
            lines.append("  %2d. %s  %s" % (index + 1, stamp, body))
        if total > len(picked):
            lines.append("      （共 %d 条，已略去中间 %d 条）" % (total, total - len(picked)))
        lines.append("")

    if digest.todo_snapshots:
        final = digest.final_todos
        assert final is not None
        lines.append(
            "== AI 待办（%d 次快照；最后一次 %s，完成 %d/%d）=="
            % (
                len(digest.todo_snapshots),
                final.at.strftime("%m-%d %H:%M") if final.at else "--",
                final.done,
                len(final.todos),
            )
        )
        for content, status in final.todos[:todo_items]:
            lines.append("  [%s] %s" % (status, content))
        if len(final.todos) > todo_items:
            lines.append("  … 另有 %d 项" % (len(final.todos) - todo_items))
        lines.append("")

    items = unique_deliverables(digest)
    if items:
        lines.append("== 交付物（AI 明确 present，%d 个去重后）==" % len(items))
        for item in items[-deliverables:]:
            stamp = item.at.strftime("%m-%d %H:%M") if item.at else "--"
            lines.append("  %s  %s" % (stamp, item.path))
            if item.description:
                lines.append("            " + " ".join(item.description.split())[:140])
        if len(items) > deliverables:
            lines.append("  （只列最近 %d 个，其余省略）" % deliverables)
        lines.append("")

    if digest.last_assistant:
        lines.append("== AI 最后一段输出 ==")
        body = " ".join(digest.last_assistant.split())
        lines.append("  " + body[:assistant_chars] + ("…" if len(body) > assistant_chars else ""))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def find_log(instance: Instance, session_id: str) -> Path | None:
    """在数据根里找某个会话的日志文件（可能带 .zstd 也可能不带）。"""
    base = session_id[8:] if session_id.startswith("session-") else session_id
    # 实测两种目录命名都存在：session-<uuid> 与裸 <uuid>
    names = ("session-" + base, base)
    sessions_dir = Path(instance.sessions_dir)
    if not sessions_dir.is_dir():
        return None
    for workspace_dir in sorted(sessions_dir.iterdir()):
        if not workspace_dir.is_dir():
            continue
        for name in names:
            candidate_dir = workspace_dir / name
            if not candidate_dir.is_dir():
                continue
            logs = sorted(candidate_dir.glob("session*.jsonl*"))
            if logs:
                # 优先带 version 的最新一代
                logs.sort(key=lambda p: (".v" in p.name, p.name))
                return logs[-1]
    return None


def _version_key(name: str) -> tuple[int, ...]:
    digits = re.findall(r"\d+", name)
    return tuple(int(d) for d in digits) if digits else (0,)


def find_node() -> str | None:
    """找 node 可执行文件。

    不能只靠 shutil.which：nvm / fnm 装的 node 不在系统 PATH 上，
    而 DSH 启动 MCP stdio 子进程时会 **scrub 环境变量** ——
    实测本机 node 在 ~/.nvm/versions/node/v24.19.0/bin/node，
    只查 PATH 会让 pm log 直接失效。
    """
    found = shutil.which("node")
    if found:
        return found
    candidates: list[Path] = []
    nvm_bin = os.environ.get("NVM_BIN")
    if nvm_bin:
        candidates.append(Path(nvm_bin) / "node")
    nvm_root = Path.home() / ".nvm" / "versions" / "node"
    if nvm_root.is_dir():
        for version_dir in sorted(nvm_root.iterdir(), key=lambda p: _version_key(p.name), reverse=True):
            candidates.append(version_dir / "bin" / "node")
    candidates.extend(
        [
            Path("/usr/local/bin/node"),
            Path("/usr/bin/node"),
            Path("/opt/homebrew/bin/node"),
        ]
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def decode(path: Path) -> tuple[str, int, int]:
    """解码日志；返回 (文本, 帧数, 失败帧数)。"""
    node = find_node()
    if node is None:
        raise LogError("找不到 node（解码 zstd 需要它）；可用 NVM_BIN 或 PATH 指明")
    if not DECODER.is_file():
        raise LogError("找不到解码器: " + str(DECODER))
    if path.suffix == ".zstd":
        try:
            proc = subprocess.run(
                [node, str(DECODER), str(path)],
                capture_output=True,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LogError("解码失败: " + str(exc)) from exc
        if proc.returncode != 0:
            raise LogError("解码失败: " + proc.stderr.decode("utf-8", "replace").strip()[:200])
        # 解码器把帧数与失败数写在 stderr 上；这里只关心有没有失败
        stderr = proc.stderr.decode("utf-8", "replace")
        frames = 0
        failed = 0
        for line in stderr.splitlines():
            if line.startswith("警告:"):
                failed = 1
        return proc.stdout.decode("utf-8", "replace"), frames, failed
    try:
        return path.read_text(encoding="utf-8"), 0, 0
    except OSError as exc:
        raise LogError("读取失败: " + str(exc)) from exc


def iter_events(text: str) -> Iterator[dict[str, Any]]:
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def build_digest(events: Iterator[dict[str, Any]], *, session_id: str, instance: str = "", path: str = "") -> Digest:
    digest = Digest(session_id=session_id, instance=instance, log_path=path)
    for event in events:
        kind = event.get("type")
        if not isinstance(kind, str):
            continue
        digest.events += 1
        digest.counts[kind] = digest.counts.get(kind, 0) + 1
        at = _ms(event.get("time"))
        if at is not None:
            if digest.first_at is None or at < digest.first_at:
                digest.first_at = at
            if digest.last_at is None or at > digest.last_at:
                digest.last_at = at
        data = event.get("data")
        data = data if isinstance(data, dict) else {}

        if kind == "session":
            cwd = event.get("cwd")
            if isinstance(cwd, str) and not digest.cwd:
                digest.cwd = cwd
        elif kind == "turn/start":
            digest.turns += 1
        elif kind == "step/start":
            digest.steps += 1
        elif kind == "user/message":
            source = data.get("source")
            source_kind = source.get("kind") if isinstance(source, dict) else None
            text = _text_of(data).strip()
            if text and source_kind not in NON_USER_SOURCES and not _is_injected(text):
                digest.user_requests.append((at, text))
        elif kind == "todo/write":
            raw = data.get("todos")
            if isinstance(raw, list):
                todos = [
                    (str(t.get("content", "")).strip(), str(t.get("status", "")).strip())
                    for t in raw
                    if isinstance(t, dict) and str(t.get("content", "")).strip()
                ]
                if todos:
                    digest.todo_snapshots.append(TodoSnapshot(at=at, todos=todos))
        elif kind == "deliverables/presented":
            files = data.get("files")
            if isinstance(files, list):
                for item in files:
                    if not isinstance(item, dict):
                        continue
                    target = str(item.get("path") or "").strip()
                    if target:
                        digest.deliverables.append(
                            Deliverable(
                                at=at,
                                path=target,
                                description=str(item.get("description") or "").strip(),
                            )
                        )
        elif kind == "assistant/message":
            text = _text_of(data).strip()
            if text:
                digest.last_assistant = text
        elif kind == "session/title":
            title = data.get("title")
            if isinstance(title, str) and title.strip():
                digest.titles.append(title.strip())
    return digest
