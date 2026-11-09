"""ULID / inbox ID 生成（设计 §5.1）。零依赖、同毫秒单调。"""

from __future__ import annotations

import re
import unittest

from pm.ids import ALPHABET, new_inbox_id, new_ulid, ulid_timestamp

ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
INBOX_RE = re.compile(r"^inbox-[0-9A-HJKMNP-TV-Z]{26}$")
#: 2100-01-01，远大于进程内可能出现的当前时间，避免时钟回拨分支干扰断言。
FUTURE_MS = 4102444800000


class UlidTest(unittest.TestCase):
    def test_format_is_crockford_base32(self) -> None:
        value = new_ulid()
        self.assertRegex(value, ULID_RE)
        self.assertEqual(len(value), 26)
        self.assertTrue(set(value) <= set(ALPHABET))

    def test_ids_are_unique(self) -> None:
        values = [new_inbox_id() for _ in range(500)]
        self.assertEqual(len(set(values)), 500)
        self.assertTrue(all(INBOX_RE.match(value) for value in values))

    def test_monotonic_within_same_millisecond(self) -> None:
        values = [new_ulid(FUTURE_MS) for _ in range(1000)]
        self.assertEqual(values, sorted(values), "同毫秒内必须单调递增")
        self.assertEqual(len(set(values)), 1000)

    def test_timestamp_roundtrip(self) -> None:
        # 取一个比前面任何用例都大的毫秒，避免触发时钟回拨分支
        value = new_ulid(FUTURE_MS + 10_000_000)
        self.assertEqual(ulid_timestamp(value), FUTURE_MS + 10_000_000)

    def test_clock_rollback_never_goes_backwards(self) -> None:
        later = new_ulid(FUTURE_MS + 10)
        earlier = new_ulid(FUTURE_MS + 1)  # 模拟时钟回拨
        self.assertGreater(earlier, later, "时间回拨时 ULID 也不能倒退")
