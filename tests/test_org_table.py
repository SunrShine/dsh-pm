from __future__ import annotations

import unittest

from pm.render.org import cell_display_width, org_table


class OrgTableTest(unittest.TestCase):
    """表格必须和 Emacs 的 org-table-align 结果一致，否则 Emacs 一 align 就推翻我们。

    两条 org 规则：链接按**描述**计宽；整列是数字时**右对齐**。
    """

    def rendered(self, line: str) -> int:
        return cell_display_width(line)

    def test_rows_share_one_rendered_width(self) -> None:
        lines = org_table(
            ["项目", "工作卡", "详情"],
            [
                ["PeTree 张量处理器", "88", "[[file:x][打开]]"],
                ["pm_tools", "5", "[[file:y][打开]]"],
                ["rui", "10", "[[file:z][打开]]"],
            ],
        )
        widths = {self.rendered(line) for line in lines}
        self.assertEqual(len(widths), 1, f"渲染宽度不一致: {sorted(widths)}")

    def test_links_measured_by_description(self) -> None:
        # [[file:a/b.org][打开]] 在 org 里只占 4 列
        self.assertEqual(cell_display_width("[[file:generated/projects/x.org][打开]]"), 4)
        self.assertEqual(cell_display_width("[[file:x.org]]"), len("file:x.org"))

    def test_numeric_columns_are_right_aligned(self) -> None:
        lines = org_table(["项目", "数量"], [["a", "5"], ["b", "100"]])
        # 右对齐的含义：两个数字的**右边缘**在同一列
        self.assertTrue(lines[2].endswith("  5 |"), lines[2])
        self.assertTrue(lines[3].endswith("100 |"), lines[3])

    def test_non_numeric_column_stays_left(self) -> None:
        lines = org_table(["项目", "进度"], [["a", "0/0"], ["b", "42/228"]])
        self.assertIn("| 0/0 ", lines[2].replace("| 0/0", "| 0/0"))

    def test_separator_matches_column_count(self) -> None:
        lines = org_table(["a", "bb"], [["1", "2"]])
        self.assertEqual(lines[1].count("+"), 1)
        self.assertTrue(lines[1].strip().startswith("|"))

    def test_pipes_in_cells_are_escaped(self) -> None:
        lines = org_table(["a", "b"], [["x|y", "z"]])
        self.assertEqual(lines[0].count("|"), 3)
        self.assertEqual(lines[2].count("|"), 3)

    def test_newlines_in_cells_are_collapsed(self) -> None:
        lines = org_table(["a"], [["多\n行"]])
        self.assertEqual(len(lines), 3)

    def test_ragged_rows_do_not_break(self) -> None:
        lines = org_table(["a", "b", "c"], [["1"]])
        widths = {self.rendered(line) for line in lines}
        self.assertEqual(len(widths), 1)


if __name__ == "__main__":
    unittest.main()
