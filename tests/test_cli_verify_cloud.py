"""Issue #60 离线部分：`verify-cloud` 只读核对 CLI。

全部用例都用 `tests/fixtures/verify_cloud/<scenario>/` 下的离线 fixture 重放：
无网络、无真实凭据。fixture 的 mobile DTO 由 `mobile_summary.build_mobile_summary`
从同一份 summary 生成（见 `TestVerifyCloudFixturesStayBoundToReadModel`），
所以「两端口径一致」不是手写出来的巧合。
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ai_usage_widget import cli


FIXTURES = Path(__file__).parent / "fixtures" / "verify_cloud"
HEALTHY = FIXTURES / "healthy"
DEGRADED = FIXTURES / "degraded"
PARITY_MISMATCH = FIXTURES / "parity_mismatch"


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    """跑一次 CLI，返回 (退出码, stdout, stderr)。"""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def copy_scenario(scenario: Path, mutate=None) -> str:
    """把一个场景复制到临时目录，可选地改写 summary.json 后返回目录路径。"""
    directory = tempfile.mkdtemp(prefix="verify-cloud-")
    for name in ("summary.json", "mobile_summary.json", "health.json"):
        shutil.copy(scenario / name, Path(directory) / name)
    if mutate is not None:
        target = Path(directory) / "summary.json"
        payload = json.loads(target.read_text(encoding="utf-8"))
        mutate(payload)
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return directory


class TestVerifyCloudSummary(unittest.TestCase):
    def tearDown(self) -> None:
        for directory in getattr(self, "_temp_dirs", []):
            shutil.rmtree(directory, ignore_errors=True)

    def _scenario(self, scenario: Path, mutate=None) -> str:
        directory = copy_scenario(scenario, mutate)
        self._temp_dirs = getattr(self, "_temp_dirs", [])
        self._temp_dirs.append(directory)
        return directory

    def test_healthy_period_totals_are_printed_and_exit_code_is_ok(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "summary", "--fixture-dir", str(HEALTHY)])

        self.assertEqual(code, 0)
        self.assertIn("today", out)
        self.assertIn("2026-06-03", out)
        self.assertIn("900000", out)
        self.assertIn("120000", out)
        self.assertIn("80000", out)
        self.assertIn("claude", out)
        self.assertIn("codex", out)
        self.assertIn("complete", out)
        self.assertIn("核对通过", out)

    def test_partial_attribution_exits_data_issue_and_names_every_leftover_bucket(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "summary", "--fixture-dir", str(DEGRADED)])

        self.assertEqual(code, 3)
        self.assertIn("partial", out)
        self.assertIn("60000", out)
        self.assertIn("40000", out)
        self.assertIn("usage_attribution_partial", out)
        self.assertNotIn("核对通过", out)

    def test_missing_coverage_block_is_a_data_issue_not_a_silent_zero(self) -> None:
        directory = self._scenario(HEALTHY, lambda payload: payload.pop("provider_usage_coverage"))

        code, out, _ = run_cli(["verify-cloud", "summary", "--fixture-dir", directory])

        self.assertEqual(code, 3)
        self.assertIn("provider_usage_coverage_missing", out)

    def test_requested_period_that_the_read_model_did_not_honour_is_reported(self) -> None:
        code, out, _ = run_cli([
            "verify-cloud", "summary", "--fixture-dir", str(HEALTHY), "--period", "week",
        ])

        self.assertEqual(code, 3)
        self.assertIn("period_mismatch", out)

    def test_requested_period_that_matches_keeps_exit_code_ok(self) -> None:
        code, _, _ = run_cli([
            "verify-cloud", "summary", "--fixture-dir", str(HEALTHY),
            "--period", "today", "--date", "2026-06-03",
        ])

        self.assertEqual(code, 0)

    def test_json_output_is_machine_decidable(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "summary", "--fixture-dir", str(HEALTHY), "--json"])

        report = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(report["command"], "summary")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["totals"]["total_tokens"], 900000)
        self.assertEqual(
            [row["provider"] for row in report["provider_slots"]],
            ["claude", "codex"],
        )
        self.assertEqual(report["coverage"]["status"], "complete")


if __name__ == "__main__":
    unittest.main()
