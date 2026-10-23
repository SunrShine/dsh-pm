"""pm 命令行入口。

子命令：
  scan      只读扫描 DSH，输出工作卡视图
  ui-cards  把扫描结果投影成 DSH UI 插件消费的稳定 JSON（契约见 pm.ui_cards）
  init      在目标目录搭建 work-memory 骨架（人工文件只在缺失时创建）
  render    把 DSH 状态写进 work-memory/generated（默认干跑）
  skill     管理随工具分发的 DSH skill
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from pm import __version__
from pm.config import (
    DEFAULT_ACTIVE_DAYS,
    ENV_CONFIG,
    Config,
    ConfigPathError,
    ENV_DSH_HOME,
    Instance,
    detect_running_home,
    load as load_config,
)
from pm import inbox_files
from pm import inbox_ops
from pm.inbox import INBOX_RELATIVE, read_inbox
from pm.instances import load_all
from pm.layout import Layout
from pm.subagents import annotate_subagents
from pm.library_view import attach_library_summaries
from pm.render import console
from pm.render import plan as plan_mod
from pm.render.plan import HUMAN, WriteOp, resolve_summaries
from pm.summaries import AI_FILE, HUMAN_FILE, load_ai, load_human, resolve, upsert_ai_summary
from pm.scan import ScanResult, scan as run_scan
from pm.scaffold import plan_for as scaffold_plan
from pm.ui_cards import build_cards_payload, build_envelope
from pm import sessions
from pm.sources import dsh_projcache
from pm.sources.dsh_projcache import CacheLoad
from pm.sources.dsh_workspace import WorkspaceRegistry

MIN_WIDTH = 80
MAX_WIDTH = 200
REPO_ROOT = Path(__file__).resolve().parents[2]


def skill_source_candidates() -> list[Path]:
    """**skill 根目录**的候选（按优先级）：根下面应当是 `<name>/SKILL.md`。

    1. 环境变量 `PM_SKILL_DIR`（显式覆盖，测试/特殊部署用）—— 既可以是**根目录**，
       也可以直接指向**单个 skill 目录**（含 `SKILL.md`，兼容旧用法）；
    2. 源码树里的 `skill/`（`bin/pm` / 开发时）；
    3. 包内副本 `pm/_skill/`（`pipx install` 之后，走 package-data 装进来）。
    """
    candidates: list[Path] = []
    override = os.environ.get("PM_SKILL_DIR")
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(REPO_ROOT / "skill")
    candidates.append(Path(__file__).resolve().parent / "_skill")
    return candidates


def skill_source() -> Path | None:
    """**兼容旧用法**：第一个真的含 `SKILL.md` 的候选（旧包是 `skill/pm`）。

    多 skill 场景请用 `discover_skills()`：那里会校验 frontmatter，并对结构问题**明确报错**。
    """
    for candidate in skill_source_candidates():
        if (candidate / "SKILL.md").is_file():
            return candidate
        try:
            skills = discover_skills(candidate)
        except SkillDiscoveryError:
            continue
        if skills:
            preferred = next((s for s in skills if s.name == SKILL_LEGACY_NAME), None)
            return (preferred or skills[0]).path
    return None


#: 旧包（单 skill）的目录名；`pm skill path` 不带参数且只发现一条时也按它优先。
SKILL_LEGACY_NAME = "pm"


class SkillDiscoveryError(Exception):
    """skill 根目录结构不合法（子目录缺 SKILL.md / frontmatter 缺 name）。"""


@dataclass(frozen=True)
class SkillInfo:
    """一条已发现的 skill：`name` 取 frontmatter（DSH catalog 用的就是它），`path` 是它的目录。"""

    name: str
    path: Path
    description: str = ""


def parse_skill_frontmatter(text: str) -> dict:
    """解析 SKILL.md 顶部的 frontmatter（`---` 包起来的 `key: value`）。

    只认最前面的那一块；不是 frontmatter 或没闭合 → 空 dict。够用就好，不引 YAML。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return {}


def _skill_dirs(root: Path) -> list[Path]:
    return sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name)


def discover_skills(root: Path | None = None) -> list[SkillInfo]:
    """发现 `root` 下的所有 skill（每个子目录一份 `SKILL.md`）。

    - `root` 自身含 `SKILL.md` → 当作**单条** skill（兼容 `PM_SKILL_DIR=…/pm` 的旧用法）；
    - 子目录缺 `SKILL.md` → `SkillDiscoveryError`（**明确报错，不静默跳过**）；
    - SKILL.md 没有 frontmatter 或缺 `name` → `SkillDiscoveryError`；
    - `name` 与目录名不一致 → frontmatter 的 `name` 为准（DSH 认的是它），并在 stderr 给一条 WARN。
    """
    if root is None:
        for candidate in skill_source_candidates():
            try:
                skills = discover_skills(candidate)
            except SkillDiscoveryError:
                raise
            if skills:
                return skills
        return []
    if not root.is_dir():
        return []
    if (root / "SKILL.md").is_file():
        dirs = [root]
    else:
        dirs = _skill_dirs(root)
        if not dirs:
            return []
        missing = [d.name for d in dirs if not (d / "SKILL.md").is_file()]
        if missing:
            raise SkillDiscoveryError(
                f"{root} 下这些目录没有 SKILL.md：{', '.join(missing)}"
                "（每个 skill 目录都必须有一份 SKILL.md；不合规的目录请移走）"
            )
    skills: list[SkillInfo] = []
    for directory in dirs:
        skill_md = directory / "SKILL.md"
        fields = parse_skill_frontmatter(skill_md.read_text(encoding="utf-8"))
        name = str(fields.get("name") or "").strip()
        if not name:
            raise SkillDiscoveryError(
                f"{skill_md} 缺 frontmatter 的 name（必须是 --- 包起来的 name: <skill 名>）"
            )
        if name != directory.name:
            print(
                f"[WARN] skill 目录名与 frontmatter name 不一致：{directory.name} vs {name}（按 {name} 安装）",
                file=sys.stderr,
            )
        skills.append(SkillInfo(name=name, path=directory, description=str(fields.get("description") or "")))
    return skills


class UnsupportedSourceError(Exception):
    """数据源版本不受支持 / 有损坏文件，且用户传了 --strict。"""


@dataclass
class Loaded:
    config: Config
    registry: WorkspaceRegistry
    cache: CacheLoad
    instances: tuple[Instance, ...]
    result: ScanResult
    now: datetime


# ---------------------------------------------------------------- argparse


def _add_common_options(parser: argparse.ArgumentParser, *, as_defaults: bool) -> None:
    """公共选项：`--config` / `--dsh-home`。

    优先级：`--config` > `PM_CONFIG` > `./pm.toml` > `~/.dsh-pm/pm.toml` > 内置默认；
    `--dsh-home` > `PM_DSH_HOME` > `~/.dsh`。

    注意：`PM_CONFIG` 由 `pm.config.discover_config_path` 解析（**不**在这里塞进 argparse 默认值）——
    这样它不会被当成"这次命令行显式给了 --config"，**写命令仍然要 `--yes`**（安全闸门不能因为环境变量而松掉）。
    `--dsh-home` 没有类似的闸门，所以这里直接读环境变量当默认值（命令行仍可覆盖）。
    """
    default = argparse.SUPPRESS if as_defaults else None
    # 与 --config 一样用**字符串**默认值（下游自己 Path(...)），避免 CLI 值与默认值类型不一致
    home_env = (os.environ.get(ENV_DSH_HOME, "").strip() or None) if not as_defaults else None
    parser.add_argument(
        "--config", metavar="PATH", default=default,
        help="指定 pm.toml（优先级最高；不给则依次用 $DSH_UI_PM_CONFIG、$PM_CONFIG、./pm.toml、~/.dsh-pm/pm.toml、内置默认）。"
             "**显式路径（命令行或两个环境变量）必须存在且可解析，否则直接失败、不回落默认库**",
    )
    parser.add_argument(
        "--dsh-home", metavar="PATH", default=home_env if home_env else default,
        help="覆盖 DSH 主目录（优先级最高；不给则用 $PM_DSH_HOME，其次 ~/.dsh）",
    )


def _add_scan_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--all", action="store_true", help="不做噪声过滤，显示全部工作卡")
    parser.add_argument("--project", metavar="KEY", help="只处理指定项目")
    parser.add_argument(
        "--instance",
        metavar="ID",
        action="append",
        help="只读指定数据根（可重复）；默认读取全部已配置的数据根",
    )
    parser.add_argument("--days", type=int, metavar="N", help=f"活跃窗口天数（默认 {DEFAULT_ACTIVE_DAYS}）")
    parser.add_argument("--limit", type=int, metavar="N", help="每个项目最多显示 N 张卡（默认 8，0 = 不限制）")
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="允许输出对话正文（默认不输出，以免泄露原文）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="数据源版本未知或有损坏文件时以非零码退出（便于 CI / 验收）",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm",
        description="把 DSH 状态投影成 org 工作记忆库",
        epilog=(
            "环境变量：DSH_UI_PM_CONFIG / PM_CONFIG = pm.toml 路径（优先级低于 --config；"
            "**实例作用域优先** —— DSH_UI_PM_CONFIG 排在 PM_CONFIG 之前，隔离实例设它即可同时约束实例侧与 MCP 子进程）；"
            "PM_DSH_HOME = DSH 主目录（等价于 --dsh-home）。"
        ),
    )
    parser.add_argument("--version", action="version", version=f"pm {__version__}")
    _add_common_options(parser, as_defaults=False)
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="只读扫描 DSH，输出工作卡视图")
    _add_scan_options(scan)
    scan.add_argument("--json", action="store_true", help="输出 JSON（机器可读）")
    scan.add_argument("--width", type=int, help="终端宽度（默认自动探测）")
    scan.add_argument("--no-color", dest="color", action="store_false", help="禁用 ANSI 颜色")
    scan.add_argument("--warnings", action="store_true", help="显示全部数据源警告")
    _add_common_options(scan, as_defaults=True)
    scan.set_defaults(color=True, handler=_command_scan)

    ui = sub.add_parser("ui-cards", help="输出给 DSH UI 插件消费的 JSON（字段契约已冻结）")
    ui.add_argument("--project", metavar="KEY", help="只输出指定项目")
    ui.add_argument(
        "--instance",
        metavar="ID",
        action="append",
        help="只读指定数据根（可重复）；默认读取全部已配置的数据根",
    )
    ui.add_argument("--days", type=int, metavar="N", help=f"活跃窗口天数（默认 {DEFAULT_ACTIVE_DAYS}）")
    ui.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="每个项目最多输出 N 张卡（默认 0 = 不限制；项目聚合始终基于全部卡）",
    )
    ui.add_argument(
        "--strict",
        action="store_true",
        help="数据源版本未知或有损坏文件时以非零码退出（便于 CI / 验收）",
    )
    ui.add_argument(
        "--include-subagents",
        dest="include_subagents",
        action="store_true",
        help="包含子 agent 会话（默认排除；它们按设计不挂工作区，是内部委派）",
    )
    _add_common_options(ui, as_defaults=True)
    ui.set_defaults(handler=_command_ui_cards)

    init = sub.add_parser("init", help="搭建 work-memory 骨架（人工文件只在缺失时创建）")
    init.add_argument("--root", metavar="PATH", required=True, help="work-memory 根目录")
    init.add_argument("--project", metavar="KEY", action="append", help="只为指定项目建目录（可重复）")
    init.add_argument("--no-git", dest="git", action="store_false", help="不执行 git init")
    init.add_argument("--dry-run", action="store_true", help="只显示将创建什么")
    _add_common_options(init, as_defaults=True)
    init.set_defaults(git=True, handler=_command_init)

    render = sub.add_parser("render", help="把 DSH 状态写进 generated/（默认干跑）")
    render.add_argument("--root", metavar="PATH", required=True, help="work-memory 根目录")
    render.add_argument("--write", action="store_true", help="真正落盘（默认只干跑）")
    render.add_argument("--print", dest="print_path", metavar="REL", help="打印某个将写入文件的完整内容")
    _add_scan_options(render)
    _add_common_options(render, as_defaults=True)
    render.set_defaults(handler=_command_render)

    summary = sub.add_parser("summary", help="管理工作卡摘要（人工优先；AI 摘要不覆盖人工）")
    summary_sub = summary.add_subparsers(dest="summary_command")
    queue = summary_sub.add_parser("queue", help="列出缺摘要的工作卡")
    queue.add_argument("--root", metavar="PATH", required=True)
    _add_scan_options(queue)
    _add_common_options(queue, as_defaults=True)
    queue.set_defaults(handler=_command_summary_queue)
    setter = summary_sub.add_parser("set", help="写入一条 AI 摘要（不覆盖人工摘要）")
    setter.add_argument("--root", metavar="PATH", required=True)
    setter.add_argument("--session", metavar="ID", required=True)
    setter.add_argument("--instance", metavar="ID", default=None, help="数据实例，默认 dsh-default")
    setter.add_argument("--text", required=True, help="一句话摘要")
    setter.add_argument("--model", default="", help="生成者标识，写入来源信息")
    _add_common_options(setter, as_defaults=True)
    setter.set_defaults(handler=_command_summary_set)

    log = sub.add_parser("log", help="读会话日志，提炼进展材料（只打印，不落库）")
    log.add_argument("--session", metavar="ID", help="单个会话 id")
    log.add_argument("--project", metavar="KEY", help="按项目批量，配合 --missing")
    log.add_argument("--missing", action="store_true", help="只处理还没有摘要的卡")
    log.add_argument("--limit", type=int, default=10, help="批量模式最多处理几个会话")
    log.add_argument("--instance", metavar="ID", action="append", help="限定数据根（可重复）")
    log.add_argument("--prompts", type=int, default=12, metavar="N", help="每条会话显示几条用户请求")
    log.add_argument("--prompt-chars", type=int, default=160, metavar="N")
    log.add_argument("--deliverables", type=int, default=15, metavar="N")
    log.add_argument("--no-prompts", dest="prompts_on", action="store_false", help="不显示用户请求正文")
    log.add_argument("--json", action="store_true")
    _add_common_options(log, as_defaults=True)
    log.set_defaults(prompts_on=True, handler=_command_log)

    capture = sub.add_parser("capture", help="向 work-memory 的 inbox.org 追加一条快速笔记（只追加）")
    capture.add_argument(
        "text",
        nargs="?",
        metavar="TEXT",
        help="要记录的文本；为空/纯空白则拒绝写入并以码 2 退出",
    )
    capture.add_argument(
        "--project",
        metavar="KEY",
        help="项目提示，写入 PM_PROJECT_HINT 并回显为 project_hint；不改变写入位置",
    )
    capture.add_argument(
        "--json",
        action="store_true",
        help="stdout 只输出纯 JSON（错误信息一律走 stderr）",
    )
    capture.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="只预演：打印将写入的文件/行号/块内容，一个字节都不落盘",
    )
    capture.add_argument(
        "--yes",
        action="store_true",
        help="确认要写「默认配置指向的库」；只在没显式给 --config 且非 --dry-run 时才必需",
    )
    _add_common_options(capture, as_defaults=True)
    capture.set_defaults(handler=_command_capture)

    api = sub.add_parser("api", help="统一 envelope（pm-api-v2）查询入口；ui-cards 形状保持不变")
    api.add_argument("--envelope", action="store_true", help="输出设计 §6 的统一 envelope（当前唯一形态）")
    api.add_argument("--project", metavar="KEY", help="只输出指定项目")
    api.add_argument(
        "--instance",
        metavar="ID",
        action="append",
        help="只读指定数据根（可重复）；默认读取全部已配置的数据根",
    )
    api.add_argument("--days", type=int, metavar="N", help=f"活跃窗口天数（默认 {DEFAULT_ACTIVE_DAYS}）")
    api.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="每个项目最多输出 N 张卡（默认 0 = 不限制；项目聚合始终基于全部卡）",
    )
    api.add_argument(
        "--include-subagents",
        dest="include_subagents",
        action="store_true",
        help="包含子 agent 会话（默认排除）",
    )
    api.add_argument(
        "--strict",
        action="store_true",
        help="数据源版本未知或有损坏文件时以非零码退出（便于 CI / 验收）",
    )
    _add_common_options(api, as_defaults=True)
    api.set_defaults(handler=_command_api)

    inbox = sub.add_parser(
        "inbox",
        help="Inbox 分流（含 :LOGBOOK: 审计）",
    )
    inbox_sub = inbox.add_subparsers(dest="inbox_command")

    inbox_list = inbox_sub.add_parser("list", help="列出 inbox 条目（含 id / status / revision）")
    inbox_list.add_argument("--status", metavar="S", help="只看某个状态，如 CAPTURED / ARCHIVED / SNOOZED")
    inbox_list.add_argument("--origin", choices=("human", "ai"), help="只看某个来源（人工 / AI）")
    inbox_list.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(inbox_list, as_defaults=True)
    inbox_list.set_defaults(handler=_command_inbox_list)

    inbox_files_cmd = inbox_sub.add_parser("files", help="列出多文件 inbox 的真源文件（人工/AI 轮转文件）")
    inbox_files_cmd.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(inbox_files_cmd, as_defaults=True)
    inbox_files_cmd.set_defaults(handler=_command_inbox_files)

    inbox_render = inbox_sub.add_parser("render", help="生成/校验 inbox.org 汇总视图（只读视图）")
    inbox_render.add_argument("--check", action="store_true", help="只校验是否最新（过期 exit 1，不写）")
    inbox_render.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(inbox_render, as_defaults=True)
    inbox_render.set_defaults(handler=_command_inbox_render)

    inbox_migrate = inbox_sub.add_parser("migrate", help="把旧单文件 inbox.org 拆成来源/周期文件（默认 dry-run）")
    inbox_migrate.add_argument("--write", action="store_true", help="真的写（默认只 dry-run 打印去向）")
    inbox_migrate.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(inbox_migrate, as_defaults=True)
    inbox_migrate.set_defaults(handler=_command_inbox_migrate)

    def _add_inbox_write_flags(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("inbox_id", metavar="INBOX_ID", help="条目 :ID:（身份只看 ID，不看行号）")
        parser.add_argument(
            "--expected-revision",
            dest="expected_revision",
            type=int,
            required=True,
            metavar="N",
            help="你看到的 :PM_REVISION:；不匹配 → 409，一字节不写（CAS）",
        )
        parser.add_argument("--reason", default="", metavar="R", help="变更原因，写入审计")
        parser.add_argument(
            "--actor",
            default="human",
            choices=["human", "ai", "system"],
            help="谁发起的，写入审计（默认 human）",
        )
        parser.add_argument(
            "--idempotency-key",
            dest="idempotency_key",
            default=None,
            metavar="KEY",
            help="同一 key 重复提交不会产生第二次变更",
        )
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            help="只预演将要发生的变更，一字节不落盘",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="确认要写「默认配置指向的库」；未显式 --config 且非 --dry-run 时必需",
        )
        parser.add_argument("--json", action="store_true", help="stdout 只输出纯 JSON")

    inbox_archive = inbox_sub.add_parser("archive", help="归档一条 inbox 记录（CAS + 原子写 + 审计）")
    _add_inbox_write_flags(inbox_archive)
    _add_common_options(inbox_archive, as_defaults=True)
    inbox_archive.set_defaults(handler=_command_inbox_archive)

    inbox_snooze = inbox_sub.add_parser("snooze", help="延期一条 inbox 记录（写 :PM_SNOOZE_UNTIL:）")
    _add_inbox_write_flags(inbox_snooze)
    inbox_snooze.add_argument(
        "--until",
        required=True,
        metavar="WHEN",
        help="到期时间：YYYY-MM-DD 或 ISO8601（带时区优先）",
    )
    _add_common_options(inbox_snooze, as_defaults=True)
    inbox_snooze.set_defaults(handler=_command_inbox_snooze)

    inbox_merge = inbox_sub.add_parser("merge", help="合并到另一条记录（源记录标 MERGED，留 :PM_MERGED_INTO:）")
    _add_inbox_write_flags(inbox_merge)
    inbox_merge.add_argument(
        "--into", required=True, metavar="ID", help="主记录 ID（inbox-… 或 task-… 等）"
    )
    _add_common_options(inbox_merge, as_defaults=True)
    inbox_merge.set_defaults(handler=_command_inbox_merge)

    inbox_note = inbox_sub.add_parser("note", help="保存为项目笔记（写 memory 候选区，不进任务列表）")
    _add_inbox_write_flags(inbox_note)
    inbox_note.add_argument(
        "--project", metavar="KEY", help="项目 key，默认取条目的 :PM_PROJECT_HINT:"
    )
    _add_common_options(inbox_note, as_defaults=True)
    inbox_note.set_defaults(handler=_command_inbox_note)

    inbox_dismiss = inbox_sub.add_parser("dismiss", help="丢弃一条记录（必须给 --reason）")
    _add_inbox_write_flags(inbox_dismiss)
    _add_common_options(inbox_dismiss, as_defaults=True)
    inbox_dismiss.set_defaults(handler=_command_inbox_dismiss)

    inbox_status = inbox_sub.add_parser("set-status", help="显式状态迁移（受 §5.1 状态机约束）")
    _add_inbox_write_flags(inbox_status)
    inbox_status.add_argument("--status", required=True, metavar="S", help="目标状态，如 TRIAGE")
    _add_common_options(inbox_status, as_defaults=True)
    inbox_status.set_defaults(handler=_command_inbox_set_status)

    inbox_annotate = inbox_sub.add_parser(
        "annotate", help="追加式补充（写在同一条目正文末尾；原文不动、不改状态）"
    )
    _add_inbox_write_flags(inbox_annotate)
    inbox_annotate.add_argument("--text", required=True, metavar="TEXT", help="补充内容（可多行）")
    _add_common_options(inbox_annotate, as_defaults=True)
    inbox_annotate.set_defaults(handler=_command_inbox_annotate)

    inbox_edit = inbox_sub.add_parser(
        "edit", help="显式修订原文（必须给 --reason；旧值逐字保留、不改状态）"
    )
    _add_inbox_write_flags(inbox_edit)
    inbox_edit.add_argument("--text", required=True, metavar="TEXT", help="新的原文（单行）")
    _add_common_options(inbox_edit, as_defaults=True)
    inbox_edit.set_defaults(handler=_command_inbox_edit)

    inbox_history = inbox_sub.add_parser("history", help="只读：原文 + 补充块 + 修订块（按时间）")
    inbox_history.add_argument("inbox_id", metavar="ID", help="条目 :ID:")
    inbox_history.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(inbox_history, as_defaults=True)
    inbox_history.set_defaults(handler=_command_inbox_history)

    inbox_pin = inbox_sub.add_parser("pin", help="置顶（写 :PM_PIN: t；不改状态）")
    _add_inbox_write_flags(inbox_pin)
    _add_common_options(inbox_pin, as_defaults=True)
    inbox_pin.set_defaults(handler=_command_inbox_pin)

    inbox_unpin = inbox_sub.add_parser("unpin", help="取消置顶（删除 :PM_PIN:；不改状态）")
    _add_inbox_write_flags(inbox_unpin)
    _add_common_options(inbox_unpin, as_defaults=True)
    inbox_unpin.set_defaults(handler=_command_inbox_unpin)

    mcp = sub.add_parser("mcp", help="以 MCP server（stdio）运行，供 DSH 调用")
    _add_common_options(mcp, as_defaults=True)
    mcp.set_defaults(handler=_command_mcp)

    skill = sub.add_parser("skill", help="管理随工具分发的 DSH skill（可以有多条）")
    skill.add_argument(
        "action", choices=["path", "install"], help="path=打印 skill 源目录；install=软链到 DSH"
    )
    skill.add_argument(
        "--skill", dest="skill", metavar="NAME", help="只处理这一条 skill（默认全部）"
    )
    skill.add_argument(
        "--all", dest="all_skills", action="store_true", help="明确处理全部 skill（默认行为）"
    )
    skill.add_argument(
        "--all-instances",
        dest="all_instances",
        action="store_true",
        help="安装到全部已配置的数据根（默认只装当前运行的实例）",
    )
    _add_common_options(skill, as_defaults=True)
    skill.set_defaults(handler=_command_skill)

    _register_domain_commands(sub)
    _register_execution_commands(sub)
    return parser


def _register_execution_commands(subparsers) -> None:
    """执行准备向导的 CLI（pm-api 拥有；契约 内部记录（未随仓库发布） §1）。

    task 的执行配置命令要挂到 pm.tasks 已经注册好的 task 子解析器上，所以必须后注册。
    """
    try:
        from pm import execution
    except Exception as exc:  # pragma: no cover - 自己的模块，坏了也不能连累 CLI
        print(
            f"pm: [execution] import 失败，执行配置命令未挂载: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return
    try:
        execution.register_cli(subparsers)
    except Exception as exc:
        print(
            f"pm: [execution] 注册失败，执行配置命令未挂载: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


def _register_domain_commands(subparsers) -> None:
    """让 pm.tasks / pm.proposals / pm.memory 自己注册子命令。

    契约：模块暴露 `register_cli(subparsers)` 与 `command_xxx(args) -> int`。

    健壮性（CLI 是所有人的入口，不能因某个领域模块而整体起不来）：
    1. 模块不存在 → 静默跳过；
    2. 模块存在但 import 失败 → stderr 警告后跳过；
    3. 先在一次性 parser 上试跑 register_cli，失败 → stderr 警告后跳过，
       绝不把半成品注册进真正的 CLI（否则 `pm <域>` 会残缺甚至崩）。
    """
    import argparse
    import importlib
    import importlib.util

    # index：记忆内容索引（pm index / pm recall）；prompt：初始系统提示词数据层（pm prompt get|set）。
    # （context_preview 已随 内部记录/22 弃用移除 —— 见 内部记录/25 §10.2：旧定位是"预览运行时注入物" ✗）
    # 同样只暴露 register_cli，注册失败不影响整体 CLI。
    for name in ("tasks", "proposals", "memory", "index", "hooks", "prompt"):
        module_name = f"pm.{name}"
        try:
            exists = importlib.util.find_spec(module_name) is not None
        except Exception:  # 连定位都失败 → 当作不存在
            exists = False
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            # 必须兜住**任何 import 期失败**：SyntaxError 不是 ImportError，
            # 之前只 catch ImportError，导致一个域文件的语法错误让 pm --help 都起不来。
            # KeyboardInterrupt / SystemExit 是 BaseException，不会被这里吞掉。
            if exists:
                print(
                    f"pm: [{name}] 模块存在但 import 失败，子命令未注册: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
            continue
        register = getattr(module, "register_cli", None)
        if not callable(register):
            continue
        # 先在一次性 parser 上试跑：注册失败绝不把半成品塞进真 CLI
        probe = argparse.ArgumentParser(add_help=False)
        try:
            register(probe.add_subparsers())
        except Exception as exc:
            print(f"pm: [{name}] register_cli 失败，子命令未注册: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        try:
            register(subparsers)
        except Exception as exc:  # pragma: no cover - 试跑过了，这里只是兜底
            print(f"pm: [{name}] register_cli 二次注册失败: {type(exc).__name__}: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    # hook 子命令特殊：Claude Code 协议里**非零退出 = block = 吞掉用户输入** ✗，
    # 而 argparse 的 usage error 恰好是 exit 2（未知 flag 由**顶层** parser 报，子解析器覆盖不到）。
    # 所以先做一次宽容解析：只要命令是 hook 且有多余 token，就零输出 + exit 0（细节见 pm.hooks.exit0 的注释）。
    try:
        tolerant, extra = parser.parse_known_args(argv)
    except SystemExit:
        tolerant, extra = None, []
    if getattr(tolerant, "command", None) == "hook" and extra:
        print("pm hook: 收到未知参数 " + " ".join(extra) + " ⇒ 零输出 exit 0（非零在本集成里=block=吞输入）",
              file=sys.stderr)
        return 0
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        # usage 一律走 stderr：--json 调用方要直接解析 stdout，不能混入帮助文本。
        parser.print_help(file=sys.stderr)
        return 2
    try:
        return handler(args)
    except ConfigPathError as exc:
        # 显式配置路径不存在 / 解析失败：明确报错 + 非零退出，**不回落默认库**（task-197）
        print(f"pm: [{exc.code}] {exc}", file=sys.stderr)
        return exc.exit_code
    except UnsupportedSourceError as exc:
        print(f"pm: {exc}", file=sys.stderr)
        return 3


# ---------------------------------------------------------------- helpers


def _prepare(args: argparse.Namespace, *, include_all: bool, limit: int, only_project: str | None) -> Loaded:
    config, config_warnings = load_config(getattr(args, "config", None))
    dsh_home = getattr(args, "dsh_home", None)
    if dsh_home:
        # 临时单实例覆盖：忽略配置里的多数据根
        config = replace(config, dsh_home=Path(dsh_home).expanduser(), instances=())
    wanted = getattr(args, "instance", None)
    if wanted:
        available = {i.id: i for i in config.effective_instances}
        missing = [w for w in wanted if w not in available]
        if missing:
            raise UnsupportedSourceError(
                "未知数据根: " + ", ".join(missing) + "；可用: " + ", ".join(sorted(available))
            )
        config = replace(config, instances=tuple(available[w] for w in wanted))
    days = getattr(args, "days", None)
    if days is not None:
        config = replace(config, active_days=days)

    now = datetime.now().astimezone()
    sources = load_all(config.effective_instances)

    problems = dsh_projcache.check_supported(sources.cache)
    for problem in problems:
        print(f"pm: {problem}", file=sys.stderr)
    if getattr(args, "strict", False) and problems:
        raise UnsupportedSourceError("--strict 已启用，遇到不支持的数据源版本或损坏文件")

    result = run_scan(
        config=config,
        registry=sources.registry,
        cache=sources.cache,
        now=now,
        include_all=include_all,
        only_project=only_project,
        limit=limit,
        source_instances=sources.instance_ids,
    )
    result.warnings = list(config_warnings) + list(sources.warnings) + list(result.warnings)
    _attach_library_summaries(config, result)
    return Loaded(config, sources.registry, sources.cache, sources.instances, result, now)


def _attach_library_summaries(config: Config, result: ScanResult) -> None:
    """把 work-memory 里的摘要挂到 agent 上（实现见 pm.library_view）。"""
    attach_library_summaries(config, result)


def _known_project_keys(loaded: Loaded) -> list[str]:
    return sorted({p.key for p in loaded.result.projects})


# ---------------------------------------------------------------- commands


def _command_scan(args: argparse.Namespace) -> int:
    if args.project:
        probe = _prepare(args, include_all=True, limit=0, only_project=None)
        known = _known_project_keys(probe) + [rule.key for rule in probe.config.merges]
        if args.project not in set(known):
            print(f"未知项目 key: {args.project}", file=sys.stderr)
            print("可用: " + ", ".join(sorted(set(known))), file=sys.stderr)
            return 2

    loaded = _prepare(
        args,
        include_all=args.all,
        limit=args.limit if args.limit is not None else -1,
        only_project=args.project,
    )
    if args.limit is None:
        loaded.result.limit = loaded.config.row_limit

    if args.json:
        print(console.render_json(loaded.result))
        return 0

    width = args.width or shutil.get_terminal_size((120, 24)).columns
    width = max(MIN_WIDTH, min(MAX_WIDTH, width))
    color = bool(args.color) and sys.stdout.isatty()
    sys.stdout.write(
        console.render_scan(
            loaded.result,
            width=width,
            color=color,
            show_warnings=args.warnings,
            show_prompt=args.show_prompt,
        )
    )
    return 0


def _command_ui_cards(args: argparse.Namespace) -> int:
    """把扫描结果投影成 DSH 插件消费的 JSON（契约见 pm.ui_cards）。

    只扫一次：needs_attention 判定与项目聚合都必须基于全部工作卡，
    所以先全量扫描，再在本地按 --project / --limit 裁剪。
    """
    loaded = _prepare(args, include_all=True, limit=0, only_project=None)
    if args.project:
        known = {p.key for p in loaded.result.projects} | {rule.key for rule in loaded.config.merges}
        if args.project not in known:
            print(f"未知项目 key: {args.project}", file=sys.stderr)
            print("可用: " + ", ".join(sorted(known)), file=sys.stderr)
            return 2
    # 子 agent 判定：一次批量 node 进程看全部会话日志的第一帧；
    # 判定失败/无日志的会话保持 False（保守，不藏真实工作）。
    annotate_subagents(loaded.result.all_agents, loaded.config.effective_instances)
    payload = build_cards_payload(
        loaded.result,
        only_project=args.project,
        limit=max(0, args.limit or 0),
        inbox=read_inbox(loaded.config.library),
        include_subagents=args.include_subagents,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _command_init(args: argparse.Namespace) -> int:
    loaded = _prepare(args, include_all=True, limit=0, only_project=None)
    layout = Layout(Path(args.root))

    projects = loaded.result.projects
    if args.project:
        wanted = set(args.project)
        missing = wanted - {p.key for p in projects}
        if missing:
            print(f"未知项目 key: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2
        projects = [p for p in projects if p.key in wanted]

    if not args.dry_run:
        for directory in layout.directories():
            directory.mkdir(parents=True, exist_ok=True)
        # projects/<id> 目录
        for project in projects:
            layout.project_dir(project.id).mkdir(parents=True, exist_ok=True)

    ops = [
        WriteOp(path=path, content=content, kind=HUMAN, skip_if_exists=True)
        for path, content in scaffold_plan(layout, projects)
    ]
    items = plan_mod.apply(ops, layout, write=not args.dry_run)
    print(_render_plan(items, layout, write=not args.dry_run, title="work-memory 骨架"))

    if not args.dry_run and args.git:
        _git_init(layout.root)
    return 0


def _command_render(args: argparse.Namespace) -> int:
    layout = Layout(Path(args.root))
    if not layout.root.is_dir():
        print(f"根目录不存在: {layout.root}（先跑 pm init）", file=sys.stderr)
        return 2

    loaded = _prepare(
        args,
        include_all=args.all,
        limit=args.limit if args.limit is not None else -1,
        only_project=args.project,
    )
    if args.limit is None:
        loaded.result.limit = loaded.config.row_limit

    human = load_human(layout.root)
    ai = load_ai(layout.root)
    resolved = resolve_summaries(loaded.result, human, ai)
    ops = plan_mod.build_plan(
        layout,
        loaded.result,
        resolved,
        now=loaded.now,
        include_scaffold=False,
    )

    if args.print_path:
        wanted = args.print_path.strip("/")
        for op in ops:
            if plan_mod._relative(op.path, layout.root).strip("/") == wanted:
                sys.stdout.write(op.content)
                return 0
        print(f"计划中没有该文件: {args.print_path}", file=sys.stderr)
        return 2

    items = plan_mod.apply(ops, layout, write=args.write)
    print(_render_plan(items, layout, write=args.write, title="generated/ 写入计划"))
    return 0


def _command_summary_queue(args: argparse.Namespace) -> int:
    layout = Layout(Path(args.root))
    loaded = _prepare(
        args,
        include_all=args.all,
        limit=args.limit if args.limit is not None else -1,
        only_project=args.project,
    )
    resolved = resolve_summaries(
        loaded.result, load_human(layout.root), load_ai(layout.root)
    )
    pending = [
        (project.key, agent)
        for project in loaded.result.projects
        for agent in project.agents
        if resolved.get(agent.identity_key) is None
    ]
    if not pending:
        print("所有工作卡都有摘要。人工摘要文件 " + HUMAN_FILE + " 优先于 AI 摘要文件 " + AI_FILE + "。")
        return 0
    print(f"待生成摘要：{len(pending)} 张")
    print("")
    for project_key, agent in pending:
        action, from_prompt = agent.recent_action()
        if from_prompt:
            action = "[对话正文，默认隐去]"
        print(f"  {agent.session_id}")
        print(f"      项目 {project_key}   目录 {agent.cwd or chr(45)}   轮/步 T{agent.turns}/S{agent.steps}")
        print(f"      缓存待办 {agent.progress}   最近动作 {action}")
    print("")
    print("生成方式：会话里的 agent 读完工作卡后调用 pm summary set 写回；人工摘要请写 " + HUMAN_FILE + "。")
    return 0


def _resolve_instance_id(config: Config, session: str) -> str | None:
    """按 projcache 文件反查这个会话属于哪个数据根。

    身份键是 (instance, session)，猜错写进去就永远匹配不上工作卡，
    所以默认不猜：扫一遍各数据根，唯一命中才采用。
    """
    hits = [
        instance.id
        for instance in config.effective_instances
        if (instance.projcache_dir / (session + ".json")).is_file()
        or (instance.projcache_dir / (session.replace("session-", "") + ".json")).is_file()
    ]
    return hits[0] if len(hits) == 1 else None


def _command_summary_set(args: argparse.Namespace) -> int:
    layout = Layout(Path(args.root))
    if not layout.root.is_dir():
        print(f"根目录不存在: {layout.root}", file=sys.stderr)
        return 2
    session = args.session if args.session.startswith("session-") else f"session-{args.session}"
    config, _ = load_config(getattr(args, "config", None))
    instance = args.instance or _resolve_instance_id(config, session)
    if instance is None:
        candidates = ", ".join(i.id for i in config.effective_instances)
        print(f"无法确定 {session} 属于哪个数据根（已查: {candidates}）：用 --instance 指定", file=sys.stderr)
        return 2
    key = f"{instance}/{session}"
    human = load_human(layout.root)
    if key in human:
        print("人工摘要已存在（" + HUMAN_FILE + "），按规则不覆盖：" + human[key].text)
        return 0
    path = upsert_ai_summary(layout.root, identity_key=key, text=args.text, model=args.model)
    print(f"已写入 {path}")
    print(f"  {key}")
    print(f"  {args.text}")
    return 0


def _command_log(args: argparse.Namespace) -> int:
    config, _ = load_config(getattr(args, "config", None))
    dsh_home = getattr(args, "dsh_home", None)
    if dsh_home:
        config = replace(config, dsh_home=Path(dsh_home).expanduser(), instances=())
    instances = list(config.effective_instances)
    wanted = getattr(args, "instance", None)
    if wanted:
        keep = set(wanted)
        instances = [i for i in instances if i.id in keep]
        if not instances:
            print("没有匹配的数据根: " + ", ".join(wanted), file=sys.stderr)
            return 2

    targets: list[tuple[str, str]] = []
    if args.session:
        for instance in instances:
            if sessions.find_log(instance, args.session) is not None:
                targets.append((instance.id, args.session))
                break
        if not targets:
            print("找不到会话日志: " + args.session, file=sys.stderr)
            return 2
    else:
        loaded = _prepare(args, include_all=True, limit=0, only_project=args.project)
        pool = [
            (project.key, agent)
            for project in loaded.result.projects
            for agent in project.agents
            if not args.missing or agent.summary_status == "not_generated"
        ]
        if not pool:
            print("没有符合条件的会话。")
            return 0
        pool.sort(key=lambda pair: pair[1].steps, reverse=True)
        for _key, agent in pool[: max(0, args.limit)]:
            targets.append((agent.source_instance, agent.session_id))
        print("待提炼会话 %d 个，本批 %d 个" % (len(pool), len(targets)))
        print("")

    payloads: list[dict] = []
    for instance_id, session_id in targets:
        instance = next((i for i in instances if i.id == instance_id), None)
        if instance is None:
            continue
        log_path = sessions.find_log(instance, session_id)
        if log_path is None:
            print("跳过（无日志）: " + session_id, file=sys.stderr)
            continue
        try:
            text, _frames, _failed = sessions.decode(log_path)
        except sessions.LogError as exc:
            print("跳过 " + session_id + ": " + str(exc), file=sys.stderr)
            continue
        digest = sessions.build_digest(
            sessions.iter_events(text),
            session_id=session_id,
            instance=instance_id,
            path=str(log_path),
        )
        if args.json:
            payloads.append(_digest_json(digest))
            continue
        print(sessions.render_digest(
            digest,
            prompts=args.prompts,
            prompt_chars=args.prompt_chars,
            deliverables=args.deliverables,
            show_prompts=args.prompts_on,
        ))
        print("-" * 72)
        print("")
    if args.json:
        print(json.dumps(payloads, ensure_ascii=False, indent=2))
    return 0


def _digest_json(digest) -> dict:
    todos = digest.final_todos
    return {
        "session_id": digest.session_id,
        "instance": digest.instance,
        "cwd": digest.cwd,
        "log_path": digest.log_path,
        "first_at": digest.first_at.isoformat() if digest.first_at else None,
        "last_at": digest.last_at.isoformat() if digest.last_at else None,
        "turns": digest.turns,
        "steps": digest.steps,
        "events": digest.events,
        "counts": digest.counts,
        "user_requests": [
            {"at": at.isoformat() if at else None, "text": text}
            for at, text in digest.user_requests
        ],
        "final_todos": [{"content": c, "status": s} for c, s in todos.todos] if todos else [],
        "deliverables": [
            {"at": d.at.isoformat() if d.at else None, "path": d.path, "description": d.description}
            for d in sessions.unique_deliverables(digest)
        ],
        "last_assistant": digest.last_assistant,
    }


def _command_api(args: argparse.Namespace) -> int:
    """设计 §6 的统一查询 envelope（pm-api-v2）。

    数据与 ui-cards 同源（同一次扫描），只是外面套一层统一形状；
    ui-cards 的既有顶层键与语义保持不变。
    """
    if not args.envelope:
        print("pm api: 需要 --envelope（当前只提供统一 envelope 形态）", file=sys.stderr)
        return 2

    loaded = _prepare(args, include_all=True, limit=0, only_project=None)
    if args.project:
        known = {p.key for p in loaded.result.projects} | {rule.key for rule in loaded.config.merges}
        if args.project not in known:
            print(f"未知项目 key: {args.project}", file=sys.stderr)
            print("可用: " + ", ".join(sorted(known)), file=sys.stderr)
            return 2
    annotate_subagents(loaded.result.all_agents, loaded.config.effective_instances)
    payload = build_cards_payload(
        loaded.result,
        only_project=args.project,
        limit=max(0, args.limit or 0),
        inbox=read_inbox(loaded.config.library),
        include_subagents=args.include_subagents,
    )
    envelope = build_envelope(payload, warnings=loaded.result.warnings)
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return 0


def _resolve_write_target(args: argparse.Namespace, json_mode: bool):
    """capture / pm inbox 写命令共用的「写到哪个库」解析 + 写入闸门。

    返回 (Layout, None) 或 (None, (code, message, exit_code))：
    - 显式 --config 指向不存在的文件 → 硬失败（否则 load_config 会静默回落默认库）；
    - 未配置 library / 库目录不存在 → 失败；
    - 没显式 --config 又不是 --dry-run 且没有 --yes → 闸门拒绝（防误写默认库）。
    """
    dry_run = bool(getattr(args, "dry_run", False))
    explicit_config = getattr(args, "config", None)
    if explicit_config is not None:
        config_path = Path(str(explicit_config)).expanduser()
        if not config_path.is_file():
            return None, ("CONFIG_NOT_FOUND", f"指定的 --config 不存在: {config_path}，未写入任何内容", 2)

    try:
        config, _warnings = load_config(explicit_config)
    except ConfigPathError as exc:
        # 环境变量给了一个坏的 pm.toml（--config 的情况上面已单独处理）→ 与读路径同一个码/句式
        return None, (exc.code, str(exc), exc.exit_code)
    if config.library is None:
        return None, ("NO_LIBRARY", "未配置 work-memory 库（pm.toml 缺 library），未写入任何内容", 2)

    if explicit_config is None and not dry_run and not getattr(args, "yes", False):
        target = Path(config.library).expanduser().resolve()
        return None, (
            "NEEDS_YES",
            "未显式指定 --config，拒绝写入。"
            f"你正在写默认配置指向的库：{target}。"
            "要写入请二选一：① 加 --config <目标 pm.toml> 显式指向目标库；"
            "② 加 --yes 确认确实要写这个库。只想预演可加 --dry-run（不需要 --yes）。",
            2,
        )

    layout = Layout(Path(config.library))
    if not layout.root.is_dir():
        return None, ("LIBRARY_MISSING", f"work-memory 库目录不存在: {layout.root}", 2)
    return layout, None


#: 供 pm.tasks / pm.proposals / pm.memory 的写命令复用同一条写入闸门。
#: 在**函数体内**延迟 import（`from pm.cli import resolve_write_target`）可避免循环导入。
resolve_write_target = _resolve_write_target


def _capture_error(json_mode: bool, message: str, code: str = "") -> int:
    """capture 失败：--json 时 stdout 仍给一个合法 JSON（ok=false），人类信息走 stderr。

    `code` 给了就带上（形如 `pm: [CONFIG_NOT_FOUND] …`）—— 与其它域的报错格式一致，
    读路径/写路径同一个错误码（task-197）。
    """
    if json_mode:
        # 保持既有契约：`{ok, error}`（不新增字段，免得动到 capture 的 JSON 契约）
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    print(f"pm: {f'[{code}] ' if code else ''}{message}", file=sys.stderr)
    return 2


def _command_capture(args: argparse.Namespace) -> int:
    """向 work-memory 的 inbox.org 追加一条快速笔记。

    只追加、绝不改写；写入实现与 MCP 工具 pm_capture 共用（pm.mcp.capture_text
    → pm.humanwrite.append_entry），这里不另写追加逻辑。
    """
    json_mode = bool(getattr(args, "json", False))
    text = (getattr(args, "text", None) or "").strip()
    if not text:
        return _capture_error(json_mode, "文本为空，未写入任何内容")

    dry_run = bool(getattr(args, "dry_run", False))
    layout, gate_error = _resolve_write_target(args, json_mode)
    if layout is None:
        return _capture_error(json_mode, gate_error[1], gate_error[0])
    # [inbox] 轮转粒度（人工 weekly / AI monthly 默认）；写入文件由 pm.mcp.capture_text 选
    capture_config, _w = load_config(getattr(args, "config", None))
    inbox_modes = capture_config.inbox.modes()

    # 复用 MCP 工具的同一条实现；preview 与真写共用 capture_block + 插入位置算法，
    # 所以 --dry-run 显示的行号/块内容就是真写时会落下的那一份。
    from pm.mcp import capture_text, plan_capture

    if dry_run:
        plan = plan_capture(
            layout.root, text, source="cli", model="cli", project_hint=args.project,
            inbox_modes=inbox_modes,
        )
        try:
            planned_relative = str(plan.path.relative_to(layout.root))
        except ValueError:  # pragma: no cover - inbox 永远在库根下
            planned_relative = str(plan.path)
        if json_mode:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "dry_run": True,
                        "entityId": plan.entity_id,
                        "inboxId": plan.inbox_id,
                        "source": plan.source,
                        "observedAt": plan.observed_at,
                        "auditEventId": plan.audit_event_id,
                        "revision": plan.revision,
                        "path": planned_relative,
                        "line": plan.line,
                        "block": plan.block,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        note = "" if plan.found_section else "（没找到 * Inbox 小节，将追加到文件末尾）"
        print(f"将写入 {plan.path}:{plan.line}（--dry-run，未落盘）{note}")
        print(f"  id {plan.inbox_id}   rev {plan.revision}   audit {plan.audit_event_id}")
        if args.project:
            print(f"  项目提示 {args.project}（写入 PM_PROJECT_HINT，不改变写入位置）")
        print("--- 块内容 ---")
        print(plan.block)
        return 0

    result = capture_text(
        layout.root, text, source="cli", model="cli", project_hint=args.project,
        inbox_modes=inbox_modes,
    )
    try:
        relative = str(result.path.relative_to(layout.root))
    except ValueError:  # pragma: no cover - inbox 永远在库根下
        relative = str(result.path)

    if json_mode:
        print(
            json.dumps(
                {
                    "ok": True,
                    "entityId": result.entity_id,
                    "inboxId": result.inbox_id,
                    "source": result.source,
                    "observedAt": result.observed_at,
                    "auditEventId": result.audit_event_id,
                    "path": relative,
                    "line": result.line,
                    "revision": result.revision,
                },
                ensure_ascii=False,
            )
        )
        return 0

    note = "" if result.found_section else "（没找到 * Inbox 小节，已追加到文件末尾）"
    print(
        f"已追加到 {result.path}:{result.line}  id={result.inbox_id}  rev={result.revision}"
        f"  audit={result.audit_event_id}{note}"
    )
    if args.project:
        print(f"  项目提示 {args.project}（写入 PM_PROJECT_HINT，不改变写入位置）")
    return 0


def _inbox_error(json_mode: bool, error: "inbox_ops.InboxOpError") -> int:
    """inbox 命令的失败输出：JSON 用设计 §6 的嵌套 error{code,message}，人类信息走 stderr。"""
    payload = {"ok": False, "error": {"code": error.code, "message": error.message}}
    payload.update(error.extra)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
    print(f"pm: [{error.code}] {error.message}", file=sys.stderr)
    return error.exit_code


def _command_inbox_list(args: argparse.Namespace) -> int:
    """列出 inbox 条目（身份看 :ID:；旧条目显示 LEGACY_UNTRACKED）。"""
    json_mode = bool(getattr(args, "json", False))
    config, _warnings = load_config(getattr(args, "config", None))
    if config.library is None:
        return _inbox_error(
            json_mode,
            inbox_ops.InboxOpError("NO_LIBRARY", "未配置 work-memory 库（pm.toml 缺 library）"),
        )
    try:
        payload = inbox_ops.list_entries(Path(config.library), status=args.status, origin=getattr(args, "origin", None))
    except inbox_ops.InboxOpError as exc:
        return _inbox_error(json_mode, exc)

    if json_mode:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
        return 0
    if not payload["entries"]:
        print("inbox 没有符合条件的条目。")
        return 0
    counts = payload.get("counts") or {}
    files = payload.get("files") or []
    if files:
        print(f"inbox 条目 {payload['count']} 条（人工 {counts.get('human', 0)} · AI {counts.get('ai', 0)}；库 {config.library}）")
        print("  文件：" + "、".join(f"{row['path']}({row['count']})" for row in files))
    else:
        print(f"inbox 条目 {payload['count']} 条（{payload['path']}，库 {config.library}）")
    for row in payload["entries"]:
        revision = row["revision"] if row["revision"] is not None else "-"
        until = f"  until {row['snoozeUntil']}" if row["snoozeUntil"] else ""
        identity = row["id"] or "(无 :ID:)"
        headline = row["text"].splitlines()[0] if row["text"] else ""
        origin = row.get("origin") or "?"
        print(f"  [{row['status']}/{origin}] {identity}  rev {revision}{until}  第 {row['line']} 行  {headline[:40]}  ({row.get('file')})")
    return 0


def _inbox_config_or_error(args, json_mode):
    config, _warnings = load_config(getattr(args, "config", None))
    if config.library is None:
        return None, _inbox_error(
            json_mode,
            inbox_ops.InboxOpError("NO_LIBRARY", "未配置 work-memory 库（pm.toml 缺 library）"),
        )
    return config, None


def _command_inbox_files(args: argparse.Namespace) -> int:
    """列出多文件 inbox 的真源文件（人工/AI 轮转文件 + 旧单文件）。"""
    json_mode = bool(getattr(args, "json", False))
    config, err = _inbox_config_or_error(args, json_mode)
    if config is None:
        return err
    from pm import inbox_files
    rows = inbox_files.discover(Path(config.library))
    payload = {
        "ok": True,
        "path": inbox_files.inbox.INBOX_RELATIVE,
        "files": [
            {"path": row["name"], "origin": row["origin"], "legacy": row["legacy"]}
            for row in rows
        ],
    }
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("inbox 没有真源文件（可用 pm capture 创建第一个）")
        return 0
    for row in rows:
        suffix = "（旧单文件，建议 pm inbox migrate）" if row["legacy"] else ""
        print(f"  [{row['origin']}] {row['name']}{suffix}")
    return 0


def _command_inbox_render(args: argparse.Namespace) -> int:
    """生成/校验 inbox.org 汇总视图（只读视图；真源是 inbox-human-*/inbox-ai-*）。"""
    json_mode = bool(getattr(args, "json", False))
    check = bool(getattr(args, "check", False))
    config, err = _inbox_config_or_error(args, json_mode)
    if config is None:
        return err
    from pm import inbox_files
    result = inbox_files.render(Path(config.library), config.inbox.modes(), check=check)
    if json_mode:
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    elif check:
        print("inbox.org 与真源一致" if not result["changed"] else "inbox.org 已过期（pm inbox render 可刷新）")
    else:
        print("已生成 inbox.org 汇总视图" if result["written"] else "inbox.org 已是最新")
    return 1 if (check and result["changed"]) else 0


def _command_inbox_migrate(args: argparse.Namespace) -> int:
    """把旧单文件 inbox.org 拆成来源/周期文件（默认 dry-run，--write 才写）。"""
    json_mode = bool(getattr(args, "json", False))
    dry_run = not bool(getattr(args, "write", False))
    config, err = _inbox_config_or_error(args, json_mode)
    if config is None:
        return err
    from pm import inbox_files
    result = inbox_files.migrate(Path(config.library), config.inbox.modes(), dry_run=dry_run)
    if json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    moves = result.get("moves") or []
    if not moves:
        print(result.get("reason") or "没有需要迁移的条目")
        return 0
    print(("[dry-run] 将迁移 " if dry_run else "已迁移 ") + str(len(moves)) + " 个块：")
    for row in moves:
        identity = row.get("id") or "(无 :ID: legacy)"
        print(f"  [{row.get('origin')}] {identity}  {row.get('status')}  -> {row.get('target')}")
    if dry_run:
        print("确认后加 --write 真正执行（会先备份 inbox.org）")
    else:
        print("备份：" + str(result.get("backup")))
        print("已重写 inbox.org 为汇总视图（pm inbox render）")
    return 0


def _run_inbox_write(args: argparse.Namespace, *, action: str) -> int:
    json_mode = bool(getattr(args, "json", False))
    layout, gate_error = _resolve_write_target(args, json_mode)
    if layout is None:
        return _inbox_error(json_mode, inbox_ops.InboxOpError(gate_error[0], gate_error[1], exit_code=gate_error[2]))
    try:
        common = {
            "expected_revision": args.expected_revision,
            "actor": args.actor,
            "reason": args.reason or "",
            "idempotency_key": args.idempotency_key,
            "dry_run": args.dry_run,
        }
        if action == "archive":
            result = inbox_ops.archive(layout.root, args.inbox_id, **common)
        elif action == "snooze":
            result = inbox_ops.snooze(layout.root, args.inbox_id, until=args.until, **common)
        elif action == "merge":
            result = inbox_ops.merge(layout.root, args.inbox_id, into=args.into, **common)
        elif action == "note":
            result = inbox_ops.note(
                layout.root, args.inbox_id, project=getattr(args, "project", None), **common
            )
        elif action == "dismiss":
            result = inbox_ops.dismiss(layout.root, args.inbox_id, **common)
        elif action == "annotate":
            result = inbox_ops.annotate(layout.root, args.inbox_id, text=args.text, **common)
        elif action == "edit":
            result = inbox_ops.edit(layout.root, args.inbox_id, text=args.text, **common)
        elif action == "pin":
            result = inbox_ops.pin(layout.root, args.inbox_id, **common)
        elif action == "unpin":
            result = inbox_ops.unpin(layout.root, args.inbox_id, **common)
        else:
            result = inbox_ops.set_status(
                layout.root, args.inbox_id, status=args.status, **common
            )
    except inbox_ops.InboxOpError as exc:
        return _inbox_error(json_mode, exc)

    if json_mode:
        # 设计 §5：写操作统一返回 entityId / revision / source / observedAt / auditEventId。
        # inboxId 保留（既有消费方在用），entityId 与之等值。
        payload = {
            "ok": True,
            "entityId": result.entity_id,
            "inboxId": result.inbox_id,
            "source": result.source,
            "observedAt": result.observed_at,
            "auditEventId": result.audit_event_id,
            "status": result.status,
            "revision": result.revision,
            "previousStatus": result.previous_status,
            "previousRevision": result.previous_revision,
            "changed": result.changed,
            "path": INBOX_RELATIVE,
        }
        if result.snooze_until:
            payload["snoozeUntil"] = result.snooze_until
        if result.idempotent:
            payload["idempotent"] = True
        if args.dry_run:
            payload["dry_run"] = True
        for key, value in (result.extra or {}).items():  # noteId / notePath / mergedInto / snoozeUntil
            payload.setdefault(key, value)
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    prefix = "[dry-run] " if args.dry_run else ""
    audit = f"  audit {result.audit_event_id}" if result.audit_event_id else ""
    if result.idempotent:
        print(
            prefix
            + f"该 idempotency-key 已处理过，未再次变更：{result.inbox_id} 仍是 {result.status} rev {result.revision}{audit}"
        )
        return 0
    if not result.changed:
        print(prefix + f"无需变更：{result.inbox_id} 已是 {result.status} rev {result.revision}{audit}")
        return 0
    verbs = {
        "archive": "归档",
        "snooze": "延期",
        "merge": "合并",
        "note": "记为笔记",
        "dismiss": "丢弃",
        "set-status": "改状态",
        "annotate": "补充",
        "edit": "修订",
        "pin": "置顶",
        "unpin": "取消置顶",
    }
    verb = verbs.get(action, action)
    detail = ""
    if result.snooze_until:
        detail += f"  到期 {result.snooze_until}"
    if result.extra.get("mergedInto"):
        detail += f"  主记录 {result.extra['mergedInto']}"
    if result.extra.get("noteId"):
        detail += f"  笔记 {result.extra['noteId']}"
    print(
        prefix
        + f"已{verb} {result.inbox_id}  {result.previous_status} → {result.status}{detail}"
        + f"  rev {result.previous_revision} → {result.revision}"
        + audit
    )
    return 0


def _command_inbox_archive(args: argparse.Namespace) -> int:
    return _run_inbox_write(args, action="archive")


def _command_inbox_snooze(args: argparse.Namespace) -> int:
    return _run_inbox_write(args, action="snooze")


def _command_inbox_merge(args: argparse.Namespace) -> int:
    return _run_inbox_write(args, action="merge")


def _command_inbox_note(args: argparse.Namespace) -> int:
    return _run_inbox_write(args, action="note")


def _command_inbox_dismiss(args: argparse.Namespace) -> int:
    return _run_inbox_write(args, action="dismiss")


def _command_inbox_set_status(args: argparse.Namespace) -> int:
    return _run_inbox_write(args, action="set-status")


def _command_inbox_annotate(args: argparse.Namespace) -> int:
    return _run_inbox_write(args, action="annotate")


def _command_inbox_edit(args: argparse.Namespace) -> int:
    return _run_inbox_write(args, action="edit")


def _command_inbox_pin(args: argparse.Namespace) -> int:
    return _run_inbox_write(args, action="pin")


def _command_inbox_unpin(args: argparse.Namespace) -> int:
    return _run_inbox_write(args, action="unpin")


def _command_inbox_history(args: argparse.Namespace) -> int:
    """只读历史：原文 + 补充块 + 修订块（不写任何文件）。"""
    json_mode = bool(getattr(args, "json", False))
    config, _warnings = load_config(getattr(args, "config", None))
    if config.library is None:
        return _inbox_error(
            json_mode,
            inbox_ops.InboxOpError("NO_LIBRARY", "未配置 work-memory 库（pm.toml 缺 library）"),
        )
    try:
        payload = inbox_ops.history(Path(config.library), args.inbox_id)
    except inbox_ops.InboxOpError as exc:
        return _inbox_error(json_mode, exc)
    if json_mode:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
        return 0
    print(f"{payload['id']}  rev {payload['revision']}  [{payload['status']}]")
    print("原文：")
    for line in payload["text"].splitlines() or [""]:
        print("  " + line)
    print(f"补充 {len(payload['annotations'])} 条 / 修订 {len(payload['revisions'])} 条")
    for row in payload["annotations"]:
        print(f"  [补充 {row['at']} actor={row['actor']} rev={row['revision']}]")
        for line in str(row["text"]).splitlines() or [""]:
            print("    " + line)
    for row in payload["revisions"]:
        print(f"  [修订 {row['at']} actor={row['actor']} rev={row['revision']}] 原因：{row['reason']}")
        print("    旧值：" + row["oldText"])
        print("    新值：" + row["newText"])
    return 0


def _command_mcp(args: argparse.Namespace) -> int:
    """stdio MCP server：stdout 只输出协议消息，日志走 stderr。"""
    from pm import mcp as mcp_module

    print("pm mcp 启动（stdio）", file=sys.stderr)
    return mcp_module.serve(getattr(args, "config", None))


def select_skills(args: argparse.Namespace) -> tuple:
    """按 `--skill NAME` / 默认全部 选出要处理的 skill。

    返回 `(skills, exit_code)`：出错时打印原因并给出 2（不抛异常，CLI 统一返回码）。
    """
    try:
        skills = discover_skills()
    except SkillDiscoveryError as exc:
        print(f"skill 目录不合法：{exc}", file=sys.stderr)
        return [], 2
    if not skills:
        print(
            "找不到 skill 源目录（源码树 skill/ 或包内副本 _skill/ 都没有）；"
            "可用 PM_SKILL_DIR 显式指定。",
            file=sys.stderr,
        )
        return [], 2
    wanted = getattr(args, "skill", None)
    if wanted:
        hit = [s for s in skills if s.name == wanted]
        if not hit:
            print(
                f"没有名为 {wanted} 的 skill；已发现：{', '.join(s.name for s in skills)}",
                file=sys.stderr,
            )
            return [], 2
        return hit, 0
    # 带不带 --all 都装/列全部（--all 只是把默认行为写明白）
    return skills, 0


def _command_skill(args: argparse.Namespace) -> int:
    skills, code = select_skills(args)
    if code:
        return code
    if args.action == "path":
        if len(skills) == 1:
            print(skills[0].path)
        else:
            for skill in skills:
                print(f"{skill.name}\t{skill.path}")
        return 0

    config, _ = load_config(getattr(args, "config", None))
    dsh_home = getattr(args, "dsh_home", None)
    if dsh_home:
        targets = [Instance(id="adhoc", path=Path(dsh_home).expanduser())]
    elif getattr(args, "all_instances", False):
        targets = list(config.effective_instances)
    else:
        # 默认只装到**当前正在运行**的实例：skill 目录是按数据根读取的，
        # 装到别的根不会被本次会话的 catalog 看到。
        running = detect_running_home()
        primary = config.primary
        if running is not None and (primary is None or primary.path != running):
            targets = [Instance(id="running", path=running)]
        elif primary is not None:
            targets = [primary]
        else:
            print("无法确定 DSH 数据根：用 --dsh-home 指定", file=sys.stderr)
            return 2

    status = 0
    for instance in targets:
        skills_root = instance.path / "skills"
        try:
            skills_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"[{instance.id}] 无法创建目录 {skills_root}: {exc}", file=sys.stderr)
            status = 2
            continue
        for skill in skills:
            target = skills_root / skill.name
            if target.is_symlink() and target.resolve() == skill.path.resolve():
                print(f"[{instance.id}] {skill.name}: 已安装（幂等，未改动）{target}")
                continue
            if target.is_symlink() or target.exists():
                print(
                    f"[{instance.id}] {skill.name}: 目标已存在且不是本工具的软链，未改动 {target}",
                    file=sys.stderr,
                )
                status = 2
                continue
            target.symlink_to(skill.path)
            print(f"[{instance.id}] {skill.name}: 已安装 {target} -> {skill.path}")
    return status


def _git_init(root: Path) -> None:
    if (root / ".git").exists():
        print(f"  git      已有仓库，跳过")
        return
    try:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        print("  git      已初始化仓库")
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"  git      初始化失败（可忽略）: {exc}", file=sys.stderr)


def _render_plan(items, layout: Layout, *, write: bool, title: str) -> str:
    counts: dict[str, int] = {}
    lines = [f"{title}    根目录 {layout.root}    模式 {'落盘' if write else '干跑（加 --write 落盘）'}", ""]
    lines.append("  动作        类别       文件")
    lines.append("  ----------  ----------  ------------------------------------------------")
    for item in items:
        counts[item.action] = counts.get(item.action, 0) + 1
        lines.append(f"  {item.action:<10}  {item.kind:<10}  {item.relative}")
    summary = " / ".join(f"{n} {a}" for a, n in sorted(counts.items()))
    lines.append("")
    lines.append(f"  合计：{summary or '无变化'}")
    return "\n".join(lines)
