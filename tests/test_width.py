from __future__ import annotations

import unittest

from pm.width import display_width, pad, strip_ansi, truncate


class DisplayWidthTest(unittest.TestCase):
    def test_ascii_width(self) -> None:
        self.assertEqual(display_width("abc"), 3)

    def test_cjk_is_double_width(self) -> None:
        self.assertEqual(display_width("中文"), 4)
        self.assertEqual(display_width("a中b"), 4)

    def test_ansi_is_ignored(self) -> None:
        painted = "\x1b[1;32mACTIVE\x1b[0m"
        self.assertEqual(display_width(painted), 6)
        self.assertEqual(strip_ansi(painted), "ACTIVE")

    def test_truncate_respects_wide_chars(self) -> None:
        self.assertEqual(truncate("abcdef", 4), "abc…")
        # 4 个汉字 = 8 列，limit 5 → 只能放 2 个汉字 + 省略号
        self.assertEqual(truncate("中文字符", 5), "中文…")
        self.assertEqual(truncate("短", 5), "短")

    def test_pad_accounts_for_width(self) -> None:
        self.assertEqual(pad("中", 4), "中  ")
        self.assertEqual(pad("中", 4, "right"), "  中")

    def test_truncate_zero_limit(self) -> None:
        self.assertEqual(truncate("abc", 0), "")


if __name__ == "__main__":
    unittest.main()
