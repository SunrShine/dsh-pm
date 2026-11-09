"""判定哪些会话是 subagent（子 agent 会话）。

子 agent 由主 agent 派发，**按设计不挂工作区** —— 在 workspace.json 里找不到它们
是正常行为，不是数据损坏。它们是内部委派，默认不该出现在面板上。

判定依据在会话日志的**第一帧**（seq 0）：
  {"type":"session", ..., "parentSession":"session-xxxx"}
  {"type":"subagent/descriptor", ...}
只看第一帧就够且便宜，实现交给 bin/subagent-probe.cjs（批量、一次 node 进程）。

⚠ 不能用「目录名是否带 session- 前缀」判定：实测有带前缀的子 agent，会漏。

保守原则（重要）：找不到日志 / 解码失败 / 没有 node → 一律当作**非**子 agent。
宁可多显示一张卡，也不能把真实工作藏起来。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pm.config import Instance
from pm.model import Agent
from pm.sessions import find_log, find_node

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = REPO_ROOT / "bin" / "subagent-probe.cjs"

#: 判定结果取值，与 bin/subagent-probe.cjs 的输出一致。
SUBAGENT = "SUBAGENT"
NORMAL = "normal"
UNKNOWN = "unknown"

#: 投影事实 `record.rows.subagent.val.identity.mode` 的取值：被 spawn 的 subagent/队友。
#: 另一个取值是 `one-shot`（普通会话）；缺字段 → 走日志探针兜底。
MODE_CONTINUABLE = "continuable"

PROBE_TIMEOUT_SECONDS = 180


def probe_paths(paths: list[str], *, timeout: int = PROBE_TIMEOUT_SECONDS) -> dict[str, str]:
    """批量判定日志文件；返回 {path: SUBAGENT|normal|unknown}。

    任何基础设施问题（没有 node、没有探针脚本、进程失败/超时）→ 返回 {}，
    调用方据此全部按「非子 agent」处理。
    """
    if not paths:
        return {}
    node = find_node()
    if node is None or not PROBE.is_file():
        return {}
    payload = "\n".join(paths) + "\n"
    try:
        proc = subprocess.run(
            [node, str(PROBE)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if proc.returncode != 0:
        return {}
    verdicts: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        verdict, _, path = line.partition("\t")
        if path:
            verdicts[path] = verdict
    return verdicts


def log_paths_for(agents: list[Agent], instances: tuple[Instance, ...]) -> dict[str, Agent]:
    """把每个 agent 映射到会话日志路径（找不到日志的会话直接没有条目）。"""
    by_id = {instance.id: instance for instance in instances}
    found: dict[str, Agent] = {}
    for agent in agents:
        instance = by_id.get(agent.source_instance)
        if instance is None:
            continue
        log = find_log(instance, agent.session_id)
        if log is not None:
            found[str(log)] = agent
    return found


def annotate_subagents(
    agents: list[Agent],
    instances: tuple[Instance, ...],
    *,
    probe=None,
) -> int:
    """给 agent 打上 is_subagent 标记，返回判为子 agent 的数量。

    **优先用投影事实**：`agent.session_mode == "continuable"`（record.rows.subagent.val.identity.mode，
    被 spawn 的 subagent/队友）→ 直接定论；`one-shot` → 不是子 agent。
    只有投影里**缺 mode**（None）时才回退到会话日志探针（`probe` 可注入，测试用；默认 `bin/subagent-probe.cjs`）。
    判定失败的会话保持 False。
    """
    if probe is None:
        probe = probe_paths
    hits = 0
    pending: list[Agent] = []
    for agent in agents:
        mode = getattr(agent, "session_mode", None)
        if mode:
            agent.is_subagent = mode == MODE_CONTINUABLE
            hits += 1 if agent.is_subagent else 0
        else:
            pending.append(agent)
    mapping = log_paths_for(pending, instances)
    if not mapping:
        return hits
    verdicts = probe(list(mapping))
    for path, agent in mapping.items():
        is_sub = verdicts.get(path) == SUBAGENT
        agent.is_subagent = is_sub
        hits += 1 if is_sub else 0
    return hits
