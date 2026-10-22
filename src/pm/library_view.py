"""把 work-memory 库里的摘要挂到扫描结果上。

cli 与 mcp 两条入口都要用，所以抽出来共享 —— 重复实现过一次，
结果 pm scan 说「全部缺摘要」而看板说有 30 条，两个数字自相矛盾。
"""

from __future__ import annotations

from pathlib import Path

from pm.config import Config
from pm.scan import ScanResult
from pm.summaries import load_ai, load_human, resolve


def attach_library_summaries(config: Config, result: ScanResult) -> int:
    """按 人工 > AI 解析摘要并写回 agent。返回命中的条数。"""
    library = config.library
    if library is None or not Path(library).is_dir():
        return 0
    human = load_human(library)
    ai = load_ai(library)
    hit = 0
    for agent in result.all_agents:
        entry = resolve(agent.identity_key, human, ai)
        if entry is None:
            continue
        agent.resolved_summary = entry.text
        agent.resolved_summary_source = entry.source
        if entry.source == "human":
            agent.human_summary = entry.text
        hit += 1
    return hit
