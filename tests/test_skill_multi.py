"""多 skill 发现与安装（task-150）：skill/*/SKILL.md + `pm skill path|install [--skill|--all]`。

只用临时目录：不碰真实 DSH 数据根，也不依赖仓库里当时有几条 skill。
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pm import cli

FRONTMATTER = "---\nname: {name}\ndescription: {name} 的说明\nwhenToUse: 测试用\n---\n\n# {name}\n\n正文\n"


def make_skill(root: Path, name: str, *, with_references: bool = True, frontmatter_name: str | None = None) -> Path:
    """在 `root/<name>/` 下造一份合法 skill（可选 references/）。"""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        FRONTMATTER.format(name=frontmatter_name or name), encoding="utf-8"
    )
    if with_references:
        refs = directory / "references"
        refs.mkdir(exist_ok=True)
        (refs / "extra.md").write_text("细节\n", encoding="utf-8")
    return directory


class DiscoverSkillsTest(unittest.TestCase):
    def test_discovers_every_skill_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_skill(root, "pm")
            make_skill(root, "pm-evidence")
            skills = cli.discover_skills(root)
            self.assertEqual([s.name for s in skills], ["pm", "pm-evidence"])
            self.assertEqual(skills[0].path, root / "pm")
            self.assertTrue(skills[0].description)

    def test_single_skill_dir_is_treated_as_one_skill(self) -> None:
        # 兼容旧用法：PM_SKILL_DIR 直接指向一个 skill 目录
        with tempfile.TemporaryDirectory() as tmp:
            single = make_skill(Path(tmp), "pm")
            skills = cli.discover_skills(single)
            self.assertEqual([s.name for s in skills], ["pm"])

    def test_missing_skill_md_is_an_explicit_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_skill(root, "pm")
            (root / "broken").mkdir()
            with self.assertRaises(cli.SkillDiscoveryError) as ctx:
                cli.discover_skills(root)
            self.assertIn("broken", str(ctx.exception))
            self.assertIn("SKILL.md", str(ctx.exception))

    def test_missing_frontmatter_or_name_is_an_explicit_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "pm"
            bad.mkdir()
            (bad / "SKILL.md").write_text("# 没有 frontmatter\n", encoding="utf-8")
            with self.assertRaises(cli.SkillDiscoveryError) as ctx:
                cli.discover_skills(root)
            self.assertIn("name", str(ctx.exception))

    def test_frontmatter_name_wins_and_warns_on_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_skill(root, "dir-name", frontmatter_name="real-name")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                skills = cli.discover_skills(root)
            self.assertEqual([s.name for s in skills], ["real-name"])
            self.assertIn("不一致", err.getvalue())


class SkillCliTest(unittest.TestCase):
    def run_cli(self, argv: list) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_path_lists_all_skills_and_skill_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_skill(root, "pm")
            make_skill(root, "pm-planning")
            with mock.patch.dict(os.environ, {"PM_SKILL_DIR": str(root)}):
                code, out, _ = self.run_cli(["skill", "path"])
                self.assertEqual(code, 0)
                lines = [line for line in out.strip().splitlines() if line]
                self.assertEqual(len(lines), 2, out)
                self.assertEqual([line.split("\t")[0] for line in lines], ["pm", "pm-planning"])
                code, out, _ = self.run_cli(["skill", "path", "--skill", "pm-planning"])
                self.assertEqual(code, 0)
                self.assertEqual(out.strip(), str(root / "pm-planning"))

    def test_unknown_skill_is_exit_2_with_known_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_skill(root, "pm")
            with mock.patch.dict(os.environ, {"PM_SKILL_DIR": str(root)}):
                code, _, err = self.run_cli(["skill", "path", "--skill", "nope"])
            self.assertEqual(code, 2)
            self.assertIn("pm", err)
            self.assertIn("nope", err)

    def test_broken_root_is_reported_not_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_skill(root, "pm")
            (root / "broken").mkdir()
            with mock.patch.dict(os.environ, {"PM_SKILL_DIR": str(root)}):
                code, _, err = self.run_cli(["skill", "path"])
            self.assertEqual(code, 2)
            self.assertIn("broken", err)

    def test_install_installs_all_then_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills-src"
            root.mkdir()
            make_skill(root, "pm")
            make_skill(root, "pm-evidence")
            dsh_home = Path(tmp) / "dsh"
            with mock.patch.dict(os.environ, {"PM_SKILL_DIR": str(root)}):
                code, out, _ = self.run_cli(["skill", "install", "--dsh-home", str(dsh_home)])
                self.assertEqual(code, 0, out)
                for name in ("pm", "pm-evidence"):
                    target = dsh_home / "skills" / name
                    self.assertTrue(target.is_symlink(), f"{name} 应被安装")
                    self.assertEqual(target.resolve(), root / name)
                    self.assertTrue((target / "SKILL.md").is_file())
                    self.assertTrue((target / "references" / "extra.md").is_file(), "references 也要齐")
                    self.assertIn(name, out)
                code, out2, _ = self.run_cli(["skill", "install", "--dsh-home", str(dsh_home)])
                self.assertEqual(code, 0)
                self.assertIn("幂等", out2)

    def test_install_skill_selects_one_and_keeps_others(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills-src"
            root.mkdir()
            make_skill(root, "pm")
            make_skill(root, "pm-planning")
            dsh_home = Path(tmp) / "dsh"
            with mock.patch.dict(os.environ, {"PM_SKILL_DIR": str(root)}):
                code, out, _ = self.run_cli(
                    ["skill", "install", "--skill", "pm-planning", "--dsh-home", str(dsh_home)]
                )
                self.assertEqual(code, 0, out)
                self.assertTrue((dsh_home / "skills" / "pm-planning").is_symlink())
                self.assertFalse((dsh_home / "skills" / "pm").exists())

    def test_install_does_not_clobber_foreign_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills-src"
            root.mkdir()
            make_skill(root, "pm")
            dsh_home = Path(tmp) / "dsh"
            foreign = dsh_home / "skills" / "pm"
            foreign.mkdir(parents=True)
            (foreign / "SKILL.md").write_text("别人的 skill\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"PM_SKILL_DIR": str(root)}):
                code, _, err = self.run_cli(["skill", "install", "--dsh-home", str(dsh_home)])
            self.assertEqual(code, 2)
            self.assertIn("不是本工具的软链", err)
            self.assertEqual((foreign / "SKILL.md").read_text(encoding="utf-8"), "别人的 skill\n")

    def test_legacy_single_skill_package_behaves_the_same(self) -> None:
        # 旧包只有一条 skill：不带 --skill 也装到 <dsh>/skills/pm（行为不变）
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills-src"
            root.mkdir()
            make_skill(root, "pm", with_references=False)
            dsh_home = Path(tmp) / "dsh"
            with mock.patch.dict(os.environ, {"PM_SKILL_DIR": str(root)}):
                code, out, _ = self.run_cli(["skill", "install", "--dsh-home", str(dsh_home)])
                self.assertEqual(code, 0, out)
                self.assertTrue((dsh_home / "skills" / "pm" / "SKILL.md").is_file())
