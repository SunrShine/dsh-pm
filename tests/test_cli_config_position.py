"""父级/子级位置的公共选项（--config / --dsh-home）必须**两处都认**。

由来（task 记）：`pm proposal create --config X` 曾报 `unrecognized arguments`（子命令位置不认），
而 `pm --config X proposal create` 认 —— 同一件事两个来源、行为还不一致 ✗。
按 `index` 那次的修法：子解析器用 `_add_common_options(..., as_defaults=True)`（SUPPRESS 默认值，
不覆盖父级）。这里把"代表性命令 × 两个位置"钉成判据，防回归。

判据：
  ① 子命令位置 + 不存在的 --config ⇒ **不得**出现 "unrecognized arguments"（这就是当时的红）；
  ② 而且必须是"**认了**"：报 CONFIG_NOT_FOUND / 不存在（证明值被采纳，不是被静默忽略）；
  ③ 父级位置同命令同期望（基线）。
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PM = str(REPO / "bin" / "pm")
BOGUS = "/tmp/definitely-not-here-config-position.toml"

#: (说明, argv 片段)。写命令都补齐必填参数，免得 argparse 先报缺参而看不到选项归属。
CASES = [
    ("proposal create", ["proposal", "create", "--source-inbox", "inbox-x", "--dry-run"]),
    ("proposal approve", ["proposal", "approve", "prop-x", "--expected-revision", "1"]),
    ("proposal reject", ["proposal", "reject", "prop-x", "--expected-revision", "1", "--reason", "r"]),
    ("proposal revise", ["proposal", "revise", "prop-x", "--expected-revision", "1"]),
    ("proposal list", ["proposal", "list"]),
    ("task list", ["task", "list", "--project", "pm_tools"]),
    ("memory context", ["memory", "context", "--scope", "global"]),
    ("inbox list", ["inbox", "list"]),
    ("project list", ["project", "list"]),
    ("index", ["index"]),
    ("recall", ["recall", "--query", "x"]),
]


def run(argv: list) -> tuple:
    proc = subprocess.run([PM, *argv], capture_output=True, text=True, cwd=str(REPO))
    return proc.returncode, proc.stdout, proc.stderr


class ConfigFlagPositionTest(unittest.TestCase):
    def test_subcommand_position_is_accepted_and_honored(self) -> None:
        for name, argv in CASES:
            with self.subTest(command=name):
                _code, out, err = run([*argv, "--config", BOGUS])
                blob = out + err
                self.assertNotIn("unrecognized arguments", blob,
                                 name + " 在子命令位置不认 --config（应照 index 那次改成 as_defaults=True）")
                self.assertTrue("CONFIG_NOT_FOUND" in blob or "不存在" in blob,
                                name + " 子命令位置接受了 --config 但没采纳（应报 CONFIG_NOT_FOUND）：" + blob[-160:])

    def test_parent_position_still_works(self) -> None:
        for name, argv in CASES:
            with self.subTest(command=name):
                _code, out, err = run(["--config", BOGUS, *argv])
                blob = out + err
                self.assertTrue("CONFIG_NOT_FOUND" in blob or "不存在" in blob,
                                name + " 父级位置回归：应报 CONFIG_NOT_FOUND，实际：" + blob[-160:])

    def test_dsh_home_two_positions_do_not_error_out(self) -> None:
        for name, argv in CASES[:6]:
            with self.subTest(command=name):
                for prefix in ([], ["--dsh-home", "/tmp/nope-dsh-home"]):
                    if prefix:
                        full = [*argv, *prefix]
                    else:
                        full = ["--dsh-home", "/tmp/nope-dsh-home", *argv]
                    _code, out, err = run(full)
                    self.assertNotIn("unrecognized arguments", out + err,
                                     name + " 的 --dsh-home 位置不被认：" + (out + err)[-120:])


if __name__ == "__main__":
    unittest.main()
