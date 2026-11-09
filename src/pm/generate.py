"""记忆生成命令（M3 第二切片）：pm memory extract / condense / distill。

设计依据：内部记录/13 §5（生成流程）· 内部记录/20（设计注）· 内部记录/11 §5。

四条纪律（每条都配判据）：
1. **LLM 只产候选**：只写 memory-candidates.org，人 verify 才升格（不新增第二条路）；
2. **派生记录引用与版本**：L2 候选 :PM_SOURCES: id@rev；L3 候选 path@hash（stale 判定靠它）；
3. **幂等**：整份产出的内容 sha256 作幂等键 ⇒ 同输入重跑 changed:false、不产重复；
4. **重跑不覆盖历史**：同目标键（layer+scope+topic）已存在且内容变了 ⇒ 新候选 :PM_SUPERSEDES: 指旧；
   旧的 **CANDIDATE** 自动转 DEPRECATED；旧的 **VERIFIED 不动**（AI 不得把人确认过的记忆自动降级）⇒
   报告 pendingHumanSupersede 并给出人该怎么做。

失败语义（绝不静默）：没给 LLM / LLM 非 0 / 超时 / 非法 JSON / schema 不符 / 超预算 ⇒ 带 code 非 0 退出、**一字节不写**。
安全：**默认零出网** —— 只有用户自己给的 --llm 命令里才可能出网；--allow-network 必须显式给（并在审计里标注）。
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from pathlib import Path

from pm import memory
from pm.config import GenerateConfig


class GenerateError(Exception):
    """生成流程的明确失败（带 code + 退出码）；CLI 统一翻成 JSON/文本。"""

    def __init__(self, code: str, message: str, exit_code: int = 2):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


#: 三条命令 → 目标层
KINDS = {"extract": memory.LAYER_L1, "condense": memory.LAYER_L2, "distill": memory.LAYER_L3}
#: LLM 返回项允许的键（严格 schema：多一个键就报错，不让「看起来还行」的东西静静进来）
_ALLOWED_KEYS = {"title", "body", "type", "topic", "sources"}


def _canonical(kind: str, scope: str, key: str, items: list[dict]) -> str:
    """把「一个目标键下的整份产出」规范化成可 hash 的 JSON（与顺序无关）。"""
    payload = {
        "kind": kind,
        "scope": scope,
        "key": key,
        "items": [
            {"title": str(item.get("title") or "").strip(),
             "body": str(item.get("body") or "").strip(),
             "type": str(item.get("type") or "").strip(),
             "topic": str(item.get("topic") or key).strip(),
             "sources": sorted(str(s) for s in (item.get("sources") or ()))}
            for item in sorted(items, key=lambda i: (str(i.get("title") or ""), str(i.get("body") or "")))
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(kind: str, scope: str, key: str, items: list[dict]) -> str:
    """整份产出的内容 hash ⇒ 幂等键（同输入同 key 一定同 hash）。"""
    return hashlib.sha256(_canonical(kind, scope, key, items).encode("utf-8")).hexdigest()


def target_key(kind: str, *, scope: str, topic: str = "", session: str = "") -> str:
    """目标键：extract=会话、condense=主题、distill=scope（一层一份）。"""
    if kind == "extract":
        return session or topic or "session"
    if kind == "condense":
        return topic or "default"
    return scope or "global"


# ---------------------------------------------------------------- 输入材料

def material_condense(root, scope: str) -> list[dict]:
    """condense 的输入：该 scope 的 VERIFIED L1（锚点 = id@revision）。"""
    root = Path(root)
    out: list[dict] = []
    for entry_type in memory.TYPES:
        path = memory.type_path(root, entry_type)
        if not path.is_file():
            continue
        for entry in memory.parse_entries_text(path.read_text(encoding="utf-8")):
            if entry.status != memory.STATUS_VERIFIED:
                continue
            if entry.scope != scope and entry.scope != memory.SCOPE_GLOBAL:
                continue
            out.append({
                "ref": (entry.id or "") + "@" + str(entry.revision),
                "id": entry.id,
                "revision": int(entry.revision),
                "text": entry.text.strip(),
                "path": path.name,
            })
    return out


def material_distill(root, scope: str) -> list[dict]:
    """distill 的输入：L2 集合（锚点 = 文件路径@内容 hash 前 12 位）。"""
    root = Path(root)
    out: list[dict] = []
    for path in sorted(memory.l2_dir(root).glob("*/*.org")):
        rel = path.relative_to(root).as_posix()
        entries = memory.parse_entries_text(path.read_text(encoding="utf-8"))
        if not entries:
            continue
        entry = entries[0]
        if entry.status != memory.STATUS_VERIFIED:
            continue
        if scope not in ("", "global") and path.parent.name != scope:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        out.append({"ref": rel + "@" + digest, "id": entry.id, "hash": digest,
                    "text": entry.text.strip(), "path": rel, "scope": path.parent.name})
    return out


def material_extract(instances, session: str, instance_id: str = "") -> list[dict]:
    """extract 的输入：会话材料（pm log 的那份 digest 文本）。锚点 = <session>@<instance>。

    instances 由调用方从 --config 的解析结果传入（不在模块里重新 load_config：那会丢掉 --config）。
    """
    from pm import sessions

    instances = list(instances or ())
    if instance_id:
        instances = [i for i in instances if i.id == instance_id]
    if not instances:
        raise GenerateError("INSTANCE_NOT_FOUND", "没有匹配的数据根：" + (instance_id or "(全部)"))
    for instance in instances:
        log_path = sessions.find_log(instance, session)
        if log_path is None:
            continue
        text, _frames, _failed = sessions.decode(log_path)
        digest = sessions.build_digest(sessions.iter_events(text), session_id=session,
                                       instance=instance.id, path=str(log_path))
        rendered = sessions.render_digest(digest, prompts=12, prompt_chars=400, deliverables=15, show_prompts=True)
        return [{"ref": session + "@" + instance.id, "id": session, "text": rendered.strip(),
                 "path": str(log_path)}]
    raise GenerateError("SESSION_NOT_FOUND", "找不到会话日志：" + session)


# ---------------------------------------------------------------- LLM 出口（方案 A）

def build_prompt(kind: str, *, scope: str, key: str, materials: list[dict], max_candidates: int) -> str:
    """确定性 prompt（同输入同 prompt）：只要求候选 JSON，不给它看任何别的库内容。"""
    head = {
        "extract": "从下面这段会话材料里提炼记忆候选（L1）。",
        "condense": "把下面这些已确认（VERIFIED）的 L1 记忆归纳成一个场景（L2）。",
        "distill": "把下面这些 L2 场景蒸馏成一条原则/准则（L3）。",
    }[kind]
    lines = [
        head,
        "",
        "硬要求：",
        "1. 只输出 JSON，形如 {\"candidates\":[{\"title\":\"...\",\"body\":\"...\",\"type\":\"fact|decision|gotcha\",\"topic\":\"...\"}]}；",
        "2. 不要写任何别的文字；不要编造材料里没有的事实（宁可少产）；",
        "3. 最多 " + str(max_candidates) + " 条；没有可产的就返回空数组。",
        "4. 若给 sources，只能用材料里出现过的来源锚点。",
        "",
        "目标：kind=" + kind + " scope=" + scope + " key=" + key,
        "",
        "材料（每段前是它的来源锚点）：",
    ]
    for item in materials:
        lines.append("--- [" + item["ref"] + "] ---")
        lines.append(item["text"])
        lines.append("")
    return "\n".join(lines)


def call_llm(command: str, prompt: str, *, timeout_s: int) -> str:
    """跑用户给的 LLM 命令：prompt 走 stdin、候选 JSON 走 stdout（不内嵌任何 SDK）。"""
    argv = shlex.split(command)
    if not argv:
        raise GenerateError("LLM_REQUIRED", "没有可用的 LLM 命令（--llm 或 [memory.generate].llm）")
    try:
        proc = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=timeout_s)
    except FileNotFoundError as exc:
        raise GenerateError("LLM_NOT_FOUND", "LLM 命令不存在：" + argv[0]) from exc
    except subprocess.TimeoutExpired as exc:
        raise GenerateError("LLM_TIMEOUT", "LLM 超时（" + str(timeout_s) + "s）：" + command) from exc
    if proc.returncode != 0:
        raise GenerateError("LLM_FAILED", "LLM 退出码 " + str(proc.returncode) + "；stderr: " + (proc.stderr or "")[-400:])
    return proc.stdout or ""


def parse_llm_output(text: str, *, max_candidates: int) -> list[dict]:
    """严格解析 LLM 输出；任何不符 ⇒ 报错（绝不挑一个看起来还行的）。"""
    raw = (text or "").strip()
    if not raw:
        raise GenerateError("LLM_EMPTY", "LLM 没有任何输出")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GenerateError("LLM_BAD_JSON", "LLM 输出不是合法 JSON：" + str(exc)) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        raise GenerateError("LLM_SCHEMA", "LLM 输出必须是 {\"candidates\": [...]}")
    items: list[dict] = []
    for index, item in enumerate(payload["candidates"]):
        where = "candidates[" + str(index) + "]"
        if not isinstance(item, dict):
            raise GenerateError("LLM_SCHEMA", where + " 必须是对象")
        unknown = sorted(set(item) - _ALLOWED_KEYS)
        if unknown:
            raise GenerateError("LLM_SCHEMA", where + " 有未知键：" + ", ".join(unknown))
        title = str(item.get("title") or "").strip()
        if not title:
            raise GenerateError("LLM_SCHEMA", where + " 缺 title（不能空）")
        ctype = str(item.get("type") or "fact").strip()
        if ctype not in memory.TYPES:
            raise GenerateError("LLM_SCHEMA", where + ".type 只能是 " + "/".join(memory.TYPES) + "，收到 " + repr(ctype))
        sources = item.get("sources") or []
        if not isinstance(sources, list) or any(not isinstance(s, str) for s in sources):
            raise GenerateError("LLM_SCHEMA", where + ".sources 必须是字符串数组")
        items.append({"title": title, "body": str(item.get("body") or "").strip(),
                      "type": ctype, "topic": str(item.get("topic") or "").strip(), "sources": sources})
    if len(items) > max_candidates:
        raise GenerateError("TOO_MANY_CANDIDATES", "候选 " + str(len(items)) + " 条 > 预算 " + str(max_candidates))
    return items


# ---------------------------------------------------------------- 同目标键的既有条目

def _item_from_entry(entry) -> dict:
    lines = entry.text.split("\n")
    return {"title": lines[0].strip(), "body": "\n".join(lines[1:]).strip(),
            "type": entry.type, "topic": entry.topic, "sources": list(entry.sources)}


def existing_targets(root, kind: str, scope: str, key: str) -> list[dict]:
    """同目标键（layer + scope + topic=key）的既有条目：候选区 + L2 文件（L3 只可能是候选）。"""
    root = Path(root)
    layer = KINDS[kind]
    found: list[dict] = []
    candidates = root / memory.CANDIDATES_RELATIVE
    if candidates.is_file():
        for entry in memory.parse_entries_text(candidates.read_text(encoding="utf-8")):
            if entry.layer != layer or (entry.topic or "") != key:
                continue
            if kind != "extract" and entry.scope != scope:
                continue
            found.append({"id": entry.id, "status": entry.status, "revision": int(entry.revision),
                          "layer": entry.layer, "path": memory.CANDIDATES_RELATIVE,
                          "line": int(entry.line), "item": _item_from_entry(entry)})
    if kind in ("condense", "distill"):
        for path in sorted(memory.l2_dir(root).glob("*/*.org")):
            rel = path.relative_to(root).as_posix()
            for entry in memory.parse_entries_text(path.read_text(encoding="utf-8")):
                if entry.layer != layer or (entry.topic or "") != key:
                    continue
                if kind == "condense" and entry.scope not in (scope, memory.SCOPE_GLOBAL):
                    continue
                found.append({"id": entry.id, "status": entry.status, "revision": int(entry.revision),
                              "layer": layer, "path": rel, "line": int(entry.line), "item": _item_from_entry(entry)})
    return found


# ---------------------------------------------------------------- 主流程

def generate(root, kind: str, *, scope: str = "global", topic: str = "", session: str = "",
             instance: str = "", config: GenerateConfig | None = None, instances=None, llm: str = "",
             skeleton: bool = False, stale_only: bool = False, actor: str = "ai",
             dry_run: bool = False, allow_network: bool = False, now=None) -> dict:
    """生成一次候选。返回报告（含 written / superseded / pendingHumanSupersede / contentHash）。"""
    root = Path(root)
    cfg = config or GenerateConfig()
    if kind not in KINDS:
        raise GenerateError("BAD_KIND", "kind 只能是 " + "/".join(KINDS))
    scope = str(scope or "global").strip() or "global"
    topic = str(topic or "").strip()
    key = target_key(kind, scope=scope, topic=topic, session=session)

    if kind == "extract":
        materials = material_extract(instances, session, instance)
    elif kind == "condense":
        materials = material_condense(root, scope)
    else:
        materials = material_distill(root, scope)
    if not materials:
        raise GenerateError("NO_MATERIAL", "没有可用的输入材料（kind=" + kind + " scope=" + scope + "）")

    old = existing_targets(root, kind, scope, key)

    if stale_only and old:
        from pm import index as index_mod
        report = index_mod.stale_check(root)
        stale_seats = {str(i["source"]) for i in report["stale"]} | {str(i["source"]) for i in report["unpinned"]}
        seats = {str(o["path"]) + ":" + str(o["line"]) for o in old}
        if not (seats & stale_seats):
            return {"kind": kind, "layer": KINDS[kind], "target": key, "scope": scope,
                    "generatedBy": "skipped", "materials": len(materials), "candidates": 0,
                    "written": [], "superseded": [], "pendingHumanSupersede": [], "changed": False,
                    "idempotent": True, "contentHash": None,
                    "note": "--stale-only：同目标键的既有条目都新鲜 ⇒ 跳过（不产重复）"}

    generated_by = "skeleton" if skeleton else "llm"
    if skeleton:
        body = "待归纳清单（未调用 LLM；等 LLM 可用后重跑）\n" + "\n".join("- " + m["ref"] for m in materials)
        items = [{"title": (topic or key) + "：待归纳清单", "body": body, "type": "fact",
                  "topic": topic or key, "sources": []}]
    else:
        command = (llm or cfg.llm or "").strip()
        if not command:
            raise GenerateError(
                "LLM_REQUIRED",
                "没给 LLM：加 --llm \"<命令>\"（prompt 走 stdin、候选 JSON 走 stdout）或配 [memory.generate].llm；"
                "只想出「待归纳清单」可用 --skeleton（不编造内容）")
        prompt = build_prompt(kind, scope=scope, key=key, materials=materials, max_candidates=cfg.max_candidates)
        size = len(prompt.encode("utf-8"))
        if size > cfg.max_input_bytes:
            raise GenerateError("INPUT_TOO_LARGE", "输入 " + str(size) + " 字节 > 预算 " + str(cfg.max_input_bytes))
        stdout = call_llm(command, prompt, timeout_s=cfg.timeout_s)
        items = parse_llm_output(stdout, max_candidates=cfg.max_candidates)

    # ★ 目标键只由 CLI 决定（--topic / scope / session）：LLM 返回的 topic 不参与，
    #   否则「LLM 换个词」就被当成新目标 ⇒ 重跑找不到旧条目、幂等与取代链全失效（实测踩过）。
    for item in items:
        item["topic"] = key

    material_refs = [m["ref"] for m in materials]
    dropped: list[str] = []
    for item in items:
        kept = [s for s in item["sources"] if s in material_refs]
        dropped.extend(s for s in item["sources"] if s not in material_refs)
        item["sources"] = kept or material_refs   # 每条都带锚点 ⇒ stale 可判

    fp_new = content_hash(kind, scope, key, items)
    fp_old = content_hash(kind, scope, key, [o["item"] for o in old]) if old else None
    base = {"kind": kind, "layer": KINDS[kind], "target": key, "scope": scope,
            "generatedBy": generated_by, "materials": len(materials), "materialRefs": material_refs,
            "candidates": len(items), "contentHash": fp_new, "previousHash": fp_old,
            "written": [], "superseded": [], "pendingHumanSupersede": [],
            "droppedSources": sorted(set(dropped)), "changed": False,
            "dryRun": bool(dry_run), "allowNetwork": bool(allow_network)}
    if not items:
        base["note"] = "LLM 判定没有可产出的候选（0 条，未写任何东西）"
        return base
    if fp_old is not None and fp_old == fp_new:
        base["idempotent"] = True
        base["note"] = "同目标键内容 hash 未变 ⇒ 幂等跳过（不产重复候选）"
        return base

    supersedes_id = old[0]["id"] if old else None
    plan = []
    for item in items:
        plan.append({"entryId": memory.new_memory_id(), "title": item["title"], "type": item["type"],
                     "topic": key, "sources": list(item["sources"]),
                     "supersedes": supersedes_id, "layer": KINDS[kind]})
    base["plan"] = plan
    if dry_run:
        base["note"] = "dry-run：只算计划，一字节不写"
        return base

    new_ids: list[str] = []
    for step, item in zip(plan, items):
        result = memory.add_candidate(
            root, text=step["title"] + ("\n" + item["body"] if item["body"] else ""),
            scope=scope, type=step["type"], sources=step["sources"], created_by="ai",
            topic=step["topic"], supersedes=step["supersedes"], entry_id=step["entryId"],
            layer=KINDS[kind], idempotency_key=fp_new,
        )
        new_ids.append(getattr(result, "entity_id", step["entryId"]))
    base["written"] = new_ids

    for record in old:
        if record["status"] == memory.STATUS_CANDIDATE:
            # 候选可以自动作废（旧转 DEPRECATED + 回写 :PM_SUPERSEDED_BY: ⇒ 双向链）
            try:
                memory.deprecate(root, record["id"], expected_revision=record["revision"],
                                 reason="重跑取代：同目标键 " + key + " 产出了新候选",
                                 superseded_by=new_ids[0] if new_ids else None,
                                 actor=actor or "ai")
                base["superseded"].append({"id": record["id"], "by": new_ids[0] if new_ids else None})
            except Exception as exc:
                base.setdefault("supersedeErrors", []).append(record["id"] + ": " + str(exc))
        elif record["status"] == memory.STATUS_VERIFIED:
            # 人确认过的记忆**不自动降级**：只挂取代链，等人 verify 时走既有 deprecate 语义
            base["pendingHumanSupersede"].append({
                "id": record["id"], "path": record["path"], "line": record["line"],
                "reason": "AI 不能自动废弃 VERIFIED 记忆",
                "command": "pm memory deprecate " + str(record["id"]) + " --superseded-by "
                           + (new_ids[0] if new_ids else "?") + " --expected-revision " + str(record["revision"])
                           + " --reason \"被新候选取代\"",
            })
    base["changed"] = bool(new_ids)
    return base



# ---------------------------------------------------------------- CLI

def _fail(json_mode: bool, error) -> int:
    import sys

    code = getattr(error, "code", "FAILED")
    message = getattr(error, "message", str(error))
    if json_mode:
        print(json.dumps({"ok": False, "error": {"code": code, "message": message}}, ensure_ascii=False, indent=2))
    print("pm: [" + code + "] " + message, file=sys.stderr)
    return int(getattr(error, "exit_code", 2))


def run_command(args, kind: str) -> int:
    """三条命令共用入口：写闸门 → 预算 → 生成 → 报告（失败一律非 0 + code + 一字节不写）。"""
    from pm.cli import load_config, resolve_write_target

    json_mode = bool(getattr(args, "json", False))
    layout, gate_error = resolve_write_target(args, json_mode)
    if layout is None:
        return _fail(json_mode, GenerateError(gate_error[0], gate_error[1], gate_error[2]))
    try:
        config, _warnings = load_config(getattr(args, "config", None))
        report = generate(
            layout.root, kind,
            scope=getattr(args, "scope", "") or "global",
            topic=getattr(args, "topic", "") or "",
            session=getattr(args, "session", "") or "",
            instance=getattr(args, "instance", "") or "",
            config=config.generate,
            instances=config.effective_instances,
            llm=getattr(args, "llm", "") or "",
            skeleton=bool(getattr(args, "skeleton", False)),
            stale_only=bool(getattr(args, "stale_only", False)),
            actor=getattr(args, "actor", "ai") or "ai",
            dry_run=bool(getattr(args, "dry_run", False)),
            allow_network=bool(getattr(args, "allow_network", False)),
        )
    except GenerateError as exc:
        return _fail(json_mode, exc)
    except (memory.MemoryError, memory.entities.EntityError) as exc:
        return _fail(json_mode, GenerateError(getattr(exc, "code", "FAILED"),
                                              getattr(exc, "message", str(exc)),
                                              getattr(exc, "exit_code", 2)))
    if json_mode:
        print(json.dumps({"ok": True, "data": report}, ensure_ascii=False, indent=2))
        return 0
    print("生成 " + kind + " → 层 " + str(report["layer"]) + " | 目标 " + str(report["target"])
          + " | 材料 " + str(report["materials"]) + " 段 | 候选 " + str(report["candidates"]) + " 条")
    print("方式: " + str(report.get("generatedBy")) + ("（默认零出网）" if not report.get("allowNetwork") else "（--allow-network 已显式给）"))
    if report.get("note"):
        print("说明: " + str(report["note"]))
    if report.get("contentHash"):
        previous = str(report["previousHash"])[:16] if report.get("previousHash") else "无"
        print("内容 hash: " + str(report["contentHash"])[:16] + " | 上次: " + previous)
    for entry_id in report.get("written", []):
        print("  已写候选: " + str(entry_id))
    for item in report.get("superseded", []):
        print("  旧候选转 DEPRECATED: " + str(item["id"]) + " ← 被 " + str(item.get("by")) + " 取代")
    for item in report.get("pendingHumanSupersede", []):
        print("  等人确认（VERIFIED 不自动降级）: " + str(item["id"]))
        print("    可执行: " + str(item["command"]))
    if report.get("supersedeErrors"):
        print("  ⚠ 取代旧候选时报错: " + "; ".join(report["supersedeErrors"]))
    if report.get("droppedSources"):
        print("  ⚠ LLM 给了材料外的来源锚点，已丢弃: " + ", ".join(report["droppedSources"]))
    if report.get("dryRun"):
        print("  （dry-run：一字节未写）")
    if not report.get("written") and not report.get("idempotent") and not report.get("candidates"):
        print("  （本次没有产出候选）")
    return 0


def command_extract(args) -> int:
    return run_command(args, "extract")


def command_condense(args) -> int:
    return run_command(args, "condense")


def command_distill(args) -> int:
    return run_command(args, "distill")
