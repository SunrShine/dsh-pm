"""可安装化自证：入口点 / 包数据 / 配置发现（task-104）。

只做「安装后是否成立」的入口与资源断言，不重复业务测试。
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from pm import __version__, cli, config

REPO_ROOT = Path(__file__).resolve().parents[1]


class PackagingMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_project_metadata(self) -> None:
        project = self.data["project"]
        self.assertEqual(project["name"], "dsh-pm")
        self.assertEqual(project["requires-python"], ">=3.11")
        self.assertEqual(project["dependencies"], [], "零运行时依赖")
        self.assertEqual(project["license"], {"text": "MIT"})

    def test_entry_point_matches_cli_main(self) -> None:
        self.assertEqual(self.data["project"]["scripts"]["pm"], "pm.cli:main")
        self.assertTrue(callable(cli.main))

    def test_version_is_single_sourced(self) -> None:
        self.assertEqual(
            self.data["project"]["version"], __version__, "pyproject 与 pm.__version__ 必须一致"
        )

    def test_package_data_declares_bundled_skill(self) -> None:
        globs = self.data["tool"]["setuptools"]["package-data"]["pm"]
        self.assertIn("_skill/**/*.md", globs)

    def test_frontend_is_not_part_of_the_python_package(self) -> None:
        # 只检查声明（注释里提到 frontend_impl 说明「刻意不打进包」是可以的）
        package_data = self.data["tool"]["setuptools"]["package-data"]
        self.assertNotIn("frontend_impl", str(package_data), "前端属插件侧，不进 Python 包")
        self.assertFalse((REPO_ROOT / "src" / "pm" / "frontend_impl").exists())


class BundledSkillTest(unittest.TestCase):
    #: skill 树里**必须存在**的文件（SKILL.md 精简 + references/ 渐进披露）
    REQUIRED_SKILL_FILES = (
        "SKILL.md",
        "references/tasks-and-states.md",
        "references/evidence.md",
        "references/inbox-and-memory.md",
    )

    @staticmethod
    def _tree(root: Path) -> dict:
        """{相对路径: 字节}，含所有文件（references/ 也要覆盖，别只比 SKILL.md）。"""
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_skill_tree_has_required_files(self) -> None:
        for rel in self.REQUIRED_SKILL_FILES:
            self.assertTrue(
                (REPO_ROOT / "skill" / "pm" / rel).is_file(), f"skill/pm 缺 {rel}"
            )

    def test_bundled_tree_matches_source_byte_for_byte(self) -> None:
        source = REPO_ROOT / "skill" / "pm"
        bundled = REPO_ROOT / "src" / "pm" / "_skill" / "pm"
        source_files = self._tree(source)
        bundled_files = self._tree(bundled)
        self.assertEqual(
            sorted(bundled_files),
            sorted(source_files),
            "包内副本与 skill/pm 的**文件集合**必须一致（新增 references 也要同步）",
        )
        for name, data in source_files.items():
            self.assertEqual(
                bundled_files[name], data, f"skill/pm/{name} 与包内副本不一致（改完要同步）"
            )

    def test_skill_prose_has_no_absolute_host_paths_and_stays_lean(self) -> None:
        for name, data in self._tree(REPO_ROOT / "skill" / "pm").items():
            text = data.decode("utf-8")
            self.assertNotIn("/home/", text, f"skill/pm/{name} 里写死了本机路径")
            self.assertNotIn("/Users/", text, f"skill/pm/{name} 里写死了本机路径")
        skill_md = (REPO_ROOT / "skill" / "pm" / "SKILL.md").read_text(encoding="utf-8")
        self.assertLessEqual(
            len(skill_md.splitlines()), 150, "SKILL.md 要精简，细节放 references/（渐进披露）"
        )

    def test_install_lays_down_the_full_tree_in_a_temp_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["skill", "install", "--dsh-home", tmp])
            self.assertEqual(code, 0, out.getvalue())
            installed = Path(tmp) / "skills" / "pm"
            self.assertTrue(installed.is_dir(), "安装后应有 <dsh-home>/skills/pm")
            for rel in self.REQUIRED_SKILL_FILES:
                target = installed / rel
                self.assertTrue(target.is_file(), f"安装后缺 {rel}")
                self.assertEqual(
                    target.read_bytes(),
                    (REPO_ROOT / "skill" / "pm" / rel).read_bytes(),
                    f"安装后 {rel} 与源不一致",
                )

    def test_skill_source_env_override_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "pm"
            fake.mkdir()
            (fake / "SKILL.md").write_text("x", encoding="utf-8")
            with mock.patch.dict(os.environ, {"PM_SKILL_DIR": str(fake)}):
                self.assertEqual(cli.skill_source(), fake)

    def test_skill_source_falls_back_to_bundle(self) -> None:
        bundled = REPO_ROOT / "src" / "pm" / "_skill" / "pm"
        with mock.patch.object(cli, "skill_source_candidates", return_value=[bundled]):
            self.assertEqual(cli.skill_source(), bundled)

    def test_skill_path_command_prints_source(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            # 用 --skill 取「单条 skill 的裸路径」；不带参数时是「全部 skill 的 name\tpath 列表」
            code = cli.main(["skill", "path", "--skill", "pm"])
        self.assertEqual(code, 0)
        self.assertTrue((Path(out.getvalue().strip()) / "SKILL.md").is_file())


class ConfigDiscoveryTest(unittest.TestCase):
    def test_user_config_used_when_no_local_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            (home / ".dsh-pm").mkdir(parents=True)
            user_config = home / ".dsh-pm" / "pm.toml"
            user_config.write_text('library = "' + str(Path(tmp) / "wm") + '"\n', encoding="utf-8")
            cwd = Path(tmp) / "cwd"
            cwd.mkdir()
            with mock.patch.object(Path, "home", return_value=home), mock.patch(
                "os.getcwd", return_value=str(cwd)
            ):
                os.environ.pop("PM_CONFIG", None)
                self.assertEqual(config.discover_config_path(), user_config)
                loaded, _warnings = config.load()
                self.assertEqual(loaded.source_path, user_config)

    def test_local_config_beats_user_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            (home / ".dsh-pm").mkdir(parents=True)
            (home / ".dsh-pm" / "pm.toml").write_text("", encoding="utf-8")
            cwd = Path(tmp) / "cwd"
            cwd.mkdir()
            local = cwd / "pm.toml"
            local.write_text("", encoding="utf-8")
            with mock.patch.object(Path, "home", return_value=home), mock.patch(
                "os.getcwd", return_value=str(cwd)
            ):
                os.environ.pop("PM_CONFIG", None)
                self.assertEqual(config.discover_config_path(), local)

    def test_no_config_at_all_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            cwd = Path(tmp) / "cwd"
            cwd.mkdir()
            with mock.patch.object(Path, "home", return_value=home), mock.patch(
                "os.getcwd", return_value=str(cwd)
            ), mock.patch.object(config, "DEFAULT_CONFIG_PATH", Path(tmp) / "nope.toml"):
                os.environ.pop("PM_CONFIG", None)
                loaded, warnings = config.load()
                self.assertIsNone(loaded.source_path, "没有配置文件也不该报错")
                self.assertTrue(warnings)

    def test_module_entrypoint_runs_with_clean_home(self) -> None:
        """干净 HOME + 无仓库配置：`python -m pm --version` 必须能跑（不依赖本机路径）。"""
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": tmp,
                "PYTHONPATH": str(REPO_ROOT / "src"),
            }
            result = subprocess.run(
                [sys.executable, "-m", "pm", "--version"],
                cwd=tmp, env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(__version__, result.stdout)


if __name__ == "__main__":
    unittest.main()
