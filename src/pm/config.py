"""配置加载：数据根（可能多个）、合并规则、噪声过滤参数、pin 列表。

配置文件查找顺序（先找到先用）：
1. `--config` 显式指定
2. 环境变量 `DSH_UI_PM_CONFIG`（**实例作用域优先**：插件/harness 给实例侧设的就是它，MCP 侧也认 → 一个 env 同时约束两侧）
3. 环境变量 `PM_CONFIG`（pm 自己的通用变量；**优先级低于实例作用域的 DSH_UI_PM_CONFIG**，否则全局 PM_CONFIG 会盖掉用户显式给某个实例的配置）
4. 当前工作目录 `./pm.toml`
5. 用户配置 `~/.dsh-pm/pm.toml`（安装后不与仓库耦合的默认位置）
6. 仓库自带 `config/pm.toml`（仅源码检出里存在；pipx 安装下不存在）

DSH 主目录（`--dsh-home`）同理：命令行 > 环境变量 `PM_DSH_HOME` > `~/.dsh`。

一个都找不到也不会失败：用内置默认值自动发现数据根（`Config()`），
所以 pipx 安装后**不需要**任何配置文件也能跑 `pm scan` / `pm init --root`。

**多数据根**是必须的：同一台机器上可能同时存在 ~/.dsh 与 ~/.dsh-preview，
它们各自有独立的工作区注册表与会话 id 空间。session id 只在实例内唯一，
所以身份键是 (instance.id, session_id)。不要把默认数据根当成唯一实例。
"""

from __future__ import annotations

import hashlib
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DSH_HOME = Path.home() / ".dsh"
PREVIEW_DSH_HOME = Path.home() / ".dsh-preview"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "pm.toml"

DEFAULT_ACTIVE_DAYS = 14
DEFAULT_ACTIVE_HOURS = 24

#: 已知数据根的稳定标识：目录名 -> 实例 id。用可读名字而不是哈希，便于看日志。
WELL_KNOWN_INSTANCE_DIRS: dict[str, str] = {
    ".dsh-learn": "learn",
    ".dsh-preview": "preview",
    ".dsh": "default",
}


@dataclass(frozen=True)
class Instance:
    """一个 DSH 数据根。

    role 用于区分用途：work = 常用工作目录；explore = 工具探索目录。
    探索目录里的会话通常不进日常看板，但也不删除，便于对照。
    """

    id: str
    path: Path
    role: str = "work"

    @property
    def is_explore(self) -> bool:
        return self.role == "explore"

    @property
    def storages_dir(self) -> Path:
        return self.path / "storages"

    @property
    def workspace_file(self) -> Path:
        return self.storages_dir / "workspace.json"

    @property
    def projcache_dir(self) -> Path:
        return self.storages_dir / "session_projcache" / "sessions"

    @property
    def sessions_dir(self) -> Path:
        return self.path / "sessions"

    @property
    def skills_dir(self) -> Path:
        return self.path / "skills"

    @property
    def exists(self) -> bool:
        return self.path.is_dir()


@dataclass(frozen=True)
class MergeRule:
    """把多个 DSH 工作区路径合并为同一个项目。"""

    key: str
    title: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Alias:
    """单独把某个路径归到（可能是自动生成的）项目 key 下。"""

    path: str
    project: str


def detect_running_home() -> Path | None:
    """从 DSH_PROFILE_DIR 推断**当前正在运行**的实例根目录。

    形如 <home>/profiles/<name>。这是判断「我这个会话用的是哪个数据根」
    最可靠的依据 —— 比猜默认目录安全得多。
    """
    profile_dir = os.environ.get("DSH_PROFILE_DIR")
    if not profile_dir:
        return None
    candidate = Path(profile_dir)
    if candidate.parent.name != "profiles":
        return None
    return candidate.parent.parent


def default_instances() -> tuple[Instance, ...]:
    """未配置时自动发现已知数据根；preview 排在前面。"""
    found: list[Instance] = []
    for dirname, ident in WELL_KNOWN_INSTANCE_DIRS.items():
        path = Path.home() / dirname
        if path.is_dir():
            found.append(Instance(id=ident, path=path, role="explore" if ident == "preview" else "work"))
    return tuple(found)


def derive_source_instance(dsh_home: Path | str) -> str:
    """已知数据根用可读名；其它路径用内容哈希，保证稳定且不碰撞。"""
    resolved = Path(dsh_home).expanduser()
    for dirname, ident in WELL_KNOWN_INSTANCE_DIRS.items():
        if resolved == Path.home() / dirname:
            return ident
    digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:8]
    return "dsh-" + digest


def normalize_path(path: str) -> str:
    """统一路径写法（去尾斜杠、折叠重复斜杠），用于跨源比对。"""
    if not path:
        return ""
    text = path.replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    if len(text) > 1 and text.endswith("/"):
        text = text.rstrip("/")
    return text


@dataclass(frozen=True)
class HooksConfig:
    """`[hooks]`：DSH hooks 记忆注入的总开关与预算（内部记录/11 §5-P2/§6）。

    安全红线：**可一键关**（`inject=false`）+ **有预算**（条数/字节/超时）；非法值**硬失败**，
    不静默挑一个"看起来还行"的值（宁可报错，也不要在用户不知情时打开注入）。
    """

    #: 总开关：false ⇒ 两个 hook 都零输出（不注入、不改任何文件）
    inject: bool = True
    #: 单次注入的条数预算
    max_items: int = 3
    #: 单次注入的字节预算（UTF-8 编码后的字节数）
    max_bytes: int = 1200
    #: session-start 的字节预算（上下文包通常比一次检索长）
    session_max_bytes: int = 2400
    #: 单次调用的墙钟超时（毫秒）；超时 ⇒ 零输出（fail-safe，不阻塞会话）
    timeout_ms: int = 1500
    #: session-start 的默认 scope；留空 = 由调用方按 cwd/global 决定
    scope: str = ""
    #: 是否把每项目 prompt.org 经 SessionStart 投递（默认 true）
    #: **默认 true；配置里没有这个键 = 开启（会出提示词节）**；
    #: 显式 false ⇒ 输出与「仅记忆」的旧口径**逐字节一致**（c6：旧读数继续可跑）
    prompt: bool = True
    #: 「提示词」节的字节预算；**含节头与截断标注**（不变量：输出 ≤ 它）
    prompt_max_bytes: int = 4000


@dataclass(frozen=True)
class GenerateConfig:
    """`[memory.generate]`：M3 第二切片（extract/condense/distill）的预算与 LLM 出口。

    安全红线：**默认零出网**（llm 空 = 没给 LLM ⇒ 命令非零退出、一字节不写）；
    预算有默认值（Lead 批的建议值），用户改配置即可；非法值硬失败（不猜、不静默降级）。
    """

    #: LLM 命令模板（方案 A：prompt 走 stdin、候选 JSON 走 stdout）。空 = 未配置 ⇒ 拒绝生成
    llm: str = ""
    #: 单次调用的墙钟超时（秒）
    timeout_s: int = 120
    #: 喂给 LLM 的输入上限（UTF-8 字节）
    max_input_bytes: int = 32768
    #: 单次最多接受几条候选
    max_candidates: int = 20
    #: 方案 B（外部 API）的出网闸门：默认关，且必须显式 --allow-network 才可能开
    allow_network: bool = False


@dataclass(frozen=True)
class Config:
    #: 临时单实例覆盖（--dsh-home）。为 None 时走 instances 或自动发现。
    dsh_home: Path | None = None
    #: 显式配置的数据根列表（[[instance]]）
    instances: tuple[Instance, ...] = ()
    #: work-memory 库根目录。scan / summary queue 靠它读取摘要；
    #: 不配的话 scan 只认人工摘要，会和 render 的结果自相矛盾。
    library: Path | None = None
    vault: Path | None = None
    active_days: int = DEFAULT_ACTIVE_DAYS
    active_hours: int = DEFAULT_ACTIVE_HOURS
    merges: tuple[MergeRule, ...] = ()
    aliases: tuple[Alias, ...] = ()
    pins: frozenset[str] = field(default_factory=frozenset)
    #: 不当作项目的工作区路径（例如家目录工作区）
    exclude_paths: tuple[str, ...] = ()
    #: 每个项目默认显示的最大行数（0 = 不限制）
    row_limit: int = 8
    #: DSH hooks 记忆注入（[hooks]）：总开关 + 预算
    hooks: HooksConfig = HooksConfig()
    #: 记忆生成命令（[memory.generate]）：LLM 出口 + 预算（默认零出网）
    generate: GenerateConfig = GenerateConfig()
    source_path: Path | None = None

    @property
    def effective_instances(self) -> tuple[Instance, ...]:
        """配置优先：[[instance]] > dsh_home（临时单实例）> 自动发现。"""
        if self.instances:
            return self.instances
        if self.dsh_home is not None:
            home = Path(self.dsh_home).expanduser()
            return (Instance(id=derive_source_instance(home), path=home),)
        return default_instances()

    @property
    def primary(self) -> Instance | None:
        """当前运行实例优先，其次配置里的第一个。"""
        instances = self.effective_instances
        running = detect_running_home()
        if running is not None:
            for instance in instances:
                if instance.path == running:
                    return instance
        return instances[0] if instances else None

    @property
    def dsh_home_resolved(self) -> Path:
        primary = self.primary
        return primary.path if primary else DEFAULT_DSH_HOME

    def merge_index(self) -> dict[str, MergeRule]:
        index: dict[str, MergeRule] = {}
        for rule in self.merges:
            for path in rule.paths:
                index[normalize_path(path)] = rule
        return index

    def alias_index(self) -> dict[str, str]:
        return {normalize_path(a.path): a.project for a in self.aliases}


def _as_paths(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(v) for v in value if isinstance(v, str) and v)
    if isinstance(value, str) and value:
        return (value,)
    return ()


#: 配置文件路径的环境变量（等价于 `--config`，优先级低于命令行）。
ENV_CONFIG = "PM_CONFIG"
#: DSH 主目录的环境变量（等价于 `--dsh-home`，优先级低于命令行）。
ENV_DSH_HOME = "PM_DSH_HOME"
#: 插件/harness 给**实例侧**设的配置路径；MCP 侧也认它 → 同一个 env 同时约束两侧（task-192）。
#: **优先级高于 `PM_CONFIG`**（task-194「实例作用域优先」）：插件侧就是 `DSH_UI_PM_CONFIG ?? DEFAULT`，
#: 若这里反过来，两者都设时会出现"插件读副本、MCP 读 PM_CONFIG"的分叉。
ENV_UI_CONFIG = "DSH_UI_PM_CONFIG"


class ConfigPathError(Exception):
    """**显式**给出的 pm.toml 不能用（不存在 / 解析失败）→ 硬失败，**绝不回落默认库**。

    为什么必须硬：显式路径（`--config` / `PM_CONFIG` / `DSH_UI_PM_CONFIG`）打错一个字，
    静默回落就会读到默认库（源码检出里 = 真实库）——"隔离实例"会静默失效。
    隐式候选（`./pm.toml`、`~/.dsh-pm/pm.toml`）缺失仍是"跳过"，不受影响。
    """

    def __init__(self, code: str, message: str, *, exit_code: int = 2) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


def env_dsh_home() -> Path | None:
    """环境变量 `PM_DSH_HOME` 指向的 DSH 主目录；未设置/空白 → None（由调用方回落到 ~/.dsh）。

    用途：**隔离实例**时不必每条命令都写 `--dsh-home`；MCP 子进程会继承这个变量，
    所以实例侧与 MCP 侧能指向同一个副本。
    """
    raw = os.environ.get(ENV_DSH_HOME, "").strip()
    return Path(raw).expanduser() if raw else None


def discover_config_path(explicit: str | None = None) -> Path | None:
    # **显式来源**（命令行 / 环境变量）：文件必须存在 → 否则**硬失败**，绝不"跳过"到下一个候选。
    # 顺序（task-194「实例作用域优先」）：--config > DSH_UI_PM_CONFIG > PM_CONFIG。
    for label, raw, subject in (
        ("--config", explicit, "指定的 --config"),
        (ENV_UI_CONFIG, os.environ.get(ENV_UI_CONFIG), f"{ENV_UI_CONFIG} 指向的 pm.toml"),
        (ENV_CONFIG, os.environ.get(ENV_CONFIG), f"{ENV_CONFIG} 指向的 pm.toml"),
    ):
        text = str(raw).strip() if raw is not None else ""
        if not text:
            continue
        candidate = Path(text).expanduser()
        if candidate.is_file():
            return candidate
        # 与写路径（_resolve_write_target）**同一个码、同一句式**：读/写都必须硬失败，绝不回落默认库。
        raise ConfigPathError(
            "CONFIG_NOT_FOUND",
            f"{subject} 不存在: {candidate}，未读取任何内容（不会回落默认库）。"
            "请修正路径，或改用隐式位置（./pm.toml、~/.dsh-pm/pm.toml）。",
        )
    local = Path.cwd() / "pm.toml"
    if local.is_file():
        return local
    # 用户级默认位置：为「pipx 安装、不依赖仓库」准备；调用时才算，便于测试覆盖 HOME。
    user = Path.home() / ".dsh-pm" / "pm.toml"
    if user.is_file():
        return user
    return DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.is_file() else None


def _parse_generate(section, path: Path | None) -> GenerateConfig:
    """解析 `[memory.generate]`；类型/取值不对 → `CONFIG_INVALID` 硬失败（不猜、不静默降级）。"""
    where = str(path or "pm.toml")
    if section is None:
        return GenerateConfig()
    if not isinstance(section, dict):
        raise ConfigPathError("CONFIG_INVALID", where + " 的 [memory] 必须是一个表（table）")
    sub = section.get("generate")
    if sub is None:
        return GenerateConfig()
    if not isinstance(sub, dict):
        raise ConfigPathError("CONFIG_INVALID", where + " 的 [memory.generate] 必须是一个表（table）")
    known = {"llm", "timeout_s", "max_input_bytes", "max_candidates", "allow_network"}
    unknown = [k for k in sub if k not in known]
    if unknown:
        raise ConfigPathError("CONFIG_INVALID", "[memory.generate] 不认识的键：" + ", ".join(sorted(unknown)))
    llm = sub.get("llm", "")
    if not isinstance(llm, str):
        raise ConfigPathError("CONFIG_INVALID", "[memory.generate].llm 必须是字符串（LLM 命令），收到 " + repr(llm))
    allow_network = sub.get("allow_network", False)
    if not isinstance(allow_network, bool):
        raise ConfigPathError("CONFIG_INVALID", "[memory.generate].allow_network 必须是 true/false，收到 " + repr(allow_network))
    limits = {}
    for name, default, low, high in (("timeout_s", 120, 1, 3600), ("max_input_bytes", 32768, 256, 4 * 1024 * 1024),
                                     ("max_candidates", 20, 1, 200)):
        value = sub.get(name, default)
        if not isinstance(value, int) or isinstance(value, bool) or not (low <= value <= high):
            raise ConfigPathError(
                "CONFIG_INVALID",
                "[memory.generate]." + name + " 必须是 " + str(low) + ".." + str(high) + " 的整数，收到 " + repr(value),
            )
        limits[name] = value
    return GenerateConfig(llm=llm.strip(), allow_network=allow_network, **limits)


def _parse_hooks(section, path: Path | None) -> HooksConfig:
    """解析 `[hooks]`；类型/取值不对 → `CONFIG_INVALID` 硬失败（不猜、不静默降级）。"""
    if section is None:
        return HooksConfig()
    if not isinstance(section, dict):
        raise ConfigPathError(
            "CONFIG_INVALID",
            str(path or "pm.toml") + " 的 [hooks] 必须是一个表（table）",
        )

    def _bool(name: str, default: bool) -> bool:
        if name not in section:
            return default
        value = section[name]
        if not isinstance(value, bool):
            raise ConfigPathError("CONFIG_INVALID", f"[hooks].{name} 必须是 true/false，收到 {value!r}")
        return value

    def _int(name: str, default: int, *, minimum: int, maximum: int) -> int:
        if name not in section:
            return default
        value = section[name]
        if isinstance(value, bool) or not isinstance(value, int) or not (minimum <= value <= maximum):
            raise ConfigPathError(
                "CONFIG_INVALID",
                f"[hooks].{name} 必须是 {minimum}..{maximum} 的整数，收到 {value!r}",
            )
        return value

    scope = section.get("scope", "")
    if not isinstance(scope, str):
        raise ConfigPathError("CONFIG_INVALID", f"[hooks].scope 必须是字符串，收到 {scope!r}")
    unknown = sorted(set(section) - {"inject", "max_items", "max_bytes", "session_max_bytes", "timeout_ms", "scope",
                                     "prompt", "prompt_max_bytes"})
    if unknown:
        # 不认识的键**不静默忽略**：拼错 max_item 会让预算悄悄变默认值
        raise ConfigPathError("CONFIG_INVALID", "[hooks] 不认识的键：" + ", ".join(unknown))
    return HooksConfig(
        inject=_bool("inject", True),
        max_items=_int("max_items", 3, minimum=0, maximum=50),
        max_bytes=_int("max_bytes", 1200, minimum=0, maximum=200_000),
        session_max_bytes=_int("session_max_bytes", 2400, minimum=0, maximum=200_000),
        timeout_ms=_int("timeout_ms", 1500, minimum=50, maximum=60_000),
        scope=scope.strip(),
        prompt=_bool("prompt", True),
        prompt_max_bytes=_int("prompt_max_bytes", 4000, minimum=0, maximum=200_000),
    )


def load(explicit: str | None = None) -> tuple[Config, list[str]]:
    """加载配置；缺失即使用内置默认值（自动发现数据根），绝不因为配置缺失而失败。"""
    warnings: list[str] = []
    path = discover_config_path(explicit)
    if path is None:
        warnings.append("未找到 pm.toml，自动发现数据根并按工作区路径分组")
        return Config(), warnings

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        # 存在的配置文件读不出来 / 语法坏了 → **硬失败**：静默改用默认值 = 静默串到默认库（真库）。
        raise ConfigPathError(
            "CONFIG_INVALID",
            f"配置文件无法解析: {path}: {exc}；不会回落默认库（请修好它，或删掉这个路径）。",
        ) from exc

    instances: list[Instance] = []
    for entry in raw.get("instance") or []:
        if not isinstance(entry, dict):
            continue
        target = str(entry.get("path") or "").strip()
        if not target:
            warnings.append(f"忽略不完整的 [[instance]] 条目: {entry!r}")
            continue
        resolved = Path(target).expanduser()
        ident = str(entry.get("id") or "").strip() or derive_source_instance(resolved)
        role = str(entry.get("role") or "work").strip() or "work"
        instances.append(Instance(id=ident, path=resolved, role=role))

    merges: list[MergeRule] = []
    for entry in raw.get("merge") or []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        paths = _as_paths(entry.get("paths"))
        if not key or not paths:
            warnings.append(f"忽略不完整的 [[merge]] 条目: {entry!r}")
            continue
        title = str(entry.get("title") or key).strip()
        merges.append(MergeRule(key=key, title=title, paths=paths))

    aliases: list[Alias] = []
    for entry in raw.get("alias") or []:
        if not isinstance(entry, dict):
            continue
        target = str(entry.get("path") or "").strip()
        project = str(entry.get("project") or "").strip()
        if target and project:
            aliases.append(Alias(path=target, project=project))

    dsh_home = raw.get("dsh_home")
    library = raw.get("library")
    vault = raw.get("vault")
    pins = raw.get("pins")
    exclude = raw.get("exclude_paths")
    row_limit = raw.get("row_limit")
    hooks = _parse_hooks(raw.get("hooks"), path)
    generate = _parse_generate(raw.get("memory"), path)

    return (
        Config(
            dsh_home=Path(str(dsh_home)).expanduser() if isinstance(dsh_home, str) and dsh_home else None,
            instances=tuple(instances),
            library=Path(str(library)).expanduser() if isinstance(library, str) and library else None,
            vault=Path(str(vault)).expanduser() if isinstance(vault, str) and vault else None,
            active_days=int(raw.get("active_days") or DEFAULT_ACTIVE_DAYS),
            active_hours=int(raw.get("active_hours") or DEFAULT_ACTIVE_HOURS),
            merges=tuple(merges),
            aliases=tuple(aliases),
            pins=frozenset(str(p) for p in pins if isinstance(p, str)) if isinstance(pins, list) else frozenset(),
            exclude_paths=_as_paths(exclude),
            row_limit=int(row_limit) if isinstance(row_limit, int) and row_limit >= 0 else 8,
            hooks=hooks,
            generate=generate,
            source_path=path,
        ),
        warnings,
    )
