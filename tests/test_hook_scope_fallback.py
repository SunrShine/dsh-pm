"""tests/test_hook_scope_fallback.py —— SessionStart 的 scope 三段回退。

依据：用户 2026-10-18 批准提案 proposal-01M56JF3Y43ZHKMDVSAKGWSZYQ。
口径：① 显式 [hooks].scope ⇒ 与今天完全一致；② scope 空 + payload cwd 推导出项目（且有 VERIFIED）⇒ 注入该项目；
      ③ 推导不出 ⇒ 0 字节（不猜）；④ 负例：别项目有 VERIFIED 而 cwd 不属于它 ⇒ 一条都不注入（防跨项目泄漏）；
      ⑤ 三级优先级自证；⑥ 输出带 tier 与来源说明；⑦ 注入只读。
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from pm import hooks, index, memory
from pm.config import HooksConfig
from pm.layout import Layout

ALPHA_FACT = """* Facts
** alpha 项目的事实
   :PROPERTIES:
   :ID: memory-alpha-001
   :PM_STATUS: VERIFIED
   :PM_SCOPE: alpha
   :PM_TYPE: fact
   :PM_REVISION: 1
   :END:
   alpha 项目专有的事实正文。
"""

PROJECT_ORG = """#+TITLE: {title}
#+PM_PATH: {path}

* 说明
{key} 项目。
"""


def project_dir(root, key, workspace):
    """在库里写一个项目（project.org 带 #+PM_KEY: 与 #+PM_PATH:）。"""
    path = root / "projects" / ("proj-" + key)
    path.mkdir(parents=True, exist_ok=True)
    (path / "project.org").write_text(
        "#+TITLE: " + key + "\n#+PM_KEY: " + key + "\n#+PM_PATH: " + str(workspace) + "\n",
        encoding="utf-8",
    )
    return path


class ScopeFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "memory").mkdir(parents=True)
        (self.root / "memory" / "facts.org").write_text(ALPHA_FACT, encoding="utf-8")
        self.ws_alpha = self.root / "ws-alpha"
        self.ws_beta = self.root / "ws-beta"
        self.ws_alpha.mkdir()
        self.ws_beta.mkdir()
        project_dir(self.root, "alpha", self.ws_alpha)
        project_dir(self.root, "beta", self.ws_beta)   # beta 没有 VERIFIED 记忆
        (self.root / "pm.toml").write_text('library = "' + str(self.root) + '"\n', encoding="utf-8")
        self.layout = Layout(self.root)
        self.addCleanup(self._tmp.cleanup)
        index._FTS5_CACHE = None

    def text(self, *, scope: str = "", cwd: str = "", hooks_cfg: HooksConfig | None = None,
             alias_index: dict | None = None) -> str:
        return hooks.session_start_text(
            self.layout, hooks_cfg or HooksConfig(), scope=scope, payload_cwd=cwd,
            alias_index=alias_index or {},
        )

    def test_explicit_scope_format_unchanged(self) -> None:
        """① 显式档：不带 tier 后缀、不带来源行（格式与改前逐字节一致）。"""
        text = self.text(scope="alpha")
        self.assertIn("[pm-memory session-start scope=alpha items=1/3 budget=2400B]", text)
        self.assertNotIn("tier=", text)
        self.assertNotIn("scope 来源", text)

    def test_config_scope_wins_over_cwd(self) -> None:
        """① 配置 [hooks].scope 也是显式档：cwd 指向别处也仍用它。"""
        text = self.text(cwd=str(self.ws_beta), hooks_cfg=HooksConfig(scope="alpha"))
        self.assertIn("scope=alpha", text)
        self.assertNotIn("tier=", text)

    def test_cwd_derivation_injects_that_project(self) -> None:
        """② cwd 属于 alpha（有 VERIFIED）⇒ 注入 alpha，并标 tier=cwd + 来源说明。"""
        text = self.text(cwd=str(self.ws_alpha))
        self.assertIn("scope=alpha", text)
        self.assertIn("tier=cwd", text)
        self.assertIn("scope 来源", text)
        self.assertIn("alpha 项目专有的事实", text)

    def test_underivable_falls_to_global_not_all_library(self) -> None:
        """③ 推导不出 ⇒ 用 global；本库 global 无 VERIFIED ⇒ 0 字节（绝不回退全库）。"""
        text = self.text(cwd="/tmp/definitely-not-a-project")
        self.assertEqual(text, "")

    def test_project_without_verified_injects_nothing(self) -> None:
        """④ 负例（防跨项目泄漏）：cwd 属 beta（无 VERIFIED），而 alpha 有 ⇒ 一条都不注入。"""
        text = self.text(cwd=str(self.ws_beta))
        self.assertEqual(text, "")
        self.assertNotIn("alpha", text)

    def test_alias_mapping_also_resolves(self) -> None:
        """cwd → 项目的第二来源：pm.toml [[alias]]（显式声明）也能解析。"""
        text = self.text(cwd=str(self.ws_beta), alias_index={str(self.ws_beta): "alpha"})
        self.assertIn("scope=alpha", text)
        self.assertIn("tier=cwd", text)

    def test_longest_prefix_wins(self) -> None:
        nested = self.ws_alpha / "sub"
        nested.mkdir()
        project_dir(self.root, "gamma", nested)
        (self.root / "memory" / "gotchas.org").write_text("""* Gotchas
** gamma 的坑
   :PROPERTIES:
   :ID: memory-gamma-001
   :PM_STATUS: VERIFIED
   :PM_SCOPE: gamma
   :PM_TYPE: gotcha
   :PM_REVISION: 1
   :END:
   gamma 专有的坑。
""", encoding="utf-8")
        text = self.text(cwd=str(nested))
        self.assertIn("scope=gamma", text)

    def test_json_summary_fields(self) -> None:
        """⑦ 结构化面：tier/scope/scopeSource 由 tier_out 透出（hook --json 用同一份）。"""
        info: dict = {}
        hooks.session_start_text(self.layout, HooksConfig(), payload_cwd=str(self.ws_alpha), tier_out=info)
        self.assertEqual(info["tier"], "cwd")
        self.assertEqual(info["scope"], "alpha")
        self.assertIn("project.org", info["scopeSource"])

    def test_injection_is_read_only(self) -> None:
        """⑧ 只读：注入前后库内 *.org 指纹不变。"""
        def fingerprint() -> str:
            parts = []
            for path in sorted((self.root / "memory").glob("*.org")):
                parts.append(path.name + ":" + hashlib.sha256(path.read_bytes()).hexdigest())
            return "|".join(parts)

        before = fingerprint()
        self.text(cwd=str(self.ws_alpha))
        self.text(cwd=str(self.ws_beta))
        self.assertEqual(fingerprint(), before)

    def test_resolve_session_scope_priority(self) -> None:
        """⑤ 三级优先级：显式 > cwd 推导 > global。"""
        alpha = hooks.resolve_session_scope(self.layout, HooksConfig(), scope="beta", payload_cwd=str(self.ws_alpha))
        self.assertEqual(alpha[0], "beta")
        self.assertEqual(alpha[1], "explicit")
        config_scope = hooks.resolve_session_scope(self.layout, HooksConfig(scope="beta"), payload_cwd=str(self.ws_alpha))
        self.assertEqual(config_scope[0], "beta")
        self.assertEqual(config_scope[1], "explicit")
        derived = hooks.resolve_session_scope(self.layout, HooksConfig(), payload_cwd=str(self.ws_alpha))
        self.assertEqual(derived[0], "alpha")
        self.assertEqual(derived[1], "cwd")
        fallback = hooks.resolve_session_scope(self.layout, HooksConfig(), payload_cwd="/tmp/nope")
        self.assertEqual(fallback[0], "global")
        self.assertEqual(fallback[1], "global")


if __name__ == "__main__":
    unittest.main()
