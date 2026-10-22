"""pm project list / create：库内项目目录 ∪ 当前投影的统一视图。

背景：用户在批准提案时填一个库外的新 key（如 pm_tools）→ PROJECT_NOT_FOUND。
现在：
- list  只读，把「库里 projects/*/ 已建目录」与「投影里的项目」合并成一张表
        （inLibrary 区分；缺 project.org 的目录按目录名兜底、title 为空）；
- create 复用 scaffold 的同一套 skeleton 函数建 projects/proj-<KEY>/，
        已存在则幂等返回 {created:false, exists:true}，不覆盖任何人工文件。

人工文件只在**缺失时**创建；不碰其它项目，不动 inbox/proposals。
"""

from __future__ import annotations

import argparse
import json
import re
import hashlib
import sys
from datetime import datetime
from pathlib import Path

from pm import entities, scaffold
from pm.config import load as load_config
from pm.layout import Layout
from pm.model import Project
from pm.org import write_atomic
from pm.render.plan import HUMAN, WriteOp
from pm.render import plan as plan_mod

#: 只允许字母数字与 . _ -（与目录名 proj-<KEY> 兼容，且不做任何路径拼接）
PROJECT_KEY_RE = re.compile(r"^[A-Za-z0-9._-]+$")

EXIT_INPUT = entities.EXIT_INPUT


class ProjectsError(entities.EntityError):
    """项目命令的语义错误（复用 entities 的错误形状）。"""


def validate_key(key) -> str:
    text = str(key or "").strip()
    if not text or not PROJECT_KEY_RE.match(text):
        raise ProjectsError(
            "INVALID_PROJECT_KEY",
            "项目 key 只允许 [A-Za-z0-9._-]+（不能为空、不能带空格或斜杠）: " + repr(key),
        )
    return text


def _read_project_org(path: Path) -> dict:
    """读 project.org：:PM_KEY: / :PM_PATHS: / #+TITLE: / #+PM_PATH:。

    文件缺失或读不了 → {}（调用方按目录名兜底，不编造数据）。
    """
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    title = ""
    pm_key = ""
    paths: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if not title and upper.startswith("#+TITLE:"):
            title = stripped.split(":", 1)[1].strip()
        elif upper.startswith("#+PM_PATH:"):
            value = stripped.split(":", 1)[1].strip()
            if value:
                paths.append(value)
        elif upper.startswith(":PM_KEY:"):
            pm_key = stripped.split(":", 2)[2].strip()
        elif upper.startswith(":PM_PATHS:"):
            value = stripped.split(":", 2)[2].strip()
            paths.extend(part.strip() for part in value.split("|") if part.strip())
    return {"title": title, "key": pm_key, "paths": paths}


def paths_by_project(library_root) -> dict[str, list[str]]:
    """`{项目 key: [工作区路径…]}`（来自 `projects/proj-*/project.org` 的 `#+PM_PATH:` / `:PM_PATHS:`）。

    用途：hooks 的 SessionStart 三段回退要把 payload 的 cwd 解析成**当前项目**；
    这里只返回**用户在项目文件里显式声明**的路径，推导不出就返回空映射（不猜）。
    """
    root = Path(library_root) / "projects"
    out: dict[str, list[str]] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.glob("proj-*/project.org")):
        info = _read_project_org(path)
        key = str(info.get("key") or "").strip() or path.parent.name.removeprefix("proj-")
        paths = [str(p).strip() for p in (info.get("paths") or []) if str(p).strip()]
        if paths:
            out.setdefault(key, []).extend(paths)
    return out


def _task_count(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        from pm import tasks as tasks_module  # 延迟 import，避免与 CLI 注册互相牵制

        return len(tasks_module.read_tasks(path))
    except Exception:
        return 0


def _relative(layout: Layout, path: Path) -> str:
    try:
        return str(path.relative_to(layout.root))
    except ValueError:
        return str(path)


def library_projects(layout: Layout) -> dict[str, dict]:
    """库里已建目录的行（inLibrary=true）。"""
    rows: dict[str, dict] = {}
    projects_dir = Path(layout.projects_dir)
    if not projects_dir.is_dir():
        return rows
    for directory in sorted(item for item in projects_dir.iterdir() if item.is_dir()):
        info = _read_project_org(directory / "project.org")
        name = directory.name
        key = info.get("key") or (name[len("proj-") :] if name.startswith("proj-") else name)
        rows[key] = {
            "key": key,
            "id": name,
            "title": info.get("title") or "",
            "inLibrary": True,
            "path": _relative(layout, directory),
            "taskCount": _task_count(directory / "tasks.org"),
            "workspaceCount": len(set(info.get("paths") or [])),
        }
    return rows


def list_projects(
    layout: Layout, *, result=None, in_library_only: bool = False
) -> dict:
    """库内项目 ∪ 投影项目（按 inLibrary 优先、key 升序）。"""
    rows = library_projects(layout)
    if result is not None:
        for project in result.projects:
            paths = {path for path in project.paths if path}
            row = rows.get(project.key)
            if row is None:
                if in_library_only:
                    continue
                rows[project.key] = {
                    "key": project.key,
                    "id": project.id or f"proj-{project.key}",
                    "title": project.title or "",
                    "inLibrary": False,
                    "path": None,
                    "taskCount": 0,
                    "workspaceCount": len(paths),
                }
            else:
                row["workspaceCount"] = max(row["workspaceCount"], len(paths))
    projects = sorted(rows.values(), key=lambda row: (0 if row["inLibrary"] else 1, row["key"]))
    return {"projects": projects, "count": len(projects)}


def _with_pm_paths(content: str, paths: list[str]) -> str:
    """把 :PM_PATHS: 塞进 project.org 的抽屉（只在创建时；值用 | 分隔）。"""
    if not paths:
        return content
    lines = content.split("\n")
    out: list[str] = []
    inserted = False
    for line in lines:
        if not inserted and line.strip() == ":END:":
            out.append(":PM_PATHS: " + "|".join(paths))
            inserted = True
        out.append(line)
    return "\n".join(out)


def create_project(
    layout: Layout,
    key,
    *,
    title: str | None = None,
    paths=None,
    projection=None,
    dry_run: bool = False,
) -> dict:
    """建 projects/proj-<KEY>/；已存在则 created=false（不覆盖、不报错）。"""
    clean_key = validate_key(key)
    project_id = f"proj-{clean_key}"
    directory = Path(layout.project_dir(project_id))
    relative = f"projects/{project_id}"
    if directory.is_dir():
        info = _read_project_org(directory / "project.org")
        return {
            "ok": True,
            "created": False,
            "exists": True,
            "key": clean_key,
            "id": project_id,
            "path": relative,
            "title": info.get("title") or "",
            "files": [],
        }

    explicit_paths = [str(path).strip() for path in (paths or []) if str(path).strip()]
    if projection is not None:
        project = Project(
            key=projection.key,
            title=(title or projection.title or clean_key),
            id=projection.id or project_id,
            paths=explicit_paths or list(projection.paths),
        )
    else:
        project = Project(key=clean_key, title=title or clean_key, paths=explicit_paths)

    project_org = scaffold.project_readme(project)
    if explicit_paths:
        project_org = _with_pm_paths(project_org, explicit_paths)
    ops = [
        WriteOp(path=Path(layout.project_file(project.id)), content=project_org, kind=HUMAN, skip_if_exists=True),
        WriteOp(path=Path(layout.tasks_file(project.id)), content=scaffold.project_tasks(project), kind=HUMAN, skip_if_exists=True),
        WriteOp(path=Path(layout.memory_file(project.id)), content=scaffold.project_memory(project), kind=HUMAN, skip_if_exists=True),
    ]
    planned = [_relative(layout, op.path) for op in ops]
    if dry_run:
        return {
            "ok": True,
            "created": False,
            "exists": False,
            "dry_run": True,
            "key": clean_key,
            "id": project.id,
            "path": relative,
            "title": project.title,
            "files": planned,
        }

    directory.mkdir(parents=True, exist_ok=True)
    plan_mod.apply(ops, layout, write=True)
    return {
        "ok": True,
        "created": True,
        "exists": False,
        "key": clean_key,
        "id": project.id,
        "path": relative,
        "title": project.title,
        "files": planned,
    }


# ---------------------------------------------------------------- 项目简报（只读）


#: 六段简报：(JSON 字段, project.org 里的 ** 标题)。顺序就是文档里的顺序。
BRIEF_SECTIONS: tuple[tuple[str, str], ...] = (
    ("goal", "目标"),
    ("scope", "范围（做什么）"),
    ("nonGoal", "非目标（明确不做什么）"),
    ("acceptance", "验收标准"),
    ("milestones", "里程碑"),
    ("risks", "风险与依赖"),
)

#: 验收标准里的复选框：- [ ] / - [x]
_CHECKBOX = re.compile(r"^-\s*\[(?P<mark>[ xX])\]\s*(?P<text>.*)$")
_HEADLINE = re.compile(r"^(?P<stars>\*+)(?:\s+(?P<title>.*))?$")


def _dedent(line: str) -> str:
    """project.org 的正文按 scaffold 约定缩进 3 空格；只削这一层，保留嵌套结构。"""
    return line[3:] if line.startswith("   ") else line


def parse_brief(text: str) -> dict:
    """把 project.org 的六段解析成结构化简报（**纯函数，不写任何文件**）。"""
    lines = text.splitlines()
    found: dict[str, list[str]] = {}
    order: list[str] = []
    current: str | None = None
    for line in lines:
        match = _HEADLINE.match(line)
        if match and len(match.group("stars")) == 2:
            title = (match.group("title") or "").strip()
            current = next((key for key, name in BRIEF_SECTIONS if name == title), None)
            if current is not None:
                found[current] = []
                order.append(current)
            continue
        if match and len(match.group("stars")) == 1:
            current = None  # 下一个一级标题：不跨项目解析
            continue
        if current is not None:
            found[current].append(_dedent(line))

    brief: dict = {}
    missing: list[str] = []
    for key, name in BRIEF_SECTIONS:
        if key not in found:
            missing.append(key)
            brief[key] = [] if key == "acceptance" else ""
            if key == "acceptance":
                brief["acceptanceNotes"] = []
            continue
        body = [line for line in found[key]]
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        if key == "acceptance":
            items: list[dict] = []
            notes: list[str] = []
            for line in body:
                stripped = line.strip()
                if not stripped:
                    continue
                box = _CHECKBOX.match(stripped)
                if box is not None:
                    items.append(
                        {"text": box.group("text").strip(), "done": box.group("mark").lower() == "x"}
                    )
                else:
                    notes.append(stripped)
            brief["acceptance"] = items
            brief["acceptanceNotes"] = notes
        else:
            brief[key] = "\n".join(body).strip()
    brief["missingSections"] = missing
    brief["sectionTitles"] = {key: name for key, name in BRIEF_SECTIONS}
    return brief


def _locate_project(layout: Layout, key) -> dict:
    """按 key 或 proj-<key> 定位已建目录的项目（brief get / set 共用）。"""
    text = str(key or "").strip()
    if not text:
        raise ProjectsError("INVALID_PROJECT_KEY", "需要项目 key")
    lookup = text[len("proj-") :] if text.startswith("proj-") else text
    rows = library_projects(layout)
    row = rows.get(lookup)
    if row is None:
        raise ProjectsError(
            "NOT_FOUND",
            f"找不到项目 {text}（projects/{text} 与 projects/proj-{lookup} 都不存在）",
            extra={
                "project": lookup,
                "hint": f"先运行 pm project create {lookup} 建目录，或用 pm project list 看有哪些项目。",
                "canCreate": True,
                "knownProjects": sorted(rows),
            },
        )
    return row


def absolute_project_org(layout: Layout, project_id: str) -> str | None:
    """**服务端解析** `<库根>/projects/<id>/project.org` 的绝对路径；解析不了 → `None`。

    为什么要有这个字段：brief 投影里的 `path` 是**相对**库根的路径，前端拿到它只能自己拼绝对路径 ——
    而面板上能看到的其它路径（`projects[].paths[]`）是 **DSH 工作区路径**，不保证等于库根；
    前端硬拼就是**编造**。所以绝对路径必须由服务端给。

    **不可解析一律 null**（文件不存在 / 库根不可用 / 异常）：不回落相对路径，也不拿工作区路径冒充。
    """
    try:
        path = Path(layout.project_file(project_id)).expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    return str(path) if path.is_file() else None


def get_brief(layout: Layout, key, *, result=None) -> dict:
    """pm project brief get：只读投影（含整文件 digest，供 brief set 做 CAS）。

    - 目录都没有（未知 key）→ NOT_FOUND（带 hint）；
    - 目录在但 project.org 缺失 → brief=null + reason（不假造空对象）；
    - `absolutePath` = 服务端解析的 project.org 绝对路径（不可解析 → null）；其余字段语义不变（additive）。
    """
    row = _locate_project(layout, key)
    directory = Path(layout.project_dir(row["id"]))
    project_org = directory / "project.org"
    payload = {
        "project": row["key"],
        "id": row["id"],
        "path": row["path"],
        # 绝对路径由服务端解析（task-224）：不可解析 → None，绝不拿工作区路径/相对路径冒充
        "absolutePath": absolute_project_org(layout, row["id"]),
        "title": row["title"],
        "readOnly": True,
        "digest": hashlib.sha256(project_org.read_bytes()).hexdigest() if project_org.is_file() else None,
        "brief": None,
        "reason": None,
        "message": None,
    }
    if not project_org.is_file():
        payload["reason"] = "NO_PROJECT_ORG"
        payload["message"] = (
            f"{row['path']}/project.org 不存在；它是人工管理区，pm 只在项目创建时生成骨架，"
            "此后只在你显式提交编辑时写入你指定的那一段（pm project brief set；actor + CAS + "
            "LOGBOOK 审计），不会自动改写、不会在后台批量改。"
        )
        return payload
    try:
        text_value = project_org.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        payload["reason"] = "UNREADABLE"
        payload["message"] = f"读不了 {row['path']}/project.org: {exc}"
        return payload
    payload["brief"] = parse_brief(text_value)
    return payload


def command_project_brief_get(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    execution = _execution()
    try:
        config, _sources, _result = execution._load(args)
        layout = Layout(execution._library_root(config))
        payload = get_brief(layout, args.key)
    except entities.EntityError as exc:
        return _fail(json_mode, exc)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if payload["brief"] is None:
        print(f"项目 {payload['project']}：没有简报（{payload['reason']}）")
        print("  " + payload["message"])
        return 0
    brief = payload["brief"]
    print(f"项目 {payload['project']}（{payload['title'] or '未命名'}）—— 只读简报，来自 {payload['path']}/project.org")
    for key, name in BRIEF_SECTIONS:
        if key == "acceptance":
            items = brief["acceptance"]
            print(f"** {name}（{sum(1 for i in items if i['done'])}/{len(items)} 已完成）")
            for item in items:
                print("   [%s] %s" % ("x" if item["done"] else " ", item["text"]))
            for note in brief["acceptanceNotes"]:
                print("   · " + note)
            continue
        value = brief[key]
        print(f"** {name}" + ("" if value else "（空）"))
        for line in str(value).splitlines() if value else []:
            print("   " + line)
    if brief["missingSections"]:
        print("（缺这几段：" + ", ".join(brief["missingSections"]) + "）")
    return 0


#: 段名归一：规范 key / 中文标题 / 常见别名 → BRIEF_SECTIONS 的 key
SECTION_ALIASES: dict[str, str] = {
    "goal": "goal", "目标": "goal",
    "scope": "scope", "范围": "scope", "范围（做什么）": "scope",
    "nongoal": "nonGoal", "non-goal": "nonGoal", "non_goal": "nonGoal",
    "非目标": "nonGoal", "非目标（明确不做什么）": "nonGoal",
    "acceptance": "acceptance", "验收标准": "acceptance", "criteria": "acceptance",
    "milestones": "milestones", "里程碑": "milestones",
    "risks": "risks", "risk": "risks", "风险与依赖": "risks",
}

BRIEF_UPDATED_PROP = "PM_BRIEF_UPDATED"
BRIEF_LOG_PREFIX = "- brief-set"


def normalize_section(value) -> str:
    text = str(value or "").strip()
    key = SECTION_ALIASES.get(text) or SECTION_ALIASES.get(text.lower())
    if key is None:
        allowed = ", ".join(name for name, _title in BRIEF_SECTIONS)
        raise ProjectsError(
            "UNKNOWN_SECTION",
            f"未知的简报段 {value!r}；可用: {allowed}（也接受中文段名）",
            extra={"allowedSections": [name for name, _title in BRIEF_SECTIONS]},
        )
    return key


def brief_digest(path) -> str:
    """整文件 sha256（project.org 没有 :PM_REVISION:，CAS 用它）。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render_section_lines(text: str) -> list[str]:
    """按行写出：空行原样；已缩进行 / 以 * 开头的行原样（子标题必须留在第 0 列）；其余加 3 空格。

    这样写进去的内容能被 parse_brief 原样读回（它只削一层 3 空格缩进）。
    """
    rendered: list[str] = []
    for line in str(text).split("\n"):
        if not line.strip():
            rendered.append("")
        elif line[:1] in (" ", "\t") or line.lstrip().startswith("*"):
            rendered.append(line)
        else:
            rendered.append("   " + line)
    while rendered and not rendered[-1].strip():
        rendered.pop()
    return rendered


def _section_span(lines: list[str], title: str) -> tuple[int, int] | None:
    """** <title> 的正文行范围 [start, stop)：标题之后 → 下一个同级/更高级标题之前。"""
    start = None
    for index, line in enumerate(lines):
        match = _HEADLINE.match(line)
        if match is None:
            continue
        level = len(match.group("stars"))
        text = (match.group("title") or "").strip()
        if start is None:
            if level == 2 and text == title:
                start = index + 1
            continue
        if level <= 2:
            return start, index
    if start is None:
        return None
    return start, len(lines)


def _drawer_spans(lines: list[str]) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """(:PROPERTIES: 抽屉, :LOGBOOK: 抽屉) 的 (start, stop)：stop 是 :END: 之后的下一行。"""

    def span_from(index: int) -> tuple[int, int]:
        stop = index + 1
        while stop < len(lines) and lines[stop].strip() != ":END:":
            stop += 1
        return index, min(stop + 1, len(lines))

    props = logbook = None
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == ":PROPERTIES:" and props is None:
            props = span_from(index)
            index = props[1]
            continue
        if stripped == ":LOGBOOK:" and logbook is None:
            logbook = span_from(index)
            index = logbook[1]
            continue
        index += 1
    return props, logbook


def _apply_line_edits(lines: list[str], edits: list[tuple[int, int, list[str]]]) -> list[str]:
    """多处 (start, stop, replacement) 编辑：从后往前应用，保证下标不串。"""
    result = list(lines)
    for start, stop, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        result[start:stop] = replacement
    return result


def set_brief_section(
    layout: Layout,
    key,
    *,
    section,
    text: str,
    actor: str,
    expect_digest: str,
    reason: str = "",
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    """只替换指定段的正文行（其余字节不动），一次 CAS + 一次原子写。

    - CAS：整文件 sha256；不一致 → DIGEST_CONFLICT（exit 3，零写入，返回当前 digest）；
    - 属性抽屉补 :PM_BRIEF_UPDATED: 与 :LOGBOOK:（首次写入时创建）记 op=brief-set；
    - 同一次写入把文件里仍写着的旧措辞（"此后永不写入"）换成新契约表述（找不到就跳过）；
    - **任何自动流程/导入都不得调用**：actor 必须由调用方显式给出。
    """
    section_key = normalize_section(section)
    if not str(actor or "").strip():
        raise ProjectsError("ACTOR_REQUIRED", "必须显式给出 --actor（human/ai/system）")
    title = dict(BRIEF_SECTIONS)[section_key]
    row = _locate_project(layout, key)
    project_org = Path(layout.project_dir(row["id"])) / "project.org"
    if not project_org.is_file():
        raise ProjectsError(
            "NO_PROJECT_ORG",
            f"{row['path']}/project.org 不存在；pm 不会凭空造人工文件。",
            extra={
                "project": row["key"],
                "path": row["path"],
                "hint": f"先运行 pm project create {row['key']}（目录不存在时会建骨架；已存在则请手工补文件）",
            },
        )

    raw = project_org.read_bytes()
    current_digest = hashlib.sha256(raw).hexdigest()
    expected = str(expect_digest or "").strip().lower()
    if expected != current_digest:
        raise ProjectsError(
            "DIGEST_CONFLICT",
            "project.org 已经被改动：你手上的 digest 与当前文件不一致，一个字节都没写。",
            exit_code=entities.EXIT_CONFLICT,
            extra={
                "expectedDigest": expected or None,
                "currentDigest": current_digest,
                "path": row["path"],
                "hint": "文件已被改动，请重新 pm project brief get 拿到新 digest、重新确认后再提交",
            },
        )

    newline = "\r\n" if b"\r\n" in raw else "\n"
    lines = raw.decode("utf-8", "replace").replace("\r\n", "\n").split("\n")
    span = _section_span(lines, title)
    if span is None:
        raise ProjectsError(
            "SECTION_NOT_FOUND",
            f"{row['path']}/project.org 里没有 ** {title} 这一段；pm 不会替你造结构。",
            extra={"section": title, "path": row["path"]},
        )
    start, stop = span
    trailing: list[str] = []
    for line in reversed(lines[start:stop]):
        if line.strip():
            break
        trailing.insert(0, line)
    new_body = render_section_lines(text) + trailing
    changed = new_body != lines[start:stop]

    at = now or datetime.now().astimezone()
    at_iso = at.isoformat(timespec="seconds")
    props_span, logbook_span = _drawer_spans(lines)
    edges = [(start, stop)]
    if props_span is not None:
        edges.append(props_span)
    if logbook_span is not None:
        edges.append(logbook_span)
    if props_span is None or start < props_span[1] or stop > max(item[1] for item in edges):
        raise ProjectsError(
            "UNEXPECTED_STRUCTURE",
            f"{row['path']}/project.org 的结构不像项目文件（** {title} 在属性抽屉之前或抽屉缺失），拒绝写入。",
            extra={"section": title, "path": row["path"]},
        )

    brief_revision = 1 + sum(1 for line in lines if line.strip().startswith(BRIEF_LOG_PREFIX))
    audit_id = entities.new_audit_id(at)
    # 抽屉的缩进跟着 :PROPERTIES: 走（project.org 是第 0 列；缩进过的文件同样适配）
    props_line = lines[props_span[0]]
    props_indent = props_line[: len(props_line) - len(props_line.lstrip())]

    # 1) 正文替换 2) :PM_BRIEF_UPDATED: 3) 旧措辞迁移 —— 先合成，再据此算「写入后摘要」
    edits: list[tuple[int, int, list[str]]] = [(start, stop, new_body)]
    prop_start, prop_stop = props_span
    existing_prop = next(
        (
            i
            for i in range(prop_start, prop_stop)
            if lines[i].strip().upper().startswith(":" + BRIEF_UPDATED_PROP + ":")
        ),
        None,
    )
    prop_line = f":{BRIEF_UPDATED_PROP}: {at_iso}"
    if existing_prop is not None:
        edits.append((existing_prop, existing_prop + 1, [prop_line]))
    else:
        end_index = max(prop_start, prop_stop - 1)
        edits.append((end_index, end_index, [prop_line]))
    for index, line in enumerate(lines):
        if scaffold.HUMAN_AREA_LEGACY_MARKER in line:
            note = scaffold.indent_lines("\n".join(scaffold.HUMAN_AREA_NOTE)).split("\n")
            edits.append((index, index + 1, note))
            break

    interim = _apply_line_edits(lines, edits)
    recorded_new = hashlib.sha256("\n".join(interim).encode("utf-8")).hexdigest()
    log_line = (
        f'{BRIEF_LOG_PREFIX} "{section_key}" [{at.strftime("%Y-%m-%d %a %H:%M")}] '
        f'id={row["id"]} audit={audit_id} at={at_iso} actor={actor} rev={brief_revision} '
        f"op=brief-set section={section_key} digest={current_digest[:12]}->{recorded_new[:12]}"
    )
    if reason:
        log_line += " reason=" + " ".join(str(reason).split())

    # 4) LOGBOOK：首次写入时创建，否则追加
    props_now, logbook_now = _drawer_spans(interim)
    indented_log = props_indent + log_line
    if logbook_now is not None:
        insert_at = max(logbook_now[0], logbook_now[1] - 1)
        final_lines = interim[:insert_at] + [indented_log] + interim[insert_at:]
    elif props_now is not None:
        insert_at = props_now[1]
        final_lines = (
            interim[:insert_at]
            + [props_indent + ":LOGBOOK:", indented_log, props_indent + ":END:"]
            + interim[insert_at:]
        )
    else:  # pragma: no cover - project.org 必有 :PROPERTIES:
        final_lines = interim + [props_indent + ":LOGBOOK:", indented_log, props_indent + ":END:"]

    final_text = "\n".join(final_lines)
    payload = {
        "ok": True,
        "entityId": row["id"],
        "revision": brief_revision,
        "source": entities.SOURCE_ORG,
        "observedAt": at_iso,
        "auditEventId": audit_id,
        "project": row["key"],
        "id": row["id"],
        "path": row["path"],
        "section": section_key,
        "sectionTitle": title,
        "previousDigest": current_digest,
        "digest": hashlib.sha256(final_text.encode("utf-8")).hexdigest(),
        "changed": bool(changed),
        "updatedAt": at_iso,
        "dry_run": bool(dry_run),
    }
    if dry_run:
        payload["written"] = False
        return payload
    if not changed and scaffold.HUMAN_AREA_LEGACY_MARKER not in "\n".join(lines):
        # 内容与旧措辞都没变 → 零变更：不写、不加审计行
        payload["digest"] = current_digest
        payload["written"] = False
        return payload
    write_atomic(project_org, final_text, newline=newline, fsync=True)
    payload["written"] = True
    payload["digest"] = hashlib.sha256(project_org.read_bytes()).hexdigest()
    return payload


def command_project_brief_set(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    execution = _execution()
    try:
        text = args.text
        if args.text_file:
            if args.text is not None:
                raise ProjectsError("TEXT_CONFLICT", "--text 与 --text-file 不能同时给")
            source = Path(args.text_file).expanduser()
            try:
                text = source.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise ProjectsError("TEXT_FILE_UNREADABLE", f"读不了 --text-file {source}: {exc}")
        if text is None:
            raise ProjectsError("TEXT_REQUIRED", "需要 --text 或 --text-file（清空某段用 --text ''）")
        layout = execution._write_layout(args, json_mode)
        payload = set_brief_section(
            layout,
            args.key,
            section=args.section,
            text=text,
            actor=args.actor,
            expect_digest=args.expect_digest,
            reason=args.reason or "",
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    except entities.EntityError as exc:
        return _fail(json_mode, exc)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if payload["dry_run"]:
        verb = "干跑"
    elif payload.get("written"):
        verb = "已写入"
    else:
        verb = "零变更（没写）"
    print(
        f"{verb} {payload['path']}/project.org 的 ** {payload['sectionTitle']}"
        f"（section={payload['section']}）"
    )
    print(
        f"  digest {payload['previousDigest'][:12]} -> {payload['digest'][:12]}"
        f"  audit={payload['auditEventId']}"
    )
    return 0

# ---------------------------------------------------------------- CLI


def _execution():
    """复用 execution 的读/写准备与错误输出（延迟 import 避免循环）。"""
    from pm import execution

    return execution


def _fail(json_mode: bool, error: "entities.EntityError") -> int:
    return _execution()._fail(json_mode, error)


def command_project_list(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    execution = _execution()
    try:
        config, _sources, result = execution._load(args)
        layout = Layout(execution._library_root(config))
        payload = list_projects(
            layout, result=result, in_library_only=bool(getattr(args, "in_library_only", False))
        )
    except entities.EntityError as exc:
        return _fail(json_mode, exc)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"项目 {payload['count']} 个")
    for row in payload["projects"]:
        where = row["path"] if row["inLibrary"] else "（仅投影，未建目录）"
        print(
            "  %-20s %-28s tasks=%d workspaces=%d %s"
            % (row["key"], where, row["taskCount"], row["workspaceCount"], row["title"])
        )
    return 0


def command_project_create(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    execution = _execution()
    try:
        key = validate_key(args.key)
        # （create 的 key 校验在 validate_key；brief 只读，不建任何东西）
        config, _sources, result = execution._load(args)
        layout = execution._write_layout(args, json_mode)
        projection = next((item for item in result.projects if item.key == key), None)
        payload = create_project(
            layout,
            key,
            title=args.title,
            paths=args.path,
            projection=projection,
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    except entities.EntityError as exc:
        return _fail(json_mode, exc)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    if payload["exists"]:
        print(f"项目 {payload['key']} 已存在：{payload['path']}（未改任何文件）")
    elif payload.get("dry_run"):
        print(f"[干跑] 将创建 {payload['path']}（{len(payload['files'])} 个文件，缺什么建什么）")
    else:
        print(f"已创建 {payload['path']}（{len(payload['files'])} 个文件）")
    return 0


def register_cli(project_subparsers) -> None:
    """挂到 pm project 的子命令下（由 pm.execution 调用）。"""
    listing = project_subparsers.add_parser(
        "list", help="统一列出库内项目与投影项目（只读）"
    )
    listing.add_argument("--in-library-only", dest="in_library_only", action="store_true",
                         help="只要库里已经建了目录的项目")
    listing.add_argument("--json", action="store_true")
    execution = _execution()
    execution._common(listing)
    listing.set_defaults(handler=command_project_list)

    create = project_subparsers.add_parser(
        "create", help="按骨架新建 projects/proj-<KEY>/（已存在则幂等返回）"
    )
    create.add_argument("key", metavar="KEY")
    create.add_argument("--title", default=None, metavar="T")
    create.add_argument("--path", dest="path", action="append", default=[], metavar="PATH",
                        help="工作区路径（可重复；写入 :PM_PATHS: 与 #+PM_PATH:）")
    create.add_argument("--workspace", dest="path", action="append", metavar="PATH",
                        help="--path 的别名")
    create.add_argument("--dry-run", dest="dry_run", action="store_true", help="只预演，不落盘")
    create.add_argument("--yes", action="store_true",
                        help="确认写默认配置指向的库；未显式 --config 且非 --dry-run 时必需")
    create.add_argument("--json", action="store_true")
    execution._common(create)
    create.set_defaults(handler=command_project_create)

    brief = project_subparsers.add_parser(
        "brief",
        help="项目简报：只读解析 project.org 的目标/范围/非目标/验收标准/里程碑/风险",
    )
    brief_sub = brief.add_subparsers(dest="brief_command")
    brief_get = brief_sub.add_parser(
        "get",
        help="读某个项目的简报（key 或 proj-<key>；只读，另返回整文件 digest 供 brief set 做 CAS）",
    )
    brief_get.add_argument("key", metavar="KEY")
    brief_get.add_argument("--json", action="store_true")
    execution._common(brief_get)
    brief_get.set_defaults(handler=command_project_brief_get)

    brief_set = brief_sub.add_parser(
        "set",
        help="只替换指定段的正文行（整文件 sha256 CAS + LOGBOOK 审计；actor 必填，只能人显式调用）",
    )
    brief_set.add_argument("key", metavar="KEY")
    brief_set.add_argument(
        "--section", required=True, metavar="S",
        help="goal/scope/nonGoal/acceptance/milestones/risks（也接受中文段名）",
    )
    brief_set.add_argument("--text", default=None, metavar="TEXT",
                           help="该段的新正文（多行；--text '' = 清空这一段）")
    brief_set.add_argument("--text-file", dest="text_file", default=None, metavar="PATH",
                           help="从文件读新正文（与 --text 互斥）")
    brief_set.add_argument(
        "--actor", required=True, choices=["human", "ai", "system"],
        help="谁提交的（必填；AI 必须显式写 ai。任何自动流程/导入不得调用本命令）",
    )
    brief_set.add_argument(
        "--expect-digest", dest="expect_digest", required=True, metavar="SHA256",
        help="pm project brief get 返回的整文件 digest；不一致 → exit 3 且零写入",
    )
    brief_set.add_argument("--reason", default="", metavar="R")
    brief_set.add_argument("--dry-run", dest="dry_run", action="store_true", help="只预演，不落盘")
    brief_set.add_argument("--yes", action="store_true",
                           help="确认写默认配置指向的库；未显式 --config 且非 --dry-run 时必需")
    brief_set.add_argument("--json", action="store_true")
    execution._common(brief_set)
    brief_set.set_defaults(handler=command_project_brief_set)
