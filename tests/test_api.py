"""pm api --envelope：设计 §6 的统一 envelope（新形态，ui-cards 形状不动）。"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from pm import cli
from pm.config import derive_source_instance

import fixtures

TOP_KEYS = {"ok", "schemaVersion", "generatedAt", "source", "data", "warnings"}


class ApiEnvelopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = fixtures.build_dsh_home(Path(self._tmp.name))
        self.config = Path(self._tmp.name) / "pm.toml"
        self.config.write_text(
            fixtures.fixture_config_toml().replace("REPLACED", str(self.home)), encoding="utf-8"
        )

    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def envelope(self, *extra: str) -> dict:
        code, stdout, _ = self.run_cli(
            ["--config", str(self.config), "api", "--envelope", *extra, "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 0)
        return json.loads(stdout)

    def test_envelope_shape_matches_design_section_6(self) -> None:
        payload = self.envelope()
        self.assertEqual(set(payload), TOP_KEYS)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["schemaVersion"], "pm-api-v2")
        self.assertIsInstance(payload["generatedAt"], str)
        self.assertEqual(set(payload["source"]), {"org", "dshInstances"})
        self.assertEqual(payload["source"]["dshInstances"], [derive_source_instance(self.home)])
        self.assertIsInstance(payload["warnings"], list)
        self.assertEqual(
            set(payload["data"]),
            {"schemaVersion", "capabilities", "runtime_status", "projects", "cards", "inbox"},
        )
        self.assertEqual(payload["data"]["schemaVersion"], "ui-cards-v1")
        self.assertEqual(payload["data"]["runtime_status"], "unknown")

    def test_envelope_data_matches_ui_cards(self) -> None:
        envelope = self.envelope()
        code, stdout, _ = self.run_cli(
            ["--config", str(self.config), "ui-cards", "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 0)
        cards = json.loads(stdout)
        # ui-cards 的既有键一个不少
        for key in ("generated_at", "library", "instances", "projects", "cards", "inbox"):
            self.assertIn(key, cards)
        # 两次调用的 generated_at 本来就会不同（各自扫描一次），比数据形状与同源字段
        self.assertTrue(envelope["generatedAt"])
        self.assertEqual(envelope["source"]["org"], cards["library"])
        self.assertEqual(envelope["source"]["dshInstances"], cards["instances"])
        self.assertEqual(
            [p["key"] for p in envelope["data"]["projects"]],
            [p["key"] for p in cards["projects"]],
        )
        self.assertEqual(len(envelope["data"]["cards"]), len(cards["cards"]))
        self.assertEqual(envelope["data"]["inbox"], cards["inbox"])

    def test_requires_envelope_flag(self) -> None:
        code, stdout, stderr = self.run_cli(
            ["--config", str(self.config), "api", "--dsh-home", str(self.home)]
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("--envelope", stderr)

    def test_project_filter_applies(self) -> None:
        payload = self.envelope("--project", "alpha_beta")
        self.assertEqual([p["key"] for p in payload["data"]["projects"]], ["alpha_beta"])
        self.assertTrue(payload["data"]["cards"])


if __name__ == "__main__":
    unittest.main()
