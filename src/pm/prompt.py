"""初始系统提示词（prompt）数据层：projects/proj-<scope>/prompt.org 的读写 + 引用展开。

依据 内部记录/25（内部记录/22「上下文预览」已弃用，见 内部记录/25 §10.2）：
- 主体是**人写的提示词**，不是运行时注入物 ⇒ 本模块不调 hooks.*、不断言「模型会看到什么」；
- 存储：projects/proj-<key>/prompt.org（scope=global 时为库根 prompt.org）；
- 块 = Org 的「* 标题」+ 正文；两种形态：自由文本 / 引用文档（#+PM_INCLUDE: <表达式>，库里只存引用）；
- 引用展开四条红线：① 路径越界（含 .. 或解析后不在声明路径内）② 凭据类文件名 ③ 缺失/不是普通文件（⚠ 展开失败）
  ④ 单文件 64 KB 上限（截断并标注）；符号链接按**解析后的目标**判定；
- 变量 v1 五个：${path} / ${path:N} / ${root} / ${project} / ${dsh_home}
  —— **纯字符串替换**，不执行命令、不支持 glob。
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

from pm import entities

PROMPT_FILENAME = "prompt.org"
PROJECTS_DIRNAME = "projects"
PROJECT_PREFIX = "proj-"
META_BLOCK = ":META:"
MAX_INCLUDE_BYTES = 64 * 1024

INCLUDE_RE = re.compile(r"^\s*#\+PM_INCLUDE:\s*(\S.*)$")
VARIABLE_RE = re.compile(r"[$]\{([a-zA-Z_][a-zA-Z0-9_]*)(?::(\d+))?\}")
CREDENTIAL_HINTS = ("id_rsa", "id_ed25519", ".env", "credential", "secret", "passwd", "shadow", ".pem", ".key")


class PromptError(Exception):
    """带 code 的明确失败（CLI 翻成 JSON/文本 + 退出码）。"""

    def __init__(self, code: str, message: str, exit_code: int = 2, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.extra = extra or {}


def prompt_path(library_root, scope: str) -> Path:
    scope = (scope or "global").strip() or "global"
    root = Path(library_root)
    if scope == "global":
        return root / PROMPT_FILENAME
    return root / PROJECTS_DIRNAME / (PROJECT_PREFIX + scope) / PROMPT_FILENAME


def include_expr(body: str) -> str:
    """块正文里的 #+PM_INCLUDE: 表达式（没有 ⇒ 空串 ⇒ 自由文本块）。"""
    for line in str(body or "").split("\n"):
        match = INCLUDE_RE.match(line)
        if match:
            return match.group(1).strip()
    return ""


def parse_blocks(text: str) -> list[dict]:
    """解析 org 正文成块列表（保真：块名与正文逐字节保留，便于无损回写）。"""
    blocks: list[dict] = []
    current: dict | None = None
    for line in str(text or "").split("\n"):
        match = re.match(r"^\* (\S.*)$", line)
        if match:
            current = {"name": match.group(1).strip(), "lines": []}
            blocks.append(current)
            continue
        if current is None:
            continue
        current["lines"].append(line)
    out = []
    for block in blocks:
        raw = block["lines"]
        # entities 写正文时按层级缩进（3 空格）⇒ 读回来去同一缩进，保证 §7 的"正文逐字节一致"
        indents = [len(l) - len(l.lstrip(" ")) for l in raw if l.strip()]
        if indents and min(indents) >= 3:
            cut = min(indents)
            raw = [l[cut:] if l.strip() else l for l in raw]
        body = "\n".join(raw).strip("\n")
        out.append({"name": block["name"], "text": body, "include": include_expr(body)})
    return out


def blocks_to_text(blocks) -> str:
    lines: list[str] = []
    for block in blocks or []:
        name = str(block.get("name") or "").strip()
        body = str(block.get("text") or "").strip("\n")
        if not name and not body:
            continue
        if name:
            lines.append("* " + name)
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def read_prompt(library_root, scope: str) -> dict:
    """读一份提示词：不存在 ⇒ revision 0 / exists False（首次保存创建文件）。"""
    path = prompt_path(library_root, scope)
    payload = {"scope": scope, "exists": path.is_file(), "revision": 0, "updatedAt": None,
               "savedBy": None, "idempotencyKey": None, "path": str(path), "blocks": [],
               "meta": {"auditCount": 0}}
    if not payload["exists"]:
        return payload
    text = entities.read_text(path)
    for line in text.split("\n"):
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith(":PM_REVISION:"):
            try:
                payload["revision"] = int(stripped.split(":", 2)[2].strip() or 0)
            except ValueError:
                payload["revision"] = 0
        elif upper.startswith(":PM_SAVED_BY:"):
            payload["savedBy"] = stripped.split(":", 2)[2].strip() or None
        elif upper.startswith(":PM_UPDATED_AT:"):
            payload["updatedAt"] = stripped.split(":", 2)[2].strip() or None
        elif upper.startswith(":PM_IDEMPOTENCY_KEY:"):
            payload["idempotencyKey"] = stripped.split(":", 2)[2].strip() or None
    payload["meta"]["auditCount"] = text.count('State "SAVED"')
    payload["blocks"] = [b for b in parse_blocks(text) if b["name"] != META_BLOCK]
    return payload


def project_paths(library_root, scope: str) -> list[str]:
    """该 scope 在 project.org 里声明的路径（#+PM_PATH: / :PM_PATHS:）。"""
    from pm import projects as projects_module

    return list(projects_module.paths_by_project(library_root).get(scope, []))


def expand_variables(expr: str, *, library_root, scope: str, dsh_home: str = "") -> str:
    """把 ${path} / ${path:N} / ${root} / ${project} / ${dsh_home} 纯字符串替换掉。"""
    paths = project_paths(library_root, scope)
    values = {
        "root": str(Path(library_root)), "project": scope,
        "dsh_home": dsh_home or os.environ.get("DSH_HOME", "") or str(Path.home() / ".dsh"),
    }
    if paths:
        values["path"] = paths[0]

    def _replace(match: re.Match) -> str:
        name, index = match.group(1), match.group(2)
        if name == "path":
            if index is None:
                if not paths:
                    raise PromptError("PATH_UNDECLARED", "项目 " + scope + " 没有声明 #+PM_PATH:，路径变量无法展开")
                return paths[0]
            position = int(index) - 1
            if position < 0 or position >= len(paths):
                raise PromptError("PATH_UNDECLARED", "路径变量索引超出声明条数（" + str(len(paths)) + "）")
            return paths[position]
        if name not in values:
            raise PromptError("UNKNOWN_VARIABLE", "不认识的变量（v1 只有 path/path:N/root/project/dsh_home）")
        return values[name]

    return VARIABLE_RE.sub(_replace, expr)


# ---------------------------------------------------------------- 渲染（已填块顺序拼接）

def render_blocks(library_root, scope: str, blocks, *, dsh_home: str = "") -> dict:
    """把已填块按顺序渲染：自由文本直出；引用文档按四条红线展开并标注来源。

    本函数是**纯数据层**（不读 hook 输出、不断言"模型会看到什么"）—— 与 内部记录/25 §4 的口径一致。
    """
    out: list[str] = []
    detail: list[dict] = []
    for block in blocks or []:
        name = str(block.get("name") or "").strip()
        body = str(block.get("text") or "").strip("\n")
        if not name and not body:
            continue                      # 空块不进渲染
        expr = include_expr(body) or str(block.get("include") or "").strip()
        if expr:
            info = expand_include(expr, library_root=library_root, scope=scope, dsh_home=dsh_home)
            detail.append({"name": name, "expression": info["expression"], "path": info["path"],
                           "lines": info["lines"], "bytes": info["bytes"],
                           "truncated": info["truncated"], "ok": info["ok"], "reason": info["reason"]})
            out.append("# " + name)
            if info["ok"]:
                mark = "（已截断：超过 64 KB 上限）" if info["truncated"] else ""
                out.append("↳ " + info["expression"] + " · 已展开 " + str(info["lines"]) + " 行 / "
                           + ("%.1f" % (info["bytes"] / 1024.0)) + " KB（上限 64 KB）" + mark)
                out.append(info["text"].rstrip("\n"))
            else:
                out.append("↳ " + info["expression"])
                out.append("⚠ 展开失败：" + info["reason"])
        else:
            detail.append({"name": name, "expression": "", "path": None,
                           "lines": len(body.splitlines()), "bytes": len(body.encode("utf-8")),
                           "truncated": False, "ok": True, "reason": ""})
            out.append("# " + name)
            out.append(body)
        out.append("")
    text = "\n".join(out).rstrip("\n")
    return {"scope": scope, "text": text, "bytes": len(text.encode("utf-8")), "blocks": detail}


def get_prompt(library_root, scope: str) -> dict:
    """§6 的 GET 载荷：**只有** scope/exists/revision/updatedAt/savedBy/blocks（不含注入侧字段 ✗）。"""
    data = read_prompt(library_root, scope)
    return {"scope": data["scope"], "exists": data["exists"], "revision": data["revision"],
            "updatedAt": data["updatedAt"], "savedBy": data["savedBy"], "blocks": data["blocks"]}


# ---------------------------------------------------------------- CLI

def command_prompt_get(args) -> int:
    """pm prompt get --scope <key> [--json] [--render]"""
    json_mode = bool(getattr(args, "json", False))
    from pm import config as config_module
    from pm.layout import Layout

    try:
        cfg, warnings = config_module.load(getattr(args, "config", None))
    except Exception as exc:
        return _cli_fail("CONFIG_INVALID", str(exc), json_mode)
    layout = Layout(cfg.library)
    scope = str(getattr(args, "scope", None) or "global")
    try:
        payload = get_prompt(layout.root, scope)
        extra = None
        if getattr(args, "render", False):
            extra = render_blocks(layout.root, scope, payload["blocks"], dsh_home=cfg.dsh_home if hasattr(cfg, "dsh_home") else "")
    except PromptError as exc:
        return _cli_fail(exc.code, exc.message, json_mode, exc.exit_code)
    if json_mode:
        body = {"ok": True, "data": payload}
        if extra is not None:
            body["render"] = extra
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    print("scope=" + payload["scope"] + " exists=" + ("yes" if payload["exists"] else "no")
          + " revision=" + str(payload["revision"])
          + (" savedBy=" + str(payload["savedBy"]) if payload["savedBy"] else "")
          + (" updatedAt=" + str(payload["updatedAt"]) if payload["updatedAt"] else ""))
    for block in payload["blocks"]:
        kind = "引用文档" if block.get("include") else "自由文本"
        print("  - " + block["name"] + " [" + kind + "]"
              + (" " + block["include"] if block.get("include") else ""))
    if extra is not None:
        print("")
        print(extra["text"])
    return 0


def command_prompt_set(args) -> int:
    """pm prompt set：尚未接线（见本文件 docstring 的写路径说明）。"""
    return _cli_fail("NOT_IMPLEMENTED", "prompt set 尚未接线：写路径要复用 entities，"
                                       "而 内部记录/25 §2 的块标题格式（无 :ID:）与 entities 的实体模型冲突，"
                                       "待裁定后接线（pm prompt get 已可用）", bool(getattr(args, "json", False)))


def _cli_fail(code: str, message: str, json_mode: bool, exit_code: int = 2, extra: dict | None = None) -> int:
    import sys as _sys

    if json_mode:
        error: dict = {"code": code, "message": message}
        if extra:
            error.update({k: v for k, v in extra.items() if k not in error})
        print(json.dumps({"ok": False, "error": error}, ensure_ascii=False, indent=2))
    else:
        print("pm prompt: [" + code + "] " + message, file=_sys.stderr)
    return exit_code


def register_cli(subparsers) -> None:
    """注册 pm prompt get|set（域模块表在 cli.py 的 DOMAIN_MODULES 里）。"""
    parser = subparsers.add_parser("prompt", help="初始系统提示词（人写；数据层）")
    sub = parser.add_subparsers(dest="prompt_command")
    get_parser = sub.add_parser("get", help="读一份提示词（缺文件 ⇒ exists=false / revision=0，exit 0）")
    get_parser.add_argument("--scope", default="global", help="项目 key（默认 global）")
    get_parser.add_argument("--render", action="store_true", help="顺带渲染（引用文档按四条红线展开）")
    get_parser.add_argument("--json", action="store_true", help="输出 JSON（§6 六字段）")
    from pm.cli import _add_common_options

    _add_common_options(get_parser, as_defaults=True)
    get_parser.set_defaults(handler=command_prompt_get)
    # ⚠️ set 暂**不注册**：写路径要复用 entities，而 内部记录/25 §2 的块格式与 entities 的实体模型冲突，
    #    裁定 (a)「每块带 :ID: 抽屉」后接线。现在注册一个 NOT_IMPLEMENTED 的子命令会：
    #    ① 让 L4（每条 CLI 路径都必须出现在 skill 里）逼我们把一个**用不了**的命令写进 skill ✗；
    #    ② 让 dsh-plugin 把它当成已实现 ✗。⇒ 先不暴露，接线时再注册（函数 command_prompt_set 保留）。
    _ = command_prompt_set



def expand_include(expr: str, *, library_root, scope: str, dsh_home: str = "") -> dict:
    """按 内部记录/25 §3.5 四条红线展开一个引用。

    返回 {ok, expression, path, text, lines, bytes, truncated, reason}；
    失败**不抛异常**（渲染层要逐块显示 ⚠ 展开失败），原因写进 reason。
    """
    item = {"ok": False, "expression": expr, "path": None, "text": "", "lines": 0,
            "bytes": 0, "truncated": False, "reason": ""}
    if ".." in str(expr):
        item["reason"] = "路径越界：含 .. —— 解析后必须落在项目声明路径之内，拒绝读取"
        return item
    try:
        expanded = expand_variables(expr, library_root=library_root, scope=scope, dsh_home=dsh_home)
    except PromptError as exc:
        item["reason"] = exc.message
        return item
    target = Path(expanded)
    if not target.is_absolute():
        target = Path(library_root) / target
    if any(hint in target.name.lower() for hint in CREDENTIAL_HINTS):
        item["reason"] = "拒绝读取凭据类文件（文件名命中黑名单：" + target.name + "）"
        return item
    try:
        resolved = target.expanduser().resolve(strict=False)
    except OSError:
        resolved = target.expanduser()
    allowed = [Path(p).expanduser() for p in project_paths(library_root, scope)]
    within = any(str(resolved) == str(p) or str(resolved).startswith(str(p) + os.sep) for p in allowed)
    if not within:
        item["reason"] = "路径越界：解析后不在项目声明路径之内（" + str(resolved) + "），拒绝读取"
        return item
    item["path"] = str(resolved)
    try:
        real = resolved.resolve(strict=True)
    except OSError:
        item["reason"] = "⚠ 展开失败：文件不存在"
        return item
    if not real.is_file():
        item["reason"] = "⚠ 展开失败：不是普通文件（目录/设备/管道）"
        return item
    try:
        data = real.read_bytes()
    except OSError as exc:
        item["reason"] = "⚠ 展开失败：读取失败（" + exc.__class__.__name__ + "）"
        return item
    if len(data) > MAX_INCLUDE_BYTES:
        data = data[:MAX_INCLUDE_BYTES]
        item["truncated"] = True
    text = data.decode("utf-8", "replace")
    item.update({"ok": True, "text": text, "bytes": len(data), "lines": len(text.splitlines())})
    return item


# ---------------------------------------------------------------- (a) 布局：节 + 实体块
# 依据 Lead 2026-10-18 裁定 (a)：每个内容块各带 :ID: 抽屉 ⇒ 复用 entities.apply_change（CAS/原子写/审计/幂等）。
# 文件形态： #+TITLE / #+PM_SCOPE + 「* 提示词」节 + 「** prompt-meta」（:META: t 机器标记 + :ID: prompt-<scope>）
#           + 每个内容块一个「** 块名」实体（:ID: 由客户端带来或现场生成）。
SECTION = "提示词"

def _gen_block_id(scope: str, name: str, taken: set) -> str:
    """生成块 :ID:（新块没有客户端 :ID: 时用）。

    用逐字符 isalnum() 拼 slug：不写正则转义（之前手写字符区间的转义写法把中文清空 ⇒ 同名块撞 id）。
    str.isalnum() 对中文为真 ⇒ 中文块名能进 id。
    """
    pieces, previous_dash = [], False
    for ch in str(name or ""):
        if ch.isalnum():
            pieces.append(ch)
            previous_dash = False
        elif not previous_dash:
            pieces.append("-")
            previous_dash = True
    slug = "".join(pieces).strip("-") or "b"
    candidate, index = "prompt-" + scope + "-" + slug, 1
    while candidate in taken:
        index += 1
        candidate = "prompt-" + scope + "-" + slug + "-" + str(index)
    return candidate


def read_document(library_root, scope: str) -> dict:
    """用 entities 读文档：返回 {exists, revision, savedBy, updatedAt, idempotencyKey, blocks, metaId}。"""
    path = prompt_path(library_root, scope)
    payload = {"exists": path.is_file(), "revision": 0, "savedBy": None, "updatedAt": None,
               "idempotencyKey": None, "blocks": [], "metaId": "prompt-" + scope, "path": path}
    if not payload["exists"]:
        return payload
    text = entities.read_text(path)
    raw_blocks = parse_entity_blocks(text)
    for block in raw_blocks:
        if block["name"] == "prompt-meta":
            continue
        payload["blocks"].append(block)
    meta = next((b for b in raw_blocks if b["name"] == "prompt-meta"), None)
    if meta is not None:
        payload["revision"] = int(meta.get("revision") or 0)
        payload["savedBy"] = meta.get("savedBy")
        payload["updatedAt"] = meta.get("updatedAt")
        payload["idempotencyKey"] = meta.get("idempotencyKey")
    return payload

def parse_entity_blocks(text: str) -> list[dict]:
    """解析 (a) 布局：每个「** 名称」一个块，块内抽屉给 :ID:/:PM_REVISION:/:PM_SAVED_*，其余为正文。"""
    blocks: list[dict] = []
    current: dict | None = None
    in_drawer = False
    in_properties = False
    for line in str(text or "").split("\n"):
        match = re.match(r"^\*\* (\S.*)$", line)
        if match:
            current = {"name": match.group(1).strip(), "id": "", "revision": 0, "savedBy": None,
                       "updatedAt": None, "idempotencyKey": None, "lines": []}
            blocks.append(current)
            in_drawer = False
            continue
        if current is None:
            continue
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith(":PROPERTIES:") or upper.startswith(":LOGBOOK:"):
            in_drawer = True
            in_properties = upper.startswith(":PROPERTIES:")
            continue
        if upper == ":END:":
            in_drawer = False
            in_properties = False
            continue
        if in_drawer:
            # 抽屉里的东西**都不是正文**：属性行只在 :PROPERTIES: 段解析，LOGBOOK 条目一并跳过
            # （曾漏掉 ⇒ 正文被 "- State ..." 污染 ✗）
            if in_properties and stripped.startswith(":"):
                matched = re.match(r"^:([A-Za-z0-9_]+):\s*(.*)$", stripped)
                if matched:
                    key = matched.group(1).upper()
                    value = matched.group(2).strip()
                    if key == "ID":
                        current["id"] = value
                    elif key == "PM_REVISION":
                        try:
                            current["revision"] = int(value or 0)
                        except ValueError:
                            current["revision"] = 0
                    elif key == "PM_SAVED_BY":
                        current["savedBy"] = value or None
                    elif key == "PM_SAVED_AT":
                        current["updatedAt"] = value or None
                    elif key == "PM_IDEMPOTENCY_KEY":
                        current["idempotencyKey"] = value or None
            continue
        if stripped:
            current["lines"].append(line)
    for block in blocks:
        raw = block["lines"]
        indents = [len(l) - len(l.lstrip(" ")) for l in raw if l.strip()]
        if indents and min(indents) >= 3:
            cut = min(indents)
            raw = [l[cut:] if l.strip() else l for l in raw]
        body = "\n".join(raw).strip("\n")
        block["text"] = body
        block["include"] = include_expr(body)
        block.pop("lines", None)
    return blocks

def get_prompt_v2(library_root, scope: str) -> dict:
    """§6 六字段（GET）；块带 id（客户端按 :ID: 匹配用），不返回 prompt-meta。"""
    data = read_document(library_root, scope)
    return {"scope": scope, "exists": data["exists"], "revision": data["revision"],
            "updatedAt": data["updatedAt"], "savedBy": data["savedBy"], "blocks": data["blocks"]}

def validate_blocks(blocks) -> list[str]:
    """保存**前**的块校验（用户设计 内部记录/25 §3）：空名 ⇒ 报错并指出第几块；保留名 ⇒ 报错；重名 ⇒ 只提醒。

    必须在**任何写入之前**调用（否则会留下只有 prompt-meta、没有块的半成品 ✗）。
    """
    warnings: list[str] = []
    seen: set = set()
    for position, block in enumerate(blocks or [], start=1):
        name = str(block.get("name") or "").strip()
        if not name:
            raise PromptError("EMPTY_BLOCK_NAME", "第 " + str(position) + " 块没有名字：块名不能为空，请填写后再保存")
        if name == "prompt-meta":
            raise PromptError("RESERVED_BLOCK_NAME", "块名 prompt-meta 是保留名（元数据块），请换一个")
        if name in seen:
            warnings.append("第 " + str(position) + " 块的名字与前面某块重名：" + name + "（可保存；如非本意建议改名）")
        seen.add(name)
    return warnings


def set_prompt(library_root, scope: str, blocks, *, expected_revision=None, actor: str = "ai",
               reason: str = "", idempotency_key: str | None = None, dry_run: bool = False) -> dict:
    """(a) 写路径：CAS + 原子写 + 审计 + 幂等全部走 entities；返回 {revision, file, ...}。"""
    import datetime as _dt

    root = Path(library_root)
    path = prompt_path(root, scope)
    current = read_document(root, scope)
    meta_id = "prompt-" + scope
    now_iso = _dt.datetime.now().astimezone().isoformat()
    warnings = validate_blocks(blocks)      # ★ 先校验再写：空名/保留名在**任何写入之前**拦下
    if current["exists"] and idempotency_key and current["idempotencyKey"] == idempotency_key:
        # §7：同一 idempotencyKey 重放 ⇒ 不产生第二次变更（且**不**因 CAS 过期而报冲突）
        return {"scope": scope, "file": str(path), "revision": int(current["revision"]),
                "changed": 0, "idempotent": True, "dryRun": bool(dry_run)}
    if current["exists"]:
        if actor == "ai":
            raise PromptError("AI_CANNOT_EDIT", "已有提示词只有人能改（人工文件）；AI 不得改写 prompts")
        if expected_revision is None:
            raise PromptError("REVISION_REQUIRED", "已存在的提示词必须带 --expected-revision（CAS，防盲写）")
        if int(expected_revision) != int(current["revision"]):
            raise PromptError("REVISION_CONFLICT",
                              "revision 冲突：当前 " + str(current["revision"]) + "，请求基于 " + str(expected_revision),
                              exit_code=3, extra={"currentRevision": current["revision"]})
    wanted_ids = {str(b.get("id") or "") for b in blocks if str(b.get("id") or "")}
    stale = [b["name"] for b in current["blocks"] if b["id"] and b["id"] not in wanted_ids]
    if stale:
        raise PromptError("BLOCK_DELETE_UNSUPPORTED",
                          "本切片不支持删除块（被省略的块：" + "、".join(stale) + "）；请保留或改名")
    taken = {b["id"] for b in current["blocks"] if b["id"]}
    by_id = {b["id"]: b for b in current["blocks"] if b["id"]}
    created = None
    if not current["exists"]:
        props_new = {"META": "t", "PM_SAVED_BY": actor, "PM_SAVED_AT": now_iso}
        if idempotency_key:
            props_new["PM_IDEMPOTENCY_KEY"] = idempotency_key     # 存抽屉 ⇒ 下次同 key 才算重放
        created = entities.create_entity(path, entity_id=meta_id, kind="prompt", status="ACTIVE",
                                         headline="prompt-meta", section=SECTION,
                                         properties=props_new, body_lines=[], actor=actor,
                                         dry_run=dry_run, idempotency_key=idempotency_key)
    changed = 0
    for block in blocks:
        name = str(block.get("name") or "").strip()      # 校验已在顶部做完（空名/保留名/重名）
        body = str(block.get("text") or "").strip("\n")
        lines = [line for line in body.split("\n")] if body else []
        block_id = str(block.get("id") or "")
        if block_id and block_id in by_id:
            # 用户设计（内部记录/25 §3）：块**身份是 :ID:** ⇒ 可改名（只改标题行，id/审计/CAS 不受影响 ✓）。
            # entities 的 replace_lines 支持 offset 0 = 标题行（要求同层级 ⇒ 前缀保持 "** "）✓
            rename = {0: "** " + name} if name != by_id[block_id]["name"] else None
            op = entities.apply_change(path, block_id, expected_revision=int(by_id[block_id]["revision"]),
                                       replace_lines=rename, replace_body=lines,
                                       actor=actor, reason=reason, dry_run=dry_run,
                                       idempotency_key=(idempotency_key + ":" + block_id) if idempotency_key else None)
            changed += 1 if getattr(op, "changed", False) else 0
        else:
            block_id = block_id or _gen_block_id(scope, name, taken)
            op = entities.create_entity(path, entity_id=block_id, kind="prompt", status="ACTIVE",
                                        headline=name, section=SECTION, body_lines=lines,
                                        actor=actor, dry_run=dry_run,
                                        idempotency_key=(idempotency_key + ":" + block_id) if idempotency_key else None)
            changed += 1 if getattr(op, "created", True) else 0
            taken.add(block_id)
    if not current["exists"]:
        return {"scope": scope, "file": str(path), "revision": int(getattr(created, "revision", 1) or 1),
                "changed": changed, "warnings": warnings,
                "idempotent": bool(getattr(created, "idempotent", False)),
                "dryRun": bool(dry_run)}
    meta_props = {"META": "t", "PM_SAVED_BY": actor, "PM_SAVED_AT": now_iso}
    if idempotency_key:
        meta_props["PM_IDEMPOTENCY_KEY"] = idempotency_key
    # ★ 派生 key：entities 的幂等键绑定单实体，若这里用原 key，会被 create/上一次写判成"重放" ⇒ **meta bump 被跳过** ✗
    #   （Lead 2026-10-18 的 RUN A/C：内容改了但文件级 revision 不动 ⇒ CAS 护栏失效 ✗）
    result = entities.apply_change(path, meta_id, expected_revision=int(current["revision"]),
                                   set_properties=meta_props, actor=actor, reason=reason,
                                   dry_run=dry_run,
                                   idempotency_key=(idempotency_key + ":meta") if idempotency_key else None)
    return {"scope": scope, "file": str(path), "revision": int(getattr(result, "revision", 0) or 0),
            "changed": changed, "warnings": warnings, "idempotent": False, "dryRun": bool(dry_run)}




# ---------------------------------------------------------------- 导出记录（派生物：<lib>/.local/prompt-exports.json）
# 依据 内部记录/25 §5.1 / §6（用户领地，只读）：记录是派生物，绝不写 projects/**；文件可丢可重建。

EXPORTS_FILENAME = "prompt-exports.json"
EXPORTS_VERSION = 1
SNAPSHOT_LIMIT = 240          # 快照用于搜索；超长截断并**显式标注** snapshotTruncated
EXPORT_FMTS = ("md", "txt", "org")


def exports_path(library_root) -> Path:
    return Path(library_root) / ".local" / EXPORTS_FILENAME


def _read_exports(library_root) -> dict:
    """读记录文件：缺失 ⇒ 空列表；**损坏 ⇒ 显式报错**（绝不静默清空）。"""
    path = exports_path(library_root)
    if not path.is_file():
        return {"version": EXPORTS_VERSION, "exports": []}
    try:
        text = entities.read_text(path)
        data = json.loads(text)
    except Exception as exc:
        raise PromptError("PROMPT_EXPORTS_CORRUPT",
                          "导出记录文件损坏（" + str(path) + "）：" + exc.__class__.__name__ + "；"
                          "请修复或删除该文件后重试（不会被静默清空）")
    if not isinstance(data, dict) or not isinstance(data.get("exports"), list):
        raise PromptError("PROMPT_EXPORTS_CORRUPT",
                          "导出记录文件结构不对（" + str(path) + "）：应为 {version, exports:[...]}；"
                          "不会被静默清空")
    return data


def _write_exports(library_root, data: dict) -> None:
    """原子写（临时文件 + os.replace）：中途崩不留下半截 JSON。"""
    path = exports_path(library_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + chr(10), encoding="utf-8")
    os.replace(tmp, path)


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _new_export_id() -> str:
    import datetime as _dt
    import secrets
    stamp = _dt.datetime.now().strftime("%Y%m%d%H%M%S")
    return "exp-" + stamp + "-" + secrets.token_hex(3)


def _public_record(record: dict) -> dict:
    """对外记录：**严格按 §5.1 字段**（内部 idempotencyKey 不外露）。"""
    return {key: record.get(key) for key in ("id", "project", "path", "name", "fmt", "bytes",
                                             "blocks", "savedAt", "snapshot", "blocksData")}


def list_exports(library_root, *, scope: str | None = None, q: str = "") -> dict:
    """只读列表：按项目筛选（ALL/空 = 不筛），q 匹配 name/path/snapshot（大小写不敏感）。"""
    data = _read_exports(library_root)
    items = [_public_record(rec) for rec in data["exports"]]
    wanted = (scope or "").strip()
    if wanted and wanted.upper() != "ALL":
        items = [rec for rec in items if rec.get("project") == wanted]
    needle = (q or "").strip().lower()
    if needle:
        def _hit(rec: dict) -> bool:
            hay = ((rec.get("name") or "") + chr(10) + (rec.get("path") or "") + chr(10) + (rec.get("snapshot") or "")).lower()
            return needle in hay
        items = [rec for rec in items if _hit(rec)]
    items.sort(key=lambda rec: (rec.get("savedAt") or "", rec.get("id") or ""), reverse=True)
    return {"scope": wanted or "ALL", "q": (q or ""), "count": len(items), "items": items}


def add_export(library_root, payload: dict) -> dict:
    """新增一条导出记录（幂等：同 idempotencyKey 重放 ⇒ 返回同一条、不新增）。"""
    if not isinstance(payload, dict):
        raise PromptError("PROMPT_EXPORT_BAD_PAYLOAD", "导出记录 payload 必须是对象")
    project = str(payload.get("scope") or payload.get("project") or "").strip()
    if not project:
        raise PromptError("PROMPT_EXPORT_BAD_PAYLOAD", "缺少 scope（记录的项目 key）")
    text = str(payload.get("text") or "")
    fmt = str(payload.get("fmt") or "md").strip().lower()
    if fmt not in EXPORT_FMTS:
        raise PromptError("PROMPT_EXPORT_BAD_FMT", "不支持的导出格式：" + fmt + "（只允许 md/txt/org）")
    blocks = payload.get("blocks")
    if isinstance(blocks, list):
        blocks_data = blocks
        block_count = len(blocks)
    else:
        blocks_data = payload.get("blocksData") if isinstance(payload.get("blocksData"), list) else []
        block_count = int(payload.get("blocks") or len(blocks_data) or 0)
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, str) or not snapshot:
        snapshot = text[:SNAPSHOT_LIMIT]
    truncated = bool(payload.get("snapshotTruncated")) or len(snapshot) > SNAPSHOT_LIMIT or len(text) > len(snapshot)
    if len(snapshot) > SNAPSHOT_LIMIT:
        snapshot = snapshot[:SNAPSHOT_LIMIT]
    key = str(payload.get("idempotencyKey") or "").strip()
    data = _read_exports(library_root)
    if key:
        for rec in data["exports"]:
            if rec.get("idempotencyKey") == key:
                return {"record": _public_record(rec), "idempotent": True}
    record = {
        "id": _new_export_id(),
        "project": project,
        "path": str(payload.get("path") or ""),
        "name": str(payload.get("name") or ("prompt." + fmt)),
        "fmt": fmt,
        "bytes": len(text.encode("utf-8")) if text else int(payload.get("bytes") or 0),
        "blocks": block_count,
        "savedAt": _now_iso(),
        "snapshot": snapshot,
        "snapshotTruncated": truncated,
        "blocksData": blocks_data,
    }
    if key:
        record["idempotencyKey"] = key
    data["exports"].append(record)
    data["version"] = EXPORTS_VERSION
    _write_exports(library_root, data)
    return {"record": _public_record(record), "idempotent": False}


def delete_export(library_root, export_id: str) -> dict:
    """删除一条记录（**只删记录**：不动导出文件、不动 prompt.org）。"""
    wanted = str(export_id or "").strip()
    if not wanted:
        raise PromptError("PROMPT_EXPORT_BAD_PAYLOAD", "缺少 --id（要删除的记录 id）")
    data = _read_exports(library_root)
    kept = [rec for rec in data["exports"] if rec.get("id") != wanted]
    if len(kept) == len(data["exports"]):
        raise PromptError("PROMPT_EXPORT_NOT_FOUND", "没有 id 为 " + wanted + " 的导出记录")
    data["exports"] = kept
    _write_exports(library_root, data)
    return {"deleted": 1, "id": wanted}


# ---------------------------------------------------------------- 只读清单（页面「从已保存的提示词复制」用）

def _prompt_files(root: Path):
    """枚举库里的提示词文件：先 global（库根 prompt.org），再各项目。"""
    yield "global", prompt_path(root, "global")
    projects_dir = root / PROJECTS_DIRNAME
    if projects_dir.is_dir():
        for child in sorted(projects_dir.iterdir()):
            if child.is_dir() and child.name.startswith(PROJECT_PREFIX):
                scope = child.name[len(PROJECT_PREFIX):]
                yield scope, prompt_path(root, scope)


def list_saved_prompts(library_root) -> dict:
    """**只读**清单：哪些项目（以及 global）已经保存过提示词。

    给页面「填充 ③ 从已保存的提示词复制」用；单项目的复制源仍走 GET（pm prompt get）✓。
    只列**已存在**的（onlySaved=true ⇒ 语义写死在载荷里，别让调用方猜）；按 global 优先、其余按 key 排序。
    """
    root = Path(library_root)
    items = []
    for scope, path in _prompt_files(root):
        if not path.is_file():
            continue
        data = get_prompt_v2(root, scope)
        items.append({
            "scope": scope, "revision": data["revision"], "updatedAt": data["updatedAt"],
            "savedBy": data["savedBy"], "blockCount": len(data["blocks"]),
            "path": str(path.relative_to(root)),
        })
    return {"onlySaved": True, "count": len(items), "items": items}


def command_prompt_list(args) -> int:
    """pm prompt list [--json]：只读清单（默认输出 JSON —— 它是给页面/脚本用的契约入口）。"""
    json_mode = bool(getattr(args, "json", False)) or True
    from pm import config as config_module
    from pm.layout import Layout

    try:
        cfg, _warnings = config_module.load(getattr(args, "config", None))
    except Exception as exc:
        return _cli_fail("CONFIG_INVALID", str(exc), True)
    layout = Layout(cfg.library)
    try:
        payload = list_saved_prompts(layout.root)
    except PromptError as exc:
        return _cli_fail(exc.code, exc.message, True, exc.exit_code)
    print(json.dumps({"ok": True, "data": payload}, ensure_ascii=False, indent=2))
    return 0



# ---------------------------------------------------------------- 导出记录的 CLI（argv-only：无 stdin）

def _load_export_payload(args) -> dict:
    """payload 三通道：--payload-file PATH / --payload-b64 B64 / 逐项 flag（后者覆盖前者）。"""
    import base64

    payload: dict = {}
    file_arg = getattr(args, "payload_file", None)
    b64_arg = getattr(args, "payload_b64", None)
    try:
        if file_arg:
            payload = json.loads(Path(file_arg).read_text(encoding="utf-8"))
        elif b64_arg:
            payload = json.loads(base64.b64decode(b64_arg.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise PromptError("PROMPT_EXPORT_BAD_PAYLOAD", "payload 解析失败：" + exc.__class__.__name__ + ": " + str(exc))
    if not isinstance(payload, dict):
        raise PromptError("PROMPT_EXPORT_BAD_PAYLOAD", "payload 必须是 JSON 对象")
    for flag, key in (("scope", "scope"), ("path", "path"), ("name", "name"), ("fmt", "fmt"),
                      ("text", "text"), ("snapshot", "snapshot"), ("idempotency_key", "idempotencyKey")):
        value = getattr(args, flag, None)
        if value not in (None, ""):
            payload[key] = value
    text_file = getattr(args, "text_file", None)
    if text_file and "text" not in payload:
        payload["text"] = Path(text_file).read_text(encoding="utf-8")
    blocks_json = getattr(args, "blocks_json", None)
    if blocks_json:
        try:
            parsed = json.loads(blocks_json)
        except ValueError as exc:
            raise PromptError("PROMPT_EXPORT_BAD_PAYLOAD", "--blocks-json 不是合法 JSON：" + str(exc))
        payload["blocksData"] = parsed if isinstance(parsed, list) else []
    return payload


def command_prompt_exports_list(args) -> int:
    from pm import config as config_module
    from pm.layout import Layout

    try:
        cfg, _warnings = config_module.load(getattr(args, "config", None))
    except Exception as exc:
        return _cli_fail("CONFIG_INVALID", str(exc), True)
    layout = Layout(cfg.library)
    try:
        payload = list_exports(layout.root, scope=getattr(args, "scope", None), q=getattr(args, "q", "") or "")
    except PromptError as exc:
        return _cli_fail(exc.code, exc.message, True, exc.exit_code)
    print(json.dumps({"ok": True, "data": payload}, ensure_ascii=False, indent=2))
    return 0


def command_prompt_exports_add(args) -> int:
    from pm import config as config_module
    from pm.layout import Layout

    try:
        cfg, _warnings = config_module.load(getattr(args, "config", None))
    except Exception as exc:
        return _cli_fail("CONFIG_INVALID", str(exc), True)
    layout = Layout(cfg.library)
    try:
        payload = _load_export_payload(args)
        result = add_export(layout.root, payload)
    except PromptError as exc:
        return _cli_fail(exc.code, exc.message, True, exc.exit_code)
    print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
    return 0


def command_prompt_exports_delete(args) -> int:
    from pm import config as config_module
    from pm.layout import Layout

    try:
        cfg, _warnings = config_module.load(getattr(args, "config", None))
    except Exception as exc:
        return _cli_fail("CONFIG_INVALID", str(exc), True)
    layout = Layout(cfg.library)
    try:
        result = delete_export(layout.root, getattr(args, "id", None))
    except PromptError as exc:
        return _cli_fail(exc.code, exc.message, True, exc.exit_code)
    print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------- CLI（末尾重定义：v2 读写 + 完整 set）

def command_prompt_get(args) -> int:
    """pm prompt get --scope <key> [--render] [--json]（§6 六字段；缺文件 ⇒ exists=false / revision=0，exit 0）"""
    json_mode = bool(getattr(args, "json", False))
    from pm import config as config_module
    from pm.layout import Layout

    try:
        cfg, _warnings = config_module.load(getattr(args, "config", None))
    except Exception as exc:
        return _cli_fail("CONFIG_INVALID", str(exc), json_mode)
    layout = Layout(cfg.library)
    scope = str(getattr(args, "scope", None) or "global")
    try:
        payload = get_prompt_v2(layout.root, scope)
        extra = None
        if getattr(args, "render", False):
            extra = render_blocks(layout.root, scope, payload["blocks"],
                                  dsh_home=getattr(cfg, "dsh_home", "") or "")
    except PromptError as exc:
        return _cli_fail(exc.code, exc.message, json_mode, exc.exit_code)
    if json_mode:
        body = {"ok": True, "data": payload}
        if extra is not None:
            body["render"] = extra
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    print("scope=" + payload["scope"] + " exists=" + ("yes" if payload["exists"] else "no")
          + " revision=" + str(payload["revision"]))
    for block in payload["blocks"]:
        print("  - [" + (block.get("id") or "?") + "] " + block["name"]
              + (" [" + block["include"] + "]" if block.get("include") else ""))
    if extra is not None:
        print("")
        print(extra["text"])
    return 0


def _blocks_from_args(args) -> list[dict]:
    """三种入口同一条路：可重复 --block-json（路由用，无 stdin）/ --blocks-json（整数组）/ --file -（终端）。"""
    blocks: list[dict] = []
    for raw in getattr(args, "block_json", None) or []:
        try:
            item = json.loads(raw)
        except ValueError as exc:
            raise PromptError("BLOCK_JSON_INVALID", "--block-json 不是合法 JSON：" + str(exc))
        if not isinstance(item, dict):
            raise PromptError("BLOCK_JSON_INVALID", "--block-json 必须是对象 {name,text,id?}")
        blocks.append(item)
    raw_array = getattr(args, "blocks_json", None)
    if raw_array:
        try:
            parsed = json.loads(raw_array)
        except ValueError as exc:
            raise PromptError("BLOCK_JSON_INVALID", "--blocks-json 不是合法 JSON：" + str(exc))
        if not isinstance(parsed, list):
            raise PromptError("BLOCK_JSON_INVALID", "--blocks-json 必须是数组")
        blocks.extend([item for item in parsed if isinstance(item, dict)])
    file_arg = getattr(args, "file", None)
    if file_arg:
        text = sys.stdin.read() if file_arg == "-" else Path(file_arg).read_text(encoding="utf-8")
        for block in parse_entity_blocks(text):
            if block["name"] == "prompt-meta":
                continue
            blocks.append(block)
    return blocks


def command_prompt_set(args) -> int:
    """pm prompt set：可重复 --block-json / --blocks-json / --file - ；CAS + 审计 + 幂等走 entities。"""
    json_mode = bool(getattr(args, "json", False))
    from pm import config as config_module
    from pm.layout import Layout

    try:
        cfg, _warnings = config_module.load(getattr(args, "config", None))
    except Exception as exc:
        return _cli_fail("CONFIG_INVALID", str(exc), json_mode)
    layout = Layout(cfg.library)
    scope = str(getattr(args, "scope", None) or "global")
    try:
        blocks = _blocks_from_args(args)
    except PromptError as exc:
        return _cli_fail(exc.code, exc.message, json_mode, exc.exit_code)
    if not blocks:
        return _cli_fail("BLOCKS_REQUIRED", "至少要给一个块（--block-json / --blocks-json / --file -）", json_mode)
    try:
        result = set_prompt(layout.root, scope, blocks,
                            expected_revision=getattr(args, "expected_revision", None),
                            actor=str(getattr(args, "actor", None) or "ai"),
                            reason=str(getattr(args, "reason", None) or ""),
                            idempotency_key=getattr(args, "idempotency_key", None),
                            dry_run=bool(getattr(args, "dry_run", False)))
    except PromptError as exc:
        return _cli_fail(exc.code, exc.message, json_mode, exc.exit_code,
                         extra=getattr(exc, "extra", None))
    if json_mode:
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
        return 0
    print("saved scope=" + scope + " revision=" + str(result["revision"]) + " changed=" + str(result["changed"]))
    return 0


def register_cli(subparsers) -> None:
    """注册 pm prompt get|set（域模块表在 cli.py 的 DOMAIN_MODULES 里）。"""
    from pm.cli import _add_common_options

    parser = subparsers.add_parser("prompt", help="初始系统提示词（人写；数据层）")
    sub = parser.add_subparsers(dest="prompt_command")
    get_parser = sub.add_parser("get", help="读一份提示词（缺文件 ⇒ exists=false / revision=0，exit 0）")
    get_parser.add_argument("--scope", default="global", help="项目 key（默认 global）")
    get_parser.add_argument("--render", action="store_true", help="顺带渲染（引用文档按四条红线展开）")
    get_parser.add_argument("--json", action="store_true", help="输出 JSON（§6 六字段）")
    _add_common_options(get_parser, as_defaults=True)
    get_parser.set_defaults(handler=command_prompt_get)
    exports_parser = sub.add_parser("exports", help="导出记录（派生物：<库>/.local/prompt-exports.json）")
    exports_sub = exports_parser.add_subparsers(dest="exports_command")
    ex_list = exports_sub.add_parser("list", help="列出导出记录（--scope 项目|ALL，--q 搜索 name/path/snapshot）")
    ex_list.add_argument("--scope", default="ALL", help="项目 key 或 ALL（默认 ALL）")
    ex_list.add_argument("--q", default="", help="搜索词（匹配 name/path/snapshot，大小写不敏感）")
    ex_list.add_argument("--json", action="store_true", help="输出 JSON（exports 恒输出 JSON，接受该参数以对齐路由）")
    _add_common_options(ex_list, as_defaults=True)
    ex_list.set_defaults(handler=command_prompt_exports_list)
    ex_add = exports_sub.add_parser("add", help="新增一条导出记录（幂等：同 --idempotency-key 重放返回同一条）")
    ex_add.add_argument("--payload-file", metavar="PATH", help="JSON payload 文件（POST body 形状，argv 友好）")
    ex_add.add_argument("--payload-b64", metavar="B64", help="base64(JSON payload)（argv 友好，避免 shell 引号）")
    ex_add.add_argument("--scope", help="项目 key（覆盖 payload.scope）")
    ex_add.add_argument("--path", help="导出目标路径（记录/建议用途）")
    ex_add.add_argument("--name", help="文件名（如 prompt.md）")
    ex_add.add_argument("--fmt", choices=("md", "txt", "org"), help="导出格式")
    ex_add.add_argument("--text", help="导出正文（短文本用；长文本请用 payload/b64/file）")
    ex_add.add_argument("--text-file", metavar="PATH", help="从文件读导出正文")
    ex_add.add_argument("--snapshot", help="内容快照（默认取正文前 240 字符，超长会标注 snapshotTruncated）")
    ex_add.add_argument("--blocks-json", metavar="JSON", help="块数组 JSON（供载入到编辑器）")
    ex_add.add_argument("--idempotency-key", metavar="KEY", help="幂等键：同 key 重放不新增")
    ex_add.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(ex_add, as_defaults=True)
    ex_add.set_defaults(handler=command_prompt_exports_add)
    ex_del = exports_sub.add_parser("delete", help="删除一条导出记录（只删记录，不动导出文件与 prompt.org）")
    ex_del.add_argument("--id", required=True, help="记录 id（exp-...）")
    ex_del.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(ex_del, as_defaults=True)
    ex_del.set_defaults(handler=command_prompt_exports_delete)
    list_parser = sub.add_parser("list", help="只读清单：哪些项目已保存过提示词（页面复制源用）")
    list_parser.add_argument("--json", action="store_true", help="输出 JSON（默认就是 JSON）")
    _add_common_options(list_parser, as_defaults=True)
    list_parser.set_defaults(handler=command_prompt_list)
    set_parser = sub.add_parser("set", help="写一份提示词（CAS + 审计 + 幂等；复用 entities）")
    set_parser.add_argument("--scope", default="global")
    set_parser.add_argument("--block-json", action="append", metavar="JSON",
                            help="一个块 {name,text,id?}（可重复；路由用，无需 stdin）")
    set_parser.add_argument("--blocks-json", metavar="JSON", help="整块数组 [{name,text,id?}]")
    set_parser.add_argument("--file", metavar="PATH", help="从 org 文件读块（- 表示 stdin；终端用）")
    set_parser.add_argument("--expected-revision", type=int, metavar="N", help="CAS：已存在时必须给")
    set_parser.add_argument("--actor", choices=("human", "ai"), default="ai", help="写入者（已存在 + ai ⇒ 拒绝）")
    set_parser.add_argument("--reason", default="", help="审计原因")
    set_parser.add_argument("--idempotency-key", metavar="KEY", help="同一 key 重放不产生第二次变更")
    set_parser.add_argument("--dry-run", action="store_true", help="只算不写")
    set_parser.add_argument("--json", action="store_true")
    _add_common_options(set_parser, as_defaults=True)
    set_parser.set_defaults(handler=command_prompt_set)

