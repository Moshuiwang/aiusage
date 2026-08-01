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


class TestVerifyCloudLimits(unittest.TestCase):
    """额度输出必须让「可信官方额度」和「降级态」一眼可分（AGENTS.md 官方额度不变量）。"""

    def tearDown(self) -> None:
        for directory in getattr(self, "_temp_dirs", []):
            shutil.rmtree(directory, ignore_errors=True)

    def _scenario(self, scenario: Path, mutate=None) -> str:
        directory = copy_scenario(scenario, mutate)
        self._temp_dirs = getattr(self, "_temp_dirs", [])
        self._temp_dirs.append(directory)
        return directory

    def test_all_official_windows_are_marked_trusted_and_exit_code_is_ok(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", str(HEALTHY)])

        self.assertEqual(code, 0)
        self.assertIn("可信官方额度", out)
        self.assertNotIn("降级", out)
        self.assertIn("42.0", out)
        self.assertIn("2026-06-08T00:00:00+08:00", out)

    def test_every_degraded_confidence_and_status_is_labelled_and_exits_data_issue(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", str(DEGRADED)])

        self.assertEqual(code, 3)
        self.assertIn("可信官方额度", out)
        self.assertIn("降级", out)
        for reason in ("confidence_estimated", "confidence_missing", "status_unsupported"):
            with self.subTest(reason=reason):
                self.assertIn(reason, out)

    def test_degraded_windows_never_print_percentages_or_reset_time(self) -> None:
        """降级窗口的百分比和 reset 时间一律不展示，否则本地估算会冒充官方额度。"""
        _, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", str(DEGRADED)])

        self.assertNotIn("61.0", out)
        self.assertNotIn("39.0", out)
        self.assertIn("42.0", out)

    def test_trusted_and_degraded_rows_carry_different_verdicts_in_json(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", str(DEGRADED), "--json"])
        report = json.loads(out)

        self.assertEqual(code, 3)
        self.assertEqual(report["command"], "limits")
        self.assertEqual(report["status"], "data_issue")
        self.assertEqual(report["trusted_count"], 1)
        self.assertEqual(report["degraded_count"], 3)

        by_key = {(row["provider"], row["window"]): row for row in report["windows"]}
        trusted = by_key[("claude", "week")]
        self.assertEqual(trusted["trust"], "trusted_official")
        self.assertEqual(trusted["degrade_reasons"], [])
        self.assertEqual(trusted["used_percent"], 42.0)
        self.assertEqual(trusted["reset_at"], "2026-06-08T00:00:00+08:00")

        estimated = by_key[("codex", "5h-block")]
        self.assertEqual(estimated["trust"], "degraded")
        self.assertIn("confidence_estimated", estimated["degrade_reasons"])
        self.assertIsNone(estimated["used_percent"])
        self.assertIsNone(estimated["remaining_percent"])
        self.assertIsNone(estimated["reset_at"])

        failed = by_key[("claude", "unknown")]
        self.assertIn("confidence_missing", failed["degrade_reasons"])
        self.assertIn("status_provider_failed", failed["degrade_reasons"])

        unsupported = by_key[("codex", "unknown")]
        self.assertIn("status_unsupported", unsupported["degrade_reasons"])

    def test_healthy_json_keeps_every_window_trusted(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", str(HEALTHY), "--json"])
        report = json.loads(out)

        self.assertEqual(code, 0)
        self.assertEqual(report["degraded_count"], 0)
        self.assertEqual(report["trusted_count"], 2)
        self.assertEqual(report["issues"], [])
        self.assertEqual(
            sorted(row["trust"] for row in report["windows"]),
            ["trusted_official", "trusted_official"],
        )

    def test_provider_without_usable_quota_is_named(self) -> None:
        _, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", str(DEGRADED)])

        self.assertIn("provider_quota_unavailable", out)

    def test_empty_limit_list_is_a_data_issue_not_a_pass(self) -> None:
        directory = self._scenario(HEALTHY, lambda payload: payload.update({"limits": []}))

        code, out, _ = run_cli(["verify-cloud", "limits", "--fixture-dir", directory])

        self.assertEqual(code, 3)
        self.assertIn("limit_windows_missing", out)


class TestVerifyCloudHealth(unittest.TestCase):
    def tearDown(self) -> None:
        for directory in getattr(self, "_temp_dirs", []):
            shutil.rmtree(directory, ignore_errors=True)

    def _scenario(self, scenario: Path, mutate=None) -> str:
        directory = copy_scenario(scenario, mutate)
        self._temp_dirs = getattr(self, "_temp_dirs", [])
        self._temp_dirs.append(directory)
        return directory

    def test_all_sources_fresh_prints_last_report_time_and_exits_ok(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "health", "--fixture-dir", str(HEALTHY)])

        self.assertEqual(code, 0)
        self.assertIn("linux-dev-wang", out)
        self.assertIn("mac-air-wang", out)
        self.assertIn("2026-06-03T11:58:00+08:00", out)
        self.assertIn("verified", out)
        self.assertIn("current", out)
        self.assertIn("核对通过", out)

    def test_stale_and_never_seen_sources_exit_data_issue_and_are_named(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "health", "--fixture-dir", str(DEGRADED)])

        self.assertEqual(code, 3)
        self.assertIn("stale", out)
        self.assertIn("never_seen", out)
        self.assertIn("source_not_ok", out)
        self.assertIn("collector_version_unsupported", out)

    def test_output_never_leaks_server_filesystem_paths(self) -> None:
        """`/api/health` 带 database.path / snapshot.path，核对输出不得把它们透出去。"""
        for extra in ([], ["--json"]):
            with self.subTest(extra=extra):
                _, out, _ = run_cli(["verify-cloud", "health", "--fixture-dir", str(HEALTHY), *extra])
                self.assertNotIn("data/usage.sqlite", out)
                self.assertNotIn("data/latest.json", out)
                self.assertNotIn(".sqlite", out)

    def test_json_output_covers_freshness_coverage_and_accuracy(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "health", "--fixture-dir", str(HEALTHY), "--json"])
        report = json.loads(out)

        self.assertEqual(code, 0)
        self.assertEqual(report["command"], "health")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["source_total"], 2)
        self.assertEqual(report["status_counts"], {"ok": 2})
        self.assertEqual(report["limits_health"]["effective_window_count"], 2)

        rows = {row["source_id"]: row for row in report["sources"]}
        linux = rows["linux-dev-wang"]
        self.assertEqual(linux["status"], "ok")
        self.assertEqual(linux["last_observed_at"], "2026-06-03T11:58:00+08:00")
        self.assertEqual(linux["accuracy_status"], "verified")
        self.assertEqual(linux["version_state"], "current")
        self.assertEqual(
            linux["coverage"],
            [{
                "agent": "claude",
                "status": "verified",
                "start": "2026-06-01T00:00:00+08:00",
                "end": "2026-06-03T11:58:00+08:00",
            }],
        )

    def test_source_count_disagreement_between_endpoints_is_reported(self) -> None:
        directory = self._scenario(
            HEALTHY,
            lambda payload: payload.__setitem__("source_status", payload["source_status"][:1]),
        )

        code, out, _ = run_cli(["verify-cloud", "health", "--fixture-dir", directory])

        self.assertEqual(code, 3)
        self.assertIn("source_count_mismatch", out)

    def test_machine_filter_suppresses_the_source_count_cross_check(self) -> None:
        """`/api/health` 不吃过滤条件，带过滤时数量本来就会对不上，不能报成异常。"""
        directory = self._scenario(
            HEALTHY,
            lambda payload: (
                payload.__setitem__("source_status", payload["source_status"][:1]),
                payload["summary"].__setitem__("machine", "linux-dev"),
            ),
        )

        code, out, _ = run_cli([
            "verify-cloud", "health", "--fixture-dir", directory, "--machine", "linux-dev",
        ])

        self.assertEqual(code, 0)
        self.assertNotIn("source_count_mismatch", out)


class TestVerifyCloudParity(unittest.TestCase):
    maxDiff = None

    def test_consistent_endpoints_exit_ok(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "parity", "--fixture-dir", str(HEALTHY)])

        self.assertEqual(code, 0)
        self.assertIn("核对通过", out)

    def test_version_fields_absent_from_mobile_are_not_reported_as_a_difference(self) -> None:
        """`/api/mobile/summary` 刻意不带版本字段，这是设计，不是口径不一致。"""
        summary = json.loads((HEALTHY / "summary.json").read_text(encoding="utf-8"))
        mobile = json.loads((HEALTHY / "mobile_summary.json").read_text(encoding="utf-8"))
        self.assertIn("version_health", summary)
        self.assertTrue(all("version" in row for row in summary["source_status"]))
        self.assertNotIn("version_health", mobile)
        self.assertTrue(all("version" not in row for row in mobile["sources"]))

        code, out, _ = run_cli(["verify-cloud", "parity", "--fixture-dir", str(HEALTHY), "--json"])
        report = json.loads(out)

        self.assertEqual(code, 0)
        self.assertEqual(report["differences"], [])
        self.assertIn(
            "source_status[].version",
            [row["field"] for row in report["known_differences"]],
        )

    def test_inconsistent_endpoints_exit_non_zero_and_list_every_differing_field(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "parity", "--fixture-dir", str(PARITY_MISMATCH), "--json"])
        report = json.loads(out)

        self.assertEqual(code, 4)
        self.assertEqual(report["status"], "mismatch")
        self.assertEqual(
            sorted(row["field"] for row in report["differences"]),
            [
                "period.total_tokens",
                "provider_slots[claude].quota.reason",
                "provider_slots[claude].quota.status",
                "provider_slots[claude].quota.window_count",
                "provider_slots[codex].usage.total_tokens",
                "provider_usage_coverage.attributed_tokens",
            ],
        )
        by_field = {row["field"]: row for row in report["differences"]}
        self.assertEqual(by_field["period.total_tokens"]["summary"], 900000)
        self.assertEqual(by_field["period.total_tokens"]["mobile"], 880000)

    def test_human_output_shows_both_sides_of_every_difference(self) -> None:
        code, out, _ = run_cli(["verify-cloud", "parity", "--fixture-dir", str(PARITY_MISMATCH)])

        self.assertEqual(code, 4)
        self.assertIn("period.total_tokens", out)
        self.assertIn("900000", out)
        self.assertIn("880000", out)
        self.assertIn("provider_slots[codex].usage.total_tokens", out)
        self.assertIn("provider_slots[claude].quota.status", out)
        self.assertNotIn("核对通过", out)

    def test_compared_field_set_is_pinned(self) -> None:
        _, out, _ = run_cli(["verify-cloud", "parity", "--fixture-dir", str(HEALTHY), "--json"])
        report = json.loads(out)

        expected = [
            "period.account",
            "period.date",
            "period.end_date",
            "period.id",
            "period.input_tokens",
            "period.machine",
            "period.output_tokens",
            "period.start_date",
            "period.total_tokens",
            "provider_usage_coverage.attributed_tokens",
            "provider_usage_coverage.other_provider_tokens",
            "provider_usage_coverage.status",
            "provider_usage_coverage.total_tokens",
            "provider_usage_coverage.unattributed_tokens",
        ]
        for provider in ("claude", "codex"):
            for leaf in (
                "quota.last_verified_at",
                "quota.reason",
                "quota.source_id",
                "quota.source_type",
                "quota.status",
                "quota.window_count",
                "usage.cache_tokens",
                "usage.input_tokens",
                "usage.output_tokens",
                "usage.status",
                "usage.total_tokens",
            ):
                expected.append(f"provider_slots[{provider}].{leaf}")
        self.assertEqual(report["compared_fields"], sorted(expected))


if __name__ == "__main__":
    unittest.main()
