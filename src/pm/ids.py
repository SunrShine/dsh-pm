"""零依赖 ULID 生成（Crockford base32，26 字符）。

设计 §5.1 要求每条 inbox 记录有稳定 ID：inbox-<ULID>。
用标准 ULID 布局：48bit 毫秒时间戳（10 字符）+ 80bit 随机（16 字符），
**同一毫秒内单调递增**（同一进程多次捕获按字典序递增，方便排序与断言）。

不引入第三方依赖：随机数走 os.urandom，编码用 Cronkford base32 字母表。
"""

from __future__ import annotations

import os
import threading
import time

#: Crockford base32（去掉 I/L/O/U，字典序 == 数值序）。
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_TIMESTAMP_CHARS = 10
_RANDOM_CHARS = 16
_RANDOM_BITS = 80
_MAX_RANDOM = (1 << _RANDOM_BITS) - 1

_lock = threading.Lock()
_last_ms = -1
_last_random = 0


def _encode(value: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        chars.append(ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def ulid_timestamp(ulid: str) -> int:
    """从 ULID 还原毫秒时间戳（测试/排查用；不参与正常流程）。"""
    value = 0
    for char in ulid[:_TIMESTAMP_CHARS]:
        value = value * 32 + ALPHABET.index(char)
    return value


def new_ulid(now_ms: int | None = None) -> str:
    """生成一个 ULID；同毫秒内重复调用递增，时钟回拨也不会倒退。"""
    global _last_ms, _last_random
    ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    with _lock:
        if ms > _last_ms:
            rand = int.from_bytes(os.urandom(10), "big") & _MAX_RANDOM
        else:
            # 同毫秒 → 随机部分 +1；时钟回拨 → 沿用上个时间戳递增，保证单调。
            if ms < _last_ms:
                ms = _last_ms
            rand = _last_random + 1
            if rand > _MAX_RANDOM:  # 同一毫秒内耗尽 2^80 次（实际不可能）
                ms += 1
                rand = 0
        _last_ms, _last_random = ms, rand
    return _encode(ms, _TIMESTAMP_CHARS) + _encode(rand, _RANDOM_CHARS)


def new_entity_id(prefix: str, now_ms: int | None = None) -> str:
    """任意实体的 ID：<prefix>-<ULID>（inbox- / task- / proposal- / memory-…）。

    所有实体共用一个 ULID 生成器，保证同一进程内跨实体也单调唯一。
    """
    return f"{prefix}-{new_ulid(now_ms)}"


def new_inbox_id(now_ms: int | None = None) -> str:
    """设计 §5.1 的 inbox 记录 ID：inbox-<ULID>。"""
    return new_entity_id("inbox", now_ms)
